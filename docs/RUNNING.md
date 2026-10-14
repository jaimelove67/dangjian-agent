# 运行指南

更新日期：2026-10-11，依据当前工作区。正式前端位于 `frontend/`。本指南说明启动方式；服务是否运行及是否就绪，需要实际请求检查。

## 本地开发

准备 Python 3.11+、满足 `frontend/package-lock.json` 中 Vite 引擎约束的 Node.js（历史验证使用 Node 24）/npm、PostgreSQL（支持 pgvector）与 Redis。以下命令在项目根目录执行。

1. 使用已有 `.env`，或从 [`.env.example`](../.env.example) 创建；配置 `DATABASE_URL`、`REDIS_URL`、`SECRET_KEY` 和 `DASHSCOPE_API_KEY`。模型与主机白名单的配置说明见该示例文件。
2. 安装后端依赖与正式前端依赖：

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
   npm --prefix frontend ci
   ```

   Linux/macOS 使用 `.venv/bin/python`。只运行服务时可安装 `requirements.txt`；运行测试需要开发依赖。

3. 确认数据库与 Redis 可用。使用项目开发容器时：

   ```bash
   docker compose -f docker-compose.dev.yml up -d postgres redis
   ```

   此 Compose 的数据库为 `party_agent_dev`，默认宿主端口为 55432；Redis 为 56379，仅绑定本机地址。可通过 `POSTGRES_PORT`、`REDIS_PORT` 覆盖宿主端口（`.env.example` 的默认值即 55432/56379）。本地应用需要连接宿主地址，不能使用容器内的 `postgres`/`redis` 主机名。开发配置示例：

   ```dotenv
   POSTGRES_PORT=55432
   REDIS_PORT=56379
   DATABASE_URL=postgresql+asyncpg://party_user:dev_password@127.0.0.1:55432/party_agent_dev
   REDIS_URL=redis://127.0.0.1:56379/0
   ```

   使用已有服务时以实际连接参数为准，避免端口冲突。**本机 8000 端口常被其它项目
   （如本仓库并行运行的其它服务）占用**，此时后端改用 `.env` 的 `APP_PORT` 启动，
   并必须给前端设置同值的 `VITE_API_TARGET`，否则 `/api` 代理会指向不存在的服务。

4. 对新建或已迁移的数据库执行迁移，当前迁移头为 `012_member_self`（包含组织生活、学习、年度考核、治理和党员本人档案/材料）：

   ```powershell
   .\.venv\Scripts\python.exe -m alembic upgrade head
   ```

5. 启动前后端：

   ```powershell
   .\scripts\start-all.bat
   ```

   Linux/macOS 使用 `bash scripts/start-all.sh`。脚本优先使用 `.venv`，可通过 `PARTY_PYTHON` 指定解释器。前端为 `http://127.0.0.1:5666`，后端默认为 `http://127.0.0.1:8000`（`APP_PORT` 被占用时以 `.env` 的 `APP_PORT` 为准）。

Windows 关闭两个服务窗口停止服务；Linux/macOS 在启动脚本终端按 `Ctrl+C`。

### PowerShell 手动启动（脚本不适用时）

```powershell
# 后端：端口与 .env 的 APP_PORT 保持一致
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18000

# 前端：在 frontend/ 目录直接 npm run dev 即可
# 端口 5666 与 /api 代理前缀已写在 frontend/vite.config.ts，不需要再传 --port
cd frontend
$env:VITE_API_TARGET = "http://127.0.0.1:18000"   # 必须与后端端口一致
npm run dev
```

> 不要使用 `npm run dev -- --port 5666`：PowerShell 会把参数传给 npm 之外的解析路径，
> Vite 收到多余参数后会以 `CACError: Unused args` 直接退出。

## 就绪检查与排障

```bash
curl http://127.0.0.1:8000/api/v1/health/live
curl http://127.0.0.1:8000/api/v1/health/ready
```

