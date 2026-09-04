from __future__ import annotations

import threading
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from app.services.realtime_quote import get_realtime_stock_quotes


CN_TZ = ZoneInfo("Asia/Shanghai")
EASTMONEY_CHANGES_URL = "https://push2ex.eastmoney.com/getAllStockChanges"

# 东方财富盘口异动类型。一个请求可以一次拉取全部类型，避免为每种异动
# 单独请求接口。正数表示偏强信号，负数表示偏弱信号，绝对值用于监控权重。
EVENT_TYPES: dict[int, tuple[str, float]] = {
    8201: ("火箭发射", 5.0),
    8202: ("快速反弹", 3.0),
    8193: ("大笔买入", 2.0),
    4: ("封涨停板", 6.0),
    32: ("打开跌停板", 4.0),
    64: ("有大买盘", 2.0),
    8207: ("竞价上涨", 2.0),
    8209: ("高开5日线", 1.0),
    8211: ("向上缺口", 2.0),
    8213: ("60日新高", 2.0),
    8215: ("60日大幅上涨", 3.0),
    8204: ("加速下跌", -4.0),
    8203: ("高台跳水", -5.0),
    8194: ("大笔卖出", -2.0),
    8: ("封跌停板", -6.0),
    16: ("打开涨停板", -4.0),
    128: ("有大卖盘", -2.0),
    8208: ("竞价下跌", -2.0),
    8210: ("低开5日线", -1.0),
    8212: ("向下缺口", -2.0),
    8214: ("60日新低", -2.0),
    8216: ("60日大幅下跌", -3.0),
}


def _format_event_time(value: Any) -> str:
    try:
        digits = str(int(value)).zfill(6)
    except (TypeError, ValueError):
        return str(value or "")
    return f"{digits[:2]}:{digits[2:4]}:{digits[4:6]}"


