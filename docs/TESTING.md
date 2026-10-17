# 测试指南

文档更新日期：2026-10-11。测试代码与样本保留在 `tests/`，历史测试报告见[归档](archive/README.md)。本次党员端的实际验证见“党员端与系统权限回归”；其他段落的历史测试数字仍限于注明的原执行日期和被测工作区。

## 执行命令

安装 `requirements-dev.txt`，从项目根目录使用同一 Python 环境执行：

```bash
python -m pytest tests/unit/
python -m pytest tests/integration/
python -m pytest tests/security/
python -m pytest
```

PowerShell 中可在测试进程启动前设置：

```powershell
$env:DASHSCOPE_API_KEY = ''
$env:QWEN_API_KEY = ''
python -m pytest tests/unit tests/security
```

### 角色界面回归（需要前后端已启动）

权限与导航的改动必须同时跑一条界面回归，确认"菜单显隐 = 真实可访问"，避免出现
点进去才 403、或某个角色看不到自己该有的入口：

```powershell
node frontend\scripts\check-roles-ui.mjs
```

脚本用 Playwright 依次以 7 个角色登录，逐路由检查：菜单项集合、越权路由是否被拦截、
本人页面是否可达、页面级横向溢出、主内容地标数量、接口与控制台报错。知识库部分额外断言
详情面板挂载了「处理与原件」工具，并按权限区分：只有具备 `knowledge.manage` 的角色能看到
元数据修正表单，只读角色仍能刷新处理状态与下载原件。
默认连接 `http://127.0.0.1:5666`、密码 `Test123456`，可用 `PARTY_BASE_URL`、
`PARTY_PASSWORD` 覆盖；Playwright 自带浏览器版本不匹配时用 `PARTY_CHROMIUM` 指定
本机 Chromium 可执行文件。脚本会自行等待登录限流窗口。

**跑之前把本地后端的接口限流放宽**：`RATE_LIMIT_PER_MINUTE` 默认 120 且**按 IP 计**
（`app/core/rate_limit.py`），7 个角色顺序跑很容易在同一个 60 秒窗口里超额。超额（429）
时脚本只会对「逐路由」那一段重试，而工作区检查（组织生活频次、民主评议、组织关系接转、
上级审批备案等）在 429 下拿到的是没渲染完的页面，会报成"某项没挂载"的**假失败**，且每次
失败的角色不固定。用 `set RATE_LIMIT_PER_MINUTE=5000` 启动后端再跑，7 个角色可稳定通过：

```powershell
# 另开一个窗口启动后端（示例端口 18000）
set RATE_LIMIT_PER_MINUTE=5000
python -m uvicorn app.main:app --host 127.0.0.1 --port 18000
$env:VITE_API_TARGET = 'http://127.0.0.1:18000'   # 前端 dev 代理指向它
node frontend\scripts\check-roles-ui.mjs
```

该检查已接入 CI（`.github/workflows/role-ui.yml`）：用隔离的 PostgreSQL/Redis 服务容器
跑迁移与合成账号初始化，起后端与前端后执行同一脚本，报告作为构建产物上传。

Linux/macOS 使用 `DASHSCOPE_API_KEY= QWEN_API_KEY= python -m pytest tests/unit tests/security`。这些设置不改写 `.env`；真实模型评测另用已授权的环境。

单元与安全回归主要使用合成输入及替代模型。完整回归需要可用的 PostgreSQL；数据库迁移测试检查已迁移的目标库，`test_repaired_storage.py` 还需要连接管理库并创建、清理随机独立测试库的权限。请配置专用测试数据库连接。

自动化回归应在测试进程中将 `DASHSCOPE_API_KEY` 和兼容变量 `QWEN_API_KEY` 覆盖为空，保持本地 `.env` 不变。检查失败数和跳过数；缺少依赖或数据库导致的跳过不能计为验收通过。

### 排障：Windows 临时目录不可写会吞掉整批用例

如果 `pytest` 在收集后立刻抛出一批 `ERROR at setup`，且错误是
`PermissionError: [WinError 5] 拒绝访问。: '...\Temp\pytest-of-<用户名>'`，
那是 pytest 临时根目录的 ACL 损坏，与本项目代码无关，且在没有管理员权限时无法修复
（`takeown` / `icacls` 同样会被拒绝）。用 `--basetemp` 指向一个可写目录即可绕开：

```powershell
python -m pytest --basetemp="$env:TEMP\pytest-bt"
```

这一错误发生在 setup 阶段，会把用例直接吞成 ERROR，并顺势掩盖同一批文件里真实的断言失败。
先绕开它、再解读结果，否则"31 个错误"之类的数字并不能说明代码有问题。

### 排障：本地全量测试的连接数会爬升并顶穿 max_connections

`tests/conftest.py` 会在导入应用之前把 `ENV` 默认为 `testing`，以对齐应用引擎的连接策略：
`app/db/session.py` 仅在 `ENV=testing` 时使用 `NullPool`，其余情况走连接池，而 pytest 每个
用例使用独立的事件循环，池化连接会跨已关闭的循环泄漏。此前本地 `.env` 的
`ENV=development` 会让全量测试的连接数持续爬升，最终顶穿 Postgres 的 `max_connections`
（实测峰值 104 / 上限 100，失败清一色是 `asyncpg.exceptions.TooManyConnectionsError`，
且会把真实的断言失败一起掩盖——单跑每个失败用例都能过）。想显式覆盖该默认值，导出 `ENV`
即可（`$env:ENV="development"; python -m pytest ...`），但那样请自行留意连接数。

## 生成测试产物

```bash
python -c "from pathlib import Path; Path('tmp/test-results').mkdir(parents=True, exist_ok=True)"
python -m pytest --junitxml=tmp/test-results/pytest.xml --cov=app --cov-report=term-missing --cov-report=html:tmp/test-results/coverage --cov-report=json:tmp/test-results/coverage.json
```

日志、覆盖率与机器可读结果统一写入已忽略的 `tmp/test-results/`。有必要保留验收证据时，在本指南记录结果及证据位置。

前端验证在正式工程中执行：

