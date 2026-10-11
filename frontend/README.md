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
| `/knowledge` | 上传、列表、详情、状态与软删除 | 向量化使用后端 API，没有原始文件下载 |
| `/members` | 授权名册、人工登记、资格校验及流转/待办建议 | 已接真实名册；没有阶段变更、评分或档案检查工作台 |
| `/study` | 年度计划、材料、提纲、参学、纪要审核、归档与 TXT 导出 | 独立人员审核，归档需要学校效力确认 |
| `/assessment` | 指标版本、任务、归集、佐证、审核、计划、提醒与目录 ZIP | 真实指标须人工登记；导出不含原文件附件 |
| `/system` | 服务状态与接口能力矩阵 | 就绪不等于业务验收 |

菜单与守卫使用 `src/api/types.ts` 中的权限码，服务端仍负责租户、组织及资料授权。完整范围见[项目状态](../docs/STATUS.md)。

## 工程结构

```text
src/api/          类型、HTTP 封装及 auth/qa/knowledge/member/study/assessment 接口
src/components/   图标、引用卡、页头及加载/错误/空状态
src/layouts/      AppShell
src/router/       路由与权限守卫
src/stores/       会话、用户与权限
src/styles/       tokens.css、base.css
src/views/        正式业务页面
tests/           business/study/assessment 浏览器流程
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
```

流程使用合成 API 响应，验证界面和请求契约；真实后端、学校数据和用户验收另行执行。可通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指定已有 Chromium。历史结果见[测试指南](../docs/TESTING.md)。
