# 党建工作智能体 · 前端（独立设计工程）

基于 Vite + Vue 3 + TypeScript 的独立前端，从零搭建，不依赖任何脚手架基座。
视觉体系遵循 `.workbuddy/skills/design-taste-frontend/SKILL.md`（taste-skill）的
反模板化规范，调性为**编辑式浅色**。

## 启动

完整环境配置见[运行指南](../docs/RUNNING.md)，验证命令与验收范围见[测试指南](../docs/TESTING.md)。以下命令在 `frontend/` 中执行。

```bash
npm install
npm run dev        # http://localhost:5666
npm run build      # 类型检查 + 生产构建
npm run typecheck  # 仅类型检查
```

需要后端在 `http://localhost:8000` 运行；开发代理把 `/api` 重写到 `/api/v1`。

## 结构

```
src/
  api/          接口层：types.ts（契约）、http.ts（axios 封装）、按路由拆分的模块
  components/   通用组件及知识库、党员发展、组织生活业务工作区
  layouts/      AppShell（顶栏 + 侧栏 + 主区）
  router/       路由与守卫（按权限码显隐菜单）
  stores/       session（会话与权限）
  styles/       tokens.css（设计令牌）、base.css、workbench.css（业务表单与表格）
  views/        登录 / 问答 / 知识库 / 党员发展 / 组织生活 / 系统状态 / 404
scripts/        Playwright 截图与交互验证脚本
```

## 设计令牌

全部颜色、间距、圆角、动效时长集中在 `src/styles/tokens.css`，组件内不写字面量色值。
三条硬约束：

- 全站唯一强调色 `--accent: #a03230`（暖砖红，饱和度 44%）
- 圆角仅四档：4 / 6 / 8 / 999
- 单一浅色主题，任何区块不得中途反色

## 与后端的诚实约定

知识库、党员名册与组织生活均调用真实 API，查询失败时显示错误，不用样例填充业务页面。
知识库新增处理状态、授权原件下载与元数据维护；党员发展新增年度批次、材料人工审核、
培养记录、辅助评分、人工阶段登记、提醒、投票与档案检查；组织生活新增资料与出勤编辑、
参考文件选择、纪要提交与人工审核、任务办理、版本记录及归档导出。
「系统状态」页的接口能力矩阵（`src/api/surface.ts`）与页面实现保持一致。
接口能力表示存在可调用入口，完整业务验收仍需数据库、规则及外部服务就绪。

本轮设计与验证范围见[模块 1 至 3 界面设计记录](../docs/MODULES123_UI_DESIGN_2026-10-10.md)。
`taste-skill` 的 Section 13 不覆盖管理面板、数据表和复杂业务表单；本次复用其字体、
颜色、信息层级、克制动效与响应式原则，沿用现有 Vue 设计系统。

以下浏览器检查使用明确标注的接口样例，不写真实数据库，也不调用模型。启动前端后运行：

```bash
node scripts/verify-modules123.mjs http://127.0.0.1:5666 ../tmp/modules123-ui
```

在仓库根目录校验浏览器捕获的请求与实际后端输入模型：

```bash
python scripts/validate_modules123_ui_contracts.py tmp/modules123-ui/contract-requests.json
```

## 合规红线在界面的落点

- 问答页：每条回答附依据充分性结论与免责声明，引用角标可点击回溯原文
- 党员发展页：决策边界声明常驻；规则分析与评分仅供核验，阶段登记必须由有权限的人工确认并记录依据、日期和意见
- 组织生活页：资料须先保存再处理当前版本；提交人不能自审；审核和归档分别核验权限与条件
- 登录页与侧栏：声明「辅助不代决」的产品边界
