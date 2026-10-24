# 党建工作智能体 · 项目全景介绍

> 文档定位：面向新成员/新用户的项目整体介绍。基于当前主分支（迁移头 `012_member_self`，2026-10-12 本地工作区）。

## 1. 项目是什么

**党建工作智能体**是一套面向高校党建工作的辅助系统，基于 **LangChain / LangGraph + FastAPI** 构建后端，**Vue 3 + TypeScript** 构建前端。它把"制度问答"、"党员发展"、"组织生活"、"中心组学习"、"年度考核"、"党员自助"等业务装进一个可多人协作、有严格权限与审计的 Web 系统，AI 只做辅助（检索、起草、评分建议），**业务结论与关键流转必须人工审核**。

GitHub 仓库：`https://github.com/jaimelove67/dangjian-agent`（MIT 协议）。

## 2. 核心功能模块

| 模块 | 入口 | 说明 |
| --- | --- | --- |
| 制度问答（RAG） | `/ask` | 基于知识库的检索增强问答，带引用出处；无依据时拒绝编造 |
| 知识库管理 | `/knowledge` | 上传 PDF/DOCX/TXT/MD，自动切分、向量化、混合检索+重排 |
| 党员发展 | `/members` | 名册、年度批次、材料登记、阶段流转、民主投票（申请人→…→正式党员人工流转） |
| 党员自助 | `/my-archive` `/my-materials` | 本人档案只读、私有原件提交（不进知识库/不发模型） |
| 组织生活（三会一课） | `/meeting` | 记录、纪要、审核、归档；**登记人≠审核人** |
| 中心组学习 | `/study` | 年度计划、条目、会议纪要、审核归档、电子效力确认 |
| 年度考核 | `/assessment` | 指标→任务→佐证归集→提醒→授权导出；学校管理员先配指标 |
| 系统管理 | `/accounts` `/governance` `/system` | 开户、租户/组织/配置治理、运行与就绪详情 |

## 3. 技术栈与架构

```
┌────────────────────────────────────────────┐
│  前端 Vue 3 + TS + Vite (frontend/, :5666)  │
│  代理 /api → 后端 /api/v1                    │
├────────────────────────────────────────────┤
│  后端 FastAPI (app/, :8000/18000)            │
│  ├─ API 层 app/api/v1/（auth/admin/knowledge│
│  │   /qa/member/meeting/study/assessment…） │
│  ├─ 服务层 app/services/（业务+权限+审计）    │
│  ├─ 链路 app/chains/qa_chain + app/rag/     │
│  ├─ 模型路由 app/llm/（网关+白名单+注册表）   │
│  └─ 配置 app/core/config.py（pydantic-settings）│
├────────────────────────────────────────────┤
│  PostgreSQL + pgvector（向量检索，1024 维）    │
│  Redis（会话/吊销/限流/任务）+ Alembic 迁移    │
│  阿里云百炼 DashScope（LLM/Embedding/Rerank） │
└────────────────────────────────────────────┘
```

- **后端**：FastAPI 0.143、SQLAlchemy 2 异步、asyncpg、Pydantic 2、pydantic-settings
- **AI**：LangChain 1.x / LangGraph 1.x、dashscope SDK、Jieba 分词、pypdf/pdfplumber、python-docx
- **数据**：PostgreSQL(pgvector) + Alembic（当前迁移 `012_member_self`，33 张表）、Redis、Celery（任务队列）
- **安全**：JWT 双令牌、bcrypt/argon2 密码、令牌吊销、全量审计、敏感数据出网白名单、文件加密、生产中强制 TLS

## 4. 目录结构

| 目录 | 内容 |
| --- | --- |
| `app/` | 后端：API、服务、模型接入、RAG、安全、租户隔离 |
| `frontend/` | 正式业务前端（Vue 3 + TS）；`frontend-test/` 是旧联调工程 |
| `config/` | 模型路由、业务规则、检索策略、学习模板 |
| `migrations/` | Alembic 迁移（001→012_member_self） |
| `tests/` | 单元 / 集成 / 安全 / 评测样本 |
| `scripts/` | 启动、初始化、种子数据脚本 |
| `deploy/` | Docker 部署与运维文档 |
| `docs/` | 运行 / 状态 / 测试 / 使用手册 / 归档 |

## 5. 角色与权限体系（7 种角色）

数据范围：`本人 < 支部 < 院系 < 学校 < 全部（平台）`，逐级包含：

