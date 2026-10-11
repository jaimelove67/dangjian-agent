# 部署入口

更新日期：2026-10-11。当前仓库提供开发和生产后端 Compose，包含 PostgreSQL、Redis、FastAPI；正式前端须另行构建和托管。

- [Docker 部署与运维](docker/README.md)：配置、启动、迁移、端口和备份。
- [本地运行指南](../docs/RUNNING.md)：宿主机正式前后端启动。
- [迁移指南](../migrations/README.md)：`001 → 002 → 003 → 004 → 005 → 006 → 007_assessment`。
- [镜像源排障](docker/MIRROR_GUIDE.md)：镜像检查与离线分发。
- [项目状态](../docs/STATUS.md)及[测试指南](../docs/TESTING.md)：范围与验证限制。

开发数据库/Redis 默认仅监听本机 `55432`/`56379`。生产 Compose 当前发布宿主 `5432`/`6379`/`8000`，需按部署环境收紧数据库和 Redis 访问、配置密钥及明确的前端来源。

迁移头为 `012_member_self`。生产容器构建、部署、备份恢复和真实学校验收仍待验证；本次文档更新未部署或迁移业务库。
