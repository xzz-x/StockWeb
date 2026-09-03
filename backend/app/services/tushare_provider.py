from __future__ import annotations

import os
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import tushare as ts
from dotenv import load_dotenv


CN_TZ = ZoneInfo("Asia/Shanghai")
load_dotenv()


class TushareProvider:
    """Thin data-access layer around Tushare Pro.

    The web/API layer talks only to this provider so individual datasets can be
    cached in MySQL or replaced with fallback sources later without changing the
    frontend contract.
    """

    INDEX_MAP = {
        "上证指数": "000001.SH",
        "深证成指": "399001.SZ",
        "创业板指": "399006.SZ",
        "沪深300": "000300.SH",
    }

    GLOBAL_INDEX_MAP = {
        "道琼斯": "DJI",
        "标普500": "SPX",
        "纳斯达克": "IXIC",
        "恒生指数": "HSI",
        "恒生科技": "HKTECH",
    }

    LIMIT_KIND_MAP = {
        "up": "涨停池",
        "broken": "炸板池",
        "down": "跌停池",
    }

    def __init__(self) -> None:
        self._pro = None
        self._stock_name_cache: dict[str, str] | None = None

    @property
    def pro(self):
        if self._pro is None:
            token = os.getenv("TUSHARE_TOKEN", "").strip()
            if not token:
                raise RuntimeError(
                    "缺少 TUSHARE_TOKEN。请复制 .env.example 为 .env 并填写 Tushare Token。"
                )
            ts.set_token(token)
            self._pro = ts.pro_api()
        return self._pro

    @staticmethod
    def records(df: pd.DataFrame | None) -> list[dict[str, Any]]:
        if df is None or df.empty:
            return []
        # DataFrame.to_json handles numpy scalars/NaN/Timestamp safely for FastAPI.
        return pd.read_json(df.to_json(orient="records", force_ascii=False)).where(
            lambda x: x.notna(), None
        ).to_dict(orient="records")

    def query(self, api_name: str, fields: str = "", **params) -> pd.DataFrame:
        try:
            return self.pro.query(api_name, fields=fields, **params)
        except Exception as exc:  # Tushare returns permission/rate-limit errors as exceptions.
            raise RuntimeError(f"Tushare {api_name} 调用失败：{exc}") from exc

    @staticmethod
    def normalize_stock_code(code: str) -> str:
        raw = code.strip().upper()
        if "." in raw:
            return raw
        if not raw.isdigit() or len(raw) != 6:
            raise ValueError("股票代码必须是 6 位数字，或完整 ts_code（如 600519.SH）。")
        if raw.startswith(("4", "8", "92")):
            return f"{raw}.BJ"
        if raw.startswith(("5", "6", "9")):
            return f"{raw}.SH"
        return f"{raw}.SZ"

    @staticmethod
    def normalize_date(value: str | None) -> str | None:
        if not value:
            return None
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) != 8:
            raise ValueError("日期格式应为 YYYYMMDD。")
        datetime.strptime(digits, "%Y%m%d")
        return digits

    @staticmethod
    def date_days_ago(end_date: str, calendar_days: int) -> str:
        dt = datetime.strptime(end_date, "%Y%m%d") - timedelta(days=calendar_days)
        return dt.strftime("%Y%m%d")

    @lru_cache(maxsize=32)
    def latest_trade_date(self, on_or_before: str | None = None) -> str:
        end_date = self.normalize_date(on_or_before) or datetime.now(CN_TZ).strftime("%Y%m%d")
        start_date = self.date_days_ago(end_date, 20)
        df = self.query(
            "trade_cal",
            exchange="SSE",
            start_date=start_date,
            end_date=end_date,
            is_open="1",
            fields="cal_date,is_open,pretrade_date",
        )
        if df.empty:
            raise RuntimeError("无法从 Tushare 获取最近交易日。")
        return str(df["cal_date"].max())

    @lru_cache(maxsize=64)
    def previous_trade_date(self, trade_date: str) -> str:
        trade_date = self.latest_trade_date(trade_date)
        end_date = self.date_days_ago(trade_date, 1)
        return self.latest_trade_date(end_date)

    def _stock_names(self) -> dict[str, str]:
        if self._stock_name_cache is None:
            df = self.query(
                "stock_basic",
                exchange="",
                list_status="L",
                fields="ts_code,name",
            )
            self._stock_name_cache = dict(zip(df["ts_code"], df["name"])) if not df.empty else {}
        return self._stock_name_cache

    # --------------------------- 资金面 / 筹码 ---------------------------

    def margin_detail(self, code: str, days: int = 90) -> list[dict[str, Any]]:
        ts_code = self.normalize_stock_code(code)
        end = self.latest_trade_date()
        start = self.date_days_ago(end, days * 2)
        df = self.query("margin_detail", ts_code=ts_code, start_date=start, end_date=end)
        if not df.empty:
            df = df.sort_values("trade_date", ascending=False).head(days)
        return self.records(df)

    def block_trade(self, code: str, days: int = 365) -> list[dict[str, Any]]:
        ts_code = self.normalize_stock_code(code)
        end = self.latest_trade_date()
        start = self.date_days_ago(end, days)
        df = self.query("block_trade", ts_code=ts_code, start_date=start, end_date=end)
        if not df.empty:
            df = df.sort_values("trade_date", ascending=False)
        return self.records(df)

    def holder_number(self, code: str) -> list[dict[str, Any]]:
        ts_code = self.normalize_stock_code(code)
        df = self.query("stk_holdernumber", ts_code=ts_code)
        if not df.empty:
            df = df.sort_values(["end_date", "ann_date"], ascending=False).head(40)
        return self.records(df)

    def dividends(self, code: str) -> list[dict[str, Any]]:
        ts_code = self.normalize_stock_code(code)
        df = self.query("dividend", ts_code=ts_code)
        sort_cols = [c for c in ["end_date", "ann_date"] if c in df.columns]
        if not df.empty and sort_cols:
            df = df.sort_values(sort_cols, ascending=False).head(60)
        return self.records(df)

    def moneyflow(self, code: str, days: int = 120) -> list[dict[str, Any]]:
        ts_code = self.normalize_stock_code(code)
        end = self.latest_trade_date()
        start = self.date_days_ago(end, days * 2)
        df = self.query("moneyflow", ts_code=ts_code, start_date=start, end_date=end)
        if not df.empty:
            df = df.sort_values("trade_date", ascending=False).head(days)
        return self.records(df)

    def chip_profile(self, code: str, days: int = 120) -> list[dict[str, Any]]:
        ts_code = self.normalize_stock_code(code)
        end = self.latest_trade_date()
        start = self.date_days_ago(end, days * 2)
        df = self.query("cyq_perf", ts_code=ts_code, start_date=start, end_date=end)
        if not df.empty:
            df = df.sort_values("trade_date", ascending=False).head(days)
        return self.records(df)

    def chip_distribution(self, code: str, trade_date: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        ts_code = self.normalize_stock_code(code)
        target = self.normalize_date(trade_date)
        if target is None:
            # cyq data may lag the normal trading calendar, so discover the latest
            # available chip-profile date first rather than assuming today's close.
            end = self.latest_trade_date()
            start = self.date_days_ago(end, 20)
            perf = self.query("cyq_perf", ts_code=ts_code, start_date=start, end_date=end)
            if perf.empty:
                target = end
            else:
                target = str(perf["trade_date"].max())
        df = self.query("cyq_chips", ts_code=ts_code, trade_date=target)
        if not df.empty:
            df = df.sort_values("price", ascending=False)
        return target, self.records(df)

    # ------------------------------- 打板 -------------------------------

    def limit_pool(self, kind: str, trade_date: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        if kind not in self.LIMIT_KIND_MAP:
            raise ValueError("kind 仅支持 up / broken / down。")
        date = self.latest_trade_date(self.normalize_date(trade_date))
        label = self.LIMIT_KIND_MAP[kind]

        # Preferred source: Tushare's THS limit list. If the account lacks the
        # 8000-point permission, fall back to another Tushare dataset (KPL list).
        try:
            df = self.query("limit_list_ths", trade_date=date, limit_type=label)
        except RuntimeError:
            df = self.query("kpl_list", trade_date=date, tag=label.replace("池", ""))

        if not df.empty:
            for col in ["limit_order", "limit_amount", "turnover"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            if "limit_amount" in df.columns:
                df = df.sort_values("limit_amount", ascending=False)
            elif "turnover" in df.columns:
                df = df.sort_values("turnover", ascending=False)
        return date, self.records(df)

    def limit_ladder(self, trade_date: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        date = self.latest_trade_date(self.normalize_date(trade_date))
        try:
            df = self.query("limit_step", trade_date=date)
            if not df.empty:
                df["nums_numeric"] = pd.to_numeric(df["nums"], errors="coerce")
                df = df.sort_values(["nums_numeric", "ts_code"], ascending=[False, True])
        except RuntimeError:
            _, rows = self.limit_pool("up", date)
            return date, rows
        return date, self.records(df)

    def emotion(self, trade_date: str | None = None) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        date = self.latest_trade_date(self.normalize_date(trade_date))
        _, up = self.limit_pool("up", date)
        _, broken = self.limit_pool("broken", date)
        _, down = self.limit_pool("down", date)
        _, ladder = self.limit_ladder(date)

        total_touched = len(up) + len(broken)
        seal_rate = round(len(up) / total_touched * 100, 2) if total_touched else None
        broken_rate = round(len(broken) / total_touched * 100, 2) if total_touched else None

        nums = []
        for row in ladder:
            value = row.get("nums_numeric", row.get("nums"))
            try:
                nums.append(int(float(value)))
            except (TypeError, ValueError):
                continue

        promotion_rate = None
        try:
            prev = self.previous_trade_date(date)
            _, prev_ladder = self.limit_ladder(prev)
            prev_map = {r.get("ts_code"): r for r in prev_ladder if r.get("ts_code")}
            today_map = {r.get("ts_code"): r for r in ladder if r.get("ts_code")}
            eligible = 0
            promoted = 0
            for code, row in prev_map.items():
                try:
                    prev_num = int(float(row.get("nums_numeric", row.get("nums"))))
                except (TypeError, ValueError):
                    continue
                eligible += 1
                now = today_map.get(code)
                if not now:
                    continue
                try:
                    now_num = int(float(now.get("nums_numeric", now.get("nums"))))
                except (TypeError, ValueError):
                    continue
                if now_num >= prev_num + 1:
                    promoted += 1
            if eligible:
                promotion_rate = round(promoted / eligible * 100, 2)
        except RuntimeError:
            pass

        summary = {
            "trade_date": date,
            "涨停家数": len(up),
            "炸板家数": len(broken),
            "跌停家数": len(down),
            "封板率%": seal_rate,
            "炸板率%": broken_rate,
            "最高连板": max(nums) if nums else None,
            "晋级率%": promotion_rate,
        }
        return date, summary, ladder

    # ----------------------------- 每日复盘 -----------------------------

    def market_overview(self, trade_date: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        date = self.latest_trade_date(self.normalize_date(trade_date))
        rows: list[dict[str, Any]] = []
        for name, code in self.INDEX_MAP.items():
            start = self.date_days_ago(date, 12)
            df = self.query("index_daily", ts_code=code, start_date=start, end_date=date)
            if df.empty:
                continue
            row = df.sort_values("trade_date", ascending=False).iloc[0].to_dict()
            row["name"] = name
            rows.append(row)
        return date, rows

    def global_indices(self, trade_date: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        target = self.normalize_date(trade_date) or datetime.now(CN_TZ).strftime("%Y%m%d")
        start = self.date_days_ago(target, 12)
        rows: list[dict[str, Any]] = []
        latest_seen = target
        for name, code in self.GLOBAL_INDEX_MAP.items():
            df = self.query("index_global", ts_code=code, start_date=start, end_date=target)
            if df.empty:
                continue
            row = df.sort_values("trade_date", ascending=False).iloc[0].to_dict()
            row["name"] = name
            rows.append(row)
            latest_seen = max(latest_seen, str(row.get("trade_date", target)))
        return latest_seen, self.records(pd.DataFrame(rows))

    def turnover_top20(self, trade_date: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        date = self.latest_trade_date(self.normalize_date(trade_date))
        df = self.query(
            "daily",
            trade_date=date,
            fields="ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount",
        )
        if df.empty:
            return date, []
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
        df = df.sort_values("amount", ascending=False).head(20).copy()
        names = self._stock_names()
        df.insert(1, "name", df["ts_code"].map(names).fillna(""))
        # Tushare daily.amount is in thousand RMB. 100,000 thousand RMB = 1 亿元.
        df["amount_yi"] = (df["amount"] / 100000).round(2)
        return date, self.records(df)

    def sector_flow(self, trade_date: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        date = self.latest_trade_date(self.normalize_date(trade_date))
        try:
            df = self.query("moneyflow_ind_dc", trade_date=date, content_type="行业")
            if not df.empty and "net_amount" in df.columns:
                df["net_amount_yi"] = (
                    pd.to_numeric(df["net_amount"], errors="coerce") / 100000000
                ).round(2)
                df = df.sort_values("net_amount", ascending=False)
        except RuntimeError:
            df = self.query("moneyflow_ind_ths", trade_date=date)
            if not df.empty and "net_buy_amount" in df.columns:
                df = df.sort_values("net_buy_amount", ascending=False)
        return date, self.records(df.head(40) if not df.empty else df)


provider = TushareProvider()