| 角色 | 数据范围 | 绑定组织 | 能力概览 |
| --- | --- | --- | --- |
| 系统管理员 | 平台全部 | 本租户任意 | 开户、治理、系统状态、审计 |
| 学校管理员 | 全校（+院系+支部） | 学校 | 全校业务 + 归档确认/指标配置/租户配置 |
| 院系管理员 | 本院系（+支部） | 院系 | 本院系业务管理 |
| 支部书记 | 本支部 | 支部 | 名册、会议、材料、阶段流转、答题 |
| 组织员 | 本支部 | 支部 | 同支部书记范围 |
| 普通党员 | 本人 | 支部 | 本人档案、材料、制度问答 |
| 申请人 | 本人 | 支部 | 仅公开制度问答 |

关键关系：
- 租户层级 `平台→学校→院系→支部` 与组织树一一对应，账号开户时角色必须匹配组织类型
- 系统管理员在"平台面"，与学校业务数据隔离（这也是平台账号看不到名册/归档的原因）
- 审核类操作强制"另一位组织人员"完成（组织生活纪要、学习纪要、考核审核）

## 6. 模型接入（阿里云百炼 DashScope）

| 用途 | 模型 | 说明 |
| --- | --- | --- |
| 聊天 LLM | `qwen3.8-flash` | 项目验证可用的聊天模型（`deepseek-v3` 在该账号不存在） |
| Embedding | `qwen3.7-text-embedding-flash` | 1024 维，写入 pgvector |
| Rerank | `qwen3.7-text-rerank` | 混合检索后重排 |

配置在 `.env`（`DASHSCOPE_API_KEY`、`CHAT_MODEL`、`EMBED_MODEL`、`RERANK_MODEL`、`DASHSCOPE_BASE_URL`）。内部数据出网受 `ALLOWED_EXTERNAL_MODELS` 白名单控制；敏感/涉密内容始终拦截。

## 7. 安全设计要点

- 数据级出网闸门 + 出网白名单；DASHSCOPE_BASE_URL 仅允许 HTTPS Host
- 登录/名册读取/材料提交/治理全部写审计日志
- JWT 访问令牌 30 分钟 / 刷新 7 天，Redis 吊销存储
- 生产环境（`ENV=production`）强制：PostgreSQL TLS、Redis TLS、32+ 字符密钥、文件加密密钥环、明确访问来源
- 电子归档效力需学校管理员确认后才可归档/查历史/导出；撤销确认立即失效

## 8. 运行与部署

- **本地开发**：`docs/RUNNING.md`。Python 3.11+ .venv + `npm ci`；PostgreSQL(pgvector)/Redis 可起 `docker-compose.dev.yml`；`alembic upgrade head`；`scripts/start-all.bat`
- **本地地址**：前端 `:5666`，后端 `:8000`（本机被占时用 `.env` 的 `APP_PORT`，前端用 `VITE_API_TARGET` 指到后端）
- **容器**：`docker-compose.yml`（生产）、`docker-compose.dev.yml`（开发热重载）
- **就绪检查**：`/api/v1/health/live`（存活）、`/api/v1/health/ready`（DB/核心表/Redis/模型，新环境需一次成功模型调用后才 200）

## 9. 测试与质量

测试见 `docs/TESTING.md`：
- 后端：`pytest tests/unit tests/security tests/integration`（合成输入+替代模型，测试进程清空云端密钥）
- 前端：`npm --prefix frontend run typecheck / build`；浏览器流程 `node tests/*.mjs`（Playwright，合成 API 响应）
- 业务评测：`tests/evaluation/run_evaluation.py`（真实问答，会产生模型费用）
- 历史回归：全项目 pytest 306–422 通过区间、覆盖率约 78%；当前文档记录边界以 `docs/STATUS.md` 为准

## 10. 当前本地环境状态（2026-10-12 已跑通）

- 前端 `http://127.0.0.1:5666`，后端 `http://127.0.0.1:18000`
- 数据库：pgvector 容器 `:15432`（`012_member_self`，33 表）、Redis `:16379`
- 测试账号（密码 `Test123456`）：`admin-verify`（系统管理员）、`test-reviewer`（学校管理员）、`branch-secretary`（支部书记）
- 已造数据：TEST_TENANT 组织树 + 6 名合成培养对象名册 + 部分演示知识文档
- **已知边界**：电子归档效力尚未确认（历史归档 403 属预期）；平台账号看不到学校业务数据（设计如此）

## 11. 文档导航

| 文档 | 内容 |
| --- | --- |
| `docs/RUNNING.md` | 安装、启动、配置、排障 |
| `docs/STATUS.md` | 已实现功能、限制与待办 |
| `docs/TESTING.md` | 测试命令与验收边界 |
| `docs/USER_GUIDE.md` | 各角色使用手册 + FAQ |
| `docs/ADMINISTRATION.md` | 开户、治理、党员自助边界 |
| `migrations/README.md` | 迁移链与旧库接管 |
| `deploy/docker/README.md` | 容器部署运维 |