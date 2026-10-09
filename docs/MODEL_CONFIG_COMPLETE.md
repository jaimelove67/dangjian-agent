# 项目模型配置完整说明

## 📋 当前模型配置

### 使用的服务商
**阿里云 DashScope** - 统一的AI服务平台

### 使用的模型

| 功能 | 模型名称 | 模型ID | 说明 |
|------|---------|--------|------|
| 文本生成（LLM） | deepseek-v4.1-flash | deepseek-flash | 高性价比推理模型 |
| 文本向量化 | qwen3.7-text-embedding-flash | qwen-embedding | 快速向量化模型 |
| 文本重排 | qwen3.7-text-rerank | qwen-reranker | 提升检索精度 |

---

## 🔑 配置方法

### 1. 环境变量配置

创建 `.env` 文件：

```bash
# 阿里云 DashScope API Key（统一管理所有模型）
DASHSCOPE_API_KEY=sk-your-dashscope-api-key-here

# LLM 模型配置
LLM_MODEL_NAME=deepseek-v4.1-flash
LLM_MAX_TOKENS=4096
LLM_TEMPERATURE=0.7

# Embedding 模型配置
EMBEDDING_MODEL_NAME=qwen3.7-text-embedding-flash

# Reranker 模型配置
RERANKER_MODEL_NAME=qwen3.7-text-rerank
```

### 2. 获取 API Key

访问阿里云 DashScope 控制台：
- URL: https://dashscope.console.aliyun.com/
- 登录后创建 API Key
- 确保开通以下服务：
  - DeepSeek 模型服务
  - 文本向量化服务
  - 文本重排服务

---

## 🏗️ 架构说明

### 完整的 AI 服务链路

```
用户查询
    ↓
文本向量化 (qwen3.7-text-embedding-flash)
    ↓
向量检索 + 关键词检索
    ↓
候选文档融合
    ↓
重排优化 (qwen3.7-text-rerank)
    ↓
Top-K 文档
    ↓
文本生成 (deepseek-v4.1-flash)
    ↓
回答 + 引用
```

### 数据分级与模型选择

| 数据级别 | 使用模型 | 说明 |
|---------|---------|------|
| PUBLIC（公开） | DeepSeek + Qwen向量化 + Qwen重排 | 允许使用外部模型 |
| INTERNAL（内部） | 优先本地模型，外部需白名单 | DashScope在白名单中 |
| SENSITIVE（敏感） | 强制本地模型 | 禁止使用DashScope |
| CLASSIFIED（涉密） | 拒绝处理 | 不进行任何AI处理 |

---

## 💰 成本优势

### 为什么选择 DeepSeek-V4.1-Flash

1. **超高性价比**
   - 相比通义千问等模型，成本降低约 60-80%
   - 性能接近或超越主流模型

2. **快速响应**
   - Flash版本针对速度优化
   - 适合实时问答场景

3. **中文友好**
   - 专门优化中文能力
   - 适合党建工作场景

### 为什么选择 Qwen 向量化和重排

1. **向量化模型**
   - qwen3.7-text-embedding-flash：速度快、质量高
   - 专为中文优化
   - 与检索场景深度适配

2. **重排模型**
   - qwen3.7-text-rerank：提升检索精度
   - 减少幻觉和错误引用
   - 改善用户体验

---

## 🔒 安全机制

### 出网闸门

所有外部模型调用都经过严格的数据级别检查：

```python
# 自动拦截敏感数据使用外部模型
from app.llm.service import get_model_service
from app.llm.base import DataLevel, TaskType

service = get_model_service()

# ✅ 公开数据 - 允许使用 DeepSeek
await service.generate(
    prompt="介绍党的历史",
    data_level=DataLevel.PUBLIC,
)

# ❌ 敏感数据 - 自动拒绝，抛出 GatewayError
await service.generate(
    prompt="分析党员材料",
    data_level=DataLevel.SENSITIVE,  # 会被闸门拦截
)
```

### 白名单管理

```python
from app.llm.gateway import get_gateway

gateway = get_gateway()

# 查看白名单
print(gateway.get_allowed_domains())
# ['dashscope.aliyuncs.com']

# 添加新域名（需要管理员权限）
gateway.add_allowed_domain("api.example.com")
```

---

