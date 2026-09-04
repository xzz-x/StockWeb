from __future__ import annotations

import json
import random
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from app.services.realtime_quote import get_realtime_stock_quotes


CN_TZ = ZoneInfo("Asia/Shanghai")
EASTMONEY_CHANGES_URLS = (
    "https://push2ex.eastmoney.com/getAllStockChanges",
    "http://push2ex.eastmoney.com/getAllStockChanges",
)

# 东方财富盘口异动类型。正数表示偏强，负数表示偏弱，绝对值用于监控权重。
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
    if value is None or value == "":
        return ""
    text = str(value).strip().replace(":", "")
    try:
        digits = str(int(float(text))).zfill(6)
    except (TypeError, ValueError):
        return str(value)
    return f"{digits[:2]}:{digits[2:4]}:{digits[4:6]}"


def _normalize_code(value: Any) -> str:
    text = str(value or "").strip().split(".")[0]
    return text.zfill(6) if text.isdigit() and len(text) < 6 else text


def _serializable_number(value: float | int | None) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return round(float(value), 4)


def _decode_json_or_jsonp(text: str) -> dict[str, Any]:
    raw = text.strip()
    if not raw:
        raise ValueError("上游返回空响应")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        matched = re.match(r"^[A-Za-z0-9_$]+\s*\(\s*(.*)\s*\)\s*;?\s*$", raw, re.DOTALL)
        if not matched:
            raise ValueError(f"无法解析东方财富响应：{raw[:120]}")
        value = json.loads(matched.group(1))
    if not isinstance(value, dict):
        raise ValueError("东方财富响应不是 JSON 对象")
    return value


