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
      subtitle="涨停、炸板、跌停、连板梯队与短线情绪集中查看。榜单优先使用 Tushare 同花顺涨跌停数据，权限不足时后端会尝试 Tushare 开盘啦榜单作为降级来源。"
      inputPlaceholder="交易日 YYYYMMDD；留空自动使用最近交易日"
      helper="重点监控和日内异动在参考站属于东财专有数据；Tushare 暂无完全等价接口，因此第一版保留入口但不伪造数据，后续再接第二数据源。"
      actions={[
        { label: "涨停池", endpoint: (date) => withDate("/limit-up/pool?kind=up", date) },
        { label: "炸板池", endpoint: (date) => withDate("/limit-up/pool?kind=broken", date) },
        { label: "跌停池", endpoint: (date) => withDate("/limit-up/pool?kind=down", date) },
        { label: "连板梯队", endpoint: (date) => withDate("/limit-up/ladder", date) },
        { label: "情绪温度", endpoint: (date) => withDate("/limit-up/emotion", date) },
        { label: "重点监控", endpoint: () => "", disabled: true, disabledHint: "待接东财重点监控数据" },
        { label: "日内异动", endpoint: () => "", disabled: true, disabledHint: "待接盘中异动第二数据源" },
      ]}
      infoCards={[
        { title: "封板率 / 炸板率", body: "由当日涨停池与炸板池数量直接计算。" },
        { title: "连板高度", body: "优先读取 Tushare limit_step 连板天梯。" },
        { title: "晋级率", body: "按昨日连板股在今日继续提高连板级别的比例计算。" },
      ]}
    />
  );
}