- `live` 只检查进程存活；`ready` 检查数据库、核心结构、Redis 与模型配置，缺少必需依赖时返回 503。
- 模型**连通性**（最近 15 分钟内有成功调用）单独作为 `model_warm` 观察项，**不参与**就绪判定：新环境或长时间没有提问时，`ready` 仍返回 200，但 `model_warm` 为 `unverified`。
- 公开健康接口仅返回整体 `status`。服务名称、版本和运行环境见 `/api/v1/admin/health`，依赖与模型配置详情见 `/api/v1/admin/health/ready`；两者均要求平台管理员登录令牌，其他角色返回 403。平台管理员可在前端“系统状态”页查看详情。
- `ready` 只检查六张基础核心表与全文检索，不核对学习/考核表或完整迁移头；业务使用前仍需执行 `python -m alembic current`。200 也不代表实际云调用或答案质量已验收，见[测试指南](TESTING.md)。
- API 文档位于 `/docs`，仅在开发调试 `DEBUG=true` 时启用。
- 登录需要已登记的用户；正式账号应关联实际组织与租户。
- 已有系统管理员登录后，可在“系统 → 创建账号”（`/accounts`）开通本租户账号，设置用户名、姓名、角色、所属组织和密码。创建需要有效组织；学校/院系管理员分别绑定学校/院系，其他组织角色及普通党员、申请人绑定支部。密码至少 8 个字符且不超过 72 个 UTF-8 字节，无默认密码。创建成功即可登录；普通党员使用本人档案及材料功能前还需关联名册档案。
- 培养对象登记需要真实学校、院系、支部记录；组织角色还需绑定正确的 `org_unit_id`。未配置组织时，页面会给出提示。
- `frontend-test/` 是旧登录联调辅助工程，正式业务页面使用 `frontend/`。

中心组学习入口为正式前端 `/study`，需要学校/院系党委组织归属及 `study.query` 权限。模块4使用迁移 `006` 新增的学习计划、条目、共用活动与修订表，按上述迁移流程升级后使用；历史验证只在随机测试库执行迁移；本次文档更新未检查或升级业务库。年度计划和纪要由另一位组织人员审核，电子归档默认关闭，学校效力确认后由校级/系统管理员登记依据。详情见[模块4使用与验收记录](MODULE4_STUDY_2026-10-10.md)。

年度考核入口为正式前端 `/assessment`，需要有效组织归属及 `assessment.query` 权限。迁移 `007_assessment` 新增八张考核业务表；历史验证只在随机测试库执行；本次文档更新未检查或升级业务库。学校管理员先登记年度指标，再由院系/支部制定任务、绑定佐证与归集。真实学校指标及人工台账对账仍待验收；没有指标时页面不会导入示例指标。站内提醒随后端启动，每 `ASSESSMENT_REMINDER_SCAN_SECONDS` 秒扫描一次（默认300秒，允许60–86400秒），也可从工作台手动扫描；详情见[模块5记录](MODULE5_ASSESSMENT_2026-10-10.md)。

## 已有数据库接管

仅包含手工创建 `users` 表的旧库，需要先备份并核对结构，再使用明确的接管参数：

```powershell
python -m alembic -x adopt_existing_users=true upgrade head
```

该参数只适用于上述旧库情形。不得删除用户表或通过 `alembic stamp head` 跳过核心建表。接管依据及此前验证见[修复记录](archive/2026-10-10/PROJECT_REPAIR_2026-10-10.md)。

## 开发账号与合成数据

首次没有任何系统管理员账号时，开发环境仍需按下方脚本初始化；已有管理员后优先使用页面开户。页面和后端开户接口适用于正常运行环境，`scripts/create_test_user.py` 的限制仅针对开发脚本。开户功能不负责初始化租户或组织。

先准备有效测试租户和组织。以下脚本只允许 `ENV=development/testing`；使用专用开发库，不导入真实人员资料。

```bash
python scripts/create_test_user.py --username test-reviewer --tenant TEST_TENANT --org-unit-id TEST_ORG --role school_admin
python scripts/seed_member_profiles.py --tenant TEST_TENANT --org-unit-id TEST_BRANCH
python scripts/seed_knowledge_docs.py --username test-reviewer
```

密码省略时交互输入，没有默认管理员密码。账号脚本不负责创建租户/组织；名册脚本要求有效支部，已有名册时跳过。知识脚本导入未核验演示资料，不属于批准的权威知识基线；只有加 `--embed` 才请求云端向量化，可能产生费用。正式组织、人员与年度指标应人工核对后登记。

`create_test_user.py` 和 `create_tables_and_user.sql` 等根目录临时文件不是标准部署入口；`scripts/init_db.py` 会先删除全部映射表，不能用于旧库接管或升级。标准流程统一使用 Alembic，见[迁移指南](../migrations/README.md)。

## 容器部署

完整开发容器启动、生产部署、备份与排障统一见 [Docker 指南](../deploy/docker/README.md)；镜像拉取问题见[镜像源指南](../deploy/docker/MIRROR_GUIDE.md)。

管理与本人资料使用见[指南](ADMINISTRATION.md)。主分支迁移至 `012_member_self`，本地 `009_admin_workspace` 与该迁移链不同，不能直接用于主分支；扩展工作台需先重新编排迁移并合入代码。
