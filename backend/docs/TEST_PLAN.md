# 党建工作智能体 — 测试文档（测试方案与规格）

> 文档类型：测试方案 / 测试规格　版本：v1.0　生成日期：2026-10-09
> 适用代码：`master`（含 PR #21 合并，本机实测运行提交 `cee1327`）
> 关联文档：[TEST_REPORT.md](./TEST_REPORT.md)（Day1–Day5 测试结果报告）、[PROJECT_STATUS_REPORT.md](./PROJECT_STATUS_REPORT.md)

---

## 1. 目的与范围

本文档规定本项目的测试策略、环境、用例组织、执行方式与验收标准，作为开发、联调与验收的统一依据。

- **被测系统**：高校党建工作智能体（FastAPI + SQLAlchemy 2.0 + PostgreSQL/pgvector + Redis + LangChain/LangGraph）。
- **测试范围**：
  - 配置与缓存、数据模型与 Alembic 迁移
  - 鉴权（JWT/bcrypt）、RBAC 权限矩阵、数据范围、脱敏、审计、租户隔离、敏感数据出网闸门
  - RAG 检索链路（向量/关键词/混合/重排/无依据）、问答链六阶段、引用核验、会话、追问改写
  - LLM 模型注册/路由/出网网关
  - 党员发展状态规则
  - HTTP 集成（登录、知识入库、党员接口、LangGraph、问答链、迁移）
- **不在范围**：前端（`frontend/`，独立工程）、压力/性能压测（见 §9 遗留）、第三方 DashScope 服务自身的 SLA。

---

## 2. 参考与术语

| 项 | 说明 |
| --- | --- |
| 测试框架 | pytest 7.4.4 + pytest-asyncio 0.23.3（`asyncio_mode=auto`）|
| 覆盖工具 | pytest-cov 4.1.0，源码范围 `app`，输出 `htmlcov/` |
| 断言辅助 | pytest-mock 3.12.0、httpx 0.26.0（ASGI 直连）|
| 分层 | 单元（unit）/ 集成（integration）/ 安全（security）/ 离线评测（evaluation）|
| 标记 | `pytestmark = pytest.mark.<unit\|integration\|security>`；`@pytest.mark.asyncio`；`@pytest.mark.parametrize` |

---

## 3. 测试策略

### 3.1 分层策略

| 层次 | 目录 | 目标 | 依赖 | 数量（见 §5）|
| --- | --- | --- | --- | --- |
| 单元测试 | `tests/unit/` | 纯逻辑/规则/算法，无外部 IO（Redis/DB 用内存假实现） | 无 | 192 |
| 集成测试 | `tests/integration/` | 真实 HTTP/DB/迁移/链路端到端 | PostgreSQL（可选 Redis） | 24 |
| 安全测试 | `tests/security/` | 权限、租户隔离、数据出网等攻防边界 | 部分需 DB | 18 |
| 离线评测 | `tests/evaluation/` | RAG 检索/问答质量指标（Recall/MRR/Precision） | 真实库 + 向量化 + DashScope | 样本集 |

> 源码内共定义 **234 个 `test_*` 函数**；经 `@pytest.mark.parametrize` 展开后实际收集约 **237 个用例**（与 [TEST_REPORT.md](./TEST_REPORT.md) 一致，全通过）。

### 3.2 标记与筛选

| 标记 | 归属 | 说明 |
| --- | --- | --- |
| `integration` | `tests/integration/` 中的 4 个文件 | `test_auth_api`、`test_db_migration`、`test_knowledge_api`、`test_member_flow` |
| `security` | `tests/security/` 的 3 个文件 | `test_data_egress`、`test_permission`、`test_tenant_isolation` |
| `unit` / `slow` / `asyncio` | 在 `pyproject.toml` 中声明 | `unit` 未在用例上显式标注（按目录区分）；`slow` 暂无用例 |

> ⚠️ 注意：`test_llm_integration.py` 虽属集成目录，但**未打 `integration` 标记**（见 §10 风险 R-2）；`pytest -m slow` 目前**选不到任何用例**。

### 3.3 测试原则

1. **不依赖真实外部服务**：单元测试用内存假缓存 / mock LLM；集成测试连真实 pgvector 库。
2. **可重复**：`conftest.py` 提供 session 级 `event_loop`；租户上下文用 autouse fixture 清理，避免跨用例污染。
3. **失败即阻断**：任何 layer 出现 failed/error 视为验收不通过。
4. **真实数据验证**：关键链路（登录、入库、迁移）需在真实 PG16+pgvector 上跑通，而非仅 mock。

