"use client";

import { Workbench } from "@/components/workbench";

const withDate = (path: string, value: string) => {
  const date = value.replace(/\D/g, "");
  return date ? `${path}${path.includes("?") ? "&" : "?"}trade_date=${date}` : path;
};

export default function LimitUpPage() {
  return (
    <Workbench
      kicker="LIMIT UP"
      title="打板"
      subtitle="涨停、炸板、跌停、连板梯队、短线情绪、重点监控与日内异动集中查看。结构化榜单优先使用 TuData，盘中异动事件流使用东方财富实时行情。"
      inputPlaceholder="交易日 YYYYMMDD；留空自动使用最近交易日"
      helper="日期输入只作用于盘后类榜单；重点监控与日内异动始终读取最近交易日/当前盘中的最新事件。重点监控是 StockWeb 按异动频次和强度生成的盯盘池，不是交易所官方监管名单。"
      actions={[
        { label: "涨停池", endpoint: (date) => withDate("/limit-up/pool?kind=up", date) },
        { label: "炸板池", endpoint: (date) => withDate("/limit-up/pool?kind=broken", date) },
        { label: "跌停池", endpoint: (date) => withDate("/limit-up/pool?kind=down", date) },
        { label: "连板梯队", endpoint: (date) => withDate("/limit-up/ladder", date) },
        { label: "情绪温度", endpoint: (date) => withDate("/limit-up/emotion", date) },
        { label: "重点监控", endpoint: () => "/limit-up/focus-monitor?limit=80&min_events=2" },
        { label: "日内异动", endpoint: () => "/limit-up/intraday-changes?limit=500" },
      ]}
      infoCards={[
        { title: "封板率 / 炸板率", body: "由当日涨停池与炸板池数量直接计算。" },
        { title: "重点监控", body: "聚合同一股票的多类盘中异动，按异动类型权重、频次和方向生成监控分。" },
        { title: "日内异动", body: "覆盖火箭发射、快速反弹、大笔买卖、封/开涨跌停、高台跳水等盘口事件。" },
      ]}
    />
  );
}
