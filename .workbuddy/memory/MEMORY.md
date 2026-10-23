# MEMORY.md — 党建工作智能体 项目长期约定

## 交付形态
- 目标：**学校私有化部署**（校内机房、数据不出校）。129.204.32.148 仅开发/演示。
- 私有化缺口：① 四个模型只有 `dashscope`，本地模型需加 OpenAI 兼容 provider + `init_models` 按 `MODEL_BACKEND` 切换；② 权重与镜像要离线导入；③ `ENV=production` 强制 DB/Redis TLS，校内单机只能留 development——但此时 `gateway` 对本地模型的 `ALLOWED_LOCAL_MODEL_HOSTS` 校验**不生效**（`or policy` 分支仍校验），交付须讲清。
- GPU：四模型全本地需单 48G（L20/A6000）或双 24G；单 24G 放不下视觉 OCR。
- 换 embedding 模型 = 历史向量全部作废（维度不一致且不报错），必须全量重入库。

## 运行环境
- 后端 18000（8000 属别的项目）。启动：`.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18000`（无 --reload，改完手动重启）。
- 三个 Python：`.venv/Scripts/python.exe`（uvicorn，启服务）；`venv-lock/Scripts/python.exe`（pytest）；托管 3.13（docx/pptx）。
- **本机 Docker 起不来**（Desktop 进程被环境杀掉）。本地库用项目内便携 PG：`tmp/pgvenv/.../pginstall/bin/postgres.exe -D "$(cygpath -w $PWD/tmp/pgdata)" -p 55432 -h 127.0.0.1`，**必须 run_in_background 常驻**（`pg_ctl start` 的子进程会被杀，报 `0xC0000142`）。Redis 用原生 6379（无密码），启动后端要 `REDIS_URL=redis://127.0.0.1:6379/0 REDIS_PASSWORD=`。细节见 `2026-10-23.md`。
- 便携 PG 只带 `vector`：`uuid-ossp` 已手写 SQL shim；**没有 `pg_trgm`**（C 扩展，`alembic upgrade head` 会挂在 002）→ 改走 `create_all` + `alembic stamp head`。
- 库 `postgresql://party_user:dev_password@127.0.0.1:55432/party_agent_dev`；查库用 psql（`tmp/pgvenv/.../bin/psql.exe`，中文输出用 python asyncpg 避免 GBK 乱码）。
- 测试账号（口令均 `Test123456`）：`admin`（platform+system_admin，能管所有下级租户）、`test-reviewer`/`test-dept`/`branch-secretary`/`test-organizer`/`test-member`/`test-applicant`（TEST_TENANT 测试大学）。本机种子：`dev_bootstrap.py --with-sample-roles` + `seed_member_profiles.py --tenant TEST_TENANT --org-unit-id TEST_BRANCH`。脚本用 heredoc `python - <<'PY'` + `runpy.run_path` 跑（直接执行 .py 会被静默拦截）。

## 身份与权限规则
- 组织树：同租户只能一个 school 根，school 无父级，department 父级必为 school，branch 父级是 school/department（`validate_tree`）。
- 租户层级 `TENANT_PARENTS`：school→platform、department→school、branch→department。学校租户父级只能是 platform 类型的「党建平台」。
- `tenant.parent_id` 只决定管辖链（`IdentityService.tenant()` 跨租户向上爬，爬不到操作者租户即 403；`list_tenants()` 用 BFS 决定下拉范围），**业务可见性只看 `tenant_id`**。
- 租户无 DELETE，只能 `is_active=false`；`update_tenant` 不能改 `parent_id`。
- 角色-组织映射统一在 `identity_service.ROLE_ORG_TYPES`（school_admin=school / department_admin=department / branch_secretary、member、applicant=branch / organizer=branch+department），开户与编辑共用；前端 `GovernanceView.formOrgs`、`AccountsView.availableOrganizations` 同口径。
- `GET /admin/org-units` 支持 `?tenant_id=`（平台管理员跨租户）；`/accounts` 的「开户租户」不预选，只有唯一可选时才自动选中。
- 管理员重置密码：`PATCH /admin/users/{id}` 的 `UserUpdate` 含可选 `password`（8–72 字节），审计只记 `password_reset: true`，不踢已登录会话。