class EastmoneyMonitorProvider:
    """Realtime/near-realtime anomaly provider with a TuData fallback.

    Eastmoney's push2* endpoints sometimes reject cloud-server traffic. The
    primary request therefore mimics the browser JSONP request used by the quote
    page, retries both HTTPS and HTTP, and uses a conservative page size. If the
    upstream still fails, the provider falls back to the latest TuData limit-up,
    broken-board and limit-down pools instead of making the UI unusable.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache_at = 0.0
        self._cache_rows: list[dict[str, Any]] = []
        self._cache_total = 0
        self._cache_ttl = 12.0
        self._cache_source = ""
        self._session = requests.Session()

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

    def _request_eastmoney(self) -> tuple[int, list[dict[str, Any]]]:
        timestamp = int(time.time() * 1000)
        callback = f"jQuery{random.randint(10**15, 10**16 - 1)}_{timestamp}"
        params = {
            "type": ",".join(str(code) for code in EVENT_TYPES),
            "cb": callback,
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "pageindex": 0,
            # 10000 is more likely to trigger upstream anti-bot rules. 1000 is
            # enough for the monitoring screen and matches current browser-like
            # implementations in the ecosystem.
            "pagesize": 1000,
            "dpt": "wzchanges",
            "_": timestamp,
        }
        headers = {
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Connection": "keep-alive",
            "Referer": "https://quote.eastmoney.com/changes/",
            "Sec-Fetch-Dest": "script",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-site",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
        }
        errors: list[str] = []
        for url in EASTMONEY_CHANGES_URLS:
            for attempt in range(2):
                try:
                    response = self._session.get(url, params=params, headers=headers, timeout=(4, 10))
                    if response.status_code in {403, 429}:
                        raise RuntimeError(f"HTTP {response.status_code}")
                    response.raise_for_status()
                    payload = _decode_json_or_jsonp(response.text)
                    if int(payload.get("rc", 0)) != 0:
                        raise RuntimeError(f"rc={payload.get('rc')}")
                    total, rows = self._parse_payload(payload)
                    # data=None can occur outside a usable upstream window; let
                    # the fallback handle that instead of returning a broken UI.
                    if not rows:
                        raise RuntimeError("返回数据为空")
                    return total, rows
                except (requests.RequestException, RuntimeError, ValueError, TypeError) as exc:
                    errors.append(f"{url}#{attempt + 1}: {exc}")
                    time.sleep(0.2 * (attempt + 1))
        raise RuntimeError("；".join(errors[-4:]) or "东方财富盘口异动接口不可用")

    @staticmethod
    def _pool_time(row: dict[str, Any]) -> str:
        for key in ("last_lu_time", "first_lu_time", "last_time", "first_time", "trade_time"):
            value = row.get(key)
            if value not in (None, ""):
                return _format_event_time(value)
        return ""

    def _tudata_fallback(self) -> tuple[int, list[dict[str, Any]]]:
        # Local import prevents the monitoring service from creating an import
        # cycle during FastAPI startup.
        from app.services.tudata_provider import provider as tudata_provider

        definitions = (
            ("up", "涨停池", "偏强", 6.0, 4),
            ("broken", "炸板池", "偏弱", 4.0, 16),
            ("down", "跌停池", "偏弱", 6.0, 8),
        )
        rows: list[dict[str, Any]] = []
        failures: list[str] = []
        for kind, label, direction, weight, event_code in definitions:
            try:
                _date, pool = tudata_provider.limit_pool(kind)
            except Exception as exc:  # individual pool permissions may differ
                failures.append(f"{kind}: {exc}")
                continue
            for item in pool:
                code = _normalize_code(item.get("ts_code") or item.get("code"))
                if not code:
                    continue
                related = item.get("lu_desc") or item.get("reason") or item.get("tag") or ""
                rows.append(
                    {
                        "event_time": self._pool_time(item),
                        "code": code,
                        "name": str(item.get("name") or ""),
                        "event_type": label,
                        "direction": direction,
                        "signal_weight": weight,
                        "related_info": str(related),
                        "event_code": event_code,
                        "market": "TuData",
                    }
                )
        if not rows:
            raise RuntimeError("TuData 降级数据也不可用：" + "；".join(failures[-3:]))
        rows.sort(key=lambda row: str(row.get("event_time") or ""), reverse=True)
        return len(rows), rows

    def _load_changes(self, force: bool = False) -> tuple[int, list[dict[str, Any]], str]:
        now = time.monotonic()
        with self._lock:
            if not force and self._cache_rows and now - self._cache_at < self._cache_ttl:
                return self._cache_total, [dict(row) for row in self._cache_rows], self._cache_source

        source = "东方财富盘口异动"
        try:
            total, rows = self._request_eastmoney()
        except RuntimeError as eastmoney_error:
            with self._lock:
                if self._cache_rows:
                    return self._cache_total, [dict(row) for row in self._cache_rows], self._cache_source
            try:
                total, rows = self._tudata_fallback()
                source = "TuData 涨停/炸板/跌停池（东方财富不可用时降级）"
            except RuntimeError as fallback_error:
                raise RuntimeError(
                    f"实时异动数据不可用。东方财富：{eastmoney_error}；降级源：{fallback_error}"
                ) from fallback_error

        with self._lock:
            self._cache_at = now
            self._cache_total = total
            self._cache_rows = [dict(row) for row in rows]
            self._cache_source = source
        return total, rows, source

    def intraday_changes(
        self,
        *,
        limit: int = 500,
        direction: str | None = None,
        event_type: str | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        total, rows, source = self._load_changes()
        if direction:
            rows = [row for row in rows if row.get("direction") == direction]
        if event_type:
            rows = [row for row in rows if row.get("event_type") == event_type]

        selected = rows[: max(1, min(limit, 2000))]
        unique_stocks = len({row.get("code") for row in selected if row.get("code")})
        positive = sum(1 for row in selected if row.get("direction") == "偏强")
        negative = sum(1 for row in selected if row.get("direction") == "偏弱")
        summary = {
            "数据模式": source,
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
        total, events, source = self._load_changes()
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
            for _event_code, (label, signed_weight) in EVENT_TYPES.items():
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

            # The fallback pool labels are not in EVENT_TYPES, so preserve a
            # meaningful score for those rows as well.
            if monitor_score == 0:
                monitor_score = sum(float(item.get("signal_weight") or 0) for item in items)
                signed_score = sum(
                    (1 if item.get("direction") == "偏强" else -1) * float(item.get("signal_weight") or 0)
                    for item in items
                )
                positive_count = sum(1 for item in items if item.get("direction") == "偏强")
                negative_count = sum(1 for item in items if item.get("direction") == "偏弱")

            monitor_score += len(type_counts) * 1.5 + min(len(items), 20) * 0.35
            if signed_score >= 4:
                bias = "偏强"
            elif signed_score <= -4:
                bias = "偏弱"
            else:
                bias = "双向异动"

            top_types = " / ".join(f"{name}×{count}" for name, count in type_counts.most_common(4))
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

        quotes = get_realtime_stock_quotes([str(row["code"]) for row in selected]) if selected else []
        quote_map = {str(item.get("code") or "").split(".")[0]: item for item in quotes}
        for row in selected:
            quote = quote_map.get(str(row["code"])) or {}
            row["price"] = _serializable_number(quote.get("price"))
            row["change_percent"] = _serializable_number(quote.get("change_percent"))

        summary = {
            "数据模式": source,
            "盘中异动总数": total,
            "监控股票数": len(selected),
            "偏强监控": sum(1 for row in selected if row.get("signal_bias") == "偏强"),
            "偏弱监控": sum(1 for row in selected if row.get("signal_bias") == "偏弱"),
            "双向异动": sum(1 for row in selected if row.get("signal_bias") == "双向异动"),
            "更新时间": datetime.now(CN_TZ).strftime("%H:%M:%S"),
        }
        return summary, selected


monitor_provider = EastmoneyMonitorProvider()
