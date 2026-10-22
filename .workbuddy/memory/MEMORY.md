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
- `admin` 是 platform + system_admin，**有权限管所有下级租户**（`/governance` 切「管理租户」即可）。`/accounts` 页无租户切换、组织列表按登录者自身租户取，所以 admin 在那页恒为空——是入口问题，不是权限问题。
- 租户**没有 DELETE 接口**，只能 `is_active=false`（字段 `is_deleted` 存在但未开放）；`update_tenant` 不能改 `parent_id`。
- `audit_logs` 对 422 只记 route/method/status/duration，不记错误正文。

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

- 镜像源不进代码，全部 ARG/环境变量注入：`DOCKERHUB_MIRROR`（默认 docker.io）、`GHCR_MIRROR`（默认 ghcr.io）、`BASE_IMAGE`、`APT_MIRROR`、`PIP_INDEX_URL`、`NODE_IMAGE`、`NGINX_IMAGE`、`NPM_REGISTRY`。**ARG 坑：stage 内 RUN 用某 ARG，必须在 FROM 之后再声明一次。**
- 国内拉镜像可靠源：`swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io`（华为云）。DaoCloud/1ms/腾讯内网加速器都不可靠，坏源返回 HTML 会让整次拉取失败且不回退。
- `scripts/*.sh` 用 LF（写完 `sed -i 's/\r$//'`）；文档统一 `bash scripts/xxx.sh`。
- 本仓库存在并行工作流，**产出后立即提交**；用平铺分支名；判断提交在不在历史只信 `git rev-list HEAD | grep <sha>`（`branch --contains` 会给错答案）。
- 本环境执行 `.py` 脚本文件会被静默拦截（exit 1、无输出），**必须 `python -c '<代码>'` 内联**。
- md→docx：`render_markdown` + `add_cover`，只能内联跑；中文字体需同时设 `run.font.name` 和 `w:eastAsia`；长内联 Python 塞 bash 会 `unexpected EOF`，写 `tmp/xxx.sh` + heredoc 才稳。中文输出路径先落 ASCII 再 `mv`。

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
- 造数硬约束：① 学习只认 `effective` 资料（seed 文档默认 expired，先 PATCH 状态）；② 依据要计划级+条目级两级 `source_doc_ids`；③ 写操作带 `expected_revision`，每步重读；④ 纪要三栏目走 `generate-minutes`；⑤ 考核 `formula=sum` 只能配 `source=manual` + `measure=sum`；⑥ 任务须逐条审核；⑦ 新建用户口令 ≥12 位；⑧ 审核不能自审，需第二个管理员。
