> 历史归档：本文保留生成时的结论与环境信息。当前功能见[项目状态](../../STATUS.md)，测试见[测试指南](../../TESTING.md)。

# 协作者版本审查：2026-10-10

结论：这次推送补齐了重要的前后端接口，修复了多处实际集成问题；但远端提交存在可复现的启动阻断、数据范围授权遗漏和 RAG 判定回归，尚不满足验收或部署条件。

## 范围与依据

- 仓库：`jaimelove67/dangjian-agent`。
- 基线：`cee13273bc58e6238f9aa176387c413bd418fa8c`。
- 目标：`10ecad45d57dfd415b27ba00fb65674ad5dec96b`，来自远端 `master`。
- 比较：`git diff cee1327...10ecad4`；2 个新增提交，41 个文件，2161 行新增、512 行删除。
- 提交：`cc333b8` 补齐知识库、名册、问答历史及 RAG 修复；`10ecad4` 修改默认 LLM 名称。作者均为 `manice`，提交时间分别为北京时间 2026-10-10 10:42、10:47。
- 没有指定新的独立 issue/spec；以 `require.txt`、项目框架文档、一周开发计划、开发规范和前后端接口契约作为评价依据。仓库没有 `docs/agents/issue-tracker.md`，因此未进行独立 issue 验收核对。
- 本地工作区存在大量未提交修改，评审和测试均使用固定提交的独立导出副本，未把本地修复算入协作者交付。

## 已有进步

1. 知识库列表与软删除、培养对象名册与新增、问答历史有了真实接口；前端对应移除了示例数据源。
2. 修正检索片段与文档的关联：使用文档内部主键，而非业务文档编号；关键词评分改为可识别的 SQL 表达式。
3. 模型路由新增模型类型检查，避免 embedding 请求错误命中 LLM 路由；兼容模型回答的 `choices[0].message.content` 字段。
4. 添加启动时的模型注册、真实数据库就绪检查，并修正 LangGraph 入口调用和默认向量化批量大小。
5. 前端类型检查和生产构建通过。阶段流转继续保留人工操作边界，没有把建议直接写成组织认定。

## Standards：规范审查

以下 6 项分别评价交付完整性、安全规范、审计和验证要求；不与下一轴合并计数。

### S1 · P1：新模型文件没有进入提交，应用和迁移被阻断

新增代码引用 `app.models.member.MemberProfile` 和 `app.models.qa_session.QASession`，但固定提交中没有 `app/models/member.py`、`app/models/qa_session.py`。应用在加载路由时就失败，Alembic 环境也无法加载。依据为《开发规范》§12.1 的功能与验证要求。