def _normalize_code(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() and len(text) < 6 else text


def _serializable_number(value: float | int | None) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return round(float(value), 4)


class EastmoneyMonitorProvider:
    """Realtime/near-realtime intraday anomaly provider.

    TuData remains the primary structured market-data source in StockWeb. These
    two screens require an event stream that TuData does not expose directly,
    so this provider uses Eastmoney's public quote anomaly endpoint. Data is
    cached briefly in-process to avoid repeatedly hitting the upstream endpoint
    when users switch between "日内异动" and "重点监控".
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache_at = 0.0
        self._cache_rows: list[dict[str, Any]] = []
        self._cache_total = 0
        self._cache_ttl = 12.0

    @staticmethod
    def _direction(weight: float) -> str:
        if weight > 0:
            return "偏强"
        if weight < 0:
            return "偏弱"
        return "中性"

    @staticmethod
    def _parse_payload(payload: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
        data = payload.get("data") or {}
        raw_rows = data.get("allstock") or []
        total = int(data.get("tc") or len(raw_rows))
        rows: list[dict[str, Any]] = []
        for item in raw_rows:
            try:
                event_code = int(item.get("t"))
            except (TypeError, ValueError):
                event_code = 0
            label, weight = EVENT_TYPES.get(event_code, (str(event_code), 0.0))
            rows.append(
                {
                    "event_time": _format_event_time(item.get("tm")),
                    "code": _normalize_code(item.get("c")),
                    "name": str(item.get("n") or ""),
                    "event_type": label,
                    "direction": EastmoneyMonitorProvider._direction(weight),
                    "signal_weight": abs(weight),
                    "related_info": str(item.get("i") or ""),
                    "event_code": event_code,
                    "market": item.get("m"),
                }
            )
        rows.sort(key=lambda row: str(row.get("event_time") or ""), reverse=True)
        return total, rows

    def _load_changes(self, force: bool = False) -> tuple[int, list[dict[str, Any]]]:
        now = time.monotonic()
        with self._lock:
            if not force and self._cache_rows and now - self._cache_at < self._cache_ttl:
                return self._cache_total, [dict(row) for row in self._cache_rows]

        params = {
            "type": ",".join(str(code) for code in EVENT_TYPES),
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "pageindex": 0,
            "pagesize": 10000,
            "dpt": "wzchanges",
            "_": int(time.time() * 1000),
        }
        headers = {
            "Referer": "https://quote.eastmoney.com/changes/",
            "User-Agent": "Mozilla/5.0 StockWeb/1.0",
            "Accept": "application/json,text/plain,*/*",
        }
        try:
            response = requests.get(EASTMONEY_CHANGES_URL, params=params, headers=headers, timeout=8)
            response.raise_for_status()
            payload = response.json()
            if int(payload.get("rc", 0)) != 0:
                raise RuntimeError(f"东方财富盘口异动接口返回 rc={payload.get('rc')}")
            total, rows = self._parse_payload(payload)
        except (requests.RequestException, ValueError, TypeError) as exc:
            with self._lock:
                if self._cache_rows:
                    return self._cache_total, [dict(row) for row in self._cache_rows]
            raise RuntimeError(f"东方财富盘口异动数据获取失败：{exc}") from exc

        with self._lock:
            self._cache_at = now
            self._cache_total = total
            self._cache_rows = [dict(row) for row in rows]
        return total, rows

    def intraday_changes(
        self,
        *,
        limit: int = 500,
        direction: str | None = None,
        event_type: str | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        total, rows = self._load_changes()
        if direction:
            rows = [row for row in rows if row.get("direction") == direction]
        if event_type:
            rows = [row for row in rows if row.get("event_type") == event_type]

        selected = rows[: max(1, min(limit, 2000))]
        unique_stocks = len({row.get("code") for row in selected if row.get("code")})
        positive = sum(1 for row in selected if row.get("direction") == "偏强")
        negative = sum(1 for row in selected if row.get("direction") == "偏弱")
        summary = {
            "抓取异动总数": total,
            "当前展示": len(selected),
            "涉及股票": unique_stocks,
            "偏强异动": positive,
            "偏弱异动": negative,
            "最新异动时间": selected[0].get("event_time") if selected else None,
        }
        return summary, selected

    def focus_monitor(
        self,
        *,
        limit: int = 80,
        min_events: int = 2,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        total, events = self._load_changes()
        by_stock: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            code = str(event.get("code") or "")
            if code:
                by_stock[code].append(event)

        candidates: list[dict[str, Any]] = []
        for code, items in by_stock.items():
            if len(items) < max(1, min_events):
                continue

            type_counts = Counter(str(item.get("event_type") or "") for item in items)
            signed_score = 0.0
            monitor_score = 0.0
            positive_count = 0
            negative_count = 0
            for event_code, (label, signed_weight) in EVENT_TYPES.items():
                count = type_counts.get(label, 0)
                if not count:
                    continue
                capped_count = min(count, 5)
                signed_score += signed_weight * capped_count
                monitor_score += abs(signed_weight) * capped_count
                if signed_weight > 0:
                    positive_count += count
                elif signed_weight < 0:
                    negative_count += count

            monitor_score += len(type_counts) * 1.5 + min(len(items), 20) * 0.35
            if signed_score >= 4:
                bias = "偏强"
            elif signed_score <= -4:
                bias = "偏弱"
            else:
                bias = "双向异动"

            top_types = " / ".join(
                f"{name}×{count}" for name, count in type_counts.most_common(4)
            )
            latest = max(items, key=lambda item: str(item.get("event_time") or ""))
            candidates.append(
                {
                    "code": code,
                    "name": str(latest.get("name") or ""),
                    "monitor_score": round(monitor_score, 2),
                    "signal_bias": bias,
                    "event_count": len(items),
                    "positive_count": positive_count,
                    "negative_count": negative_count,
                    "unique_event_types": len(type_counts),
                    "latest_time": latest.get("event_time"),
                    "latest_event": latest.get("event_type"),
                    "event_types": top_types,
                }
            )

        candidates.sort(
            key=lambda row: (float(row.get("monitor_score") or 0), int(row.get("event_count") or 0)),
            reverse=True,
        )
        selected = candidates[: max(1, min(limit, 200))]

        # 使用项目现有的腾讯实时行情一次性补充价格和涨跌幅，不额外逐股请求。
        quotes = get_realtime_stock_quotes([str(row["code"]) for row in selected]) if selected else []
        quote_map = {str(item.get("code") or "").split(".")[0]: item for item in quotes}
        for row in selected:
            quote = quote_map.get(str(row["code"])) or {}
            row["price"] = _serializable_number(quote.get("price"))
            row["change_percent"] = _serializable_number(quote.get("change_percent"))

        summary = {
            "盘中异动总数": total,
            "监控股票数": len(selected),
            "偏强监控": sum(1 for row in selected if row.get("signal_bias") == "偏强"),
            "偏弱监控": sum(1 for row in selected if row.get("signal_bias") == "偏弱"),
            "双向异动": sum(1 for row in selected if row.get("signal_bias") == "双向异动"),
            "更新时间": datetime.now(CN_TZ).strftime("%H:%M:%S"),
        }
        return summary, selected


monitor_provider = EastmoneyMonitorProvider()
