import { Workbench } from "@/components/workbench";

const withDate = (path: string, value: string) => {
  const date = value.replace(/\D/g, "");
  return date ? `${path}?trade_date=${date}` : path;
};

export default function DailyReviewPage() {
  return (
    <Workbench
      kicker="DAILY REVIEW"
      title="每日复盘"
      subtitle="把大盘指数、全球市场、短线情绪、成交额 TOP20 和板块资金流放到一个复盘入口中，避免在多个行情页面之间切换。"
      inputPlaceholder="交易日 YYYYMMDD；留空自动使用最近可用数据"
      helper="A 股相关数据按最近交易日读取；全球指数按目标日期向前寻找最近可用交易数据。"
      actions={[
        { label: "市场总览", endpoint: (date) => withDate("/daily-review/overview", date) },
        { label: "短线情绪", endpoint: (date) => withDate("/daily-review/emotion", date) },
        { label: "成交额TOP20", endpoint: (date) => withDate("/daily-review/turnover-top20", date) },
        { label: "全球指数", endpoint: (date) => withDate("/daily-review/global", date) },
        { label: "板块资金", endpoint: (date) => withDate("/daily-review/sector-flow", date) },
      ]}
      infoCards={[
        { title: "大盘", body: "上证指数、深证成指、创业板指、沪深300。" },
        { title: "全球", body: "道琼斯、标普500、纳斯达克、恒生指数、恒生科技。" },
        { title: "热点资金", body: "行业板块主力净流入排名，优先使用东财板块资金接口。" },
      ]}
    />
  );
}
