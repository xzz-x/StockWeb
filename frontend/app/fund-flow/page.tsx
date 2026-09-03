import { Workbench } from "@/components/workbench";

export default function FundFlowPage() {
  return (
    <Workbench
      kicker="FUND FLOW / CHIPS"
      title="资金面 / 筹码"
      subtitle="融资融券、大宗交易、股东户数、分红送转、个股资金流、筹码成本与板块归属集中在同一页面。第一版优先使用 Tushare，接口与展示层解耦，后续可以直接增加 MySQL 缓存或第二数据源。"
      inputPlaceholder="输入股票代码，如 600519 或 600519.SH"
      inputRequired
      helper="输入股票代码后选择查询类型。筹码和东财概念成分等特色数据需要对应的 Tushare 积分权限；分钟资金流暂无标准 Tushare 等价接口，第一版不伪造数据。"
      actions={[
        { label: "融资融券", endpoint: (code) => `/fund-flow/${code}/margin` },
        { label: "大宗交易", endpoint: (code) => `/fund-flow/${code}/block-trade` },
        { label: "股东户数", endpoint: (code) => `/fund-flow/${code}/holders` },
        { label: "分红送转", endpoint: (code) => `/fund-flow/${code}/dividends` },
        { label: "资金流120日", endpoint: (code) => `/fund-flow/${code}/moneyflow` },
        { label: "筹码成本", endpoint: (code) => `/fund-flow/${code}/chip-profile` },
        { label: "筹码分布", endpoint: (code) => `/fund-flow/${code}/chips` },
        { label: "板块归属", endpoint: (code) => `/fund-flow/${code}/sector` },
        { label: "分钟资金流", endpoint: () => "", disabled: true, disabledHint: "待接分钟级第二数据源" },
      ]}
      infoCards={[
        { title: "两融", body: "融资余额、融资买入/偿还、融券余额与余量。" },
        { title: "资金流", body: "按大中小单拆分，默认展示最近约 120 个交易日。" },
        { title: "筹码", body: "展示成本分位、加权平均成本、获利比例及价格档筹码占比。" },
        { title: "板块归属", body: "优先读取东财概念/行业成分；权限不足时回退到上市公司基础行业。" },
      ]}
    />
  );
}
