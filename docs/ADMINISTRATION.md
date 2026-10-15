# 管理与党员自助指南

更新日期：2026-10-15。依据本次与主分支的文档合并结果；操作前按[运行指南](RUNNING.md)准备环境并迁移至 `013_notification_delivery`。涉及迁移的部署需先执行 `alembic upgrade head`。

## 主分支当前管理入口

| 页面 | 当前功能 | 权限及边界 |
| --- | --- | --- |
| `/accounts` | 创建本租户登录账号 | 直接限定 `system_admin`；需要有效组织 |
| `/governance` | 租户、组织、账号、配置、审核和运维治理 | 按治理权限及实际数据范围限制；实现和验收见模块6交付 |
| `/system` | 运行和就绪详情 | 仅 `system_admin`；就绪不代表真实学校验收 |
| `/my-archive`、`/my-materials`、`/ask`、`/knowledge` | 普通党员与申请人的本人档案、个人材料、制度问答与只读制度目录 | 本人档案需明确账号关联；私有原件不进入知识库/模型；知识库维护操作需 `knowledge.manage`（院系管理员及以上） |

公开探针只返回整体状态，详细信息由平台管理员请求 `/api/v1/admin/health` 和 `/api/v1/admin/health/ready`。校级、院系管理权限不等于平台系统详情访问权。默认登录入口仍为 `/ask`。

## 账号创建

已有平台管理员从“系统→创建账号”开户。学校/院系管理员分别绑定学校/院系；支部书记、组织员、普通党员及申请人绑定支部。用户名全局唯一，重复返回冲突；密码至少8字符且不超过72个UTF-8字节，创建结果不返回密码明文。普通党员开户后还需组织人员关联本人档案。

开户接口为 `POST /api/v1/admin/users`，组织选项为 `GET /api/v1/admin/org-units`。该接口只注册一次：同一方法+路径出现两个处理函数时，后注册的那个会被静默遮蔽，权限判定随注册顺序变化。治理模块的“组织与账号”页对学校/院系管理员只提供组织维护与既有账号维护，新增账号与登记租户在服务端仅限平台系统管理员，界面同样不对其他角色显示这两个入口。本指南不提供默认管理员密码，也不以删表脚本处理初始化问题。

## 对外通知渠道

站内提醒与外部通知共用同一条“事件→渠道”链路，已登记事件为 `member_reminder`、`assessment_reminder`、`member_stage_transition`、`meeting_archived`、`assessment_completed`、`channel_self_test`。渠道实现只需登记即可接入；出厂登记的站内渠道 `inapp` 把投递记录直接作为用户可见提醒，不产生任何外部调用。

系统默认**不投递任何消息**：`NOTIFICATION_ROUTES` 为空即不外发；按事件配置渠道后才投递，例如：

```bash
NOTIFICATION_ROUTES={"member_stage_transition": ["inapp"]}
```

单渠道投递失败最多重试 `NOTIFICATION_MAX_ATTEMPTS` 次（默认 3），退避基数为 `NOTIFICATION_BACKOFF_SECONDS`（默认 2 秒，设 0 表示不等待）。同一 `(租户, 去重键, 渠道)` 只投递一次：补偿扫描与重复请求命中台账去重，不重复外发、也不重复写审计；重试用尽后保留失败分类（如 `delivery_failed:TimeoutError`），不记录渠道异常原文、凭据或正文。

治理页「运行审计」展示渠道清单（含“未配置（不投递）”状态）、事件路由与投递台账；具备 `config.manage` 的角色可“发起渠道自检”，确认动作与投递结果都进审计。接口为 `GET /api/v1/admin/notification-channels`、`GET /api/v1/admin/notification-deliveries` 与 `POST /api/v1/admin/notifications/dispatch`（后者需 `config.manage`）。企业微信、邮件等外部渠道尚未实现：凭据与主机补齐后按同一渠道协议登记即可接入，未配置的渠道不参与投递。注意：目前只有“发起渠道自检”与显式调用会经 `dispatch()` 投递，党员发展、考核等业务流仍各写自己的站内提醒台账、尚未接线；接线前需先确定“站内提醒与投递台账不重复生成”的口径。

## 本人档案与私有材料

1. 组织人员在授权名册中选择正确台账，明确关联同组织的有效党员**或申请人**账号，不按姓名推断，也不覆盖其他账号既有关系。
2. 党员与申请人使用 `/my-archive` 只读本人档案；未关联时联系组织人员。
3. 通过 `/my-materials` 填写标题、类型和说明并上传原件。支持PDF、DOCX、TXT、MD、PNG、JPG/JPEG，默认上限10MB，由 `MAX_UPLOAD_SIZE` 配置。稳定重试编号防止同一提交重复保存。
4. 本人读取/下载自己提交的材料，组织人员按授权档案查询；提交不自动等于组织核验通过或阶段变更。

私有材料与组织材料共用主分支既有数据模型，具体迁移以 `012_member_self_service.py` 为准。知识原文件和个人材料原件是不同访问路径，不以材料下载权限放行制度文件或其他人的原件。备份须覆盖私有材料字段与实际文件存储；生产存储及验收见[模块6交付](MODULE6_DELIVERY_2026-10-11.md)。

## 本地待合入的工作台扩展

文档源分支基于另一套本地代码记录了 `/admin` 默认首页、独立 `/organizations` 与 `/audit`、账号启停/密码重置和持久 `auth_version`。这些扩展代码尚未合入当前主分支，不作为可用页面或接口操作步骤。主分支已有治理管理能力，不能将其与待合入页面混淆。

该本地迁移链 `008_member_self → 009_admin_workspace` 与主分支 `008_org_life_tasks → 009_member_workflow → 010_security_governance → 011_governance_timestamps → 012_member_self` 不同。未来合入扩展须重新设计兼容迁移，不能直接替换主分支版本或对业务库执行旧分支脚本。

本地工作台XML中179项隔离回归通过，另有30项PostgreSQL准备错误，均只适用于被测本地扩展。文档合并没有将扩展代码或其测试带入主分支。当前开户回归、主分支治理交付及学校验收限制见[测试指南](TESTING.md)和[项目状态](STATUS.md)。
