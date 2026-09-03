from __future__ import annotations

import os
from typing import Any, Callable

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.services.tushare_provider import provider


load_dotenv()

app = FastAPI(
    title="StockWeb API",
    version="0.1.0",
    description="StockWeb 投研工作台后端。第一阶段数据优先来自 Tushare。",
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
        # Includes missing token, Tushare permission/rate-limit and upstream errors.
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


@app.get("/api/fund-flow/{code}/{dataset}")
def fund_flow(
    code: str,
    dataset: str,
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
):
    if dataset == "margin":
        rows = invoke(provider.margin_detail, code)
        return payload(rows, source="Tushare margin_detail")
    if dataset == "block-trade":
        rows = invoke(provider.block_trade, code)
        return payload(rows, source="Tushare block_trade")
    if dataset == "holders":
        rows = invoke(provider.holder_number, code)
        return payload(rows, source="Tushare stk_holdernumber")
    if dataset == "dividends":
        rows = invoke(provider.dividends, code)
        return payload(rows, source="Tushare dividend")
    if dataset == "moneyflow":
        rows = invoke(provider.moneyflow, code, 120)
        return payload(rows, source="Tushare moneyflow", note="最近约 120 个交易日")
    if dataset == "chip-profile":
        rows = invoke(provider.chip_profile, code, 120)
        return payload(rows, source="Tushare cyq_perf", note="筹码成本/胜率")
    if dataset == "chips":
        date, rows = invoke(provider.chip_distribution, code, trade_date)
        return payload(rows, source="Tushare cyq_chips", trade_date=date)
    raise HTTPException(status_code=404, detail=f"未知资金面数据集：{dataset}")


@app.get("/api/limit-up/pool")
def limit_pool(
    kind: str = Query(pattern=r"^(up|broken|down)$"),
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
):
    date, rows = invoke(provider.limit_pool, kind, trade_date)
    return payload(
        rows,
        source="Tushare limit_list_ths / kpl_list",
        trade_date=date,
        note="优先 THS 涨跌停榜单，权限不足时降级到 KPL 榜单",
    )


@app.get("/api/limit-up/ladder")
def limit_ladder(
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
):
    date, rows = invoke(provider.limit_ladder, trade_date)
    return payload(rows, source="Tushare limit_step", trade_date=date)


@app.get("/api/limit-up/emotion")
def limit_emotion(
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
):
    date, summary, rows = invoke(provider.emotion, trade_date)
    return payload(
        rows,
        source="Tushare limit_list_ths + limit_step",
        trade_date=date,
        summary=summary,
        note="晋级率按昨日连板股票在当日继续晋级计算",
    )


@app.get("/api/daily-review/{dataset}")
def daily_review(
    dataset: str,
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
):
    if dataset == "overview":
        date, rows = invoke(provider.market_overview, trade_date)
        return payload(rows, source="Tushare index_daily", trade_date=date)
    if dataset == "emotion":
        date, summary, rows = invoke(provider.emotion, trade_date)
        return payload(
            rows,
            source="Tushare limit_list_ths + limit_step",
            trade_date=date,
            summary=summary,
        )
    if dataset == "turnover-top20":
        date, rows = invoke(provider.turnover_top20, trade_date)
        return payload(rows, source="Tushare daily", trade_date=date)
    if dataset == "global":
        date, rows = invoke(provider.global_indices, trade_date)
        return payload(rows, source="Tushare index_global", trade_date=date)
    if dataset == "sector-flow":
        date, rows = invoke(provider.sector_flow, trade_date)
        return payload(
            rows,
            source="Tushare moneyflow_ind_dc / moneyflow_ind_ths",
            trade_date=date,
        )
    raise HTTPException(status_code=404, detail=f"未知每日复盘数据集：{dataset}")
