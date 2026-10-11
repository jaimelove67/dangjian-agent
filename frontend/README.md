# 党建工作智能体 · 正式前端

更新日期：2026-10-11。正式业务工程使用 Vite、Vue 3、TypeScript 和 Vue Router；`frontend-test/` 为旧登录联调工程。本文依据当前工作区，不代表其他分支或远端版本。

## 安装与启动

从项目根目录执行：

```bash
npm --prefix frontend ci
npm --prefix frontend run dev
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

开发端口为 5666，代理默认连接 `http://localhost:8000`，把 `/api` 改写为 `/api/v1`；启动 Vite 进程时设置 `VITE_API_TARGET` 可覆盖后端地址。完整配置见[运行指南](../docs/RUNNING.md)。生产输出为 `frontend/dist/`，静态服务器须配置 SPA 路由回退及 `/api` 到后端 `/api/v1` 的代理；开发代理不会进入生产构建。当前 Compose 不包含前端托管。

## 页面与实现边界

| 路由 | 功能 | 当前边界 |
| --- | --- | --- |
| `/login` | 登录与会话恢复 | 需要已登记用户、后端与 Redis |
| `/ask` | 引用问答、会话及持久历史 | 非流式，语义质量需真实评测 |
| `/my-archive` | 本人档案查询 | 仅普通党员；组织人员明确关联账号后可读，不按姓名匹配 |
| `/my-materials` | 个人材料提交、记录与原件下载 | 仅普通党员；私有原件不进入知识库，提交不等于组织核验 |
| `/knowledge` | 授权制度目录、详情与摘要；管理员可上传、改状态及软删除 | 查询用户只读；维护需 `knowledge.manage`，没有原始文件下载 |
| `/members` | 授权名册、登记、账号关联、提交原件查询及规则建议 | 组织人员按授权范围操作；没有自动阶段变更、评分或档案检查工作台 |
| `/study` | 年度计划、材料、提纲、参学、纪要审核、归档与 TXT 导出 | 独立人员审核，归档需要学校效力确认 |
| `/assessment` | 指标版本、任务、归集、佐证、审核、计划、提醒与目录 ZIP | 真实指标须人工登记；导出不含原文件附件 |
| `/accounts` | 系统管理员创建登录账号，设置角色、密码与所属组织 | 仅 `system_admin`；账号与组织限当前租户，不创建租户或组织 |
| `/system` | 服务状态与接口能力矩阵 | 仅平台管理员（`system_admin`）可访问；就绪不等于业务验收 |
| `/forbidden` | 权限不足提示与返回问答入口 | 无权限访问页面时进入此页，不请求系统信息 |

菜单与守卫使用 `src/api/types.ts` 中的权限码；系统入口与路由直接限定 `system_admin` 角色。服务端仍负责租户、组织及资料授权。完整范围见[项目状态](../docs/STATUS.md)。

普通党员端仅提供本人档案、个人材料、制度问答三个功能。党员没有 `knowledge.query` 或组织管理权限，直接访问知识库或管理工作台也会被拒绝。问答仍依据公共政策和本校授权资料，使用 `qa.ask` 权限；申请人的原有公共资料查询范围保持。系统页面及 `/api/v1/admin/health*` 详情直接校验平台管理员角色（`system_admin`），校级及院系管理员也不能查看；其他角色即使收到 `admin.config` 权限码，也不会显示系统入口或获得详情访问权。

应用迁移 `012_member_self` 后，组织人员在 `/members` 选中本人台账，打开“账号与个人提交”，输入同一组织的有效普通党员登录账号并关联。已有档案不自动绑定，已有不同账号关联不能覆盖。材料默认限 10MB，原件存于私有数据库表；提交记录与组织登记的已具备材料分开，不自动核验、流转或向外部模型发送。

系统管理员在“系统 → 创建账号”开通账号，输入用户名、姓名、密码与确认密码，选择角色和有效组织。默认角色为普通党员；学校/院系管理员分别绑定学校/院系，支部书记、组织员、党员及申请人绑定支部。密码至少 8 个字符且不超过 72 个 UTF-8 字节，仅以 bcrypt 哈希保存，创建结果不返回密码。失败时保留表单，成功后清空用户名、姓名和密码。用户名全局唯一，重复创建返回冲突；普通党员开户后仍需在名册中明确关联本人档案。

## 工程结构

```text
src/api/          类型、HTTP 封装及 auth/qa/knowledge/member/study/assessment 接口
src/components/   图标、引用卡、页头及加载/错误/空状态
src/layouts/      AppShell
src/router/       路由与权限守卫
src/stores/       会话、用户与权限
src/styles/       tokens.css、base.css
src/views/        正式业务页面
tests/           business/study/assessment 业务流程与 role-access 角色权限回归
scripts/          设计与页面截图
```

`src/api/mock.ts` 保留开发辅助资料，名册页面读取真实 API。接口变化需同步维护 `src/api/surface.ts`、页面和文档。

## 设计与业务约定

采用编辑式浅色界面，设计令牌集中在 `src/styles/tokens.css`，强调色使用暖砖红 `--accent`，优先复用既有组件、圆角档位和样式。

问答提供引用与风险提示；党员发展仅给人工确认建议。学习材料推荐采用授权检索，提纲采用模板，纪要采用原文摘录，没有调用外部模型。审核、归档和导出重新检查资料权限；学校电子效力未确认时不能归档。

## 验证

在 `frontend/` 执行：

```bash
node tests/business-workflows.mjs
node tests/study-workflows.mjs
node tests/assessment-workflows.mjs
node tests/role-access.mjs
node tests/member-self-workflows.mjs
node tests/admin-accounts.mjs
```

流程使用合成 API 响应，验证界面和请求契约；真实后端、学校数据和用户验收另行执行。可通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指定已有 Chromium。历史结果见[测试指南](../docs/TESTING.md)。

## 文档合并边界

主分支已有组织生活 `/meeting`、治理审核 `/governance`、账号开户 `/accounts`、党员 `/my-archive` 和 `/my-materials` 页面。平台系统详情限 `system_admin`，治理功能另按服务端权限限制。当前路由尚未提供本地扩展的 `/admin` 首页、独立 `/organizations`、`/audit` 和账号启停/密码重置页面；默认仍进入 `/ask`。这些扩展不能因文档合并而视为页面已交付，见[使用指南](../docs/ADMINISTRATION.md)。
