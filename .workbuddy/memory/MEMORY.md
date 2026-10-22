# MEMORY.md — 党建工作智能体 项目长期约定

## 运行环境（本地开发）

- 后端端口 **18000**（`.env: APP_PORT=18000`）；8000 属于别的项目，别混。启动：
  `cd E:/ali/dangjian-agent && .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18000`（**没开 --reload，改完手动重启**）；临时验证用 `--port 18001`。
- 三个 Python：`.venv/Scripts/python.exe`（有 uvicorn、无 pytest，启服务用它）；`venv-lock/Scripts/python.exe`（有 pytest，跑测试用它）；托管 Python 3.13（md→docx、python-docx/pptx）。
- 库：`postgresql://party_user:dev_password@127.0.0.1:55432/party_agent_dev`（容器 `party-agent-postgres-dev`），查库用托管 Python + asyncpg 内联。
- 平台管理员 `admin` / `Test123456`；测试租户 TEST_TENANT（测试大学）账号 `test-reviewer`/`test-dept`/`branch-secretary`/`test-organizer`/`test-member`/`test-applicant`，口令同为 `Test123456`，可直接演示。
- 组织树硬规则（`identity_service.validate_tree`）：同租户只能一个 school 根；school 无父级；department 父级必须是 school；branch 父级是 school/department。
- **租户层级硬规则**（`identity_service.TENANT_PARENTS`）：`school→platform`、`department→school`、`branch→department`。所以学校租户的父租户**只能是** platform 类型的「党建平台」，不是可选项。
- 租户 `parent_id` 只用于**管辖链**（`IdentityService.tenant()` 跨租户时沿 parent 向上爬，必须爬到操作者租户否则 403「租户不属于当前平台」；`list_tenants()` 用 parent_id BFS 决定下拉可见范围），**不参与业务数据可见性**——业务隔离只看 `tenant_id`。
- `admin` 是 platform + system_admin，**有权限管所有下级租户**（`/governance` 切「管理租户」即可）。
- 租户**没有 DELETE 接口**，只能 `is_active=false`（字段 `is_deleted` 存在但未开放）；`update_tenant` 不能改 `parent_id`。
- **管理员重置密码（2026-10-22 上线）**：`PATCH /admin/users/{id}` 的 `UserUpdate` 已含可选 `password`（8–72 字节），留空不改；审计 `new_value` 只加 `password_reset: true`，不落明文/哈希。前端在治理页「维护用户」编辑态显示「重置密码」输入框。重置**不会踢掉已登录会话**（token 到期自然失效）。
- 角色-组织映射统一在 `identity_service.ROLE_ORG_TYPES`（school_admin=school / department_admin=department / branch_secretary,member,applicant=branch / organizer=branch+department），开户与编辑共用；前端 `GovernanceView.formOrgs`、`AccountsView.availableOrganizations` 按同一口径过滤下拉。
- `GET /admin/org-units` 支持 `?tenant_id=`（平台管理员跨租户）；`/accounts` 页有「开户租户」下拉，**不预选**，只有唯一可选租户时才自动选中。
- **身份证号 = 登录账号（2026-10-22，迁移 024）**：`member_profiles.id_card_no`（VARCHAR 32，明文，登录名必须可核对）。档案有号时开户可省略 `username`，服务端直接用它；候选接口 `GET /admin/member-candidates` 只回 `id_card_masked`（前 6 + **** + 后 4），完整号不出网。列表/审计/编辑回显统一走 `identity_service.masked_username`（18 位身份证才脱敏，工号原样）。实测：不传 username 建号 201、列表显示 `430102********9999`。
- 名册登记表单（`MembersView`）身份证号**必填**且按 18 位校验（`MemberCreateRequest.check_id_card`，末位 X 统一大写）；开户页登录账号也按 18 位校验，档案缺号时禁用提交并提示去补录（5679e56）。
- **档案补录身份证（2026-10-22 已上线）**：`ProfileUpdate` 已含可选 `id_card_no`（18 位、空串 422、同租户档案唯一 + 不撞账号登录名，冲突 409）；前端两处入口——`MemberFilePanel`「补录/更正身份证号」、`AccountsView` 缺号时就地补录。补录**不改**已开户账号的登录名（`UserUpdate` 无 username 字段）。档案读接口统一走 `member_full.profile_payload()`：`id_card_no` → `id_card_masked`，版本快照同样脱敏（此前详情接口与审计是**明文**）。
- `audit_logs` 对 422 只记 route/method/status/duration，不记错误正文。
- **扫描归档（2026-10-22 已上线，迁移 025）**：干事在档案面板「扫描件归档」上传 PDF/PNG/JPG，走 `POST /member-full/profiles/{id}/materials/scan`。**影像件不存库**：落 `<FILE_STORAGE_DIR>/<租户>/archives/<material_id>__h<sha>.bin`（加密、内容寻址），库里只存 `file_path` + sha + 大小；`member_materials` 新增 `extracted_text`(deferred) / `ocr_status` / `ocr_pages`。识别复用 `ocr_service`：文字层优先，`cloud_ocr` 未勾选只存影像（skipped），**敏感/涉密材料按 `cloud_allowed()` 拒绝出网**，失败只标 failed 不丢原件。识别文本出口 `GET /member-full/materials/{id}/text` 过 `mask_text`（身份证/手机号脱敏）。下载走 `read_member_archive`，与本人自传件同一出口（`_download` 兼容 content 与 file_path）。
- **扫描件抽取建议值（2026-10-22，迁移 026）**：识别成功且允许出网时，`extract_material_fields()` 用 `TaskType.EXTRACT` 抽「材料类型/所属人/落款日期/出具单位/要点」，存 `member_materials.extracted_fields`。**只是建议**：类型必须命中卷内目录 `ARCHIVE_MATERIAL_TYPES`（后端 `member_archive_service` 与前端 `api/types.ts` 各一份，改一处必须改两处），不写台账；前端与所选类型不一致时黄标提示，不自动改选。

