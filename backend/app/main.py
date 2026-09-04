from __future__ import annotations

import os
from typing import Any, Callable

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.services.eastmoney_monitor import EVENT_TYPES, monitor_provider
from app.services.realtime_quote import get_realtime_stock_quotes, get_single_realtime_stock_quote
from app.services.tudata_provider import provider


load_dotenv()

app = FastAPI(
    title="StockWeb API",
    version="0.2.0",
    description="StockWeb 投研工作台后端。结构化数据优先来自 TuData，实时异动使用东方财富公开行情接口。",
)

origins = [
    item.strip()
    for item in os.getenv(
        "CORS_ORIGINS", "http://127.0.0.1:3000,http://localhost:3000"
    ).split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def invoke(fn: Callable[..., Any], *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # Includes missing token, TuData permission/rate-limit and upstream errors.
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def payload(
    rows: list[dict[str, Any]],
    *,
    source: str,
    trade_date: str | None = None,
    summary: dict[str, Any] | None = None,
    note: str | None = None,
):
    return {
        "meta": {
            "source": source,
            "trade_date": trade_date,
            "count": len(rows),
            "note": note,
        },
        "summary": summary or {},
        "rows": rows,
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "stockweb-api"}


# Legacy StockInfoWeb quote endpoints. These stay stable so existing Excel
# WEBSERVICE formulas and bookmarks keep working after the server cutover.
@app.get("/api/realtime-price/raw")
@app.get("/api/realtime-price/raw/{code}")
@app.get("/api/stock/price-val")
@app.get("/api/stock/price-val/{code}")
def realtime_price_raw(code: str | None = None):
    quote = get_single_realtime_stock_quote(code or "")
    return PlainTextResponse(str(quote["price"]) if quote and quote["price"] is not None else "0")


@app.get("/api/realtime-price")
@app.get("/api/stock/quote")
@app.get("/api/stock-price")
def realtime_price(
    code: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    codes: str | None = Query(default=None),
    raw: bool = Query(default=False),
):
    query_target = code or symbol or codes
    if not query_target:
        return {
            "code": 200,
            "message": "请提供股票代码，例如：/api/realtime-price?code=600519",
            "examples": ["/api/realtime-price?code=600519", "/api/realtime-price/raw?code=601939.SH"],
        }
    if any(separator in query_target for separator in (",", ";", " ")):
        quote_list = get_realtime_stock_quotes(query_target)
        return {"code": 200, "message": "success", "total": len(quote_list), "data": quote_list}
    quote = get_single_realtime_stock_quote(query_target)
    if raw:
        return PlainTextResponse(str(quote["price"]) if quote and quote["price"] is not None else "0")
    if quote:
        return {"code": 200, "message": "success", "data": quote}
    return {"code": 404, "message": f"未查询到股票 [{query_target}] 的实时行情数据", "data": None}


@app.get("/api/realtime-price/{code}")
@app.get("/api/stock/quote/{code}")
def realtime_price_by_path(code: str):
    quote = get_single_realtime_stock_quote(code)
    if quote:
        return {"code": 200, "message": "success", "data": quote}
    return {"code": 404, "message": f"未查询到股票 [{code}] 的实时行情数据", "data": None}


@app.get("/api/fund-flow/{code}/{dataset}")
def fund_flow(
    code: str,
    dataset: str,
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
):
    if dataset == "margin":
        rows = invoke(provider.margin_detail, code)
        return payload(rows, source="TuData margin_detail")
    if dataset == "block-trade":
        rows = invoke(provider.block_trade, code)
        return payload(rows, source="TuData block_trade")
    if dataset == "holders":
        rows = invoke(provider.holder_number, code)
        return payload(rows, source="TuData stk_holdernumber")
    if dataset == "dividends":
        rows = invoke(provider.dividends, code)
        return payload(rows, source="TuData dividend")
    if dataset == "moneyflow":
        rows = invoke(provider.moneyflow, code, 120)
        return payload(rows, source="TuData moneyflow", note="最近约 120 个交易日")
    if dataset == "chip-profile":
        rows = invoke(provider.chip_profile, code, 120)
        return payload(rows, source="TuData cyq_perf", note="筹码成本/胜率")
    if dataset == "chips":
        date, rows = invoke(provider.chip_distribution, code, trade_date)
        return payload(rows, source="TuData cyq_chips", trade_date=date)
    if dataset == "sector":
        rows = invoke(provider.sector_membership, code)
        return payload(
            rows,
            source="TuData dc_concept_cons / stock_basic",
            note="优先东财概念/行业成分；权限不足或无结果时回退到上市公司基础行业",
        )
    raise HTTPException(status_code=404, detail=f"未知资金面数据集：{dataset}")


@app.get("/api/limit-up/pool")
def limit_pool(
    kind: str = Query(pattern=r"^(up|broken|down)$"),
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
):
    date, rows = invoke(provider.limit_pool, kind, trade_date)
    return payload(
        rows,
        source="TuData limit_list_ths / kpl_list",
        trade_date=date,
        note="优先 THS 涨跌停榜单，权限不足时降级到 KPL 榜单",
    )


@app.get("/api/limit-up/ladder")
def limit_ladder(
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
):
    date, rows = invoke(provider.limit_ladder, trade_date)
    return payload(rows, source="TuData limit_step", trade_date=date)


@app.get("/api/limit-up/emotion")
def limit_emotion(
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
):
    date, summary, rows = invoke(provider.emotion, trade_date)
    return payload(
        rows,
        source="TuData limit_list_ths + limit_step",
        trade_date=date,
        summary=summary,
        note="晋级率按昨日连板股票在当日继续晋级计算",
    )


@app.get("/api/limit-up/intraday-changes")
def intraday_changes(
    limit: int = Query(default=500, ge=1, le=2000),
    direction: str | None = Query(default=None, pattern=r"^(偏强|偏弱)$"),
    event_type: str | None = Query(default=None),
):
    valid_types = {label for label, _weight in EVENT_TYPES.values()}
    if event_type and event_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"未知异动类型：{event_type}。支持：{', '.join(sorted(valid_types))}",
        )
    summary, rows = invoke(
        monitor_provider.intraday_changes,
        limit=limit,
        direction=direction,
        event_type=event_type,
    )
    return payload(
        rows,
        source="东方财富 getAllStockChanges",
        summary=summary,
        note="最近交易日盘口异动事件流；约 12 秒进程内缓存，盘中刷新可获得最新事件。",
    )


@app.get("/api/limit-up/focus-monitor")
def focus_monitor(
    limit: int = Query(default=80, ge=1, le=200),
    min_events: int = Query(default=2, ge=1, le=50),
):
    summary, rows = invoke(
        monitor_provider.focus_monitor,
        limit=limit,
        min_events=min_events,
    )
    return payload(
        rows,
        source="东方财富盘口异动 + 腾讯实时行情",
        summary=summary,
        note=(
            "重点监控为 StockWeb 工程规则：按盘中异动频次、异动类型权重和方向聚合排序，"
            "用于盯盘，不是证券交易所官方监管/重点监控名单。"
        ),
    )


@app.get("/api/daily-review/{dataset}")
def daily_review(
    dataset: str,
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
):
    if dataset == "overview":
        date, rows = invoke(provider.market_overview, trade_date)
        return payload(rows, source="TuData index_daily", trade_date=date)
    if dataset == "emotion":
        date, summary, rows = invoke(provider.emotion, trade_date)
        return payload(
            rows,
            source="TuData limit_list_ths + limit_step",
            trade_date=date,
            summary=summary,
        )
    if dataset == "turnover-top20":
        date, rows = invoke(provider.turnover_top20, trade_date)
        return payload(rows, source="TuData daily", trade_date=date)
    if dataset == "global":
        date, rows = invoke(provider.global_indices, trade_date)
        return payload(rows, source="TuData index_global", trade_date=date)
    if dataset == "sector-flow":
        date, rows = invoke(provider.sector_flow, trade_date)
        return payload(
            rows,
            source="TuData moneyflow_ind_dc / moneyflow_ind_ths",
            trade_date=date,
        )
    raise HTTPException(status_code=404, detail=f"未知每日复盘数据集：{dataset}")
