# 后端接口与业务边界

核对日期：2026-10-24。参考版本：[jaimelove67/dangjian-agent，b190fcb](https://github.com/jaimelove67/dangjian-agent/commit/b190fcb9464c2fb2a9116b469b5a0a4d2a4cd274)。本地启动修复和真实接口验证见 [后端基线记录](backend-baseline.md)。

当前真实页面、接口和业务闭环结果见 [前后端联调报告](integration-check-2026-10-24.md)。本地源码已在参考版本上增加账号安全、校级业务、课程活动、受控运维接口，以及党员发展流程与党员基本信息采集，当前迁移头为 `036_member_procedures`；不能再把参考提交的能力边界当作当前本地版本的能力边界。

本项目保留独立 React 前端，参考项目正式前端使用 Vue 3 + TypeScript。`backend/` 为固定版本的本地源码副本，已修复启动和测试问题；没有修改或推送远端工程、正式数据库或线上配置。后端沿用原项目的 FastAPI API、权限码、租户和组织授权、人工审核及资料分级。

## 适配原则

- API 统一使用 `/api/v1`，不重复重写成 `/api/v1/v1`。
- 成功响应 `code === 0` 时读取 `data`；失败保留 `message` 与 `trace_id`。
- 访问令牌与刷新令牌由参考后端签发。刷新接口使用 `Authorization: Bearer <refresh_token>`，不放入请求正文。
- 权限码控制菜单和页面入口，实际权限、租户、组织范围仍由服务端执行。前端隐藏不能代替后端校验。
- 真实账号退出或切换时清空前端内存业务数据；前一账号未完成的请求不能填入新账号工作区。
- 后端模式不把真实档案、问答和业务材料写入演示 `localStorage`。

## 当前页面使用的接口

| 模块       | 接口                                                                                                     | 适配情况                                                                |
| ---------- | -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| 认证       | `POST /auth/login`、`GET /auth/me`、`GET /auth/codes`                                                    | 已适配                                                                  |
| 会话       | `POST /auth/refresh`、`POST /auth/logout`                                                                | 已适配；并发共享刷新                                                    |
| 组织范围   | `GET /member/org-units`                                                                                  | 已读取 id / name / org_type / parent_id；仅返回同一授权集合内的父节点，组织架构按真实隶属关系展示，学校统计仅计 branch |
| 名册       | `GET /member/roster`、`POST /member/roster`、`GET /member/roster/export`                                 | 已适配；列表先加载前 100 条，搜索在已加载范围内；导出走后端完整授权范围 |
| 三会一课   | `GET /meeting/org-units`、`GET /meeting/records`、`POST /meeting/records`、`PATCH /meeting/records/{id}` | 已适配；遵循创建与修订的不同字段约束                                    |
| 制度问答   | `POST /qa`                                                                                               | 已适配；支持分级、会话号、回答与引用，错误不回退为示例回答              |
| 本人档案   | `GET /member/self/archive`                                                                               | 已适配；不通过同名人员猜测本人档案                                      |
| 个人原件 | GET /member/self/materials、POST /member/self/materials、GET /member/self/materials/{id}/file | 列表 / 分页、multipart 原件与 submission_key、本人下载 |
| 材料接收 | GET /member/roster/{profile}/materials、GET /member/roster/{profile}/materials/{id}/file | 绑定请求所属档案与分页，不重用上一提交人的列表 |
| 明确关联 | PUT /member/roster/{profile}/account | 只提交 username，由后端核对组织、租户与既有归属 |
| 人工发展 | GET /member-full/profiles/{id}、POST /member-full/profiles/{id}/materials、POST /member-full/materials/{id}/review、POST /member-full/profiles/{id}/cultivation、POST /member-full/profiles/{id}/transition、POST /member-full/archive-check | 人工登记、核验、培养、阶段依据与材料核对 |
| 纪要审核 | POST /meeting/records/{id}/submit、POST /meeting/records/{id}/review | expected_revision、reason，审核附 decision；不可自审 |
| 综合审核 | GET /admin/reviews、GET /admin/reviews/{id}、POST /admin/reviews/{id}/decision | 原始 source_version 与人工意见，过期来源禁止通过 |
| 账号维护 | GET /admin/users、PATCH /admin/users/{id}、GET /admin/org-units | 已真实联调本校读取与维护；组织选项允许本校身份管理权限，跨校与开户仍受后端限制；账号编辑使既有登录会话失效，保护最后有效管理员及本人档案组织一致性 |
| 平台开户 | POST /admin/users、GET /admin/member-candidates | 开户与明确档案关联；仅平台角色进入 |
| 租户 / 审计 | GET /admin/tenants、POST /admin/tenants、GET /admin/audit-logs、GET /admin/audit-logs/export、GET /admin/operations | 租户登记、审计查询 / 导出、平台状态 |
| 知识库 | `GET/POST /knowledge-docs`、`GET /knowledge-docs/{id}/chunks`、`PUT /knowledge-docs/{id}/content`、`GET /knowledge-docs/{id}/file?revision=...` | 原件上传、正文解析、换版、历史原件下载；待审片段仅向有维护权限且在授权范围的人员开放 |
| 知识复核 | `PATCH /knowledge-docs/{id}/metadata`、`PATCH /knowledge-docs/{id}/status`、`POST /knowledge-docs/{id}/review`、`POST /knowledge-docs/{id}/maintenance` | 来源信息修正、发布审核、时效状态和供给复核；原件替换保留办理原因 |
| 检索处理 | `GET /knowledge-docs/{id}/processing-status`、`POST /embeddings/embed` | 显示实际向量状态和失败原因；向量化单独办理，按资料级别和模型网关执行 |
| 中心组学习 | `GET/POST /study/plans`、计划及分期条目修订、计划送审/审核、`POST /study/plans/{id}/items/{item}/activity` | 学校/院系年度重点、有效制度来源、分期安排和独立审核 |
| 学习纪要 | `/study/activities/{id}` 下的修订、`generate-minutes`、`submit`、`review`、`archive`、`export`、`revisions` | 真实日期/实名出勤/原文、带位置的纪要、独立审核和单独归档 |
| 年度考核   | `GET /assessment/org-units`、`GET /assessment/workspace`、`POST /assessment/recalculate`                 | 已适配组织范围、工作台与归集                                            |
| 考核目录   | `POST /assessment/runs/{id}/export`                                                                      | 仅选择人工审核通过的归集版本                                            |
| 就绪检查   | `GET /health/ready`                                                                                      | 已适配；不把管理员运行详情暴露给普通账号                                |
| 本人改密 | `/auth/password-state`、`/auth/password-change`、`/auth/password-requests` | 累计首次机会、再次申请及原子消费；成功后旧会话失效，见 [安全契约](password-security.md) |
| 平台改密审批 | `/admin/password-requests`、`/admin/password-requests/{id}/review` | 按真实平台身份、目标租户和申请版本审批 |
| 会话管理 | `/admin/login-sessions`、`/admin/login-sessions/{id}/revoke` | 实际登录登记、按范围查询、指定会话撤销 |
| 校级业务 | `/school/business/records`、`/notices`、`/tasks`、`/permission-requests`、`/rules` 及记录办理接口 | 通知草稿/发布，任务下发/完成佐证/独立核验/归档，学校参数版本和平台角色审批 |
| 教育课程 | `/education/offerings`、`/courses`、`/enroll`、`/heartbeat`、`/exam`、`/credits` | 草稿发布、真实视频区间去重计时、服务端考试计分、本人积分及管理范围进度 |
| 主题党日 | `/education/events`、活动 `/enroll`、`/cancel`、`/attendance` | 限额与截止校验，取消释放名额，活动开展后由另一人核验出席授分 |
| 选优及推优 | `/member-full/batches`、`/votes`、`/selections`、`/league-recommendations` | 批次、本人投票、拟推荐名单修订/送审/独立审核及推优登记/作废 |
| 民主评议 | `/meeting/member-reviews`、其工作台/发起/办理接口及 `/member/self/reviews` | 程序、汇总票数、拟定等次与独立审核；本人档案只读取本人已生效结果 |
| 接转及报送 | `/member-full/transfers`、`/member-full/upper-reports` 及回执/批复/作废接口 | 转入转出、介绍信、回执和批复事实；报送 Excel 导出使用 **GET** |
| 党员信息采集 | `/member/info-collection/self`、`/member/info-collection/self/submit`、`/member/info-collections`、`/member/info-collections/{id}` | 本人填报、支部初核、院系复核、学校备案；按状态与版本办事，退回后修订重新提交 |
| 发展闸门与台账 | `/member-full/profiles/{id}/political-reviews`、`/trainings`、`/procedures`、`/scoring` | 政审、集中培训与程序事实只增不改；缺项提示补录，阶段流转不默认通过 |
| 备份恢复 | `GET/POST /admin/backups`、`GET /admin/backups/{id}/file` | 默认关闭；真实加密备份、持久结果及只写新目标的隔离恢复，见 [运维契约](backup-operations.md) |

上述路径均附加 `/api/v1` 前缀，表中的分组路径不是穷尽的 OpenAPI 清单。年度考核当前还包括指标版本、责任任务、真实文件佐证、独立审核、年度计划、提醒办理和单独归档。页面可打开、接口存在与完整业务闭环分别验收，执行结果及限制见联调报告。

个人原件使用 multipart 的 file、title、category、description、submission_key，不由前端指定所属账号。类别为 thought_report、study_note、certificate、other，上传上限从本人档案响应取得；无明确档案关联时禁止提交。

新增账号使用 username、name、password、role、org_unit_id 以及可选 member_id。不附加租户、启用状态或其他禁止字段。独立会议审核使用 approved / rejected；综合审核使用 approved / returned，二者不混用。

## 核对过的关键请求

党员阶段取自 [原项目 types.ts](https://github.com/jaimelove67/dangjian-agent/blob/b190fcb9464c2fb2a9116b469b5a0a4d2a4cd274/frontend/src/api/types.ts)：`applicant`、`activist`、`candidate`、`probationary`、`member`；后端返回的 `stage` 与新增请求的 `current_stage` 不同。新增请求只提交 `name`、`org_unit_id`、`current_stage`、`materials`、`pending`。该接口没有学号、工号、性别和备注字段，真实模式不伪造这些字段。

会议契约取自 [app/schemas/meeting.py](https://github.com/jaimelove67/dangjian-agent/blob/b190fcb9464c2fb2a9116b469b5a0a4d2a4cd274/app/schemas/meeting.py)。`ActivityCreate` 禁止额外字段，创建时提交标题、组织、活动类型、计划日期、主持人、议程、参会名单、来源文件与理由。真实页面支持逐人填写编号、姓名与出勤；更新增加 `held_on` 和实际参会名单，使用 `topic`、`expected_revision`、`reason`，不擅自更改组织和活动类型。保存原文后经 `generate-minutes` 提取有定位的纪要，再送审；审核通过后单独确认归档，后端继续校验学校电子效力政策。独立的时间、地点和出勤汇总不在该契约中，因此真实模式禁用相应输入，也不填入虚假的召开时间。

问答契约的 `question` 上限 500 字。React 输入框、发送前与适配层均校验，按 Unicode 字符计数并去除首尾空白；超长或空问题不发送。提交问题、默认公开范围、`use_reranker`、`top_k`、可选 `session_id`；读取回答、引用、警告和免责声明。501 字返回 422。经用户明确授权，当前已用一份公开合成制度完成向量化、重排和两次真实回答，其中一次在浏览器打开来源引用；没有发送真实学校材料，不能据此认定真实制度供给或广泛回答质量已验收。

## 演示与正式业务的区别

- 演示模式继续使用本地演示数据；真实模式的校级通知、督办、课程/考试、主题党日报名和积分使用新增后端表及接口，失败不回退演示结果。扫码和外部身份认证未作为本轮新增能力。
- 演示会话和材料模板为固定本地内容，不是真实模型推理，不构造政策引用。真实问答通过后端知识库与模型完成。
- 选优和民主评议的名单、程序及等次由组织人员填写，经另一人审核；上级报送保存真实批复事实。这些记录不自动推进党员阶段，不代替实际组织程序。
- 会议和学习纪要接通原文定位、实名出勤、独立审核、学校电子效力门禁及单独归档，不能以“审核通过”推断已归档。
- 备份恢复按真实任务执行；隔离恢复通过后仍须单独配置运行账号权限，不自动切换当前服务或删除数据。
- 本地生成的 CSV / TXT 标为演示或普通工作记录，不提供正式签章和归档效力。

## 部署与后续联调

开发时由 Vite 的 `/api` 代理连接 `VITE_API_TARGET`，保留原始 URL。静态构建不包含这个代理。实际部署需由原项目网关或 Nginx 将 `/api/v1` 转发至 FastAPI，并配置正式认证、HTTPS、组织和租户数据。

本轮使用独立合成库和有明确归属的账号验证各角色表单、权限边界、版本冲突、审核与归档，以及限定范围的真实模型引用和真实隔离恢复。没有访问生产业务库、修改正式账号或发布。真实学校数据对账、模型质量样本集、生产权限、容灾切换和发布验收仍需各自完成。
