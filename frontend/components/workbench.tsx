"use client";

import { useMemo, useState } from "react";

type Row = Record<string, unknown>;
type ApiResponse = {
  meta: { source?: string; trade_date?: string | null; count?: number; note?: string | null };
  summary: Record<string, unknown>;
  rows: Row[];
};

type Action = {
  label: string;
  endpoint: (value: string) => string;
  disabled?: boolean;
  disabledHint?: string;
};

type Props = {
  kicker: string;
  title: string;
  subtitle: string;
  inputPlaceholder?: string;
  inputRequired?: boolean;
  helper?: string;
  actions: Action[];
  infoCards?: { title: string; body: string }[];
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8001/api";

const LABELS: Record<string, string> = {
  trade_date: "交易日",
  ts_code: "代码",
  name: "名称",
  price: "价格",
  pct_chg: "涨跌幅%",
  pct_change: "涨跌幅%",
  close: "收盘",
  pre_close: "昨收",
  open: "开盘",
  high: "最高",
  low: "最低",
  amount: "成交额(千元)",
  amount_yi: "成交额(亿元)",
  vol: "成交量",
  turnover: "成交额",
  turnover_rate: "换手率%",
  open_num: "开板次数",
  lu_desc: "涨停原因",
  tag: "连板标签",
  status: "板型",
  first_lu_time: "首次涨停",
  last_lu_time: "最后涨停",
  limit_order: "封单量",
  limit_amount: "封单额",
  rzye: "融资余额",
  rqye: "融券余额",
  rzmre: "融资买入额",
  rzche: "融资偿还额",
  rqyl: "融券余量",
  buyer: "买方营业部",
  seller: "卖方营业部",
  ann_date: "公告日",
  end_date: "截止日",
  holder_num: "股东户数",
  cash_div: "每股分红",
  stk_div: "每股送转",
  buy_sm_amount: "小单买入(万元)",
  sell_sm_amount: "小单卖出(万元)",
  buy_md_amount: "中单买入(万元)",
  sell_md_amount: "中单卖出(万元)",
  buy_lg_amount: "大单买入(万元)",
  sell_lg_amount: "大单卖出(万元)",
  buy_elg_amount: "特大单买入(万元)",
  sell_elg_amount: "特大单卖出(万元)",
  net_mf_amount: "净流入(万元)",
  his_low: "历史最低",
  his_high: "历史最高",
  cost_5pct: "5%成本",
  cost_15pct: "15%成本",
  cost_50pct: "50%成本",
  cost_85pct: "85%成本",
  cost_95pct: "95%成本",
  weight_avg: "加权成本",
  winner_rate: "获利比例%",
  percent: "筹码占比%",
  nums: "连板数",
  nums_numeric: "连板数值",
  industry: "行业",
  lead_stock: "领涨股",
  net_amount: "主力净流入(元)",
  net_amount_yi: "主力净流入(亿元)",
  net_buy_amount: "净流入(亿元)",
};

function displayValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "--";
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toLocaleString("zh-CN") : value.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function Workbench({ kicker, title, subtitle, inputPlaceholder, inputRequired = false, helper, actions, infoCards = [] }: Props) {
  const [value, setValue] = useState("");
  const [active, setActive] = useState<string | null>(null);
  const [data, setData] = useState<ApiResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const columns = useMemo(() => {
    if (!data?.rows?.length) return [];
    const keys: string[] = [];
    data.rows.slice(0, 20).forEach((row) => {
      Object.keys(row).forEach((key) => {
        if (!keys.includes(key)) keys.push(key);
      });
    });
    return keys;
  }, [data]);

  async function run(action: Action) {
    if (action.disabled) return;
    if (inputRequired && !value.trim()) {
      setError("请先输入股票代码。")
      return;
    }

    setActive(action.label);
    setLoading(true);
    setError(null);
    setData(null);
    try {
      const endpoint = action.endpoint(value.trim());
      const response = await fetch(`${API_BASE}${endpoint}`, { cache: "no-store" });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(body?.detail || `请求失败：HTTP ${response.status}`);
      }
      setData(body as ApiResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "请求失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <section>
        <div className="page-kicker">{kicker}</div>
        <h1 className="page-title">{title}</h1>
        <p className="page-subtitle">{subtitle}</p>
      </section>

      <section className="query-panel">
        <div className="query-row">
          {inputPlaceholder && (
            <input
              className="query-input"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder={inputPlaceholder}
              onKeyDown={(event) => {
                if (event.key === "Enter" && actions[0]) run(actions[0]);
              }}
            />
          )}
        </div>
        <div className="action-grid">
          {actions.map((action) => (
            <button
              className={active === action.label ? "action-button active" : "action-button"}
              key={action.label}
              onClick={() => run(action)}
              disabled={action.disabled || loading}
              title={action.disabledHint}
            >
              {action.label}
            </button>
          ))}
        </div>
        {helper && <div className="helper-text">{helper}</div>}
      </section>

      {infoCards.length > 0 && (
        <section className="info-strip">
          {infoCards.map((card) => (
            <div className="info-card" key={card.title}>
              <strong>{card.title}</strong>
              <span>{card.body}</span>
            </div>
          ))}
        </section>
      )}

      <section className="result-section">
        {loading && <div className="loading-state">正在读取数据…</div>}
        {error && <div className="error-state">{error}</div>}
        {!loading && !error && !data && <div className="empty-state">选择上方查询项后显示数据。</div>}

        {!loading && !error && data && (
          <>
            <div className="result-head">
              <div className="result-title">{active || "查询结果"}</div>
              <div className="result-meta">
                {data.meta?.trade_date ? `数据日 ${data.meta.trade_date} · ` : ""}
                {data.meta?.count ?? data.rows?.length ?? 0} 条
              </div>
            </div>

            {Object.keys(data.summary || {}).length > 0 && (
              <div className="stat-grid">
                {Object.entries(data.summary).map(([key, item]) => (
                  <div className="stat-card" key={key}>
                    <div className="stat-label">{key}</div>
                    <div className="stat-value">{displayValue(item)}</div>
                  </div>
                ))}
              </div>
            )}

            {data.rows?.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      {columns.map((column) => <th key={column}>{LABELS[column] || column}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((row, index) => (
                      <tr key={`${String(row.ts_code || "row")}-${String(row.trade_date || index)}-${index}`}>
                        {columns.map((column) => <td key={column}>{displayValue(row[column])}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty-state">该查询没有返回数据。</div>
            )}

            <div className="source-note">
              数据源：{data.meta?.source || "--"}
              {data.meta?.note ? ` · ${data.meta.note}` : ""}
            </div>
          </>
        )}
      </section>
    </>
  );
}
