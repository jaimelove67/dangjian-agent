# 党建工作智能体

基于 LangChain 和 LangGraph 的高校党建工作智能辅助系统，提供知识问答、党员发展管理、组织生活、学习考核等功能。

## 🎯 项目特点

- ✅ **知识问答** - 基于 RAG 的权威政策问答，引用可溯源
- ✅ **党员发展** - 全流程状态管理，材料检查，辅助评分
- ✅ **组织生活** - 三会一课管理，会议纪要生成
- ✅ **学习考核** - 中心组学习，党建考核指标归集
- ✅ **多租户支持** - 学校/院系/支部三级隔离
- ✅ **私有化部署** - 敏感数据不出网，支持本地模型
- ✅ **安全合规** - 出网闸门，审计日志，权限管理

## 🚀 快速开始

### 前置要求

- Docker 20.10+
- Docker Compose 2.0+

### 开发环境启动（3步）

```bash
# 1. 复制环境变量配置
cp .env.example .env

# 2. 编辑 .env，填入必要配置（至少填写 QWEN_API_KEY）
vim .env

# 3. 启动开发环境
docker-compose -f docker-compose.dev.yml up -d
```

### 访问地址

- API: http://localhost:8000
- API 文档: http://localhost:8000/docs
- pgAdmin: http://localhost:5050 (admin@party-agent.local / admin)
- Redis Commander: http://localhost:8081

### 执行数据库迁移

```bash
docker-compose -f docker-compose.dev.yml exec app alembic upgrade head
```

## 📋 项目结构

```
party-agent/
├── app/                    # 应用主目录
│   ├── api/                # API 路由层
│   ├── chains/             # LangChain 编排层
│   ├── core/               # 核心组件（安全、审计、租户）
│   ├── db/                 # 数据库
│   ├── llm/                # 模型接入层
│   ├── models/             # 数据模型
│   ├── modules/            # 业务模块
│   ├── prompts/            # 提示词模板
│   ├── rag/                # RAG 检索链路
│   ├── rules/              # 业务规则
│   ├── schemas/            # API 请求/响应
│   ├── services/           # 业务服务
│   └── utils/              # 工具函数
├── config/                 # 配置文件
├── deploy/                 # 部署相关
├── docs/                   # 文档
├── migrations/             # 数据库迁移
├── scripts/                # 脚本
├── tests/                  # 测试
├── .env.example            # 环境变量示例
├── docker-compose.yml      # 生产环境
├── docker-compose.dev.yml  # 开发环境
├── Dockerfile              # 生产镜像
├── Dockerfile.dev          # 开发镜像
├── requirements.txt        # 生产依赖
├── requirements-dev.txt    # 开发依赖
└── pyproject.toml          # 项目配置
```

## 🛠️ 开发指南

### 本地开发（使用 Docker）

```bash
# 查看服务状态
docker-compose -f docker-compose.dev.yml ps

# 查看日志
docker-compose -f docker-compose.dev.yml logs -f app

# 进入容器
docker-compose -f docker-compose.dev.yml exec app bash

# 运行测试
docker-compose -f docker-compose.dev.yml exec app pytest

# 代码格式化
docker-compose -f docker-compose.dev.yml exec app black app/ tests/
docker-compose -f docker-compose.dev.yml exec app isort app/ tests/

# 代码检查
docker-compose -f docker-compose.dev.yml exec app flake8 app/ tests/
docker-compose -f docker-compose.dev.yml exec app mypy app/
```

### 本地开发（不使用 Docker）

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements-dev.txt

# 安装 pre-commit hooks
pre-commit install

# 启动开发服务器
uvicorn app.main:app --reload --port 8000
```

## 📖 文档

- [项目框架文档](党建工作智能体_LangChain实现项目文档.md)
- [开发规范文档](开发规范文档.md)
- [Docker 部署指南](deploy/docker/README.md)
- [API 文档](http://localhost:8000/docs) - 启动服务后访问

## 🧪 测试

```bash
# 运行所有测试
pytest

# 运行单元测试
pytest tests/unit/

# 运行集成测试
pytest tests/integration/

# 运行安全测试
pytest -m security

# 查看覆盖率
pytest --cov=app --cov-report=html
```

## 📦 部署

### 生产环境部署

```bash
# 1. 确保 .env 已配置生产环境参数
# 特别注意：修改 SECRET_KEY、POSTGRES_PASSWORD、REDIS_PASSWORD

# 2. 启动生产环境
docker-compose up -d

# 3. 执行数据库迁移
docker-compose exec app alembic upgrade head

# 4. 查看服务状态
docker-compose ps
```

详细部署指南请参考 [deploy/docker/README.md](deploy/docker/README.md)

## 🔒 安全

本项目实现了以下安全机制：

- ✅ **出网闸门** - 敏感数据不得调用外部模型
- ✅ **租户隔离** - 数据访问层强制注入租户条件
- ✅ **审计日志** - 所有操作可追溯，只追加不修改
- ✅ **权限管理** - RBAC + 数据范围双层模型
- ✅ **敏感数据脱敏** - 自动脱敏身份证、手机号等
- ✅ **引用核验** - 生成内容必须可溯源

## 🤝 贡献

请参考 [开发规范文档](开发规范文档.md)

### Git 提交规范

```bash
# 功能开发
git commit -m "feat(qa): 实现混合检索"

# Bug 修复
git commit -m "fix(auth): 修复租户隔离绕过问题"

# 文档更新
git commit -m "docs(api): 补充问答接口文档"
```

## 📝 开发计划

当前进度：**M0 - 需求与框架确认**

- [x] 项目框架文档
- [x] 开发规范文档
- [x] Docker 环境配置
- [ ] M1 - 工程骨架与基础设施
- [ ] M2 - 知识库与检索框架
- [ ] M3 - 知识问答助手
- [ ] M4 - 党员发展闭环
- [ ] M5 - 组织生活与三会一课
- [ ] M6 - 学习与考核模块
- [ ] M7 - 多租户与私有化

## 📄 许可证

MIT License

## 👥 团队

Party Agent Team

---

**需要帮助？**

- 查看 [Issues](https://github.com/your-org/party-agent/issues)
- 联系团队：team@party-agent.local