## 身份证号（= 登录账号，迁移 024）
- `member_profiles.id_card_no`（VARCHAR 32 明文，租户内唯一，且不能撞账号登录名，冲突 409）。档案有号时开户可省略 `username`；候选接口 `GET /admin/member-candidates` 只回 `id_card_masked`；列表/审计/编辑回显走 `identity_service.masked_username`（仅 18 位身份证脱敏，工号原样）。
- 名册登记 `MembersView` 身份证必填按 18 位校验（末位 X 大写）；开户页同样校验，档案缺号时禁用提交。
- 补录 `ProfileUpdate.id_card_no`（空串 422、可更正不可清空），前端入口 `MemberFilePanel`「补录/更正身份证号」与 `AccountsView` 缺号就地补录。补录**不改既有账号登录名**（`UserUpdate` 无 username）。
- 读接口统一 `member_full.profile_payload()`：`id_card_no` → `id_card_masked`，版本快照同样脱敏。
- `audit_logs` 对 422 只记 route/method/status/duration，不记错误正文。

## 扫描归档与 OCR（迁移 025/026）
- 上传 `POST /member-full/profiles/{id}/materials/scan`（PDF/PNG/JPG）。**影像不存库**：落 `<FILE_STORAGE_DIR>/<租户>/archives/<material_id>__h<sha>.bin`（加密、内容寻址），库里只存 `file_path`+sha+大小；`member_materials` 增 `extracted_text`(deferred)/`ocr_status`/`ocr_pages`。
- 识别文字层优先；`cloud_ocr` 未勾选只存影像（skipped）；敏感/涉密按 `cloud_allowed()` 拒绝出网；失败只标 failed，不丢原件。文本出口 `GET /member-full/materials/{id}/text` 过 `mask_text`。
- 抽取建议值 `extract_material_fields()` 存 `extracted_fields`，**只是建议**：类型须命中 `ARCHIVE_MATERIAL_TYPES`（后端 `member_archive_service` 与前端 `api/types.ts` 各一份，改一处必须改两处），不写台账、不自动改选。

## 前端（frontend/）
- 独立 Vite + Vue3（dev 5666，`VITE_API_TARGET` 默认 localhost:8000，本地联调须指 18000；`npx vite` 会卡住，用 `./node_modules/.bin/vite`）。页面 `src/views/*.vue`，接口层 `src/api/*.ts`，`http.ts` 统一包裹体 `{code,message,data,trace_id}`。
- 历史规划的 vben 5.7.0 monorepo 方案**已作废**。

## 模型接入
- 文本 `qwen3.8-flash` / 向量 `qwen3.7-text-embedding-flash` / 重排 `qwen3.7-text-rerank` + 视觉 `VISION_OCR_MODEL`（默认 `qwen-vl-ocr`，留空即关闭图片与扫描件）。
- **OCR 提示词别写"用 Markdown 表格还原"**（qwen-vl-ocr 会包成 `$\begin{aligned}$`），写"表格按行逐条转录"；出口统一过 `normalize_ocr_text()`。
- PDF 渲染用 `pypdfium2`（`page.render(scale=2)`），页数上限 `OCR_MAX_PAGES`。图片出网须 `cloud_ocr=true`，否则 428 + `OCR_CONSENT_REQUIRED`。

