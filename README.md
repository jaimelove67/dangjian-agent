# 党建工作智能体

基于 LangChain、LangGraph 与 FastAPI 的高校党建工作辅助系统，正式前端使用 Vue 3 和 TypeScript。

更新日期：2026-10-11，依据主分支合并结果。当前版本提供知识库与软删除、引用问答与持久历史、鉴权与系统管理员开户、真实名册与人工登记、党员发展完整流程、党员本人档案查询和私有材料提交、组织生活、中心组年度学习及纪要审核归档，以及年度考核指标、任务、佐证归集、人工计划、站内提醒和目录导出。党员端仅保留本人档案、个人材料、制度问答；现有档案需由组织人员关联登录账号。系统详情仅平台管理员可查看；真实学校指标、电子记录效力与用户验收仍待进行。实现与验证边界见[项目状态](docs/STATUS.md)和[测试指南](docs/TESTING.md)。

## 使用入口

| 目标 | 文档 |
| --- | --- |
| 安装、配置、启动前后端 | [运行指南](docs/RUNNING.md) |
| 管理与党员自助的使用边界 | [使用指南](docs/ADMINISTRATION.md) |
| 查看已实现功能与待办 | [项目状态](docs/STATUS.md) |
| 运行测试、生成覆盖率与业务评测 | [测试指南](docs/TESTING.md) |
| 查找规范、设计、部署及历史报告 | [文档导航](docs/README.md) |

本地环境准备好后，Windows 使用 `scripts/start-all.bat`，Linux/macOS 使用 `bash scripts/start-all.sh`。正式前端默认地址为 `http://127.0.0.1:5666`，后端默认 `http://127.0.0.1:8000`（被占用时按 `.env` 的 `APP_PORT` 启动，并给前端设置同值的 `VITE_API_TARGET`）；通过 `/api/v1/health/ready` 检查就绪状态。具体前置条件与迁移方式见运行指南。

## 项目结构

```text
app/           后端应用：API、模型接入、知识检索、规则与服务
frontend/      正式业务前端
frontend-test/ 旧登录联调辅助工程
config/        模型路由、业务规则、检索策略及学习模板
migrations/    数据库迁移
tests/         单元、集成、安全测试与评测样本
scripts/       启动、安装与辅助检查
deploy/        容器部署与运维说明
docs/          日常指南、设计资料与历史归档
```

模型配置见 [`.env.example`](.env.example)。角色与资料范围决定访问权限，问题及文档的实际等级决定模型调用边界；敏感及涉密内容禁止发送到云端。业务结论与党员发展操作需要人工审核。

## 开发与部署

- [项目框架](党建工作智能体_LangChain实现项目文档.md)定义完整目标；当前进度以项目状态为准。
- [开发规范](开发规范文档.md)规定代码、接口、安全、测试与 Git 提交要求。
- [正式前端说明](frontend/README.md)记录前端结构与设计约定。
- [迁移指南](migrations/README.md)记录当前迁移头 `012_member_self` 与已有数据库接管。
- [Docker 指南](deploy/docker/README.md)包含容器部署与运维；镜像问题见[镜像源排障](deploy/docker/MIRROR_GUIDE.md)。

历史日报、PR 审查、完成与联调报告集中在[归档索引](docs/archive/README.md)。更新现有指南即可；测试日志与覆盖率统一写入 `tmp/test-results/`。

许可证：MIT。
