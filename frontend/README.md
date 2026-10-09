# 党建工作智能体 · 前端（独立设计工程）

基于 Vite + Vue 3 + TypeScript 的独立前端，从零搭建，不依赖任何脚手架基座。
视觉体系遵循 `.workbuddy/skills/design-taste-frontend/SKILL.md`（taste-skill）的
反模板化规范，调性为**编辑式浅色**。

## 启动

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
  components/   通用组件（图标、引用卡、状态块、页头）
  layouts/      AppShell（顶栏 + 侧栏 + 主区）
  router/       路由与守卫（按权限码显隐菜单）
  stores/       session（会话与权限）
  styles/       tokens.css（设计令牌）、base.css（原子类）
  views/        登录 / 问答 / 知识库 / 党员发展 / 系统状态 / 404
scripts/        Playwright 截图与交互验证脚本（node scripts/screenshot-pages.mjs）
```

## 设计令牌

全部颜色、间距、圆角、动效时长集中在 `src/styles/tokens.css`，组件内不写字面量色值。
三条硬约束：

- 全站唯一强调色 `--accent: #a03230`（暖砖红，饱和度 44%）
- 圆角仅四档：4 / 6 / 8 / 999
- 单一浅色主题，任何区块不得中途反色

## 与后端的诚实约定

后端部分查询接口尚未提供（知识库列表、党员名册、问答历史），对应页面使用
`src/api/mock.ts` 的示例数据，并在界面上以「示例数据」徽标标注；
「系统状态」页的接口能力矩阵（`src/api/surface.ts`）与之呼应。
后端补齐接口后，两处同步更新，不允许只改一边。

## 合规红线在界面的落点

- 问答页：每条回答附依据充分性结论与免责声明，引用角标可点击回溯原文
- 党员发展页：决策边界声明常驻，结果一律表述为「待人工确认」，不提供流转操作入口
- 登录页与侧栏：声明「辅助不代决」的产品边界