## 工程陷阱
- Git：`origin`=manice2005（无共同历史，别推），日常 `git push jaimelove67 master`。`.workbuddy/memory/*.md` 已被跟踪，需 `git add -f`。
- **⚠️ `.git` 会被 safe-delete shim 破坏**（refs/pack 被删、`git status` 变 No commits yet）。见到立即停手：不 `add -A`、不 `reset --hard`、不 `gc/prune`；先 tar 备份 `.git` → `git fetch jaimelove67 "+refs/heads/*:refs/remotes/jaimelove67/*" --force` → 从 reflog 取 sha `update-ref refs/heads/master <sha>` → `git reset --mixed <sha>` → `git fsck`。
- `pytest` 必须 `--basetemp=tmp/pt-<唯一后缀>`（默认 %TEMP% 报 WinError 5；复用报 183）。`module6_*`/`modules123_*` 有 8 个用例多文件连跑必挂、单跑能过，属既有干扰。
- 镜像源全走 ARG：`DOCKERHUB_MIRROR`/`GHCR_MIRROR`/`BASE_IMAGE`/`APT_MIRROR`/`PIP_INDEX_URL`/`NODE_IMAGE`/`NGINX_IMAGE`/`NPM_REGISTRY`，**stage 内 RUN 用 ARG 必须在 FROM 后再声明**。国内可靠源 `swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io`。
- `scripts/*.sh` 用 LF；`bash scripts/xxx.sh`。产出后立即提交；平铺分支名；判断提交是否在历史只信 `git rev-list HEAD | grep <sha>`。
- 本环境**执行 .py 文件会被静默拦截**，必须 `python -c` 或 heredoc；长代码写 `tmp/xxx.sh` + heredoc。
- `npm run build` 本机必失败（safe-delete shim 清 dist 超时），验证构建用 `npx vite build --outDir ../tmp/dist-check`。
- 本机 `tar` 写 `/tmp` 被静默拦截，产物写项目内 `tmp/`。
- 本地无 Docker → `tests/integration` 全部 ERROR，验证以「导入检查 + OpenAPI 契约 + 部署后真实接口」为准。

## 服务器（129.204.32.148）
- OpenCloudOS 9.6，SSH 免密 root；代码 `/opt/dangjian-agent`，容器 `party-agent-*`，库 `party_agent`。`ENV` 必须 development。
- ready 以接口为准 `curl http://127.0.0.1/api/v1/health/ready`；`docker compose exec app python` 不跑 lifespan，直接调 `_readiness_details()` 会误报。
- 备份：`docker exec party-agent-postgres pg_dump -U party_user -d party_agent -Fc > /root/backups/pg_$(date +%F).dump`。
- 租户：`d5584666-…` 湖南科技职业技术学院（在用）；孤立同名 `e410e3b3-…` 待清理；`PLATFORM_TENANT` 是 platform，治理页选错租户 = 白填（platform 点"已确认"直接 422）。
- 治理配置：四项确认 + pilot_scope 到位才 configured；`allowed_hosts` 须为 `ALLOWED_EXTERNAL_MODELS` 子集；模型 id `cloud-llm`/`cloud-embedding`/`cloud-reranker`；权重五项和=1；保存带 `expected_version`（冲突 409）。
- 待办：清理孤立租户、替换演示数据、改初始口令。手册 `docs/线上操作手册.md`，实录 `docs/DEPLOY_SERVER.md`。

## 演示数据
- 种子：`seed_demo_school.py`（租户/组织/账号）、`seed_demo_business.py`（学习依据+考核）、`seed_demo_study_finish.py`（计划→活动→纪要→审核）、`seed_member_profiles.py`（名册 6 人）。走真实 API、幂等；容器内需 `docker cp`。
- 硬约束：① 学习只认 `effective` 资料；② 依据要计划级+条目级两级 `source_doc_ids`；③ 写操作带 `expected_revision`，每步重读；④ 纪要三栏目走 `generate-minutes`；⑤ 考核 `formula=sum` 只能配 `source=manual`+`measure=sum`；⑥ 任务逐条审核；⑦ 口令 ≥8 位；⑧ 审核不能自审。