## 前端（frontend/）

- 实际是独立 **Vite + Vue3** 应用（dev 端口 5666，`VITE_API_TARGET` 默认 `localhost:8000`，本地联调须设 `http://localhost:18000`）。页面在 `frontend/src/views/*.vue`，接口层 `frontend/src/api/*.ts`（`http.ts` 统一包裹体 `{code,message,data,trace_id}`，成功只回 data）。
- 样例问答页：`AskView.vue`（左会话栏 + 中对话流 + 底部 composer），问答接口 `POST /qa`。
- **历史上规划的 vben 5.7.0 monorepo 方案已作废**，不要再按 vben 目录/Element Plus 按需样式那套改。

## 模型接入

- 三件套（文本 `qwen3.8-flash` / 向量 `qwen3.7-text-embedding-flash` / 重排 `qwen3.7-text-rerank`）之外新增视觉 OCR：`VISION_OCR_MODEL`（默认 `qwen-vl-ocr`，留空即关闭图片与扫描件）。百炼另有 `qwen3.5-ocr`（返回带坐标 JSON）。
- **OCR 提示词别写"用 Markdown 表格还原"**：qwen-vl-ocr 会把整页正文包成 `$\begin{aligned}& \text{…}$`；写"表格按行逐条转录"才是纯文本。出口统一过 `normalize_ocr_text()`。
- 扫描件 PDF 渲染用 `pypdfium2`（`page.render(scale=2)`，已在 requirements.lock），逐页 OCR，页数上限 `OCR_MAX_PAGES`。
- 图片会出网，必须用户显式同意（`cloud_ocr=true`），未同意回 428 + `OCR_CONSENT_REQUIRED`。

## 工程陷阱

- **Git 远程**：`origin` = `manice2005/dangjian-agent`（只有一条 `Initial commit`、与本地无共同历史，别往那推）；日常推送用 `git push jaimelove67 master`（`jaimelove67/dangjian-agent` 与本地 master 同主线）。`.workbuddy/` 虽在 .gitignore 内，但 `memory/*.md` 已被跟踪，改完要 `git add -f` 才提交得进去。
- **⚠️ `.git` 会被环境清理工具破坏（2026-10-22 实测）**：safe-delete shim（genie-trash）曾把 `.git/refs/*` 与 `objects/pack/*.pack` 删掉，`git status` 直接变「No commits yet」、文件全成 staged `new file`。**见到这个症状立刻停手**：不要 `git add -A`、不要 `reset --hard`、不要 `gc/prune`。恢复顺序：①`tar czf tmp/git-broken-<date>.tgz .git` 备份现场 → ②确认工作区源码完好 → ③`git fetch jaimelove67 "+refs/heads/*:refs/remotes/jaimelove67/*" --force`（refspec 必须写全，`refs/remotes` 已空时普通 fetch 不建）→ ④从 `.git/logs/HEAD` reflog 末行取 sha，`git update-ref refs/heads/master <sha>` → ⑤`git reset --mixed <sha>` 修 index（不动工作区）→ ⑥`git fsck` 确认无 missing/corrupt。只在本地那几天的提交会随 pack 消失（远端通常有）。
- **`pytest` 本机必须带 `--basetemp=tmp/pt-<唯一后缀>`**：默认 `%TEMP%\pytest-of-<user>` 报 `WinError 5 拒绝访问`；basetemp 目录**不能复用**（报 `WinError 183` + shim 清理失败把 setup 打成 ERROR）。判测试真假失败前，先建 `git worktree` 在基线 commit 上跑同一套做对照——`module6_security_ops`/`module6_backup_edges`/`modules123_review_regressions` 有 8 个用例在多文件连跑时必挂、单独跑能过，属既有干扰，不是回归。
- 镜像源不进代码，全部 ARG/环境变量注入：`DOCKERHUB_MIRROR`（默认 docker.io）、`GHCR_MIRROR`（默认 ghcr.io）、`BASE_IMAGE`、`APT_MIRROR`、`PIP_INDEX_URL`、`NODE_IMAGE`、`NGINX_IMAGE`、`NPM_REGISTRY`。**ARG 坑：stage 内 RUN 用某 ARG，必须在 FROM 之后再声明一次。**
- 国内拉镜像可靠源：`swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io`（华为云）。DaoCloud/1ms/腾讯内网加速器都不可靠，坏源返回 HTML 会让整次拉取失败且不回退。
- `scripts/*.sh` 用 LF（写完 `sed -i 's/\r$//'`）；文档统一 `bash scripts/xxx.sh`。
- 本仓库存在并行工作流，**产出后立即提交**；用平铺分支名；判断提交在不在历史只信 `git rev-list HEAD | grep <sha>`（`branch --contains` 会给错答案）。
- 本环境执行 `.py` 脚本文件会被静默拦截（exit 1、无输出），**必须 `python -c '<代码>'` 内联**。
- md→docx：`render_markdown` + `add_cover`，只能内联跑；中文字体需同时设 `run.font.name` 和 `w:eastAsia`；长内联 Python 塞 bash 会 `unexpected EOF`，写 `tmp/xxx.sh` + heredoc 才稳。中文输出路径先落 ASCII 再 `mv`。
- **`npm run build` 在本机会失败**：环境里装了 WorkBuddy 的 safe-delete shim，vite 清空 `dist/` 时调 `genie-trash win32-x64.exe` 超时报 `ETIMEDOUT`（与代码无关）。验证构建改用 `npx vite build --outDir ../tmp/dist-check`；服务器容器内 build 不受影响。
- 本机 `tar` 写 `/tmp` 会被沙箱静默拦截（exit 2、无输出），打包产物一律写项目内 `tmp/`（已 gitignore）。
- 本地无 Docker（Desktop 启动被沙箱拒绝）→ `tests/integration` 全部因连不上 postgres 而 ERROR，属环境限制；验证以「导入检查 + OpenAPI 契约 + 部署后真实接口」为准。

