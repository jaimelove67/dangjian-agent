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
本机 Chromium 可执行文件。脚本会自行等待登录/接口限流窗口，无需手工调整频率。

该检查已接入 CI（`.github/workflows/role-ui.yml`）：用隔离的 PostgreSQL/Redis 服务容器
跑迁移与合成账号初始化，起后端与前端后执行同一脚本，报告作为构建产物上传。

Linux/macOS 使用 `DASHSCOPE_API_KEY= QWEN_API_KEY= python -m pytest tests/unit tests/security`。这些设置不改写 `.env`；真实模型评测另用已授权的环境。

单元与安全回归主要使用合成输入及替代模型。完整回归需要可用的 PostgreSQL；数据库迁移测试检查已迁移的目标库，`test_repaired_storage.py` 还需要连接管理库并创建、清理随机独立测试库的权限。请配置专用测试数据库连接。

自动化回归应在测试进程中将 `DASHSCOPE_API_KEY` 和兼容变量 `QWEN_API_KEY` 覆盖为空，保持本地 `.env` 不变。检查失败数和跳过数；缺少依赖或数据库导致的跳过不能计为验收通过。

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

## 本地扩展证据与主分支区分

文档分支所引用的 `admin-workspace-isolated.xml`（179项、0失败/错误/跳过）与 `admin-workspace-backend.xml`（205项、30项准备错误）属于未合入的本地管理员工作台扩展，不能套用到本次主分支合并结果；各范围有重复用例，不累加为通过总数。原先开户43项及相关91项记录保留其原始范围。

本次合并只改文档，没有重跑上述应用测试。主分支其他安全运维、独立环境及生产验收证据见[模块6交付](MODULE6_DELIVERY_2026-10-11.md)，该报告中的日期/提交/环境限制继续适用。