```bash
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

业务与角色权限浏览器回归从 `frontend/` 执行：

```bash
node tests/business-workflows.mjs
node tests/study-workflows.mjs
node tests/assessment-workflows.mjs
node tests/role-access.mjs
node tests/member-self-workflows.mjs
node tests/admin-accounts.mjs
```

流程使用合成 API 响应；需要可用的 Playwright Chromium，可通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指定。`frontend/scripts/screenshot-pages.mjs` 使用拦截响应生成设计截图，适合版面检查；真实业务联调需要实际后端、数据库、Redis 与模型调用。

## 业务评测

后端就绪后，通过进程环境变量 `EVALUATION_ACCESS_TOKEN` 提供已有登录令牌，再执行：

```bash
python tests/evaluation/run_evaluation.py --base-url http://127.0.0.1:8000/api/v1 --output tmp/test-results/evaluation.json
```

评测器请求真实检索与问答接口；会产生模型调用。缺令牌、未就绪或调用失败返回阻塞/失败，退出码为 2。默认输出目录 `tests/evaluation/results/` 也已加入忽略规则。

当前 `tests/evaluation/qa_samples.json` 的问答样本为 20 条，其中拒答 6 条、时效 0 条，尚未达到验收要求的 200/30/20。关键词命中不能代替专家答案正确性审查，串行请求延迟不能代替负载性能。

## 党员端与系统权限回归（2026-10-11）

当前本地工作区将党员功能限定为本人档案、个人材料、制度问答。本人档案需组织人员明确关联，私有原件与组织登记材料分开，提交支持重试幂等；党员不能访问知识库或管理工作台。系统菜单、页面及运行/就绪详情仅平台管理员可查看，公开探针只返回整体状态及原有 200/503 状态码。

- `python -m pytest tests/unit tests/security tests/integration/test_member_self_service.py -o addopts= -p no:cacheprovider -q --tb=short`：359 通过、1 跳过；跳过为缺少 `pypdf` 的 PDF 读取用例。测试进程清空两种云端密钥变量；包含组织被删除后的提交门禁和新增迁移唯一约束断言。
- 前端类型检查通过；`npm --prefix frontend run build -- --configLoader native` 通过，使用 native 配置加载避免当前 Windows 沙箱的子进程限制。
- `node tests/member-self-workflows.mjs`：4组检查通过，覆盖三个功能菜单、只读本人档案、原件提交、失败保留输入、提交重试编号、刷新后记录、下载原件、未关联门禁及移动布局。`role-access` 覆盖七种角色、系统页直达及授权异常；原有 business（含账号关联）、study、assessment 三个工作流也通过。
- `test_member_self_service.py` 使用实际 HTTP、SQLite 表和 ORM 事务，覆盖明确账号关联、同名、跨账号/租户、文件大小/格式、下载、重复与唯一约束竞争、组织接收范围。PostgreSQL 迁移 SQL 离线渲染通过；系统 HTTP 测试使用替代探针。

浏览器 API 为合成响应；本次截图保存在 `tmp/test-results/member-self/`。未执行真实账号联调、真实 PostgreSQL 升级、数据库集成全套或发布部署。迁移 `012_member_self` 应用后，组织人员还需在名册中明确关联现有登录账号，不会自动推断关联关系。

## 已有验证记录

最近记录日期：2026-10-10；被测对象为当时的本地工作区，包含未提交修改。来源为[修复记录](archive/2026-10-10/PROJECT_REPAIR_2026-10-10.md)和[云端联调记录](archive/2026-10-10/MODEL_INTEGRATION_2026-10-10.md)。

| 检查 | 此前记录 | 范围 |
| --- | --- | --- |
| 完整 pytest | 306 通过、0 失败、0 跳过；分支覆盖率合计 78.00% | Python 3.13.9，部分共享依赖不同于锁定版本 |
| 前端构建 | 正式前端与登录测试前端通过 | 类型检查与生产构建 |
| 浏览器联调 | 基础 14 项、云端 9 项通过，页面异常 0 | 正式页面、实际后端与独立测试库；云端阶段使用合成资料 |
| 三个模型 | 聊天、1024 维向量及重排实际调用通过 | 仅覆盖当时配置与合成输入 |
| 静态与配置检查 | 57 个 Python 文件格式/风格、两套 Compose 配置及 Bash 语法通过 | 未执行生产构建或部署 |
| mypy | 前置检查未通过 | SQLAlchemy 插件缺失，未进入业务代码分析 |

完整日志与截图的位置保留在上述归档记录中。真实业务质量与专家复核、负载测试、锁定依赖的干净 Python 3.11 环境、生产镜像和备份恢复仍未验收。

## 最新业务整合回归

2026-10-10 的整合工作区完成以下检查；来源与边界见[整合记录](LOCAL_FIX_AND_SELECTED_INTEGRATION_2026-10-10.md)。

- `python -m pytest tests -o addopts= -q --tb=short`：339 通过、1 跳过，跳过原因是当前环境缺少 `pypdf`。测试进程清空云端密钥，数据库测试使用随机独立 PostgreSQL 库。
- 正式前端类型检查与生产构建通过。
- `node tests/business-workflows.mjs`：在 `frontend/` 中执行，四组浏览器流程通过，覆盖名册、流转参数、软删除与历史会话；API 使用合成响应。
- 开发库升级至 `005`，原六张核心表数据摘要一致；实际 Redis 7 认证读写探针通过。

浏览器脚本可用 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指定已有 Chromium，截图默认写入 `tmp/`。最新整合没有重新调用真实云模型，也没有以真实账号进行人工验收。

## 模块5与共用业务回归

2026-10-10 当前工作区完成全项目 `pytest`：409通过、0失败、1跳过，跳过原因为缺少 `pypdf`。模块5包含17项规则及18项真实HTTP/独立数据库测试，覆盖权限、期间、去重、组织转接、源版本、审核、提醒、归档及导出；迁移升级/回滚保留既有文档。结果位于 `tmp/test-results/assessment-regression.xml`。

前端类型与生产构建通过。在 `frontend/` 执行 `node tests/assessment-workflows.mjs` 的7组浏览器流程通过；接口使用合成响应，截图位于 `tmp/test-results/assessment-browser/`。真实学校指标、组织认可的人工台账对照及现有业务库迁移未验收，详见[模块5记录](MODULE5_ASSESSMENT_2026-10-10.md)。

## 中心组学习回归（模块4）

2026-10-10，模块4本地实现、隔离数据库迁移及正式前端验证见[实现与验收记录](MODULE4_STUDY_2026-10-10.md)。测试进程不读取云端密钥，数据库用例使用随机独立测试库；没有改动业务库。

模块4回归执行 `python -m pytest tests/unit/test_study_minutes.py tests/integration/test_study_workflow.py`；正式页面从 `frontend/` 执行 `node tests/study-workflows.mjs`。浏览器API使用合成响应，覆盖年度计划、材料提纲、不同审核人、参学与原文纪要、归档门禁、可读导出、历史统计、请求重试和移动布局。学校真实组织、电子效力确认及用户验收仍待完成。

## 审查分支记录的适用范围

[模块4/5审查](MODULE4_MODULE5_REVIEW_2026-10-10.md)记录独立分支 `codex/modules4-5-review-20261010` 的最终整合：422通过、0失败、1跳过，缺少 `pypdf`；未验证覆盖率、mypy、锁定Python3.11环境或生产部署。这是历史分支结果，本次没有重跑或将其视为当前工作区验收。

[模块1—3审查](MODULE1_MODULE2_MODULE3_REVIEW_2026-10-10.md)针对另一固定上传版本和独立修补分支，包含本工作区没有的文件存储、全流程党员发展与独立组织生活代码。报告的测试数和修补不能直接套用到当前项目。以实际检出的代码、明确版本和新执行日志为准。

## 系统管理员开户回归

2026-10-11，当前工作区新增 `/accounts`、`POST /api/v1/admin/users` 和 `GET /api/v1/admin/org-units`。测试进程清空云端密钥；使用合成人员、实际 SQLite ORM、真实 JWT 鉴权及内存吊销存储，不连接业务数据库或 Redis。

- `tests/integration/test_admin_accounts.py`：43 项通过，覆盖七种角色分配、未登录和非系统管理员拒绝、跨租户/已删除组织拦截、角色与组织类型、输入校验、不回显密码、重名与唯一性冲突恢复、失败事务回滚、审计以及创建后登录。并发冲突通过模拟预检查后插入同名账号并由实际 SQLite 唯一约束验证。
- 与 `tests/security/test_system_access.py`、`tests/security/test_permission.py` 和 `tests/unit/test_migrations.py` 一并执行：91 项通过；这是相关回归，未重跑全项目测试，未执行真实 PostgreSQL 升级。
- `npm --prefix frontend run typecheck` 与 `npm --prefix frontend run build` 通过；构建在允许 Vite 启动子进程的环境执行。
- `node frontend/tests/admin-accounts.mjs` 的 7 组流程通过，使用合成 API 响应，覆盖六种其他角色的菜单/路由拒绝、角色组织选择、Unicode 密码边界及确认、重名后修正、重复提交拦截、成功后清空凭证、组织加载重试和空组织阻止开户。桌面与 390px 手机截图已检查，位于 `tmp/test-results/admin-accounts/`。
- 浏览器测试指定本机已安装的 Chromium，并在允许启动浏览器子进程的环境执行；没有浏览器运行错误或意外接口请求。

开户复用现有用户表，无新增数据库迁移。未在业务库创建实际账号，未执行生产部署、真实 PostgreSQL 并发或负载测试；正式租户/组织与真实账号人工验收仍需完成。

## 对外通知渠道抽象层回归

2026-10-15，新增 `013_notification_delivery` 迁移、`app/services/notifications.py`（事件→渠道协议、登记表、去重/重试/审计）以及治理页「运行审计」的通知渠道与投递台账区块。

- `tests/integration/test_notifications.py`：7 项通过。使用一次性 PostgreSQL 库并 `alembic upgrade head`（顺带验证 `013` 真的建表），外部渠道由假发送器代替，不依赖任何凭据；覆盖默认不外发、站内渠道按路由投递、同键重放不重复外发、失败重试到成功、重试用尽保留失败分类且不抛异常、未登记与未配置渠道一律留痕、按内容派生去重键。
- `tests/integration/test_db_migration.py` 新增用例断言库版本等于由迁移脚本推导的 head：此前就绪探针把期望版本写死为 `012_member_self`，新增迁移会让 `/health/ready` 永久 503，故障表现与真实原因完全错位。
- 与 `tests/integration/test_module6_http.py`、`tests/integration/test_admin_accounts.py`、`tests/integration/test_module6_governance.py`、`tests/unit/test_module6_security_ops.py`、`tests/security/test_permission.py` 一并执行：全部通过。
- `node frontend/scripts/check-roles-ui.mjs`（7 个角色）通过：具备 `ops.query` 的角色能在「运行审计」看到渠道 `inapp`、路由与投递台账并带「发起渠道自检」，其他角色连标签都不出现。
- 开发库端到端手工核对：`POST /api/v1/admin/notifications/dispatch` 对站内渠道返回 `sent`（尝试 1 次），对未登记渠道返回 `failed/unknown_channel` 并留下台账与审计；普通党员访问三个通知接口均为 403。

未覆盖：企业微信/邮件等外部渠道尚无实现与凭据，未做真实外发验收，也未做多副本投递协调。

## 审计高级检索与对账包导出回归

2026-10-16，`GET /admin/audit-logs` 补数据级别与跨租户筛选，新增 `GET /admin/audit-logs/export`（对账包：台账 CSV + 导出说明 + manifest），并把审计查询条件收口为 `app/core/audit.py::AuditQuery`（列表与导出共用同一份条件与字段清单）。

- `tests/unit/test_audit.py`：15 项通过（原有 10 项 + 新增 `TestAuditQuery` 5 项：条件齐全、计数语句无排序、口径话术含北京时间与匿名口径、`audit_view` 字段与 ISO 时间）。
- `tests/unit/test_audit_export.py`：9 项通过。台账列值与北京时间换算、JSON 与空值回落、说明含导出人 / 条数 / 筛选口径、zip 三件套、公式注入防护、空结果仍是可打开的文件。
- `tests/integration/test_module6_http.py`：新增 2 项通过（一次性 PostgreSQL 库 + `alembic upgrade head`）。覆盖动作筛选与数据级别叠加、时间窗（北京时间 `+08:00` 入参）、跨租户 `tenant_id` 403 与外校管理员只见本租户、导出内容与口径说明、导出动作审计留痕（摘要口径 sha256 + 字节数）、超限 413 话术。
- 与 `tests/unit/test_qa_records.py`、`tests/integration/test_selected_business_features.py`、`tests/security/test_permission.py` 一并执行：全部通过。
- `node frontend/scripts/check-roles-ui.mjs`（7 个角色）通过：具备 `ops.query` 的角色在「运行审计」能看到对象类型 / 数据级别 / 北京时间筛选、导出当前筛选入口与「当前口径」说明，跨租户「租户编号」只对平台系统管理员出现；不具备的角色连标签都不出现。
- 导出失败提示（新增）：`frontend/src/api/http.ts` 对 `responseType: 'blob'` 的错误体按内容类型解回 JSON，否则后端为导出准备的可执行提示会退化成「请求失败（HTTP 413）」。真机点"导出当前筛选"（当前 7599 条 > 上限 5000）确认界面显示完整提示与请求编号。
- 开发库端到端手工核对：`GET /api/v1/admin/audit-logs/export?action=query` 返回可打开的 zip（台账 1684 行、manifest 写明导出人 / 条数 / 筛选口径 / 排序，行时间为北京时间并按正序），`branch-secretary` 访问审计查询为 403。

未覆盖：导出件无数字签名与水印（复制件的二次传播不可控）；审计表只留操作摘要（`old_value` / `new_value` 为 sha256 与字节数），导出不含被操作对象原文；未做 5000 条以上大表的性能验收（超限直接 413 并提示分批）。

## 工作流运行日志回归（T-SYS-06E）

2026-10-16，新增 `GET /admin/run-logs`（权限 `admin.ops`，与「运行审计」标签同一枚）与前端「运行审计 → 运行日志」。运行日志**不新建表**：任务队列的入队 / 每次尝试失败 / 完成，以及三处定时扫描本来就已经写进审计，这里按事件把它们读成可筛选的运行日志（`app/services/run_log_service.py`：纯查询构造 + 行映射，租户边界与权限判定留在接口层），并给 `job_completed` / `job_attempt_failed` 的审计补上实测耗时 `duration_ms`。

- `tests/unit/test_run_logs.py`：15 项通过。事件集合只含运行事件（普通请求审计不在内）、事件 / 结果 / 时间窗 WHERE 子句、任务类型走任务表子查询（不引入 JSON 运算符）、口径话术与北京时间换算、行映射（入队摘要行按任务表补类型、失败行带第几次与错误类型、扫描行带条数、未知事件回落、不可信字段类型不进数字）。
- `tests/integration/test_module6_http.py`：新增 1 项通过（一次性 PostgreSQL 库 + `alembic upgrade head`）。覆盖支部角色 403、入队 → 完成 → 失败三条事件的关键字段（任务类型、处理条数、耗时、第几次、错误类型、状态）、事件 / 结果 / 时间窗筛选、未知事件与未知任务类型 422、起止时间反向 422、跨租户不可见。
- `tests/integration/test_module6_governance.py`：扩展既有队列用例，钉住耗时语义——真正执行后的失败必须有实测耗时；**领取时发现租约已耗尽、事实上没有执行**的尝试（`error_code=lease_exhausted`）不写耗时；并把 `asyncio.wait_for` 超时（`TimeoutError`）分支走通：落失败审计（带实测耗时）、任务转 `retry`、`run_once()` 正常返回（调度循环存活）。
- `node frontend/scripts/check-roles-ui.mjs`（7 个角色）通过：具备 `admin.ops` 的角色在「运行审计」能看到「运行日志」区块、查询入口、任务类型筛选与失败口径说明；不具备的角色连「运行审计」标签都不出现。
- `node frontend/scripts/verify-module6.mjs --serve`：14 项通过（原 13 项 + 运行日志 1 项）。`/admin/run-logs` 纳入界面契约（一条完成 + 一条失败），并断言时间筛选按 `+08:00` 发出、界面显示「139 毫秒」与 `HTTPException`、分页显示「第 1 页 · 共 2 条」。
- 开发库端到端手工核对：`GET /api/v1/admin/run-logs` 返回 699 条（613 条任务完成 + 86 条考核提醒同步），口径说明为「租户 TEST_TENANT」；`test-member` / 支部书记访问 403、未知事件 422；实跑一条正常任务与一条必然失败，审计行分别为 `{"kind":"member_reminders","processed":0,"duration_ms":139}` 与 `{"kind":"embedding","attempt":1,"status":"failed","error_code":"HTTPException","duration_ms":16}`，界面按事件筛「执行失败」后只剩这一行（第 1 次 / 16 毫秒 / HTTPException）。

未覆盖：运行日志是审计的读模型，能回溯多久由学校配置的审计保留天数决定，不另存更长历史；`assessment_reminders_scan`（手动补扫，走 `audit_operation`）只记"跑过 / 结果"，不记生成条数（该端点 `new_value` 走统一摘要口径，条数只在接口响应里）；失败不记供应商错误正文；不提供导出；未做真实 120 秒超时的长跑验证（超时分支由单测注入 `TimeoutError` 覆盖，不是真等满 120 秒）。

## 版本留痕回归（T-SEC-11）

2026-10-16，新增 `GET /admin/version-trail`（权限 `admin.audit`，与审计查询 / 问答记录同一枚）与前端「运行审计 → 版本留痕」，问答记录列表与 Excel 台账新增「版本」列。三块来源各自权威、**不新建版本登记表**：提示词版本取自 `config_revisions` 的变更历史（当前值来自租户配置，未配置回落出厂默认 `v1`），工作流契约版本取自代码常量（`app/schemas/wf.py` 的 `WF-03` / `WF-04`），知识库版本取自条目的入库与内容更新审计。写侧在**回答产生的那一刻**记指纹：`qa_sessions.versions`（迁移 `016_qa_session_versions`）＋ `Citation.content_revision`，存量不回填。

- `tests/unit/test_version_trail.py`：15 项通过。提示词历史只列真的改了提示词的提交、首次登记基准为"未设置"、出厂默认回落；工作流契约版本清单；知识库事件集合与 WHERE 子句（只收 `create` / `update_content` 且 `result=success`）、修订号与前后版本回落、不可信字段类型不进数字；口径话术与 UTC→北京时间换算。
- `tests/integration/test_module6_http.py`：新增 `test_version_trail_shows_prompt_workflow_and_knowledge_versions` 通过（一次性 PostgreSQL 库 + `alembic upgrade head`）。覆盖支部角色 403、三次配置提交只有两次动提示词（只调别的字段那次不出现）、首次登记 `before=null`、工作流契约版本、入库 + 内容更新两条留痕与「第 2 → 3 版」、只改元数据不出现、跨租户不可见；问答记录用例补断言「版本指纹随记录返回、上线前记录给空对象」、Excel「版本」列值与导出说明口径。
- `tests/integration/test_qa_regressions.py`：新增写侧用例通过——回答返回版本指纹（`prompt` / `workflow`）、落库的就是那一刻的指纹（不是按当前配置重算）、引用带被引文档修订号。
- `node frontend/scripts/check-roles-ui.mjs`（7 个角色）通过：具备权限的角色在「运行审计」能看到「版本留痕」区块、当前生效提示词、工作流契约版本与知识库版本三块及来源口径，问答记录列表有「版本」列且写明历史记录不倒推。
- `node frontend/scripts/verify-module6.mjs --serve`：15 项通过（原 14 项 + 版本留痕 1 项）。`/admin/version-trail` 纳入界面契约，并断言「当前生效：问答提示词 v2 / 追问改写 v1」「问答提示词 v1 → v2」「wf-03/1」与「第 2 → 3 版」。
- 开发库端到端手工核对：`GET /api/v1/admin/version-trail` 三块齐备（当前提示词 `{"qa":"v1","rewrite":"v1"}`、工作流 `wf-03/1` / `wf-04/1`、知识库修订事件 13 条含操作人 / 标题 / 文档标识），`test-member` 403；再走一次真实「入库 → 内容更新」：入库记「第 1 版」（`previous_revision=null`）、内容更新记「第 1 → 2 版」，软删除条目后审计留痕按只追加保留。

未覆盖：留痕上线前的问答记录没有版本指纹（`versions` 为空、界面与导出显示「未留痕」），不按当前配置倒推；工作流契约版本只有现行值，其历史变更在代码与发布记录里，数据库无痕；提示词变更历史最多回溯最近 200 次配置提交；知识库留痕按审计保留天数自然过期，不另存更长历史；只改元数据 / 状态 / 权限的动作不算版本变更；未做真实多租户并发的留痕压力验证。

## 三会一课频次合规回归（T-ORG-10）

2026-10-16，把频次口径单源到 `config/business_rules.yaml` 的 `activity_requirements`（`period` + `per_period`，年度次数由周期推导），按《中国共产党支部工作条例（试行）》校准为支部党员大会每季度 1 次、党支部委员会会议每月 1 次、党小组会每月 1 次、党课每季度 1 次（`other` 为 `period: none` 不出提醒）；新增纯计算服务 `app/services/activity_frequency.py` 与 `GET /meeting/frequency`（参数 `as_of`、`org_unit_id`），前端「组织生活 → 年度统计」新增「三会一课频次合规」区块。

- `tests/unit/test_activity_frequency.py`：37 项通过（无需数据库）。覆盖频次表与年度次数推导（季度→4 / 月→12 / `none`→不出提醒）、`config/business_rules.yaml` 缺失或损坏时回落内置口径、周期窗口（季度 1–4、月 1–12，含闰年 2 月与 12 月跨年边界）、三种状态（已达标 / 已召开未过审 / 期内还差）、按活动类型与组织取数（防串型：支委会不能顶支部大会）、提醒文案、已结束周期缺口聚合（一条支部 × 类型、含 `missed_periods` 与自述文案）、无支部、任意日期参数化。
- `tests/integration/test_meeting_workflow.py`：新增 2 项通过（一次性 PostgreSQL 库 + `alembic upgrade head`）。`test_declared_frequency_matches_the_regulation` 钉住口径本身（`by_type` 的 `required` 为 4/12/12/4、`period_text` 与 `basis`）；`test_frequency_reminder_counts_only_approved_and_scopes_to_branches` 用 `as_of=2026-05-10` + 专用支部（`branch-c`）做隔离，钉住"已召开未过审 → 过审后计入本周期""**审核通过不消除上一季度缺口**（跨周期不抵扣）""只统计已审核""非支部 422、越权支部 403、只读角色 403"。
- `node frontend/scripts/verify-modules123.mjs`：20 组接口契约与界面检查通过。新增 `/meeting/frequency` 契约（一条"已召开未审核"提醒 + 一条上季度缺口）并断言界面出现「三会一课频次合规」「本周期需处理（1）」「纪要尚未通过人工审核」「已召开待审核」「每季度至少 1 次」「每月至少 1 次」，且缺口在「已结束周期缺口（1）」分区内单列。
- `python scripts/validate_modules123_ui_contracts.py tmp/modules123-ui/contract-requests.json`：23 个请求体经后端输入模型校验通过。
- `node frontend/scripts/check-roles-ui.mjs`（7 个角色）通过：可访问组织生活的角色在「年度统计」必须能看到频次合规区块、本周期结论、周期要求与「完成认定以人工审核通过为准」的口径；`/meeting/frequency` 不得出现 4xx。
- 开发库端到端手工核对：`test-reviewer` 调 `GET /api/v1/meeting/frequency` 返回 1 个支部 × 4 类（支部大会 / 支委会 / 党小组会 / 党课），`period_text` 与 `annual_required`（4 / 12 / 12 / 4）与法定口径一致，4 条本周期提醒都带最晚日期与「召开并完成纪要审核」，已结束周期缺口按「本年度已结束 N 个周期中 M 个未达标（逐个列出周期）」聚合成 4 条（支部大会 / 党课各 3 个季度，支委会 / 党小组会各 9 个月）；`as_of=2026-05-10` 复现历史时点；越权组织 403「无权查询该组织」、`test-member` 403「权限不足：缺少 meeting.query」；`GET /meeting/stats?year=2026` 的 `by_type` 同步为 4 / 12 / 12 / 4 并带 `period_text` / `basis`（`other` 为「不设固定频次」）。
- 顺带修掉的既有问题（都在共享件里，非本任务引入）：`frontend/src/components/PageHeader.vue` 的 `.page-head__actions` 未换行，390px 下把页面撑出横向滚动（`members-mobile` 检查可复现，已加 `flex-wrap: wrap`）；`verify-modules123.mjs` 的「空数据状态」断言停留在旧文案（`KnowledgeView` 已区分无筛选的「授权范围内暂无可读文件」与有筛选的「没有匹配的文件」），该脚本不在质量门禁内所以长期失败，现按两条分支分别断言。

未覆盖：系统没有党小组模型，党小组会提示恒给（`basis` 标明「未划分党小组的支部不适用」，可在配置里设 `period: none` 关闭）；不做自动认定完成（完成认定仍以人工审核通过为准）；只做页面提醒，不生成待办任务、不发通知；`as_of` 只读、不回填历史缺口、不产生数据；未做超 200 个支部的分页查看（截断时显式提示）。

## 组织生活会 / 民主评议党员回归（T-ORG-11）

2026-10-16，组织生活会复用 `meeting_records`（`activity_type = organizational_life_meeting`，口径入 `activity_requirements` 为 `period: year` × `per_period: 1`）并**按活动类型切换纪要栏目**（查摆问题 / 批评意见 / 整改方向，模板 `org-life-meeting-1`；原三会一课标准模板仍是 `org-life-1`）；民主评议党员新增**一人一年一条**的 `member_reviews`（迁移 `017_member_reviews`，唯一约束 tenant × year × profile），「组织生活」新增「民主评议党员」工作区，统一人工审核新增 `source_kind = "member_review"`，原「三会一课频次合规」区块改名「组织生活频次合规」（面板现在也覆盖年度组织生活会）。

- `tests/unit/test_member_review.py`：28 项通过（无需数据库）。覆盖民主测评票数校验（实到不得超应到、各等次合计不得超实到、弃权允许、应到为 0 不做合计校验）、等次受 `config/business_rules.yaml` 的 `democratic_review.grades` 驱动（配置改了列表就跟着改、未知等次键回落默认四项、配置缺失回落内置）、缺项只列四项阻断字段且各一次（个人自评 / 支部评定意见 / 等次 / 评定依据）、党员互评与测评票数是 `advisories` 不阻断、**只打空格不算填**、逐行视图的 `can_review`（提交人本人不给审核入口、无审核权不给入口、只有 `pending` 可审）、评议对象只含正式党员与预备党员（未知 / 空阶段不抛异常）、以及三条文案口径（不承诺自动定等次、优秀比例按上级规定且系统不截断、不合格处置由党组织研究决定）。
- `tests/unit/test_org_life_minutes.py`：8 项通过。钉住组织生活会的栏目恰为「查摆问题 / 批评意见 / 整改方向」、按该类型提取原文与缺项、**三会一课模板不能顶替组织生活会**（反之亦然）、组织生活会缺项用会议口径而不是中心组学习口径、条目上限对新栏目同样生效。
- `tests/unit/test_activity_frequency.py`：42 项通过（新增组织生活会的年度周期：`period_text` 为「年度」、`annual_required` 为 1、`periods_in_year` 为 1，类型键与 `ACTIVITY_TYPES` 保持键相等）。
- `tests/integration/test_member_review_workflow.py`：5 项通过（一次性 PostgreSQL 库 + `alembic upgrade head`）。钉住发起 → 录入 → 送审 → **另一位**审核 → 生效 → 本人可见的完整链路；越权组织 403；送审缺项 / 只打空格 / 票数越界 / 等次非法 / `expected_revision` 过期分别 422 与 409，退回后可重新送审；低等次进「需按党章党规研究处置」提醒且带整改要求；统一审核队列 `POST /admin/reviews` 送审 + `.../decision` 决定同一条记录。
- `tests/integration/test_meeting_workflow.py`：9 项通过（新增 1 项：组织生活会用自己的纪要模板，断言栏目恰为三项且不含「学习要点 / 讨论共识 / 工作要求」；既有频次用例的待审集合加入 `organizational_life_meeting`）。
- `node frontend/scripts/verify-modules123.mjs`：26 组接口契约与界面检查通过。新增 6 项：民主评议工作区（应评议党员、未发起进度、`优秀 1 人，占应评议 20%`、四个等次徽标、缺项「个人自评待录」与提示「未登记民主测评票数」分别显示、低等次提醒带整改要求）、未发起党员的「录入评议」新建草稿、按年度发起**只补缺不覆盖**（断言「已发起：新建 1 条草稿，跳过 4 条已有记录（共 5 名在册党员）」）、录入送审与**提交人不能自审**（断言审核按钮数量不因自己送审而增加）、他人审核生效、已生效评议修订回到草稿；查询权限账号看不到「按年度发起 / 录入修订 / 审核 / 保存并送审」任何写入口。
- `python scripts/validate_modules123_ui_contracts.py tmp/modules123-ui/contract-requests.json`：29 个请求体经后端输入模型校验通过（新增 5 个 `/meeting/member-reviews*` 契约：发起 / 新建 / 修订 / 送审 / 审核）。
- `node frontend/scripts/check-roles-ui.mjs`（7 个角色）通过：可访问组织生活的角色在「民主评议党员」工作区必须看到年度工作区标题、应评议党员口径、进度与「系统不按票数排名、不自动定等次」的口径；`/meeting/member-reviews/workspace` 不得出现 4xx；改名后的「组织生活频次合规」区块与周期要求仍在「年度统计」。
- 开发库端到端手工核对（`TEST_TENANT` / `TEST_BRANCH`，2 名应评议党员）：工作区 200 只列正式党员与预备党员、给出 4 个等次选项与两条边界口径；按年度发起新建 2 条草稿（再点返回 `created: 0`、`skipped: 2`）；录入后 `missing: []`、`advisories: ["未登记党员互评意见"]`；送审 `pending` → 另一位审核 `approved`、生效等次「合格」，留痕 `v1 launch / v2 revise / v3 submit / v4 review`；`GET /admin/reviews?status=pending` 能列出 `source_kind = member_review` 并由另一名同租户成员审核通过；组织生活会从登记 → 生成议程（含会前谈心谈话）→ 纪要只出「查摆问题 / 批评意见 / 整改方向」（未选政策依据时如实列「政策依据待补」）→ 提交 → 他人审核通过，`GET /meeting/frequency` 随之把该支部 2026 年度组织生活会从「还差 1 次」变成达标。

未覆盖：不自动生成 / 不按票数排名等次、不自动生成不合格处置意见、不自动限制优秀比例（只在页面写明「按上级规定执行、系统不自动截断」）；不产生组织生活会与民主评议的个体通知与待办；评议结果不自动写入档案正文（本人经「本人档案」看自己的结果，归档正文仍走既有流程）；**年度考核 `source: meetings` 的会议计数会把组织生活会一并计入 `LIFE_001` / `LIFE_002`**（`assessment_sources.py` 只排除中心组学习，未按活动类型拆分——计数口径如此，未改）；民主测评只存汇总票数、不存逐人票向（不可回溯到人）；本人查看只返回本人 `approved` 的年度结果，测试账号未与名册档案关联时为空列表（关联后的可见性由集成用例覆盖）；未做多支部大批量发起的性能验证。

## 党员组织关系接转回归（T-MEM-14）

2026-10-16，党员组织关系接转落在**独立台账** `member_transfers`（迁移 `018_member_transfers`，接转不是阶段流转：转出不动 `current_stage`、不删档案），登记转入 / 转出与介绍信要素（编号 / 开具日期 / 有效期至）、对方组织名称与回执；组织关系状态由台账唯一推导并同步到 `member_profiles.relation_status` 缓存列，供名册列表 / 名册统计 / 民主评议应评议名单三处共用。「党员发展」新增「组织关系接转」工作区（汇总、筛选、登记转出 / 登记转入 / 登记回执 / 作废 / 逐行留痕），名册新增「含组织关系已转出人员」筛选与状态标识。

- `tests/unit/test_member_transfer.py`：10 项通过（无需数据库）。覆盖介绍信有效期换算与配置回落（默认 +90 天、配置改了跟着改、`issued_on` 晚于 `valid_until` 时 `valid_until` 优先）、逾期只对「待接收」成立（已回执 / 已作废不算逾期）、`days_left` 正负号与端点、**状态推导**（同一档案多条记录时取最新有效记录；作废一条不能把另一条仍然有效的转出关掉；只有作废与已回执记录时回到「在册」）、阶段与方向标签、受访组织 / 阶段为空时的兜底文案、接转只适用于预备党员与正式党员、`StageRules.materials_for_stage` 与既有 `material_requirements` 逐阶一致（申请人 0 / 积极分子 2 / 预备党员 10 / 正式党员 12，非发展阶段为空）、以及转出 / 转入 / 回执 / 作废四类输入契约（转入必须给接收组织、姓名与档案编号不能同填、理由不得为空或只有空格、日期不得为未来、`revision` 必须为正）。
- `tests/integration/test_member_transfer_workflow.py`：4 项通过（一次性 PostgreSQL 库 + `alembic upgrade head`）。钉住转出 → 待接收 → 回执 → 已转出并**移出名册与民主评议应评议名单**（可显式 `include_transferred` 查回，带 `relation_status`）；转入可关联既有档案（校内支部之间调动，只改档案归属、不新建档案）或按姓名 / 阶段 / 进入阶段日期新建档案，并按阶段给出档案清单与缺项 `member_archive_checks`；以及越权组织 403、培养对象 422、同一档案重复未办结 409、已转出再转出 409、重复回执 409、已作废再回执 409、作废后状态回推、超过有效期只标记 `overdue` 不判定失败。
- `node frontend/scripts/verify-modules123.mjs`：32 组接口契约与界面检查通过。新增 6 项：登记转出后状态停在「转出待接收」且不改发展阶段（转出候选里不出现入党积极分子）、收到回执才算转出完成并移出在册名单、已转出人员默认不在名册但勾选后可查且带标识、转入关联既有档案并当场列出档案缺项、超过介绍信有效期只提示核实不自动判定失败、接转可作废（视同未发生但记录保留）。
- `python scripts/validate_modules123_ui_contracts.py tmp/modules123-ui/contract-requests.json`：35 个请求体经后端输入模型校验通过（新增 3 个 `/member-full/transfers*` 契约：登记 / 回执 / 作废）。
- `node frontend/scripts/check-roles-ui.mjs`（7 个角色，本地后端 `RATE_LIMIT_PER_MINUTE=5000`）通过并新增「接转工作区必须挂载」检查：可访问党员发展的角色在「组织关系接转」必须看到台账汇总与「转出开了介绍信不等于转出完成」的口径、「登记转出 / 登记转入」写入入口（这些角色都具备 `member.stage_transition`），名册必须有「含组织关系已转出人员」筛选，`/member-full/transfers*` 不得出现 4xx、工作区不得出现错误态。
- 开发库端到端手工核对（`TEST_TENANT` / 支部秘书账号，`合成周砚青` 正式党员）：名册带出 `relation_status: in_place`；登记转出 → 状态「待接收」；紧接着重复转出 → 409「该党员已有一次未办结的接转（转出介绍信 手工核对转字2026-001），请先回执或作废后再发起」；回执 → 「已转出」且名册默认查询不再包含该党员；重复回执 → 409「本次接转已回执，无需重复登记」；明细留痕 `create` / `settle` 两条且各带办理理由；再开一封 200 天前的介绍信走转入 → `overdue: true`、`days_left: -110`、档案清单 12 项（正式党员）；作废 → 「已作废」且组织关系状态回推到「已转出」（更早那条已回执的转出仍然有效，作废只让本次视同未发生）；汇总计数随之为 `settled_out: 1 / revoked: 1`。

未覆盖：不做上级党组织审批 / 备案与报送导出（`T-MEM-11`）；**不采集接收单位联系人与电话**（第三人身份信息，`T-MEM-12` 已建立分级与脱敏，但这条输入契约本身仍然不含联系人与电话，见该任务的 OpenAPI 请求字段测试）；不自动认定接收、不自动判定转出失败、不自动改发展阶段；不产生个体通知与待办；不写党员档案正文（只落既有档案检查的缺项提示，且缺项只提示不阻断登记）；对方组织只记名称文本，不做跨租户 / 跨学校机构字典比对；介绍信有效期是**可配置默认值**（`member_transfer.letter_valid_days`，注释写明按上级党组织规定填写，不编造国家规定天数）；**年度考核 `source: members` 等既有统计未同步排除已转出人员，阶段提醒（`member_scheduler`）也仍会按原档案产生**——本次只统一了名册列表 / 名册统计 / 民主评议三处口径。

## 上级党组织审批 / 备案与报送导出回归（T-MEM-11）

2026-10-16，上级审批 / 备案落在**报送台账** `member_upper_reports`（迁移 `019_member_upper_reports`）：一条记录 = 一次"向上级党组织报送 + 回填上级批复结果"。这是**两件事实的登记，不是系统审批**——系统里没有上级党组织的登录身份，因此**没有"审批通过"接口**，回填批复也不动 `member_profiles.current_stage`（阶段仍走人工流转）。四件事项与目标阶段 1:1：确定入党积极分子报上级党委**备案**（细则第八条）、列为发展对象**备案**（第十三条）、接收预备党员报上级党委**审批**（第二十一 / 二十二条）、预备党员转正报上级党委**审批**（第五章）。「党员发展」新增「上级审批备案」工作区（汇总、事项 / 类别 / 状态筛选、登记报送 / 回填批复 / 作废 / 导出台账 / 逐行留痕）。

- `tests/unit/test_member_upper_report.py`：12 项通过（无需数据库）。覆盖四项事项的键 / 类别 / 目标阶段与依据（备案两项 + 审批两项，依据必须能引到"细则"、空话不算依据）、`can_report` 的阶段前提（入党申请人任何事项都报不了、积极分子只能报积极分子备案而正式党员可补登历史备案 / 审批、退回与非法阶段一律不受理）、随报材料与 `StageRules.materials_for_stage` 同源再叠加事项另需材料（去重保序，预备党员档案清单是其子集）、配置项（`approval_days: 90` / `remind_advance_days: 15` / 四事项都有 `extra_materials`）、超期只对"审批类 + 待批复"成立且到期当天不算（备案类 `days_left` 为 `None`、已回填与已作废不算）、临近提示 `is_due_soon` 只在到期前配置天数内为真（提前天数为 0 即不提示、已超期交给 `overdue` 不再算"临近"）、标签与阶段快照容错（历史行阶段值读不出留空而不是抛错）、回填契约（同意 / 不同意必须给批复文号、需补充材料必须写清缺什么、批复日期不得晚于今天、不接受"由系统批准"之类字段）、报送与作废契约（前后空格清理、不得未来报送、事项必须在目录内、多余字段拒绝、理由不得只有空格）、导出行的 XLSX 结构与空值处理。
- `tests/integration/test_member_upper_report_workflow.py`：3 项通过（一次性 PostgreSQL 库 + `alembic upgrade head`）。钉住报送 → 重复报送 409 → 缺文号回填 422 → 回填（批复文号 / 日期 / 留痕 `submit` / `settle`）→ 重复回填 409，并断言**回填后党员阶段不变**；阶段前提 422、备案类不给期限与 `no_deadline_note` 口径、作废 → 重复作废 409 → 作废后回填 409 → 作废后可重新报送、批复"不同意"只提示不自动回退阶段、重新报送时点名上一次"不同意"、"需补充材料"必须写缺什么；越权组织的档案 404、越权组织筛选 403、非法事项 / 类别 / 状态 422、导出 XLSX（表头与"不含材料原件"的说明页）与本人视角 403。
- `node frontend/scripts/verify-modules123.mjs`：39 组接口契约与界面检查通过。新增 7 项：登记报送只表示材料已报出（依据条文、报给谁与随报材料清单由后端目录给出，界面不自己编）、阶段未到该环节的党员不出现在报送候选里、回填"同意"必须填批复文号（缺文号时提交按钮禁用）且回填不改动党员阶段、审批类超期只提示向上级核实进度（不判定审批失效、不改阶段）、备案类可报送但不显示倒计时且时限如实写「按上级党委规定」、临近审批时限提前提示（不等到超期才第一次提醒）、导出台账只含报送要素与材料清单（不含材料原件与政治审查材料内容）；作废（视同未发生但保留记录）与导出同批断言。
- `python scripts/validate_modules123_ui_contracts.py tmp/modules123-ui/contract-requests.json`：41 个请求体经后端输入模型校验通过（新增 6 个 `/member-full/upper-reports*` 契约：报送 4 次 / 回填 / 作废）。
- `node frontend/scripts/check-roles-ui.mjs`（7 个角色，本地后端 `RATE_LIMIT_PER_MINUTE=5000`）通过并新增「上级审批备案工作区必须挂载」检查：可访问党员发展的角色必须看到台账汇总与三条边界口径（不代替上级党组织审批 / 回填批复不改动党员阶段 / 备案类时限按上级党委规定）、「登记报送」与「导出台账」入口，且不得出现「系统审批 / 审批通过 / 批准入党」这类假入口；`/member-full/upper-reports*` 不得出现 4xx、工作区不得出现错误态与页面级横向溢出。
- 开发库端到端手工核对（`TEST_TENANT` / 支部秘书账号，脚本可重复执行、开跑前先作废上一轮遗留的未办结记录）：四事项目录与材料数（备案 3 / 7 项、审批 12 / 14 项）；报送"接收预备党员" → 「已报送待批复」、`deadline` 为报送日 +90 天、`days_left: 80`、`due_soon: false`；重复报送 → 409；用入党积极分子报"接收预备党员" → 422（并提示应在支委会 / 支部大会作出决定后登记）；报"确定入党积极分子备案" → 200 且 `deadline` / `days_left` 为 `null`；缺文号回填 → 422；回填「同意」→「已回填批复」且 `GET /member-full/profiles/{id}` 的 `current_stage` 不变；重复回填 → 409；留痕 `submit` / `settle` 两条；200 天前的"预备党员转正" → `overdue: true` / `days_left: -110`，`?overdue=true` 只出这 1 条；80 天前的一条 → `due_soon: true` / `days_left: 10`（临近时限提前亮出来）；作废 → 重复作废 409、作废后回填 409；导出 200（`spreadsheetml`、7543 字节、`PK` 头），openpyxl 复读表头 15 列与说明页均正确。

未覆盖：**不代替上级党组织审批**、不生成"是否批准"的结论；不做"应报未报"的自动扫描（存量名册噪声大，且没有可核对的"应报"规则）；不产生个体通知与待办；不自动改阶段、不自动回退阶段、不自动把人移出名册；不采集上级组织联系人与电话（第三人身份信息，`T-MEM-12` 已建立分级与脱敏与请求字段测试，这条输入契约仍然不采集）；`upper_org` 只记名称文本，不做跨租户 / 跨学校机构字典比对；不与档案检查（`T-MEM-09`）联动（报送不因档案缺项被拦）；批复件原件不入本台账（导出只带材料清单，原件仍走既有材料 / 归档流程）；`remind_advance_days` 只用于台账与界面里的"临近审批时限"提示，**未接入通知 / 待办通道**（超期同样只在台账与界面提示）。

## 政审 / 评议第三人信息脱敏与字段级敏感分级回归（T-MEM-12、T-SEC-01）

2026-10-16，党员材料 / 民主评议 / 选优投票接上**字段级密级**：密级的唯一来源是 `app/rules/data_sensitivity.py`（读 `config/business_rules.yaml` 的 `data_sensitivity`：材料类型→密级、简称归一、评议 / 投票密级，配置损坏时回落到更保守的出厂默认），密级落到记录字段 `member_materials.data_level`（迁移 `020_member_data_levels`，登记时按材料类型快照）与 `member_reviews.data_level`（存量材料按材料类型回填、存量评议回填 `sensitive`）。读取出口按查看者等级（由登录角色推导，不接受客户端传入）收敛**第三人字段**（`note` / `description` / `comment` / `peer_review`，含 `procedure` 内与留痕快照内的同名字段）；**选优投票汇总改成无记名**（不再返回他人 `voter_id`，只回 `voted_by_me` 与票数）；第三人字段不进名册 / 报送台账导出；材料 / 评议 / 投票密级直接喂给既有出网与向量化判定。

- `tests/unit/test_data_sensitivity.py`：22 项通过（无需数据库）。覆盖出厂配置下的材料密级（政审 = 涉密、群众评议 = 敏感、其余 = 内部）、简称不能绕开密级（换写法仍归一到正式名）、未知类型按内部、配置读不到时回落到更保守的默认而不是放行、配置可抬高单项而不连带抬高其它、密级比较与标签、出网（敏感及以上不出网）与向量化（涉密不入向量库）口径、按等级脱敏（同级保留原文、低等级换成占位、涉密用涉密占位、空值不算被脱敏、`procedure` 与留痕快照递归脱敏）、导出用整列丢弃、占位文本判定，以及**扫 OpenAPI 全部请求体断言不含第三人身份字段**（投票人 `user_id` 这类身份信息不返回、也不接受客户端提交）。
- `tests/unit/test_member_review.py`：33 项通过（新增 5 项：同级查看者看得到党员互评原文只多出密级标注、低等级查看者看不到互评但**自己的**个人自评仍可见（自评不是第三人信息）、留痕快照里的互评同样按等级脱敏、涉密级评议对全部角色都不返回第三人字段正文、客户端把脱敏占位原样提交回来时不写回、保留数据库里的原值）。
- `tests/unit/test_modules123_review_regressions.py`：25 项通过（改 1 项 + 新增 1 项：选优投票汇总只回 `agree` / `disagree` / `abstain` / `voted_by_me` 与 `voter_count`，响应文本里不出现任何投票人 id，另一位账号看到自己的 `voted_by_me` 也为真（`tally` 是渲染给个人看的"我投没投过"）；材料登记按类型带出密级、政审材料的备注与留痕快照都不返回正文、用简称登记同样按正式名给密级、未登记类型按内部）。
- `tests/unit/test_roster_io.py`：23 项通过（新增 1 项：即使上游把 `note` / `description` / `comment` / `peer_review` 塞进导出行数据，导出件里也搜不到这些正文）。
- `tests/unit/test_member_upper_report.py`：13 项通过（新增 1 项：报送台账导出不含第三人字段正文，但**批复说明 `decide_note` 属于台账要素、照样导出**——这是一条要被钉住的边界，防止以后"顺手全脱敏"把台账要素也丢掉）。
- `tests/security/test_content_privacy.py`：4 项通过（新增 1 项：政审 / 群众评议材料的密级直接套既有 `require_cloud_eligible` 与向量化判定——敏感及以上不出网、涉密不入向量库，材料分级不是一句文档承诺而是喂给同一套闸门）。
- `tests/integration/test_member_review_workflow.py`：5 项通过（新增断言：评议详情带 `data_level` / `data_level_label` / `cloud_allowed` / `embedding_allowed` 标注，同级查看者 `redacted_fields` 为空）。
- `tests/integration/test_member_full_workflow.py`：6 项通过（新增断言：材料列表每行都带密级标注且未登记类型 `cloud_allowed` 为真、政审材料登记即 `classified` 且 `cloud_allowed` / `embedding_allowed` 均为假、审核备注写成第三人姓名后读取出口是涉密占位、`redacted_fields` 含 `note`、整个响应文本搜不到原始备注；选优投票汇总不含他人 `voter_id` **响应文本里也不出现投票人 id**，`voted_by_me` 与投票人本人一致）。
- `tests/unit/test_module6_security_ops.py`：改 1 项（`source_kind="vote"` 的"固定提交时的候选范围"测试改成无记名口径，并钉住票数**只能由服务端计数**、不能靠返回的投票人身份再数）。
- `tests/integration/test_module6_governance.py`：新增 1 项——治理页「人工审核」里的选优投票汇总：无记名后审核人打开**不再 500**（票数由服务端按冻结候选范围计数），且换一位"自己没投过票"的审核人打开时**不被判成版本失效**（`voted_by_me` 不进内容指纹）。这是 T-MEM-12 的连带修复：把 `voters` 从汇总里拿掉之后，原来"靠返回明细再数票"的审核路径必须一起改，否则脱敏会把审核页直接打坏。
- `node frontend/scripts/verify-modules123.mjs`：40 组接口契约与界面检查通过。新增 1 项：涉密材料在材料面板标出「涉密级材料：不进名册 / 台账导出，也不交给模型；其中的第三人信息按查看者等级脱敏」，第三人字段正文（脱敏占位以外的原文）不展示；投票汇总 mock 同步改为无记名口径（`voted_by_me` 代替 `voters`），前端「已投票」判断跟着改。
- `python scripts/validate_modules123_ui_contracts.py tmp/modules123-ui/contract-requests.json`：41 个请求体经后端输入模型校验通过（本次没有新增请求体——脱敏与分级都发生在响应出口，输入契约不变）。

未覆盖：**不做内容识别**（不猜自由文本里有没有提到第三人，分级只按材料类型与登记口径，因此"把第三人信息写进别的字段"系统识别不出来——要收紧只能把该材料类型的密级调高）；政审类材料默认涉密，其第三人字段对**全部角色**都不返回正文（含系统管理员），界面只留密级标注与"正文请查党组织线下原件"的占位，学校若要放宽到"组织人员可见"需改配置（注释写明这是放宽）；群众评议材料默认敏感级，而当下能读评议的角色都是敏感级，因此这条字段级门槛今天只在配置抬高或角色降级时才真正改变可见性（不写成"已经挡住了谁"）；不按等级屏蔽整条记录（只收敛第三人字段，记录元数据与业务要素照常可见）；不新增权限（等级门槛与权限门槛是两条独立的线）；政审材料的电子原件不入系统（仍是元数据登记，原件走线下 / 既有档案流程），所以"不进知识库 / 不向量化"当下是**结构上成立 + 有守卫**，而不是有一条会把政审正文送进向量库的路径被拦住；不联动 `T-MEM-13` 选优分析的"第二位组织人员审核"节点。

## 选优结论双人审核与团组织推优回归（T-MEM-13、T-MEM-06）

2026-10-17，多轮选优的**人工结论**落地：新表 `member_selections` 与 `member_league_recommendations`（迁移 `021_member_selection`）。结论走「草稿 → 送审 → **第二位组织人员审核** → 生效」，`candidates`（逐人勾选）与 `basis`（依据原文）都是人填的必填输入，`evidence` 只是本轮 `vote_summary` 的无记名汇总按名单裁剪后的**依据快照**（只含票数与 `voter_count`，不含投票人身份）；系统不排序、不自动补人、不定等次，生效也不改 `member_profiles.current_stage`，只按目标阶段给「该报哪一项上级备案 / 审批」的提示（只提示不自动报送）。团组织推优只登记事实（推荐团组织 / 推荐日期 / 推优说明，可作废保留记录）：**系统不判断年龄**（全仓库没有出生年月字段，不新增生日字段、不做 28 周岁校验），缺推优记录只在结论明细里提示、不阻断选优与阶段流转。同时修掉一个只有真机会暴露的既有问题（迁移 `022_member_vote_dedup_batch`）：`member_votes` 的唯一约束漏了 `batch_no`，比服务层查重更严，同一投票人在新年度批次的第 1 轮投票会被抛成 500。

- `tests/unit/test_member_selection.py`：13 项通过（无需数据库）。覆盖结论必须由人给名单与依据（不按票数生成）、研究日期不得晚于今天、目标阶段只能向前、只有 `approved` 才生效且自己送审的版本不给审核入口（`can_review` 为假）、低等级查看者不能审核、结论视图带密级与边界口径、四个目标阶段都有对应的上级备案 / 审批提示、四种审核状态都有中文标签、推优说明对低等级查看者脱敏（密级抬高到涉密时不返回正文且不入向量库）、**年龄从不被判成结论且缺推优记录不阻断任何环节**、请求体不能伪造结论内容（`extra="forbid"`）、创建契约只接受人填字段（`evidence` / `review_status` / 审核人这类字段根本不接受客户端提交）。
- `tests/unit/test_data_sensitivity.py`：扩展（选优结论与推优记录的密级来自 `config/business_rules.yaml` 的 `member_selection_level`（默认 `sensitive`）、与 `selection_level()` 同一来源、敏感不出网；原 22 项继续通过）。
- `tests/integration/test_member_selection_workflow.py`：4 项通过（一次性 PostgreSQL 库 + `alembic upgrade head`）。钉住「登记出来还是草稿、自己审自己的版本 403、第二位组织人员审核通过才 `effective`、留痕动作 `create` / `submit` / `review` 且版本只增不改、**生效不改阶段**、跨租户不可见、普通党员 403」；「送审后修订回到草稿并必须重新送审、过期 `expected_revision` 409、未送审不能审 409」；「目标阶段不可后退 422、未来研究日期 422、空名单 / 空依据 422、跨组织范围 404」；「推优登记 → 按人查询 `has_record` → 作废后重复作废 409、缺推优记录只提示不阻断」。
- `tests/integration/test_member_full_workflow.py`：7 项通过（新增 1 项回归：同一投票人在**另一个年度批次**的同一轮投票不算重复提交——旧唯一约束漏了 `batch_no` 时这里会 500）。
- `node frontend/scripts/verify-modules123.mjs`：47 组接口契约与界面检查通过。新增 7 项：「拟推荐名单只由人勾选，阶段不到的人勾不上」、「团组织推优只登记事实并提示组织核对年龄」、「选定名单与依据后仍是草稿（不自动生成结论）」、「修订只追加版本并回到草稿」、「送审后登记人看不到审核入口」、**「选优结论双人审核留痕与阶段不自动流转」**（第二位审核在**第二个浏览器上下文**里用另一位账号真实点出来，并断言生效后档案阶段没被改动、留痕 4 版含 `create` / `revise` / `submit` / `review`）、「作废推优记录保留留痕且不影响生效结论」。
- `python scripts/validate_modules123_ui_contracts.py tmp/modules123-ui/contract-requests.json`：47 个请求体经后端输入模型校验通过（新增 6 个契约：`/member-full/selections`（登记 / 修订 / 送审 / 审核）与 `/member-full/league-recommendations`（登记 / 作废））。
- `node frontend/scripts/check-roles-ui.mjs`：7 个角色通过。新增「选优结论面板必须挂载并写开三条口径、不许出现自动生成名单的入口、不许出现年龄判定字段、接口不得报错」检查（`system_admin` 没有组织范围、批次下拉为空，这一条在它身上只记一条信息、不当作回归）。
- 开发库端到端手工核对（`TEST_TENANT` / 支部秘书 + 组织员两个账号，脚本可重复执行）：登记推优 → `active: true` / `age_notice` 含「系统不判断年龄」/ `data_level: sensitive`；登记结论（入党积极分子 → 拟推荐列为发展对象）→ `draft` / `effective: false` / `can_review: false` / `voter_count: 1` / 依据快照里既无 `voter_id` 也无登记人账号 / 提示指向细则第十三条备案；送审 → `pending`；**登记人自己审核 → 403**；过期版本号修订 → 409；换组织员账号 → `can_review: true` → 审核通过 → `effective: true`、留痕 `['create', 'submit', 'review']`；回读档案阶段不变；再修订 → 回到 `draft`、`submitted_by: null`；作废推优 → `active: false`、重复作废 409、已生效结论不受影响；未来研究日期 422、同阶段登记 422。

未覆盖：**不自动生成结论、不排序、不定等次**（只存人填的名单与依据）；**不判断年龄、不新增出生年月字段**；不新增权限码（沿用 `member.query` / `member.scoring` / `member.stage_transition`）；生效结论**不自动改阶段、不自动向上级报送**；不产生个体通知与待办；不与 `T-MEM-09` 档案检查联动；结论的「同批次同轮次」不加唯一约束（重复由双人审核与留痕约束）；推优记录不自动写进结论；`evidence` 是无记名汇总快照，**不含投票明细**（要核对到票只能另开投票明细，且明细本身按最小权限）。

## 名册按支部筛选与名册统计回归（T-MEM-02）

2026-10-17，补齐 `T-MEM-02` 验收句里"按支部筛选"这一条，并把**早已实现却没有页面引用**的名册统计（`GET /member-full/stats`）挂到「党员发展 → 人员档案」的筛选行下方。名册列表、导出、统计三处共用同一口径（租户 + 未删除 + 有效 + 默认不含已转出 + 权限范围内的组织）；传范围外 / 已删除 / 不存在 / 没有组织的 id 一律 403，不静默忽略（"假筛选比没有筛选更糟"）。

- `tests/integration/test_selected_business_features.py`：新增 9 项通过（一次性 PostgreSQL 库 + `alembic upgrade head`）。`test_roster_filters_by_one_org_within_scope` 钉住"学校管理员按某一个支部筛选时，名册只回该支部人员、名册统计与名册列表总数一致、导出与列表同一口径"；`test_roster_org_filter_rejects_out_of_scope_org`（跨租户 / 已删除 / 不存在 / 没有组织的 id × 名册与统计两条链路）钉住 403 而不是"忽略参数回退成全量"。
- `tests/unit/test_member_roster_filters.py`：5 项通过（SQLite 实际执行）。新增 1 项钉住"范围内的组织能收窄、范围外的组织 403"；并修正既有 4 项——直接调用端点函数不会走 FastAPI 的默认值解析，`include_transferred` 与新增的 `org_unit_id` 会是真值 `Query` 对象，现在显式传入解析后的默认值（否则测的是一条真实请求不会走的路径）。
- `node frontend/scripts/verify-modules123.mjs`：47 组检查通过。既有"建立批次与完整名册筛选"扩为：支部下拉有「全部支部（权限范围内）」+ 1 个本支部、选中后名册列表与名册统计请求**都带同一个 `org_unit_id`**（只用 mock 收到的参数判定，避免"看起来筛了"）、复位为空后仍能查。
- `node frontend/scripts/check-roles-ui.mjs`：7 个角色通过。新增 `checkRosterOrgFilter`：支部下拉必须挂载、"当前筛选共 N 人"统计文案必须可见、选了支部后名册与统计请求都带同一 `org_unit_id`、接口不得报错、页面不得出现错误态（`system_admin` 没有组织范围，下拉只有"全部支部"一项，按此跳过联动断言）。
- 开发库端到端手工核对（`C:\pt\e2e_roster_org.py`，`test-dept` 账号）：权限范围内 2 个组织；全范围名册 5 人 = 名册统计 5 人；按支部筛选后列表只含该支部人员、统计总数与列表一致；按支部导出返回真 xlsx（6424 字节）；范围外组织 id 在名册 / 统计 / 导出上都是 403。

未覆盖：不新增"公示"实体（公示期提醒待学校确认工作日口径）；名册筛选只能在既有权限范围内收窄（不是越权通道）；名册统计只按当前阶段与在册状态计数，不出等次、不排名。

## 本地扩展证据与主分支区分

文档分支所引用的 `admin-workspace-isolated.xml`（179项、0失败/错误/跳过）与 `admin-workspace-backend.xml`（205项、30项准备错误）属于未合入的本地管理员工作台扩展，不能套用到本次主分支合并结果；各范围有重复用例，不累加为通过总数。原先开户43项及相关91项记录保留其原始范围。

本次合并只改文档，没有重跑上述应用测试。主分支其他安全运维、独立环境及生产验收证据见[模块6交付](MODULE6_DELIVERY_2026-10-11.md)，该报告中的日期/提交/环境限制继续适用。
