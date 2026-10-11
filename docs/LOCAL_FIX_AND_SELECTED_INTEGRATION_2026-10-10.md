# 本地修补与协作者业务功能整合

> 历史记录（2026-10-10）：保留当时版本、环境与测试结论。2026-10-11文档整理未重跑这些检查；当前本地功能见[项目状态](STATUS.md)，运行见[运行指南](RUNNING.md)，验证范围见[测试指南](TESTING.md)。


已以当前本地工作区为基础修复三个已确认问题，选择性接入协作者的软删除、真实名册和持久问答历史。整合来源固定为 `10ecad45d57dfd415b27ba00fb65674ad5dec96b`，本地原有权限、隐私、审计、引用核验、内容版本更新和服务端分页继续使用。

日期：2026-10-10，Asia/Shanghai。

## 本地修补

| 问题 | 修补与证据 |
| --- | --- |
| 流转建议漏传目标阶段，后端返回 422 | 页面发送选中的 `target_stage`，API 参数类型采用必填契约。同一浏览器回归在整合前快照上因字段缺失失败，在当前页面通过。 |
| 正式问答链未调用追问改写模型 | 为 QAChain 注入 `TaskType.REWRITE` 回调；完整历史提示词先通过内容分级和出网检查，改写结果在检索前再次检查。正式 HTTP 回归验证改写进入检索适配器，敏感历史在模型调用前被拦截。 |
| Redis 故障时仍签发无法使用的登录凭证 | 签发前执行短 TTL 读写探针，读失败和写失败均返回 503。刷新重放、退出吊销及实际 Redis 7 探针验证通过。 |

## 选择性吸收的业务功能

**知识文档软删除。** 新增 `DELETE /api/v1/knowledge-docs/{doc_id}`，校验维护权限、资料可见范围、同租户和管理组织范围。锁定文档后停用文档与片段，并在同一事务追加审计，保留历史版本。页面成功后刷新后端计数、关闭对应详情，删除最后一页最后一项时返回上一页，失败时保留条目。

**真实培养对象名册与人工登记。** 补齐 `MemberProfile`，提供分页 `GET /member/roster`、人工登记 `POST /member/roster` 和组织选择 `GET /member/org-units`。支部角色限本支部，院系和学校角色限本组织及有效后代，系统管理员限当前租户。组织名称取数据库，防止客户端伪造所属组织；无效阶段、未来日期和非法材料等输入被拒绝。登记和名册读取追加审计，不将姓名或材料原文写入审计摘要。规则分析只提供建议，待办请求发送所选对象的材料和阶段天数。

**长期问答历史。** 补齐 `QASession`，保存答案、完整引用、风险提示、免责声明、拒答状态与会话编号；`GET /qa/sessions` 只分页返回当前租户当前用户的记录。写入通过 SQL SAVEPOINT 隔离，真实历史 flush 失败时问答仍可返回，审计仍可提交，页面收到保存失败提示。日志只记录异常类型。Redis 上下文继续按租户、用户、会话隔离并设置 TTL。页面支持历史回看、继续所属会话、清空后开启新会话及查询失败重试。

## 迁移与开发环境

- 协作者的 003/004 迁移原样保留，字节一致性检查通过；补齐实体与迁移导入。
- 新增 005，补充问答风险信息、会话编号和组织名册索引。旧历史缺少来源标识时提示核对原文。
- 独立库验证了新库升级，以及含旧问答记录的 004 数据库升级后仍可读取。
- 本地开发库 `party_agent_dev` 已从 002 升级到 005。更换端口和迁移前后，原六张核心表的行数与内容摘要一致；原 PostgreSQL、Redis 命名数据卷继续使用。
- 默认端口存在本机服务冲突，缓存客户端实际连接到 Redis 3.2.100。开发容器改用 `127.0.0.1:55432`、`127.0.0.1:56379`；本地 `.env` 同步地址，保留凭据与模型配置，示例配置注明开发端口。
- `.gitignore` 的模型资源目录规则限定到仓库根目录，新增 ORM 文件已正常出现在 Git 状态中。

## 验证

| 检查 | 结果 |
| --- | --- |
| 全量后端 `python -m pytest tests -o addopts= -q --tb=short` | **339 passed, 1 skipped**。跳过 `test_blank_pdf_page_count`，当前环境未安装 `pypdf`。 |
| 新功能与既有真实存储回归 | 35 项通过，使用随机独立 PostgreSQL 库，覆盖租户、组织、权限、分页、软删除检索、旧迁移、历史隔离与事务恢复。 |
| `npm run typecheck` / `npm run build` | 均通过。 |
| `node tests/business-workflows.mjs` | 四组流程通过：流转参数、名册登记与规则输入、软删除分页及失败路径、历史会话重置与重试；API 采用合成响应。 |
| 反向检查 | 可读资料被误删、组织伪造、历史越权、失败事务污染和敏感历史出网均有边界回归；未发现额外需要阻止整合的代码问题。 |

浏览器测试可用 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指定已有 Chromium，`UI_SCREENSHOT_DIR` 指定截图位置，`UI_SOURCE_ROOT` 对旧源码快照运行同一回归。

## 使用前提与验证边界

当前开发库尚无组织记录。登记真实培养对象前，需要录入实际学校、院系、支部，并为组织角色绑定正确的 `org_unit_id`；界面会显示组织未配置提示。知识库也为空，实际有依据的问答需要录入真实制度文件。

本次没有调用真实云模型；检索与生成回归采用合成响应，云端适配测试使用模拟 HTTP 服务。未以真实账号做人工业务验收。PDF 解析需安装已列入依赖的 `pypdf`。该记录对应整合后的工作区，提交与推送状态以 Git 分支为准。

测试记录：[后端结果 XML](</C:/Users/jaime/.codex/visualizations/2026/10/10/01a123b7-b772-7e83-b723-3c5ecd7bd7a7/business-integration/backend-results.xml>)。

界面记录采用合成数据：[人工登记](</C:/Users/jaime/.codex/visualizations/2026/10/10/01a123b7-b772-7e83-b723-3c5ecd7bd7a7/business-integration/member-registration.png>)、[移除后的知识库](</C:/Users/jaime/.codex/visualizations/2026/10/10/01a123b7-b772-7e83-b723-3c5ecd7bd7a7/business-integration/knowledge-after-removal.png>)、[历史回看](</C:/Users/jaime/.codex/visualizations/2026/10/10/01a123b7-b772-7e83-b723-3c5ecd7bd7a7/business-integration/qa-history.png>)、[移动端历史](</C:/Users/jaime/.codex/visualizations/2026/10/10/01a123b7-b772-7e83-b723-3c5ecd7bd7a7/business-integration/qa-history-mobile.png>)。
