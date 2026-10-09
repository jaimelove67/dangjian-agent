# 模型配置更新说明

## 更新时间
2026-10-09

## 变更概述
将项目的模型供应商统一调整为阿里云DashScope服务，使用以下模型：
- **LLM模型**：DeepSeek-V4.1-Flash
- **向量化模型**：Qwen3.7-Text-Embedding-Flash

---

## 主要变更

### 1. 配置文件更新

#### `app/core/config.py`
- 移除：`QWEN_API_KEY`、`EMBEDDING_MODEL_PATH`
- 新增：
  - `DASHSCOPE_API_KEY`：阿里云DashScope统一API Key
  - `LLM_MODEL_NAME`：LLM模型名称（默认：deepseek-v4.1-flash）
  - `LLM_MAX_TOKENS`：最大token数（默认：4096）
  - `LLM_TEMPERATURE`：温度参数（默认：0.7）
  - `EMBEDDING_MODEL_NAME`：向量化模型名称（默认：qwen3.7-text-embedding-flash）

### 2. 模型提供者更新

#### `app/llm/providers/qwen.py`
- 类名更新：`QwenProvider` → `DashScopeProvider`
- 支持DeepSeek和通义千问等所有DashScope模型
- 保留`QwenProvider`作为兼容性别名

#### `app/llm/providers/dashscope_embedding.py`（新增）
- 实现阿里云向量化服务
- 支持Qwen3.7-Text-Embedding-Flash等向量化模型
- 完整的异常处理和日志记录

### 3. 模型初始化更新

#### `app/llm/init_models.py`
- 使用DeepSeek-V4.1-Flash作为默认LLM
- 使用Qwen3.7-Text-Embedding-Flash作为向量化模型
- 两个模型共用同一个`DASHSCOPE_API_KEY`

### 4. 路由配置更新

#### `config/model_routing.py`
- 公开数据路由到`deepseek-flash`
- 更新模型列表和描述

### 5. 环境变量更新

#### `.env.example`
- 使用`DASHSCOPE_API_KEY`替代`QWEN_API_KEY`
- 新增LLM和Embedding模型配置项

---

## 使用的模型

### DeepSeek-V4.1-Flash
- **用途**：文本生成（问答、摘要、信息抽取等）
- **特点**：高性价比、快速推理
- **数据级别**：适用于公开和内部数据
- **调用方式**：通过阿里云DashScope API

### Qwen3.7-Text-Embedding-Flash
- **用途**：文本向量化
- **特点**：快速、高质量的中文向量化
- **数据级别**：适用于所有级别数据
- **调用方式**：通过阿里云DashScope TextEmbedding API

---

## 安全机制

所有通过阿里云DashScope的调用均受出网闸门保护：

1. **公开数据（PUBLIC）**：允许使用DashScope模型
2. **内部数据（INTERNAL）**：DashScope在白名单中可使用
3. **敏感数据（SENSITIVE）**：强制使用本地模型，禁止DashScope
4. **涉密数据（CLASSIFIED）**：禁止任何AI处理

白名单配置：
```python
gateway.add_allowed_domain("dashscope.aliyuncs.com")
```

---

## 配置方法

### 1. 设置环境变量

```bash
# .env 文件
DASHSCOPE_API_KEY=sk-your-dashscope-api-key-here
LLM_MODEL_NAME=deepseek-v4.1-flash
EMBEDDING_MODEL_NAME=qwen3.7-text-embedding-flash
```

### 2. 初始化模型

```python
from app.llm.init_models import init_models

# 自动注册DeepSeek和Qwen向量化模型
init_models()
```

### 3. 使用模型服务

```python
from app.llm.service import get_model_service
from app.llm.base import DataLevel, TaskType

service = get_model_service()

# 文本生成（自动使用DeepSeek）
response = await service.generate(
    prompt="介绍中国共产党的历史",
    data_level=DataLevel.PUBLIC,
    task_type=TaskType.QA,
)

# 文本向量化（自动使用Qwen向量化）
response = await service.embed(
    texts=["文本1", "文本2"],
    data_level=DataLevel.PUBLIC,
)
```

---

## 兼容性

### 代码兼容性
- 保留了`QwenProvider`和`create_qwen_provider`别名
- 现有调用代码无需修改

### 配置兼容性
- 旧的`QWEN_API_KEY`配置不再生效
- 需要迁移到`DASHSCOPE_API_KEY`

---

## 成本优势

使用DeepSeek-V4.1-Flash的优势：
1. **更低的API调用成本**
2. **更快的响应速度**
3. **相当的模型能力**
4. **统一的API管理**（通过DashScope）

---

## 测试状态

- ✅ 单元测试全部通过（27/27）
- ✅ 模型路由正常工作
- ✅ 出网闸门验证通过
- ✅ 向量化服务可用

---

## 迁移步骤

如果从旧配置迁移，按以下步骤操作：

1. **更新环境变量**
   ```bash
   # 旧配置（删除）
   QWEN_API_KEY=sk-xxx
   
   # 新配置（添加）
   DASHSCOPE_API_KEY=sk-xxx
   LLM_MODEL_NAME=deepseek-v4.1-flash
   EMBEDDING_MODEL_NAME=qwen3.7-text-embedding-flash
   ```

2. **拉取最新代码**
   ```bash
   git pull origin master
   ```

3. **重新初始化模型**
   ```python
   from app.llm.init_models import init_models
   init_models()
   ```

4. **验证模型状态**
   ```python
   from app.llm.service import get_model_service
   service = get_model_service()
   results = await service.health_check()
   print(results)
   ```

---

## API Key获取

阿里云DashScope API Key获取方式：
1. 访问：https://dashscope.console.aliyun.com/
2. 登录阿里云账号
3. 创建API Key
4. 确保开通以下服务：
   - DeepSeek模型服务
   - 文本向量化服务

---

## 注意事项

1. **API Key安全**
   - 不要将API Key提交到代码仓库
   - 使用环境变量或密钥管理系统
   - 定期轮换API Key

2. **成本控制**
   - 监控API调用量
   - 设置合理的并发限制
   - 对于高频调用考虑缓存策略

3. **降级方案**
   - 敏感数据已配置为强制使用本地模型
   - 确保本地模型部署可用作为后备

---

**更新完成时间**：2026-10-09  
**更新人**：开发者B  
**状态**：✅ 已完成并测试