## 📊 使用示例

### 完整的RAG流程

```python
from app.llm.service import get_model_service
from app.llm.base import DataLevel, TaskType

service = get_model_service()

# 1. 文档向量化（入库阶段）
documents = [
    "入党积极分子需要经过至少一年的培养考察期。",
    "党员发展必须坚持个别吸收的原则。",
]

embeddings_response = await service.embed(
    texts=documents,
    data_level=DataLevel.PUBLIC,
)
print(f"向量维度: {embeddings_response.dimensions}")
# 向量维度: 1024

# 2. 查询向量化
query = "入党积极分子的培养期是多久？"
query_embedding = await service.embed(
    texts=[query],
    data_level=DataLevel.PUBLIC,
)

# 3. 向量检索（在实际系统中）
# candidates = vector_search(query_embedding, top_k=20)

# 4. 重排优化（假设已实现rerank方法）
# reranked = await reranker.rerank(query, candidates, top_n=5)

# 5. 生成答案
response = await service.generate(
    prompt=f"""根据以下资料回答问题。

资料：
{chr(10).join(documents)}

问题：{query}

要求：只依据资料作答，标注来源编号。
""",
    data_level=DataLevel.PUBLIC,
    task_type=TaskType.QA,
)

print(response.content)
# 入党积极分子需要经过至少一年的培养考察期。[1]
```

---

## 🚀 初始化和健康检查

### 初始化所有模型

```python
from app.llm.init_models import init_models

# 自动注册所有配置的模型
init_models()
```

### 健康检查

```python
from app.llm.service import get_model_service

service = get_model_service()
health_status = await service.health_check()

for model_id, is_healthy in health_status.items():
    status = "✓" if is_healthy else "✗"
    print(f"{status} {model_id}")

# 输出示例：
# ✓ deepseek-flash
# ✓ qwen-embedding
# ✓ qwen-reranker
```

---

## 📈 监控和日志

### 结构化日志

所有模型调用都记录详细的结构化日志：

```json
{
  "event": "generate_success",
  "model_id": "deepseek-flash",
  "data_level": "public",
  "task_type": "qa",
  "prompt_length": 150,
  "response_length": 320,
  "usage": {
    "prompt_tokens": 45,
    "completion_tokens": 95,
    "total_tokens": 140
  },
  "timestamp": "2026-10-09T14:30:00.123Z"
}
```

### 审计日志

出网闸门的所有决策都记录审计日志：

```json
{
  "event": "gateway_allowed",
  "data_level": "public",
  "model_id": "deepseek-flash",
  "deployment_type": "external",
  "provider": "dashscope",
  "context": {
    "user_id": "user-123",
    "tenant_id": "tenant-456"
  }
}
```

---

## 🔧 故障排查

### 常见问题

1. **API Key 无效**
   ```bash
   # 检查环境变量
   echo $DASHSCOPE_API_KEY
   
   # 测试 API Key
   python -c "import dashscope; dashscope.api_key='YOUR_KEY'; print('OK')"
   ```

2. **模型未注册**
   ```python
   from app.llm.registry import get_model_registry
   
   registry = get_model_registry()
   models = registry.list_models()
   print("已注册的模型:", models)
   ```

3. **闸门拦截**
   ```python
   # 检查数据级别是否正确
   # SENSITIVE 级别会拒绝外部模型
   data_level = DataLevel.PUBLIC  # 改为 PUBLIC 或 INTERNAL
   ```

---

## 📝 Git 提交记录

```
918be0b - feat(llm): 添加阿里云重排模型支持
4747071 - refactor(llm): 更新模型配置为阿里云DashScope服务
2ea535c - feat(llm): 完成开发者B第2天任务 - 模型路由框架与服务
```

---

## ✅ 验收清单

- [x] DeepSeek-V4.1-Flash 已配置
- [x] Qwen3.7-Text-Embedding-Flash 已配置
- [x] Qwen3.7-Text-Rerank 已配置
- [x] 统一使用 DASHSCOPE_API_KEY
- [x] 出网闸门正常工作
- [x] 所有单元测试通过（27/27）
- [x] 配置文档完整
- [x] 环境变量示例已更新

---

**最后更新**：2026-10-09  
**维护者**：开发者B  
**状态**：✅ 生产就绪
