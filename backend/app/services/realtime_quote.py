from __future__ import annotations

import re
from typing import Any

import requests


_INDEX_ALIASES = {
    "sh000001": "sh000001",
    "上证指数": "sh000001",
    "上证": "sh000001",
    "上证综指": "sh000001",
    "sz399001": "sz399001",
    "深证成指": "sz399001",
    "深成指": "sz399001",
}


def _number(value: str | None, default: float | None = None) -> float | None:
    try:
        if value is None or value.strip().lower() in {"", "none", "nan", "null"}:
            return default
        return round(float(value), 4)
    except (TypeError, ValueError):
        return default


def _integer(value: str | None, default: int = 0) -> int:
    try:
        return int(float(value or ""))
    except (TypeError, ValueError):
        return default


def _symbol(code: str) -> str | None:
    """Convert a legacy query code to a Tencent quote symbol.

    The old service accepted six-digit A-share codes as well as `.SH`, `.SZ`,
    `.BJ`, `.HK`, and the two major mainland index aliases.
    """
    raw = str(code).strip()
    if not raw:
        return None
    alias = _INDEX_ALIASES.get(raw.lower()) or _INDEX_ALIASES.get(raw)
    if alias:
        return alias

    compact = raw.lower().replace(" ", "")
    if re.fullmatch(r"hk\d{5}", compact):
        return compact
    if compact.endswith(".hk") and compact[:-3].isdigit():
        return f"hk{compact[:-3].zfill(5)}"
    if len(compact) == 5 and compact.isdigit():
        return f"hk{compact}"

    match = re.fullmatch(r"(?:(sh|sz|bj))?(\d{6})(?:\.(sh|sz|bj))?", compact)
    if not match:
        return None
    prefix, digits, suffix = match.groups()
    market = suffix or prefix
    if not market:
        market = "bj" if digits.startswith(("4", "8", "92")) else "sh" if digits.startswith(("5", "6", "9")) else "sz"
    return f"{market}{digits}"


def _quote_from_fields(symbol: str, fields: list[str]) -> dict[str, Any] | None:
    # Tencent's quote protocol uses a tilde-separated payload.  The positions
    # below are stable across the A-share, ETF, index and Hong Kong feeds.
    if len(fields) < 5 or not fields[1]:
        return None
    price = _number(fields[3])
    pre_close = _number(fields[4])
    if price == 0 and pre_close is not None:
        price = pre_close
    change = round(price - pre_close, 3) if price is not None and pre_close not in (None, 0) else None
    change_percent = round(change / pre_close * 100, 2) if change is not None and pre_close else None

    def value(index: int) -> str | None:
        return fields[index] if len(fields) > index else None

    bids = []
    asks = []
    # Bid/ask fields are not available for every instrument, so leave their
    # arrays empty when the upstream response omits them.
    for level, price_index, volume_index in ((1, 9, 10), (2, 11, 12), (3, 13, 14), (4, 15, 16), (5, 17, 18)):
        bid_price = _number(value(price_index))
        if bid_price and bid_price > 0:
            bids.append({"level": level, "price": bid_price, "volume": _integer(value(volume_index))})
    for level, price_index, volume_index in ((1, 19, 20), (2, 21, 22), (3, 23, 24), (4, 25, 26), (5, 27, 28)):
        ask_price = _number(value(price_index))
        if ask_price and ask_price > 0:
            asks.append({"level": level, "price": ask_price, "volume": _integer(value(volume_index))})

    market_code = value(2) or symbol[2:]
    return {
        "code": f"{market_code}.HK" if symbol.startswith("hk") else market_code,
        "name": value(1) or "",
        "price": price,
        "change": change,
        "change_percent": change_percent,
        "pre_close": pre_close,
        "open": _number(value(5)),
        "high": _number(value(33)),
        "low": _number(value(34)),
        "bid": bids[0]["price"] if bids else None,
        "ask": asks[0]["price"] if asks else None,
        "volume": _number(value(6)),
        "amount": _number(value(37)),
        "currency": "HKD" if symbol.startswith("hk") else "CNY",
        "timestamp": value(30) or "",
        "bids": bids,
        "asks": asks,
    }


def get_realtime_stock_quotes(codes: list[str] | str) -> list[dict[str, Any]]:
    raw_codes = re.split(r"[,;\s]+", codes.strip()) if isinstance(codes, str) else codes
    symbols = [symbol for code in raw_codes if (symbol := _symbol(str(code)))]
    if not symbols:
        return []
    try:
        response = requests.get(
            "http://qt.gtimg.cn/q=" + ",".join(symbols),
            headers={"Referer": "https://gu.qq.com/", "User-Agent": "StockWeb/1.0"},
            timeout=5,
        )
        response.raise_for_status()
        payload = response.content.decode("gbk", errors="ignore")
    except requests.RequestException:
        return []

    quotes: list[dict[str, Any]] = []
    for symbol in symbols:
        matched = re.search(rf'v_{re.escape(symbol)}="([^"]*)"', payload, re.IGNORECASE)
        if matched and (quote := _quote_from_fields(symbol, matched.group(1).split("~"))):
            quotes.append(quote)
    return quotes


def get_single_realtime_stock_quote(code_or_name: str) -> dict[str, Any] | None:
    quotes = get_realtime_stock_quotes(code_or_name)
    return quotes[0] if quotes else None