---

## 4. 测试环境

### 4.1 软件与依赖

| 项 | 要求 | 本机实测 |
| --- | --- | --- |
| Python | **≥ 3.11**（推荐 3.11/3.12，**避免 3.13**，部分依赖轮子兼容风险） | 3.11.15 可用；默认 3.13.9 |
| PostgreSQL | `pgvector/pgvector:pg16`（含 `vector`/`pg_trgm`/`uuid-ossp` + `chinese_zh` 检索配置） | `party-agent-postgres-dev`，宿主端口 **5433** |
| Redis | 7.x（会话/缓存；单元测试用内存假实现） | `party-agent-redis-dev`，宿主端口 **16379** |
| DashScope | `DASHSCOPE_API_KEY`（Embedding/Reranker/LLM；离线评测需真实 Key） | `.env` 已配置 |
| 依赖安装 | `pip install -r requirements-dev.txt`（含 `-r requirements.txt`） | — |

### 4.2 运行形态（二选一）

**A. Docker（推荐，最省事）**
```powershell
# 依赖（Postgres 已在跑；启动 Redis）
docker start party-agent-redis-dev
# 应用（注意：Windows 下不要加 --reload，见 §10 R-6）
docker run -d --name party-agent-app-run --network dangjian-agent_party-agent-dev-network `
  -p 18000:8000 -e DATABASE_URL=postgresql+asyncpg://party_user:dev_password@postgres:5432/party_agent_dev `
  -e REDIS_URL=redis://redis:6379/0 -e ENV=development --env-file .env dangjian-agent-app:latest `
  uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**B. 本地 venv（PyCharm 调试用）**
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
# 注意端口：本机 5432/6379/8000 被其他项目占用，需覆盖为 5433/16379/自定义端口
$env:DATABASE_URL="postgresql+asyncpg://party_user:dev_password@localhost:5433/party_agent_dev"
$env:REDIS_URL="redis://localhost:16379/0"
uvicorn app.main:app --reload --port 8000
```

### 4.3 环境变量（测试相关）

| 变量 | 用途 | 集成测试要求 |
| --- | --- | --- |
| `DATABASE_URL` | 真实库连接（异步 `+asyncpg`） | **必须**，未设置时 DB 集成测试自动跳过 |
| `REDIS_URL` | 缓存/会话 | 可选（失败降级） |
| `DASHSCOPE_API_KEY` | 向量化/重排/LLM | 离线评测必须 |
| `ENV` | `development`/`testing` | 建议 `testing` |
| `NO_EVIDENCE_THRESHOLD` | 无依据判定阈值 | 可选，默认 0.5 |

---

## 5. 测试资产清单

### 5.1 单元测试 `tests/unit/`（192）

| 文件 | 用例 | 覆盖点 |
| --- | --- | --- |
| `test_config.py` | 10 | 配置加载、ENV/日志级别校验、租户配置覆盖 |
| `test_cache.py` | 13 | 缓存读写、TTL、序列化、降级 |
| `test_db_models.py` | 10 | ORM 元数据、表名、主键默认值、关系 |
| `test_migrations.py` | 2 | Alembic 离线渲染一致性 |
| `test_security.py` | 10 | 密码哈希、JWT、权限矩阵、数据范围 |
| `test_desensitization.py` | 11 | 身份证/手机号等敏感字段脱敏 |
| `test_audit.py` | 8 | 审计日志只追加、字段完整性 |
| `test_tenant.py` | 9 | 租户上下文、注入、过滤强约束 |
| `test_document_metadata.py` | 11 | 文档元数据校验（级别/时效/文号）|
| `test_splitter.py` | 8 | 中文章条切分 |
| `test_loader.py` | 7 | 文档解析器注册（PDF/Word/文本）|
| `test_member_stages.py` | 12 | 党员发展状态机与转换规则 |
| `test_qa_chain.py` | 5 | 问答链六阶段编排 |
| `test_verifier.py` | 11 | 引用核验 |
| `test_session.py` | 6 | 多轮会话、TTL、最大轮次 |
| `test_rewrite.py` | 5 | 追问改写 |
| `test_knowledge_service.py` | 2 | 知识服务基础路径 |
| `test_datetime_utils.py` | 7 | 日期工具 |
| `llm/test_gateway.py` | 9 | 出网网关（涉密拒绝、敏感本地）|
| `llm/test_router.py` | 11 | 模型路由与降级 |
| `llm/test_registry.py` | 7 | 模型注册表 |
| `llm/test_model_service.py` | 7 | 向量化/生成服务 |
| `rag/test_rag_service.py` | 5 | RAG 服务编排 |
| `rag/test_retrieval.py` | 6 | 检索（向量/关键词/混合/RRF）|

### 5.2 集成测试 `tests/integration/`（24，标记 `integration`）

| 文件 | 用例 | 覆盖点 |
| --- | --- | --- |
| `test_auth_api.py` | 3 | `POST /auth/login`（200/401）、`GET /auth/me` |
| `test_knowledge_api.py` | 2 | 知识入库、权限 401/403 |
| `test_member_flow.py` | 4 | 党员发展接口 |
| `test_db_migration.py` | 5 | 迁移 head、中文全文检索、生成列 |
| `test_llm_integration.py` | 10 | LangGraph 图 / 问答链端到端（**未打 integration 标记**）|

### 5.3 安全测试 `tests/security/`（18，标记 `security`）

| 文件 | 用例 | 覆盖点 |
| --- | --- | --- |
| `test_permission.py` | 8 | 角色×接口权限矩阵、越权 403 |
| `test_tenant_isolation.py` | 5 | 上下文隔离、写入注入、跨租户拒绝 |
| `test_data_egress.py` | 5 | 出网闸门：涉密拒绝、敏感强制本地 |

### 5.4 离线评测 `tests/evaluation/`

| 资产 | 说明 |
| --- | --- |
| `run_evaluation.py` | 检索/问答评测脚本（指标定义见 §8）|
| `retrieval_samples.json` | 检索样本（含 `expected_docs`/`expected_articles`）|
| `qa_samples.json` | 问答样本 |
| `results/` | 评测输出目录 |

---

## 6. 执行指南

```powershell
# 0) 激活环境并安装依赖
pip install -r requirements-dev.txt

