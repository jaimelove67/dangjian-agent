# 测试报告（Day1–Day5 / M1 验收）

> 生成日期：2026-10-09 ｜ 被测提交：master `6276baf`（含 PR #18 完整性修复）

## 1. 概述

- **项目**：高校党建工作智能体（LangChain / LangGraph，FastAPI + PostgreSQL + pgvector）。
- **范围**：Day1–Day5 开发者A 的全部交付，以及已并入 master 的开发者B 模块。
- **结论**：目标提交**可启动**；全套测试 **237 passed / 0 failed / 0 skipped**（连接真实 PostgreSQL 16 + pgvector 执行）。

## 2. 测试环境

| 项 | 说明 |
| --- | --- |
| Python | 3.13 |
| 数据库 | `pgvector/pgvector:pg16`（Docker，宿主端口 5433），Alembic head = **002** |
| 缓存 | Redis（会话/缓存沿用 `CacheService`；单测以内存假缓存替代） |
| 关键依赖 | SQLAlchemy 2.0、FastAPI、Alembic、python-jose、bcrypt、langgraph、pypdf |

## 3. 测试分层与结果

| 层次 | 目录 | 用例数 | 结果 |
| --- | --- | --- | --- |
| 单元测试 | `tests/unit/` | 205 | ✅ 全通过 |
| 集成测试 | `tests/integration/` | 14 | ✅ 全通过 |
| 安全测试 | `tests/security/` | 18 | ✅ 全通过 |
| **合计** | （30 个测试文件） | **237** | ✅ **全通过** |

## 4. 覆盖内容

- **单元**：配置/缓存、DB 模型元数据、迁移离线渲染、密码哈希与 JWT、角色+数据范围与接口权限矩阵、脱敏、审计（只追加）、租户隔离、文档元数据校验、章条切分、解析器注册、问答链六阶段、引用核验、会话、追问改写、党员发展规则；以及开发者B 的 `rag_service` / `retrieval` / `datetime` 等。
- **集成**：登录与 `/auth/me`、知识库入库（权限 401/403）、党员发展接口、LangGraph 图、问答链端到端、DB 迁移（中文全文检索 / 生成列）。
- **安全**：越权访问（权限矩阵、租户隔离）、敏感数据出网（出网闸门：涉密拒绝、敏感强制本地）。

## 5. 真实环境验证（实机）

- `alembic upgrade head` → head = **002**；6 张表 + 扩展（`vector`/`pg_trgm`/`uuid-ossp`）+ `chinese_zh` 检索配置 + `knowledge_docs.search_vector` 生成列。
- **文档入库 e2e**：入库→章条切分为 3 个片段→`search_vector` 自动填充→状态变更 `abolished`。
- **鉴权 e2e**：`POST /auth/login` 200 → 错误密码 401 → `GET /auth/me` 200（邮箱/手机号自动脱敏）。

## 6. 本轮发现并修复的缺陷

| 编号 | 问题 | 影响 | 修复 |
| --- | --- | --- | --- |
| D-1 | `main.py` 引用不存在的 `qa`/`embeddings`；`qa_enhanced.py` 依赖缺失的 `enhanced_rag_service` | 应用无法启动、测试无法收集 | PR #18（合并 Dev B Day4 分支 + 移除孤立增强路由） |
| D-2 | 迁移 001 缺 `knowledge_docs`、`embedding_chunks` 两表 | 002 迁移失败、模型与库不一致 | PR #18 |
| D-3 | `app/db/base.py` 无 uuid 默认值、表名未驼峰转下划线 | 主键需显式赋值、表名生成错误 | PR #18 |
| D-4 | `User.role` 列类型与迁移不一致（原生枚举 vs VARCHAR） | 用户写入失败、登录不可用 | PR #15 |
| D-5 | `alembic.ini` 中文注释在 Windows GBK locale 下解析失败 | 本机无法执行迁移 | PR #12 |

## 7. 遗留问题（非阻塞）

1. **审计表数据库级只追加权限**（`GRANT INSERT / REVOKE UPDATE, DELETE`）未添加（应用层已拦截）。
2. **开发者B 的 Day5**（评测样本与指标、API/开发者文档、演示数据、周总结）未完成；**联合联调/并发压测/版本标签**待办。
3. `mypy` 在既有文件仍有少量报错（如 `app/core/config.py` 的 `TenantConfig.__init__`）。
4. DB 集成测试在未设置 `DATABASE_URL` 时自动跳过（本报告为连接真实库执行）。

## 8. 结论

- **M1（工程骨架与基础设施）**：验收就绪（数据库/迁移/缓存/鉴权/审计/租户隔离均已就绪并测试）。
- **M2（知识库与检索）**：知识文档入库完整；检索链路由开发者B 落地。
- **M3（知识问答原型）**：问答链框架 + 引用核验可用，`/api/v1/qa` 接口已并入。
- **建议**：将 `pytest -m security` 纳入 CI 卡点；补齐审计表数据库级权限。