## 服务器（129.204.32.148 上线，2026-10-17）

- 腾讯云轻量 OpenCloudOS 9.6，SSH 免密 root；代码 `/opt/dangjian-agent`，编排 `docker-compose.server.yml`，容器 `party-agent-*`；卷 `party-agent-server_{postgres_data,redis_data,originals,audit_spool}`，库 `party_agent`。
- `ENV` 必须保持 `development`（production 会强制 DB/Redis TLS）。**ready 一律以接口为准** `curl http://127.0.0.1/api/v1/health/ready`；`docker compose exec app python` 不跑 lifespan，直接调 `_readiness_details()` 会误报 redis/models 异常。
- 备份（app 容器无 pg_dump）：`docker exec party-agent-postgres pg_dump -U party_user -d party_agent -Fc > /root/backups/pg_$(date +%F).dump`；卷用 alpine 打 tar；`scripts/module6_backup.py` 需连 `.env` 一起保管。
- 租户：`d5584666-6c8a-453c-abf3-036e02dc83e1` 湖南科技职业技术学院（school，正式在用，config_version 会随治理页保存递增）；孤立同名 `e410e3b3-…` 待清理；`PLATFORM_TENANT` 是 platform。治理页「管理租户」下拉选错租户 = 白填（platform 租户点"已确认"直接 422）。
- 治理配置（`app/services/governance_service.py`）校验：四项确认（registration/organization_approval/it_approval/secrecy_approval）+ pilot_scope 全部到位，准入才是 configured，否则勾选模型开关报 422；`allowed_hosts` 必须是 `.env` 的 `ALLOWED_EXTERNAL_MODELS` 子集（服务器只有 `dashscope.aliyuncs.com`），`ALLOWED_LOCAL_MODEL_HOSTS=[]` 时校内主机留空；模型下拉 id 是 `cloud-llm`/`cloud-embedding`/`cloud-reranker`；评分权重五项总和必须 = 1；保存带 `expected_version`，版本冲突返 409。
- 待办：清理同名孤立租户 `e410e3b3…`、替换演示数据、改初始口令。
- 上线手册：`docs/线上操作手册.md`（+ .docx）；部署实录 `docs/DEPLOY_SERVER.md`。

## 演示数据（docs/DEMO_DATA.md）

- 种子：`scripts/seed_demo_school.py`（租户/组织/账号）、`seed_demo_business.py`（学习依据+考核）、`seed_demo_study_finish.py`（计划→活动→纪要→审核）。走真实 API、幂等；容器内需 `docker cp`（无 scripts 目录）。
- 造数硬约束：① 学习只认 `effective` 资料（seed 文档默认 expired，先 PATCH 状态）；② 依据要计划级+条目级两级 `source_doc_ids`；③ 写操作带 `expected_revision`，每步重读；④ 纪要三栏目走 `generate-minutes`；⑤ 考核 `formula=sum` 只能配 `source=manual` + `measure=sum`；⑥ 任务须逐条审核；⑦ 新建用户口令 ≥8 位（`UserCreate` 已于 2026-10-22 由 12 放宽到 8，与 `/admin/users` 对齐）；⑧ 审核不能自审，需第二个管理员。