# 1) 全量测试（推荐 CI 卡点命令）
pytest

# 2) 分层
pytest tests/unit/
pytest tests/integration/     # 需 DATABASE_URL
pytest tests/security/

# 3) 按标记
pytest -m security
pytest -m integration

# 4) 单文件 / 单用例
pytest tests/unit/rag/test_retrieval.py -v
pytest tests/unit/test_config.py::test_xxx -v

# 5) 覆盖率
pytest --cov=app --cov-report=html      # 生成 htmlcov/index.html

# 6) 代码质量门禁（可选）
black --check app/ tests/
isort --check app/ tests/
flake8 app/ tests/
mypy app/
```

集成测试前需保证库可达：
```powershell
$env:DATABASE_URL="postgresql+asyncpg://party_user:dev_password@localhost:5433/party_agent_dev"
alembic upgrade head
```

---

## 7. 详细用例要点（关键断言）

- **鉴权**：正确凭据 200 且返回 access/refresh token；错误密码 401；无 token 访问受保护端点 401；`/auth/me` 返回中手机号/邮箱已脱敏。
- **权限矩阵**：不同 `UserRole` × 接口的允许/拒绝；越权返回 403。
- **租户隔离**：无租户上下文 flush 抛 `TenantIsolationError`；查询未绑定 tenant 抛错；绑定后 SQL 含 `tenant_id`；跨租户数据不可见。
- **数据出网**：涉密数据调用外部模型被拒；敏感数据强制走本地模型；白名单外域名被拦截。
- **RAG 检索**：向量检索按余弦相似度降序；关键词检索 `ts_rank` 降序；混合检索用 RRF 融合且权重可配；重排失败时降级为原始结果；最高分低于阈值判为「无依据」。
- **问答链**：六阶段顺序（改写→检索→融合→重排→判定→生成）；无依据时返回明确拒答文案；引用可核验；会话语义（TTL、最大轮次）。
- **迁移**：`alembic upgrade head` = 002；`knowledge_docs.search_vector` 生成列随入库自动填充；`chinese_zh` 检索配置存在。
- **党员发展**：状态转换合法性（非法跳转被拒）、培养期/预备期天数上限。

---

## 8. 离线评测（RAG 质量）

运行：`python tests/evaluation/run_evaluation.py`（需真实库 + 已向量化文档 + DashScope Key）。

| 指标 | 定义 | 目标（建议） |
| --- | --- | --- |
| Recall@5 / Recall@10 | 期望文档出现在 top-K 的比例 | ≥ 0.85 |
| MRR | 期望文档首次出现位置的平均倒数排名 | ≥ 0.7 |
| Precision@5 | top-5 中相关文档比例 | ≥ 0.6 |
| 答案相关性 | 答案是否覆盖期望要点 | 人工/规则抽样 |
| 引用准确性 | 引用是否指向真实文档/条款 | 100% 可核验 |
| 拒答率 | 无关问题的正确拒答比例 | ≥ 0.9 |

> 当前脚本为**评测框架 + 指标定义 + 样本加载**；完整指标计算需接入真实环境后补全。

---

## 9. 验收标准（质量门禁）

| 门禁 | 标准 |
| --- | --- |
| 全量测试 | `pytest` **0 failed / 0 error**（允许按条件 skip，如无 `DATABASE_URL`）|
| 安全测试 | `pytest -m security` 全通过 |
| 集成测试 | `pytest -m integration` 全通过（连真实 PG16）|
| 覆盖率 | 新增模块行覆盖 ≥ 80%（存量按 `pytest --cov` 报告评估）|
| 静态检查 | `black --check` / `isort --check` 无差异；`flake8` 无 error |
| 可启动性 | `uvicorn app.main:app` 启动成功，`/api/v1/health` 200、`/docs` 200 |
| 迁移 | 空库可 `alembic upgrade head` 到最新且无报错 |

---

## 10. 已知问题与风险

| 编号 | 问题 | 影响 | 建议 |
| --- | --- | --- | --- |
| R-1 | `requirements.txt` **缺 `python-multipart`**，但 `app/api/v1/knowledge.py` 使用文件上传 | 干净环境启动报 `RuntimeError: Form data requires "python-multipart"` | 加入依赖并重建镜像 |
| R-2 | `test_llm_integration.py` 属集成但**未打 `integration` 标记** | `pytest -m integration` 漏跑该 10 个用例 | 补 `pytestmark = pytest.mark.integration` |
| R-3 | `pyproject.toml` 声明 `slow` 标记，但无用例使用 | `pytest -m slow` 选不到 | 移除或补充慢用例 |
| R-4 | 未设置 `DATABASE_URL` 时 DB 集成测试自动跳过 | 本地无库时「绿」但不完整 | CI 必须注入 `DATABASE_URL` |
| R-5 | Python 3.13 下部分依赖（asyncpg 等）轮子兼容风险 | 本地 venv 启动/安装可能失败 | 固定使用 3.11/3.12 |
| R-6 | Windows + Docker 绑定挂载下 `uvicorn --reload` 监视 `/app/tests` 触发 `os error 5`，进程崩溃 | 开发容器反复退出 | 容器内关闭 `--reload`，或用 `--reload-dir /app/app` |
| R-7 | 审计表**数据库级只追加权限**（GRANT INSERT / REVOKE UPDATE,DELETE）未添加 | 仅应用层拦截，DB 层可被绕过 | 补充 DDL 权限 |
| R-8 | `mypy` 在既有文件仍有少量报错（如 `config.py` 的 `TenantConfig`） | CI 严格卡点会失败 | 分批修复或临时豁免 |
| R-9 | 未做并发/性能压测 | 生产容量未知 | 增加 Locust/k6 场景 |

---

## 11. 附录：命令速查

| 目的 | 命令 |
| --- | --- |
| 全部测试 | `pytest` |
| 只跑单元 | `pytest tests/unit/` |
| 只跑安全 | `pytest -m security` |
| 只跑集成 | `pytest -m integration` |
| 显示慢用例统计 | `pytest --durations=10` |
| 失败即停 + 详细 | `pytest -x -vv` |
| 覆盖率 HTML | `pytest --cov=app --cov-report=html` |
| 迁移到最新 | `alembic upgrade head` |
| 迁移预览 SQL | `alembic upgrade head --sql` |
| 启动服务 | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| 健康检查 | `curl http://localhost:8000/api/v1/health` |

---

*本测试文档与 [TEST_REPORT.md](./TEST_REPORT.md) 配套：后者记录每次执行的**结果**，本文档规定**策略、范围、用例与验收标准**。*
