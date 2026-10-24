# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build the current React app UI in `frontend/src/`; the FastAPI application is in `backend/app/`. `backend/frontend/` preserves the upstream Vue reference and its regression tools. For installation, startup, API origins or container changes, read `docs/frontend-backend.md`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

# 学校管理员设计约定

- 学校管理员使用 7 个一级导航：学校工作台、组织与党员、党员发展、组织生活、学习教育、考核与统计、校级管理；具体业务放入二级菜单，账号设置置于右上角，材料接收从相关业务进入。
- 首页优先展示全校待审核事项、逾期与缺失材料、组织工作进度和重要通知；统计、问题和待办均可进入具体组织及业务记录。
- 业务记录呈现提交人、审核人、材料版本、处理意见、退回原因和归档状态。审核与归档分别确认，学校管理员按学校制度办理，支部及组织员负责日常登记，院系负责核验及督办。
- 校级管理提供本校账号管理：学校管理员可编辑本校账号的姓名、业务角色、组织归属、启停状态与密码，管理范围固定本校。账号开户、租户开通、平台服务配置由平台管理员负责。

Member archive details open in a centered, flat modal with small corners, no shadow or backdrop blur, compact two-column details and horizontal development stages on desktop. Narrow screens use one column and compact vertical stages; retain scrollable content and the existing close controls.

原有右侧抽屉统一使用与党员档案一致的居中扁平弹窗（`Modal` 的 `wide flat` 形式），包括校级业务办理和智能体会话记录。详情与办理窗口保留可滚动内容及原有表单、权限校验和关闭操作；导航侧栏沿用原有布局。

管理角色的个人中心以 `个人中心.png` 为视觉参考：顶部通栏资料卡，桌面左侧为我的工作与最近操作，右侧为账号与安全及通知设置，窄屏改为单列。身份、工作统计和操作记录按当前账号与租户隔离；未接入的认证、资料更正和联系方式维护入口如实说明，通知开关只保存本人当前浏览器偏好。

## Accepted platform administrator design

The platform administrator has exactly six primary navigation entries, in this order: 平台工作台、租户管理、账号与权限、系统运维、平台配置、安全审计. Use the existing red navigation and white workspace cards. Keep school party-affairs menus in their own roles; personal account information belongs in the avatar menu. The platform workspace prioritizes service health, tenants/accounts, alerts, failed jobs and pending actions. Tenant, identity, operations, configuration and audit pages follow the user's specified functions. Demo operations persist locally; real mode must reflect verified backend capabilities and never simulate a successful account, restore, session or configuration mutation.

平台管理员可以编辑各类账号的属性，包括姓名、业务角色、组织范围与启停状态。账号列表和详情均提供编辑入口，保留本人档案关联、修改审计及当前账号和最后一位有效管理员的保护。

平台及学校管理员的账号编辑提供新密码与确认新密码，打开时为空且默认隐藏，留空保留原密码；只允许显示本次输入的新密码。管理员改密保留累计自主改密次数，当前账号改密后重新登录，明文密码不进入存储或审计。

## 本人档案与头像菜单

教师党员、学生党员与入党申请人的侧栏保留“本人档案”和“个人材料”，不提供“账号设置”或“个人中心”入口。右上角头像菜单使用“个人档案”，打开同一份本人档案；旧的 profile 地址转到 self-archive。管理角色的个人中心仍从头像菜单进入。

## 制度问答

问答输入框仅提供问题输入、快捷键提示与发送按钮，移除资料选择控件。问答请求沿用接口默认的公开资料范围。

## 系统文案

页面、弹窗、通知、错误提示、帮助说明及导出文件统一使用正式系统用语，不展示演示、原型或示例标记。功能不可用或尚未配置时，说明实际状态及可采取的下一步；仅登记信息的操作须明确登记结果，不提示已执行业务操作。内部模式、存储键和业务关联标识保留兼容。

## 材料填写建议

个人材料及发展材料上传后先展示提取建议与原文依据，用户点击采用后仅填入空白项，保留人工填写内容；更换文件时清除尚未人工改动的旧建议。确认提交后保存材料，档案身份、组织收到日期、核验意见和发展阶段由人工办理。无法识别时继续支持手动填写；本地提取默认不调用外部模型。

## 修改密码与申请

支部书记、组织员、教师党员、学生党员和入党申请人从头像菜单“修改密码”办理。每账号累计仅一次自主修改；之后每次修改须提交原因，由平台管理员在“账号与权限 → 改密申请”批准或驳回，每次批准仅授权一次成功修改。平台、学校和院系管理员不开放本人自主修改入口。保留原有导航、个人档案和管理角色个人中心。

次数及申请按租户和账号保存，失败不消耗次数或审批授权，修改成功后原会话失效。管理员恢复密码保留累计次数。演示模式可保存加盐密码校验值，明文密码不进入浏览器存储、申请或审计；真实次数和授权由后端原子校验，未接入时如实说明。实现与正式后端所需能力见 docs/password-security.md。
