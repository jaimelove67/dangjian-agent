# 后端基线与本地联调

验证日期：2026-10-24。来源固定为 [dangjian-agent 的 b190fcb](https://github.com/jaimelove67/dangjian-agent/commit/b190fcb9464c2fb2a9116b469b5a0a4d2a4cd274)，不将其描述为此后的最新 master。

本文件保留此前基线的检查结果；随后一轮的修复、完整回归、真实 React 角色页面和业务闭环结果见 [前后端联调报告](integration-check-2026-10-24.md)，以该报告判断当前剩余接入缺口。

当前 React 界面继续保留。`backend/` 是固定提交的本地文本源码副本，来源、每个上游文件的 Git blob SHA 和省略文件清单记录在 `backend/UPSTREAM.json`；未包含上游 Git 历史、设计截图、Word 手册及部分历史说明。没有推送、发布或操作正式账户。

## 已修复的问题

| 问题 | 修复与验证方式 |
| --- | --- |
| CI 启动报 `No module named 'openpyxl'` | 生产锁已包含该包，开发锁遗漏；重新生成带哈希的开发锁，干净虚拟环境同步后可导入并启动 FastAPI。新增直接依赖 pin 检查，在两个 CI 工作流安装前执行。 |
| Python 格式、导入、lint 和 4 处类型错误 | 按原有 Black、isort、flake8、mypy 规则修复，没有降低检查规则或覆盖率门槛。 |
| 原 Vue 构建被 `leaderOrg.value` 的空值错误阻断 | 操作前保存并校验组织引用，异步操作后使用同一引用；保留原维护流程。 |
| CI 依赖扫描失败 | 锁定已有依赖的修复版本：certifi 2026.10.19、Pillow 13.0.0、pypdf 6.21.2、setuptools 84.1.0，以及仅用于开发环境的 filelock 4.2.1、virtualenv 21.14.10。2026-10-24 对实际安装的 213 个开发环境包运行 `pip-audit --strict`，退出码为 0，未发现已知漏洞；该结果不保证此后新增公告仍为零。 |
| 原 Vue 治理页面的回归无法定位结论选择框 | 为原选择框提供明确的“人工结论”无障碍标签；回归独立验证默认不预选、提交意见、自审和来源失效保护，保留原审核条件。 |
| 原 Vue 刷新时把限流、断网误判为登录失效 | 仅在确认认证失效时清除凭证；临时故障保留会话并阻止业务页面挂载，显示错误及重试入口。分别验证 429、503、断网恢复和 401 清除会话。 |
| 旧快照测试误把 OCR 文本视为已加载列 | 同时验证延迟二进制、OCR 文本不进入快照，并确认序列化不发出额外 SQL；显式登记外键目标模型，独立运行也可通过。 |
| 平台审计总数非零但列表为空 | 目标租户经过真实平台角色及祖先链校验后，在读取和导出期间只采用已验证目标租户条件，避免再叠加平台自身租户；原权限、外校拒绝和上下文恢复保留。 |
| React 问答输入与后端 500 字限制不一致 | 输入提示、发送前校验及 API 适配层统一到 500 个 Unicode 字符；移除按 UTF-16 单位计数的原生输入限制，避免提前截断合法的混合字符问题。空白、超长输入在请求前拒绝，不截断请求，不回退演示答案。 |
| React 学校工作台将学校、院系也计入党支部 | 按实际 `org_type` 只统计支部；缺少院系父子关系时按已授权支部显示进度，不凭名称猜测院系。 |

## 实际运行与数据边界

本机专用 PostgreSQL 容器为 `dangjian-baseline-postgres-20261023`，仅监听 `127.0.0.1:55434`；Redis 为 `dangjian-baseline-redis-20261023`，仅监听 `127.0.0.1:56381`。浏览器联调使用 `dangjian_baseline` 数据库，后端回归使用独立的 `dangjian_ci`；原生集成测试还会创建并清理自身随机命名的测试库。迁移已执行到 `027_org_leader_terms`。

后端监听 `127.0.0.1:18001`，React 真实接口预览为 `http://127.0.0.1:4177/`，原 Vue 的角色回归实例为 `http://127.0.0.1:5666/`。测试账号、名册、材料和知识条目均为合成数据；未导入正式人员资料，未配置或调用真实模型。公开存活检查成功不表示模型或生产就绪验收通过。

`scripts/verify-live-backend.mjs` 通过当前 React 的实际 API 适配函数连接 FastAPI，不使用业务响应 mock。它要求本机 URL、`DANGJIAN_SMOKE_ALLOW_WRITES=isolated` 和环境变量中的合成账号密码，验证：

1. 真实登录、权限与本人档案读取。
2. 授权组织员登记名册并明确关联本人账号。
3. 本人上传原件、同一 submission_key 重试去重、列表持久化与下载内容一致。
4. 授权组织员接收及下载原件。
5. 另一名个人账号无法读取该原件、名册或材料接收接口。
6. 后端拒绝 501 字问答请求；该检查不调用模型。
7. 退出后原登录会话失效。
8. 平台管理员在所属学校审计中查到明确关联记录。

脚本只把方法、路径、HTTP 状态和检查名称写入报告，不保存密码、令牌、原件正文或授权头。执行结果位于 `tmp/qa/backend-integration.json`；汇总证据见 `docs/backend-verification.json`。

真实浏览器还验证了学校工作台的支部统计与工作进度、成员本人档案及材料、含 emoji 的合法 500 字输入完整保留，以及 501 字问题通过键盘发送时在请求前被拦截。390 像素宽度无整页横向溢出。截图和五项结果位于 `docs/screenshots/backend-integration/`；这些检查没有提交有效问答，也没有调用模型。

## 验证结果

各项检查使用的真实后端、合成响应和运行边界分别记录，不以其中一类替代另一类。最终机器可读汇总为 `docs/backend-verification.json`。

| 检查 | 结果 | 证据与边界 |
| --- | --- | --- |
| Python 静态检查 | 依赖 pin、Black、isort、flake8、mypy 均通过 | `backend/tmp/local-quality/static-checks.json`；未降低规则 |
| Python 完整回归 | 1131 项通过，0 失败 / 错误 / 跳过；覆盖率 85.11% | `backend/tmp/local-quality/backend-final.log`、`pytest.xml`、`coverage.json`；依赖最终升级后执行，保留 80% 门槛 |
| 仅生产依赖启动 | 121 个包兼容，FastAPI 存活检查通过 | `backend/tmp/local-quality/runtime-startup.json`；使用独立 `.venv-runtime`，未安装开发依赖 |
| Python 依赖安全 | 213 个已安装包，0 条已知漏洞 | `backend/tmp/local-quality/audit-final.json`，2026-10-24 严格扫描 |
| React 自动化 | 67 项通过 | 包含 500 字 Unicode、超长拒绝及组织分类 |
| React 构建及 Sites | 构建成功，4 项检查通过 | 产出 `dist/client/index.html`、`dist/server/index.js`、`dist/.openai/hosting.json`；没有发布 |
| 原 Vue 构建 | 类型检查与生产构建通过 | 使用原工程构建入口 |
| 原 Vue 治理界面 | 16 项检查、5 个写请求契约通过 | `backend/tmp/local-quality/frontend/report.json`；API 合成响应 |
| 原 Vue 会话恢复 | 4 项通过 | `backend/tmp/local-quality/session-recovery.log`；429、503、断网保留凭证，401 清除凭证 |
| 原 Vue 真实七角色 | 77 个角色与路由组合通过 | `backend/tmp/local-quality/role-ui-final.log`；43 个允许、34 个拒绝；数据相关跳过项见下文 |
| React 真实接口闭环 | 8 项通过，35 个请求 | `tmp/qa/backend-integration.json`；隔离 FastAPI / PostgreSQL / Redis |
| React 真实浏览器 | 5 项通过 | `docs/screenshots/backend-integration/browser-results.json`；真实账号，无模型调用 |

七角色检查完整执行菜单与路由权限断言。由于没有相应数据，平台管理员及申请人的知识原件下载入口、五个管理 / 组织角色的年度选优结论面板未参与本次检查。院系、支部及组织员没有组织与账号、运行审计、学校配置和集中问答记录权限，检查确认相应入口隐藏。系统页实际返回的 503 仅在精确就绪接口、有效 `not_ready` 结构及界面原因均通过验证后被接受；本机阻塞项为 `models=configuration_required`，没有把该环境认定为生产就绪。

## 仍需完成的接入与验收

- 本次是本地修复与分项验证，尚未推送上游或重新触发 GitHub CI，不能将旧的失败记录描述为已变绿。
- `module6_container_check.py` 要求 Linux、非 root 和可用 Docker。本机 Windows 未执行该完整验收；镜像、TLS、非 root 运行权限、实际加密备份恢复、迁移回退和恢复后数据库审计权限仍须在符合条件的隔离 Linux / CI 环境验证。
- 此前学校管理员的组织选项接口拒绝本校身份管理角色，已在后续本地联调修复，并验证本校编辑、跨校拒绝、开户限制、会话失效和管理员/档案关联保护；未向正式环境发布。
- 一次自主改密、后续申请审批、会话列表和管理员强制下线仍缺少完整后端契约。真实模式不得用浏览器演示状态模拟成功，见 `docs/password-security.md`。
- 组织生活、学习、考核和知识管理虽有后端模块及回归测试，当前 React 的每个表单仍须真实联调；视频课程、考试、积分和活动自助报名需要独立后端能力。
- 制度问答的模型连通、真实制度引用质量、业务评测样本扩充及正式知识供给尚未验收。此次合成知识条目没有向量化，不能作为权威制度基线。

## 可重复检查

前端目录执行 `npm test`、`npm run build`、`npm run test:sites`。后端目录在其隔离虚拟环境执行 `python scripts/check_dependency_locks.py`、`python -m pytest tests --cov=app --cov-fail-under=80`，以及项目原有质量命令。完整原仓库质量入口为 `python scripts/module6_acceptance.py quality --report-dir tmp/module6-quality`，现已包括会话恢复回归。

原 Vue 的治理界面检查使用浏览器拦截响应，真实七角色回归使用隔离后端；这两类证据分别记录，均不代替模型质量或正式业务验收。
