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
时脚本只会对「逐路由」那一段重试，而工作区检查（组织生活频次、民主评议、组织关系接转
等）在 429 下拿到的是没渲染完的页面，会报成"某项没挂载"的**假失败**，且每次失败的角色
不固定。用 `set RATE_LIMIT_PER_MINUTE=5000` 启动后端再跑，7 个角色可稳定通过：

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

未覆盖：不做上级党组织审批 / 备案与报送导出（`T-MEM-11`）；**不采集接收单位联系人与电话**（第三人信息，`T-MEM-12` 范畴）；不自动认定接收、不自动判定转出失败、不自动改发展阶段；不产生个体通知与待办；不写党员档案正文（只落既有档案检查的缺项提示，且缺项只提示不阻断登记）；对方组织只记名称文本，不做跨租户 / 跨学校机构字典比对；介绍信有效期是**可配置默认值**（`member_transfer.letter_valid_days`，注释写明按上级党组织规定填写，不编造国家规定天数）；**年度考核 `source: members` 等既有统计未同步排除已转出人员，阶段提醒（`member_scheduler`）也仍会按原档案产生**——本次只统一了名册列表 / 名册统计 / 民主评议三处口径。

## 本地扩展证据与主分支区分

文档分支所引用的 `admin-workspace-isolated.xml`（179项、0失败/错误/跳过）与 `admin-workspace-backend.xml`（205项、30项准备错误）属于未合入的本地管理员工作台扩展，不能套用到本次主分支合并结果；各范围有重复用例，不累加为通过总数。原先开户43项及相关91项记录保留其原始范围。

本次合并只改文档，没有重跑上述应用测试。主分支其他安全运维、独立环境及生产验收证据见[模块6交付](MODULE6_DELIVERY_2026-10-11.md)，该报告中的日期/提交/环境限制继续适用。
