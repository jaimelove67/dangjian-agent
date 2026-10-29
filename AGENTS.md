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

## 学习教育访问

学习教育面向全体党员和申请人开放查看。普通党员、申请人、支部书记和支部组织员进入课程、主题党日与本人积分；中心组年度计划、审核和归档仍由学校、院系管理员使用 `study.query` 办理，不因开放课程查看而扩大中心组范围。

课程与活动是学习教育的独立入口。校级管理员可从“学习教育 → 课程与活动”直接编制课程；院系、支部书记、组织员在学习教育内维护。课程先保存草稿，确认发布后党员和申请人可见；课程按全校、院系或支部范围控制可见性。

## 制度问答

问答输入框提供问题输入、附件上传（回形针按钮）、快捷键提示与发送按钮。附件走 `POST /qa/attachments`：上传后显示可移除的材料条，发送时随 `attachment_ids` 带出，回答生成后自动摘除；只上传材料不写问题也允许发送。图片与扫描件上传前须经本人确认送云端识别（涉密材料不出网）。附件只作提问背景，不作制度依据、不占引用编号，问答请求沿用接口默认的公开资料范围。

无制度依据时，问答返回明确标注的“办理参考”：不附引用、不构成政策依据，只给通用工作思路；不得编造条款、文号、时限、比例、处分种类或组织认定结论。检索到可引用依据时，仍按原文作答并附引用。界面分别显示“办理参考”和“未找到依据”。

## 系统文案

页面、弹窗、通知、错误提示、帮助说明及导出文件统一使用正式系统用语，不展示演示、原型或示例标记。功能不可用或尚未配置时，说明实际状态及可采取的下一步；仅登记信息的操作须明确登记结果，不提示已执行业务操作。内部模式、存储键和业务关联标识保留兼容。

## 材料填写建议

个人材料及发展材料上传后先展示提取建议与原文依据，用户点击采用后仅填入空白项，保留人工填写内容；更换文件时清除尚未人工改动的旧建议。确认提交后保存材料，档案身份、组织收到日期、核验意见和发展阶段由人工办理。无法识别时继续支持手动填写；本地提取默认不调用外部模型。

## 材料来源与核验

党员发展材料清单可以展示本人提交的个人材料，但须标注“个人提交”，材料类型按个人材料分类显示，例如“思想汇报（个人提交）”；组织登记材料标注“组织登记”，历史材料名称标注“历史登记”。个人材料不纳入发展材料核验、材料完整性判断和阶段流转，不得通过发展材料核验接口改变核验状态。

## 团组织推优资格

团组织推优按中央《共青团推优入党工作实施办法（试行）》核验：推优对象年满 18 周岁、入团满 1 年。党员档案补录出生年月与入团时间，登记推优时按推荐日期核算；档案缺项或明确不符时拒绝登记并提示补录，不默认通过，不解析身份证号推算生日，不提供绕过校验的开关。名册只显示“资格已核验 / 不符 / 待补录”摘要，28 周岁以上通过时提示组织核对是否仍适用。缺推优记录不阻断选优与阶段流转。

## 修改密码与申请

支部书记、组织员、教师党员、学生党员和入党申请人从头像菜单“修改密码”办理。每账号累计仅一次自主修改；之后每次修改须提交原因，由平台管理员在“账号与权限 → 改密申请”批准或驳回，每次批准仅授权一次成功修改。平台、学校和院系管理员不开放本人自主修改入口。保留原有导航、个人档案和管理角色个人中心。

次数及申请按租户和账号保存，失败不消耗次数或审批授权，修改成功后原会话失效。管理员恢复密码保留累计次数。演示模式可保存加盐密码校验值，明文密码不进入浏览器存储、申请或审计；真实次数和授权由后端原子校验，未接入时如实说明。实现与正式后端所需能力见 docs/password-security.md。

## 登录页

登录页保持原有设计，不增加“选择登录身份”等演示切换控件；账号、密码、账号登录/扫码登录、忘记密码入口与整体布局保持原样。
