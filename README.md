# StockWeb

个人股票投研工作台。当前优先实现三个页面：

- **资金面 / 筹码**
- **打板**
- **每日复盘**

技术栈：

- Frontend: Next.js + TypeScript
- Backend: Python + FastAPI
- Database: MySQL + SQLAlchemy（当前先预留连接层）
- Structured market data: TuData 优先
- Realtime quote: 腾讯行情
- Intraday anomaly stream: 东方财富盘口异动

## 项目结构

```text
StockWeb/
├── frontend/
│   ├── app/
│   │   ├── fund-flow/            # 资金面 / 筹码
│   │   ├── limit-up/             # 打板 / 重点监控 / 日内异动
│   │   └── daily-review/         # 每日复盘
│   └── components/
├── backend/
│   └── app/
│       ├── main.py               # FastAPI 路由
│       ├── services/
│       │   ├── tudata_provider.py
│       │   ├── realtime_quote.py
│       │   └── eastmoney_monitor.py
│       └── core/
│           └── database.py       # MySQL / SQLAlchemy
├── .env.example
└── .github/workflows/ci.yml
```

## 页面与数据源

### 1. 资金面 / 筹码

| 页面功能 | 数据 |
|---|---|
| 融资融券 | TuData `margin_detail` |
| 大宗交易 | TuData `block_trade` |
| 股东户数 | TuData `stk_holdernumber` |
| 分红送转 | TuData `dividend` |
| 资金流 120 日 | TuData `moneyflow` |
| 筹码成本 / 获利比例 | TuData `cyq_perf` |
| 筹码分布 | TuData `cyq_chips` |
| 板块归属 | 优先 TuData `dc_concept_cons`，回退 `stock_basic` |
| 分钟资金流 | 尚未实现 |

### 2. 打板

| 页面功能 | 数据 / 计算 |
|---|---|
| 涨停池 | 优先 TuData `limit_list_ths`，权限不足时尝试 `kpl_list` |
| 炸板池 | 同上 |
| 跌停池 | 同上 |
| 连板梯队 | TuData `limit_step` |
| 情绪温度 | 涨停家数、炸板家数、跌停家数、封板率、炸板率、最高连板、晋级率 |
| 重点监控 | 东方财富盘口异动聚合 + 腾讯实时行情 |
| 日内异动 | 东方财富 `getAllStockChanges` |

晋级率当前定义：昨日连板股票中，当日继续提高连板级别的股票占比。

#### 日内异动

一次请求读取东方财富最近交易日的 22 类盘口异动，包括：

```text
火箭发射 / 快速反弹 / 大笔买入 / 封涨停板 / 打开跌停板 / 有大买盘
竞价上涨 / 高开5日线 / 向上缺口 / 60日新高 / 60日大幅上涨
加速下跌 / 高台跳水 / 大笔卖出 / 封跌停板 / 打开涨停板 / 有大卖盘
竞价下跌 / 低开5日线 / 向下缺口 / 60日新低 / 60日大幅下跌
```

后端按时间倒序返回事件流，并使用约 12 秒的进程内缓存，避免在页面切换时高频重复访问上游。

API：

```text
GET /api/limit-up/intraday-changes?limit=500
GET /api/limit-up/intraday-changes?direction=偏强
GET /api/limit-up/intraday-changes?event_type=火箭发射
```

#### 重点监控

`重点监控` 是 StockWeb 自己的盯盘规则，不是证券交易所官方重点监控证券名单。

计算逻辑：

1. 按股票聚合当日盘口异动；
2. 对不同异动类型设置强弱方向和权重；
3. 单一类型出现次数做上限截断，防止“大笔买入/卖出”等高频事件单独支配排名；
4. 根据异动强度、异动频次、异动类型数量计算 `monitor_score`；
5. 根据强弱方向净权重标记为 `偏强 / 偏弱 / 双向异动`；
6. 对排名靠前股票一次性补充腾讯实时价格和实时涨跌幅。

API：

```text
GET /api/limit-up/focus-monitor?limit=80&min_events=2
```

### 3. 每日复盘

| 页面功能 | 数据 |
|---|---|
| 市场总览 | TuData `index_daily` |
| 短线情绪 | 复用打板情绪模块 |
| 成交额 TOP20 | TuData `daily` + `stock_basic` |
| 全球指数 | TuData `index_global` |
| 板块资金 | 优先 `moneyflow_ind_dc`，回退 `moneyflow_ind_ths` |

市场总览目前包括：上证指数、深证成指、创业板指、沪深 300。

全球指数目前包括：道琼斯、标普 500、纳斯达克、恒生指数、恒生科技。

## 数据层原则

前端不直接访问任何外部行情源。当前数据流：

```text
Next.js
   ↓ HTTP
FastAPI
   ↓
Service Layer
   ├── TuDataProvider            # 日频/特色结构化数据
   ├── EastmoneyMonitorProvider # 盘口异动
   ├── Tencent Quote            # 实时价格
   └── MySQL                    # 后续缓存/历史快照
```

这样页面接口不会因为底层数据源调整而重写。

## API 凭据

不要把 Token 提交到 GitHub。

复制环境变量模板：

```bash
cp .env.example .env
```

然后填写：

```dotenv
TUDATA_TOKEN=你的_TuData_Token
DATABASE_URL=mysql+pymysql://stockweb:你的密码@127.0.0.1:3306/stockweb?charset=utf8mb4
CORS_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
```

东方财富盘口异动和腾讯实时行情当前不需要额外 Token。

## 本地运行

### Backend

建议 Python 3.12。

```bash
cd backend
python -m venv .venv
```

Linux / macOS：

```bash
source .venv/bin/activate
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
```

安装依赖并启动：

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

健康检查：

```text
http://127.0.0.1:8001/health
```

FastAPI 文档：

```text
http://127.0.0.1:8001/docs
```

### Frontend

```bash
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

打开：

```text
http://127.0.0.1:3000
```

页面：

```text
/fund-flow
/limit-up
/daily-review
```

## MySQL

当前已经建立 SQLAlchemy MySQL 连接配置，但页面查询暂时不要求 MySQL 在线。后续建议把高频读取的数据和每日快照落库，用于：

1. 减少重复外部请求；
2. 保留历史快照；
3. 支持更复杂的复盘统计；
4. 给定时任务、自定义模型和告警提供统一数据层。

建议数据库名称：`stockweb`。

## 服务器部署建议

同一台服务器可与现有后端共存，例如：

```text
现有后端       127.0.0.1:8000
StockWeb API   127.0.0.1:8001
StockWeb Web   127.0.0.1:3000
MySQL          127.0.0.1:3306
Nginx          :80 / :443
```

生产环境建议只让 Nginx 暴露 80/443，不直接把 8001 和 3000 暴露到公网。

## CI

GitHub Actions 会执行：

- Python 依赖安装与语法编译；
- FastAPI 应用导入检查；
- Next.js production build。

## 当前边界

- `重点监控` 是工程化盯盘评分，不等同于交易所官方重点监控名单；交易所此类名单并非稳定公开数据源。
- `日内异动` 依赖东方财富公开行情端点，若上游接口结构变化需要同步适配。
- `分钟资金流` 尚未实现。
- MySQL 当前主要是连接层，缓存表和定时落库将在后续加入。

> 本项目仅用于个人研究与数据分析，不构成投资建议。
