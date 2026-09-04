# StockWeb

个人股票投研工作台。第一阶段先实现三个页面：

- **资金面 / 筹码**
- **打板**
- **每日复盘**

技术栈：

- Frontend: Next.js + TypeScript
- Backend: Python + FastAPI
- Database: MySQL + SQLAlchemy（第一版先预留连接，Tushare 可直接查询）
- Market data: Tushare 优先

## 项目结构

```text
StockWeb/
├── frontend/                     # Next.js 页面
│   ├── app/
│   │   ├── fund-flow/            # 资金面 / 筹码
│   │   ├── limit-up/             # 打板
│   │   └── daily-review/         # 每日复盘
│   └── components/
├── backend/
│   └── app/
│       ├── main.py               # FastAPI 路由
│       ├── services/
│       │   └── tushare_provider.py
│       └── core/
│           └── database.py       # MySQL / SQLAlchemy
├── .env.example
└── .github/workflows/ci.yml
```

## 第一版页面与数据源

### 1. 资金面 / 筹码

| 页面功能 | Tushare 数据 |
|---|---|
| 融资融券 | `margin_detail` |
| 大宗交易 | `block_trade` |
| 股东户数 | `stk_holdernumber` |
| 分红送转 | `dividend` |
| 资金流 120 日 | `moneyflow` |
| 筹码成本 / 获利比例 | `cyq_perf` |
| 筹码分布 | `cyq_chips` |
| 板块归属 | 优先 `dc_concept_cons`，回退 `stock_basic` |
| 分钟资金流 | 第一版暂不伪造；等待接入分钟级第二数据源 |

### 2. 打板

| 页面功能 | 数据 / 计算 |
|---|---|
| 涨停池 | 优先 `limit_list_ths`，权限不足时尝试 `kpl_list` |
| 炸板池 | 同上 |
| 跌停池 | 同上 |
| 连板梯队 | `limit_step` |
| 情绪温度 | 涨停家数、炸板家数、跌停家数、封板率、炸板率、最高连板、晋级率 |
| 重点监控 | 第一版保留入口，等待第二数据源 |
| 日内异动 | 第一版保留入口，等待盘中异动数据源 |

晋级率当前定义：昨日连板股票中，当日继续提高连板级别的股票占比。

### 3. 每日复盘

| 页面功能 | Tushare 数据 |
|---|---|
| 市场总览 | `index_daily` |
| 短线情绪 | 复用打板情绪模块 |
| 成交额 TOP20 | `daily` + `stock_basic` |
| 全球指数 | `index_global` |
| 板块资金 | 优先 `moneyflow_ind_dc`，回退 `moneyflow_ind_ths` |

市场总览目前包括：上证指数、深证成指、创业板指、沪深 300。

全球指数目前包括：道琼斯、标普 500、纳斯达克、恒生指数、恒生科技。

## 数据层原则

前端不直接调用 Tushare。数据流为：

```text
Next.js
   ↓ HTTP
FastAPI
   ↓
TushareProvider
   ↓
Tushare
```

这样后续可以改为：

```text
Next.js
   ↓
FastAPI
   ↓
Service
   ├── MySQL 缓存 / 历史数据
   ├── Tushare
   └── 第二数据源
```

页面接口不需要跟着数据源变化而重写。

## API 凭据

不要把 Token 提交到 GitHub。

复制环境变量模板：

```bash
cp .env.example .env
```

然后填写：

```dotenv
TUSHARE_TOKEN=你的_Tushare_Token
DATABASE_URL=mysql+pymysql://stockweb:你的密码@127.0.0.1:3306/stockweb?charset=utf8mb4
CORS_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
```

不同 Tushare 特色数据接口有不同积分要求。如果某项接口权限不足，FastAPI 会返回明确错误；已经实现回退策略的接口会优先尝试备用 Tushare 数据集。

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

首页会自动进入：

```text
/fund-flow
```

三个页面：

```text
/fund-flow
/limit-up
/daily-review
```

## MySQL

第一版已经建立 SQLAlchemy MySQL 连接配置，但页面查询暂时不要求 MySQL 在线，因此可以先验证 UI、FastAPI 和 Tushare 数据链路。

下一阶段再把需要高频读取的日频数据落到 MySQL，主要目的：

1. 减少重复调用 Tushare；
2. 保留历史快照；
3. 支持更复杂的复盘统计；
4. 给未来的定时任务和自定义模型提供统一数据层。

建议数据库名称：

```text
stockweb
```

## 服务器部署建议

如果服务器已有另一个后端，可以继续共存。例如：

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

- `重点监控`、`日内异动`、`分钟资金流`：参考网站有对应功能，但 Tushare 暂无完全等价的标准接口，因此第一版不使用虚假/mock 行情填充。
- MySQL：连接层已经准备好，缓存表和定时落库将在下一阶段加入。
- 页面第一版以数据可用性、接口完整性和移动端可读性为优先；图表化和更细的交互将在后续迭代加入。

> 本项目仅用于个人研究与数据分析，不构成投资建议。