证据：[member.py:22](https://github.com/jaimelove67/dangjian-agent/blob/10ecad45d57dfd415b27ba00fb65674ad5dec96b/app/api/v1/member.py#L22)、[qa_session_service.py:14](https://github.com/jaimelove67/dangjian-agent/blob/10ecad45d57dfd415b27ba00fb65674ad5dec96b/app/services/qa_session_service.py#L14)、[migrations/env.py:17](https://github.com/jaimelove67/dangjian-agent/blob/10ecad45d57dfd415b27ba00fb65674ad5dec96b/migrations/env.py#L17)。

独立副本执行 `python -c "import app.main"`，得到 `ModuleNotFoundError: No module named 'app.models.member'`；两项离线迁移测试因缺少 `app.models.qa_session` 报错。`git check-ignore -v` 确认 `.gitignore:139:models/` 会忽略这两个新文件。忽略规则是存量，本次加入未交付文件的导入才引发阻断。

建议补交两个模型及相应注册，并限定忽略规则的路径，随后从干净检出重新验证启动与迁移。

### S2 · P1：新查询没有执行角色对应的数据范围

知识列表和党员名册只有租户过滤。现有鉴权依赖只验权限点，ORM 自动过滤也只处理 `tenant_id`，不会补上知识可见范围、保密级别或组织范围。修复 S1 后，这些遗漏会形成数据越权。违反框架 §9.1 的“角色 + 数据范围”和《开发规范》§1.1、§12.1 的安全要求。

证据：[knowledge_service.py:237](https://github.com/jaimelove67/dangjian-agent/blob/10ecad45d57dfd415b27ba00fb65674ad5dec96b/app/services/knowledge_service.py#L237)、[member.py:172](https://github.com/jaimelove67/dangjian-agent/blob/10ecad45d57dfd415b27ba00fb65674ad5dec96b/app/api/v1/member.py#L172)。具体用户场景见 Spec 轴的 F1/F2。

### S3 · P2：新增人员登记、文件删除没有写入审计库

两项操作没有调用 `write_audit`。删除仅记录普通日志，无法满足按操作人、对象及结果追溯的审计要求。违反《开发规范》§8.4、§12.1。

证据：[member.py:216](https://github.com/jaimelove67/dangjian-agent/blob/10ecad45d57dfd415b27ba00fb65674ad5dec96b/app/api/v1/member.py#L216)、[knowledge_service.py:289](https://github.com/jaimelove67/dangjian-agent/blob/10ecad45d57dfd415b27ba00fb65674ad5dec96b/app/services/knowledge_service.py#L289)。

### S4 · P2：历史写入失败后，主请求事务仍会失败

`create_session` 调用 `flush`，API 捕获异常后只写日志，没有回滚或保存点。若 flush 发生数据库错误，SQLAlchemy 会将事务置为失败状态；随后 `get_db` 的提交仍会抛出 `PendingRollbackError`，“历史写入失败不影响回答”的预期不能成立。违反《开发规范》§12.1 的异常处理要求。

证据：[qa.py:130](https://github.com/jaimelove67/dangjian-agent/blob/10ecad45d57dfd415b27ba00fb65674ad5dec96b/app/api/v1/qa.py#L130)、[db/session.py:47](https://github.com/jaimelove67/dangjian-agent/blob/10ecad45d57dfd415b27ba00fb65674ad5dec96b/app/db/session.py#L47)。使用 SQLAlchemy 与 SQLite 内存数据库复现了 flush 唯一键错误被捕获后，下一次 commit 抛出 `PendingRollbackError`。这验证了事务机制，尚未进行真实 HTTP 故障注入。

建议为历史写入使用独立事务或保存点，并正确处理失败。

### S5 · P2：历史写入失败日志可能包含完整问答内容

`logger.warning("qa_history_save_failed: %s", exc)` 输出 SQLAlchemy 异常字符串，可能包含 SQL 绑定参数中的问题、回答、引用；当前引擎未隐藏参数。违反《开发规范》§11.3 的敏感日志要求。

证据：[qa.py:131](https://github.com/jaimelove67/dangjian-agent/blob/10ecad45d57dfd415b27ba00fb65674ad5dec96b/app/api/v1/qa.py#L131)。内存数据库复现使用合成问题和答案，确认异常字符串同时包含两者。未使用真实人员信息。

### S6 · P2：新增接口没有配套回归测试

新增名册、历史、知识列表、删除接口，没有对应的权限、业务或错误路径测试。测试文件唯一改动修正旧健康检查的 `AsyncMock`；新增 `TEST_PLAN.md` 声明针对旧提交 `cee1327`，不能证明新版本通过验收。违反《开发规范》§10.5、§12.1。

现有单元测试已直接暴露 S1 和 F3，因此此处不是仅凭测试数量提出的形式要求。

## Spec：需求实现审查

以下 4 项分别评价用户可见的功能与需求契约；F1/F2 与 S2 共享缺陷证据，两个轴的数量不能简单相加为独立缺陷数。

### F1 · P1：申请人可以枚举超出可见范围的知识文档

框架文档 §9.1 规定“申请人／积极分子：公共”。新增列表接口对申请人开放，查询没有按可见范围或数据级别限制；响应包含标题、文件名、摘要等字段。修复 S1 后，申请人可枚举同租户内部、院系、支部及敏感文档的元数据与摘要。

证据：[knowledge_service.py:237](https://github.com/jaimelove67/dangjian-agent/blob/10ecad45d57dfd415b27ba00fb65674ad5dec96b/app/services/knowledge_service.py#L237)。原先按 ID 查询的范围遗漏属于存量，本条针对新增的批量枚举入口。

### F2 · P1：支部书记可以读取同租户其他支部的人员台账

框架文档 §9.1 规定“支部书记／组织员……业务数据范围：本支部”。名册查询未用当前用户的 `org_unit_id` 或组织树，只按租户取所有在用档案；多支部学校中可读取其他支部的姓名、阶段和材料。新增登记还直接接受客户端组织 ID，未校验组织归属。

证据：[member.py:172](https://github.com/jaimelove67/dangjian-agent/blob/10ecad45d57dfd415b27ba00fb65674ad5dec96b/app/api/v1/member.py#L172)、[member.py:220](https://github.com/jaimelove67/dangjian-agent/blob/10ecad45d57dfd415b27ba00fb65674ad5dec96b/app/api/v1/member.py#L220)。这也是修复 S1 后会实际暴露的问题。

### F3 · P2：重排关闭或失败时，无充分依据也会被标为“依据充分”

框架文档 §5.5 要求“最高分低于阈值即判定‘无依据’”，§5.7 要求“未标注则记风险”。新增降级分支只检查存在片段、答案未命中几个拒答关键词，就直接返回 `True`，没有验证相关性或有效引用。无关回答、未引用的回答、使用 `[999]` 非法角标的回答均可获得肯定标志，前端据此显示“依据充分”。

证据：[rag_service.py:330](https://github.com/jaimelove67/dangjian-agent/blob/10ecad45d57dfd415b27ba00fb65674ad5dec96b/app/rag/rag_service.py#L330)。现有 `test_check_evidence_sufficiency` 的低分断言在目标版本失败、在基线通过；纯内存前后版本谓词对照也复现了无关低分片段与非法引用的结果从 `False` 变为 `True`。

RRF 分数是排名权重，降级需要单独的相关性和有效引用判定。已有生成前判定、引用核验链路遗漏属于存量，本条聚焦新引入的依据标志回归。

### F4 · P2：知识库超过 100 条后，较早文件无法在页面检索维护

`require.txt` §三.1 要求“支持知识分类、更新、检索”。页面只请求第一页 100 条，丢弃总数；搜索、状态过滤和“全部”计数均基于这一页，未实现翻页或服务端搜索。第 101 条起的较早文档无法从此页面展示、搜索或进入维护。

证据：[KnowledgeView.vue:50](https://github.com/jaimelove67/dangjian-agent/blob/10ecad45d57dfd415b27ba00fb65674ad5dec96b/frontend/src/views/KnowledgeView.vue#L50)。建议将搜索与筛选参数传给后端，并提供分页或完整的分批加载。

未发现需要另列的需求扩张；保留人工阶段流转符合当前组织决策边界。

## 验证记录与限制

| 检查 | 结果 |
| --- | --- |
| 远端分支与固定提交核对、完整树导出 | 已完成 |
| `python -c "import app.main"` | 失败：缺少 `app.models.member` |
| 两个新模型单独导入 | 均失败：模块未在提交中 |
| 目标提交 `python -m pytest tests/unit -q --maxfail=6` | 212 项；1 失败、2 错误、1 跳过，其余通过 |
| 基线相同 3 项：依据充分性与两项离线迁移测试 | 3 passed；同一 Python 环境 |
| 前端 Vue/TypeScript 类型检查（应用与 Vite 配置） | 通过 |
| 前端 Vite 生产构建 | 通过，使用已有本机依赖 |
| 内存数据库失败事务、异常参数复现 | 确认 PendingRollback 与日志内容风险 |
| 需求、权限依赖、租户 ORM 事件、审计入口反向检查 | 已完成 |

测试环境为本机 Python 3.13.9、Node 24.14.0；并非项目推荐的 Python 3.11/3.12 全新锁定依赖环境。PDF 用例因缺少 `pypdf` 跳过。未运行真实 HTTP／PostgreSQL 迁移与集成测试、未调用公网模型、未做浏览器 E2E 或性能测试；没有把旧测试报告中的“全通过”当成此版本结果。没有修改协作者代码或覆盖工作区现有修改。

建议先补齐模型文件及数据范围授权，再修复依据判定、事务和日志问题，补充新接口回归测试；完成干净检出启动、迁移和端到端验证后再验收。

Standards：6 项，最严重为必要模型未交付及授权遗漏；Spec：4 项，最严重为知识可见范围与支部数据范围越权。
