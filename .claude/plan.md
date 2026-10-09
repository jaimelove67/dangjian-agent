# 完成开发者B所有剩余任务的实现计划

## 任务概述

基于本地代码库探索，需要完成以下工作：

### 已完成但未PR（优先级🔴最高）
- **Issue #4 (Day2-DevB)**: 模型路由、出网闸门、向量化服务
  - ✅ 代码已完整实现
  - ❌ 缺少单元测试
  - ❌ 未创建PR

### 待实现（优先级🟠高）
- **Issue #6 (Day3-DevB)**: 混合检索、重排、无依据判定
- **Issue #8 (Day4-DevB)**: 问答生成、API接口、链路整合
- **Issue #10 (Day5-DevB)**: 评测、API文档、演示准备

---

## 架构分析

### 现有代码模式
1. **分层架构**：API → Service → Model
2. **依赖注入**：FastAPI Depends + Protocol抽象
3. **安全机制**：租户上下文自动注入、权限装饰器
4. **数据模型**：
   - `KnowledgeDoc`: 文档元数据
   - `EmbeddingChunk`: 切分后的片段（含向量字段）
5. **已有模型服务**：
   - `ModelRouter`: 路由模型选择
   - `DataLevelGateway`: 出网闸门
   - `ModelService`: 统一调用接口
   - Provider实现：Qwen LLM、Embedding、Reranker

### 缺失功能
1. **检索层** (`app/rag/retrieval/`):
   - 向量检索
   - 关键词检索（PostgreSQL全文检索）
   - 混合检索融合
   - 重排集成
   - 无依据判定
   
2. **问答API** (`app/api/v1/qa.py`):
   - `/api/v1/qa/ask` 接口
   - 检索→生成集成
   
3. **评测与文档**:
   - 评测样本
   - API文档增强

---

## 实现计划

### 阶段1: 补充Day2-DevB测试并创建PR ⚡

**文件**:
- `tests/unit/llm/test_model_service.py` (新增)
- `tests/integration/test_llm_integration.py` (新增)

**测试覆盖**:
- 模型服务统一接口
- 路由+闸门集成
- 向量化服务调用
- 健康检查

**PR内容**:
- 现有`app/llm/`下所有文件
- 新增测试文件
- 更新`app/main.py`中的模型初始化

---

### 阶段2: 实现检索模块 (Issue #6) 🔴

#### 2.1 向量检索模块

**文件**: `app/rag/retrieval/vector.py`

```python
class VectorRetriever:
    """向量检索器
    
    使用pgvector进行相似度检索
    """
    async def retrieve(
        query: str,
        top_k: int,
        filters: RetrievalFilters,
        embedding_provider: BaseModelProvider
    ) -> List[RetrievalResult]
```

**功能**:
- 查询向量化（使用ModelService）
- pgvector余弦相似度检索
- 租户隔离过滤
- 可见范围过滤
- 时效过滤（排除失效文件）

#### 2.2 关键词检索模块

**文件**: `app/rag/retrieval/keyword.py`

```python
class KeywordRetriever:
    """关键词检索器
    
    使用PostgreSQL全文检索（基于search_vector）
    """
    async def retrieve(
        query: str,
        top_k: int,
        filters: RetrievalFilters
    ) -> List[RetrievalResult]
```

**功能**:
- PostgreSQL `ts_rank` 排序
- 使用`KnowledgeDoc.search_vector`字段
- 同样的过滤条件

#### 2.3 混合检索融合

**文件**: `app/rag/retrieval/hybrid.py`

```python
class HybridRetriever:
    """混合检索器
    
    融合向量检索和关键词检索结果
    """
    async def retrieve(
        query: str,
        top_k: int,
        filters: RetrievalFilters
    ) -> List[RetrievalResult]
```

**融合策略**:
- RRF (Reciprocal Rank Fusion) 算法
- 可配置权重

#### 2.4 重排模块

**文件**: `app/rag/retrieval/reranker.py`

```python
class Reranker:
    """重排器
    
    使用交叉编码器对候选进行精排
    """
    async def rerank(
        query: str,
        candidates: List[RetrievalResult],
        top_k: int
    ) -> List[RetrievalResult]
```

**功能**:
- 调用`DashScopeRerankerProvider`
- 返回top_k结果

#### 2.5 无依据判定

**文件**: `app/rag/retrieval/no_evidence.py`

```python
def has_evidence(
    results: List[RetrievalResult],
    threshold: float
) -> bool:
    """判定是否有足够依据"""
```

**逻辑**:
- 检查最高分是否达到阈值
- 检查是否有结果返回

#### 2.6 统一检索服务

**文件**: `app/services/retrieval_service.py`

```python
class RetrievalService:
    """检索服务
    
    整合混合检索、重排、过滤
    """
    async def retrieve(
        query: str,
        tenant_id: str,
        data_level: DataLevel,
        top_k: int = 5
    ) -> RetrievalResponse
```

#### 2.7 Schema定义

**文件**: `app/schemas/retrieval.py`

```python
class RetrievalFilters(BaseModel):
    tenant_id: str
    data_level: DataLevel
    visibility_levels: List[str]
    exclude_expired: bool = True

class RetrievalResult(BaseModel):
    chunk_id: str
    doc_id: str
    content: str
    score: float
    article: Optional[str]
    metadata: dict

class RetrievalResponse(BaseModel):
    results: List[RetrievalResult]
    has_evidence: bool
    total_count: int
```

---

### 阶段3: 实现问答API (Issue #8) 🟠

#### 3.1 问答Schema

**文件**: `app/schemas/qa.py` (扩展现有)

```python
class QARequest(BaseModel):
    question: str
    session_id: Optional[str] = None
    context: Optional[dict] = None

class QAStreamChunk(BaseModel):
    type: str  # "text" | "citation" | "done"
    content: str
    metadata: Optional[dict] = None
```

#### 3.2 问答服务

**文件**: `app/services/qa_service.py`

```python
class QAService:
    """问答服务
    
    整合检索、生成、核验
    """
    async def answer(
        question: str,
        tenant_id: str,
        data_level: DataLevel,
        session_id: Optional[str] = None
    ) -> QAResponse
    
    async def stream_answer(
        question: str,
        tenant_id: str,
        data_level: DataLevel,
        session_id: Optional[str] = None
    ) -> AsyncIterator[QAStreamChunk]
```

**流程**:
1. 会话管理（追问改写）- 使用现有`app/chains/rewrite.py`
2. 检索（调用RetrievalService）
3. 无依据判定
4. 生成（调用ModelService）
5. 引用核验（使用现有`app/rag/verifier.py`）
6. 返回响应

#### 3.3 问答API

**文件**: `app/api/v1/qa.py`

```python
@router.post("/qa/ask")
async def ask_question(
    request: QARequest,
    user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_tenant)
) -> APIResponse[QAResponse]

@router.post("/qa/stream")
async def stream_question(
    request: QARequest,
    user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_tenant)
) -> StreamingResponse
```

**权限**: 需要`member.query`权限（普通党员及以上）

#### 3.4 集成到main.py

**更新**: `app/main.py`
```python
from app.api.v1 import qa
app.include_router(qa.router, prefix="/api/v1", tags=["知识问答"])
```

---

### 阶段4: 评测与文档 (Issue #10) 🟡

#### 4.1 评测样本

**文件**: 
- `tests/evaluation/retrieval_samples.json`
- `tests/evaluation/qa_samples.json`

**内容**:
- 检索样本：20-30条（问题+期望文档）
- 问答样本：20-30条（问题+期望答案+拒答样本）

#### 4.2 评测脚本

**文件**: `tests/evaluation/run_evaluation.py`

```python
async def evaluate_retrieval():
    """评测检索准确率"""
    # Recall@K, Precision@K, MRR
    
async def evaluate_qa():
    """评测问答质量"""
    # 答案相关性、引用准确性、拒答准确率
```

#### 4.3 API文档增强

**更新**: 
- `app/main.py` - 完善OpenAPI描述
- 各API文件的docstring

#### 4.4 演示数据

**文件**: `data/demo/`
- `sample_documents.zip` - 示例文档
- `sample_questions.json` - 示例问题

#### 4.5 开发总结

**文件**: `docs/DEV_B_WEEK_SUMMARY.md`

---

## 测试策略

### 单元测试
- 每个模块独立测试
- 使用mock避免外部依赖
- 覆盖边界情况

### 集成测试
- 端到端检索流程
- 端到端问答流程
- 权限控制验证

### 评测
- 离线评测（样本数据）
- 指标记录

---

## 文件清单

### 新增文件 (19个核心文件)

**检索层** (7个):
1. `app/rag/retrieval/__init__.py`
2. `app/rag/retrieval/vector.py`
3. `app/rag/retrieval/keyword.py`
4. `app/rag/retrieval/hybrid.py`
5. `app/rag/retrieval/reranker.py`
6. `app/rag/retrieval/no_evidence.py`
7. `app/schemas/retrieval.py`

**服务层** (2个):
8. `app/services/retrieval_service.py`
9. `app/services/qa_service.py`

**API层** (1个):
10. `app/api/v1/qa.py`

**测试** (7个):
11. `tests/unit/llm/test_model_service.py`
12. `tests/unit/rag/test_vector_retrieval.py`
13. `tests/unit/rag/test_hybrid_retrieval.py`
14. `tests/integration/test_llm_integration.py`
15. `tests/integration/test_retrieval_flow.py`
16. `tests/integration/test_qa_flow.py`
17. `tests/evaluation/run_evaluation.py`

**评测数据** (2个):
18. `tests/evaluation/retrieval_samples.json`
19. `tests/evaluation/qa_samples.json`

### 修改文件 (3个)
1. `app/main.py` - 注册qa路由、初始化模型
2. `app/schemas/qa.py` - 扩展QARequest等
3. `app/services/knowledge_service.py` - 可能需要添加向量化调用

---

## 技术依赖

### 已有依赖（可直接使用）
- ✅ pgvector (向量检索)
- ✅ PostgreSQL全文检索 (search_vector字段)
- ✅ DashScope SDK (LLM、Embedding、Reranker)
- ✅ 模型路由和闸门
- ✅ 租户隔离机制

### 可能需要新增
- `rank_bm25` (可选，如果要用BM25而非PG全文检索)

---

## 实现顺序

1. **Day2-DevB测试+PR** (2小时)
   - 补充测试
   - 创建PR #18

2. **检索模块** (4-5小时)
   - 向量检索 → 关键词检索 → 混合融合 → 重排 → 服务层
   - 单元测试 + 集成测试

3. **问答API** (3-4小时)
   - 问答服务 → API接口 → 集成测试
   - 流式响应支持

4. **评测与文档** (2-3小时)
   - 评测样本准备
   - 评测脚本
   - 文档完善

**总预计时间**: 11-14小时

---

## 风险与依赖

### 风险
1. **向量化未完成**: EmbeddingChunk.embedding字段可能为NULL
   - 缓解：检索时过滤NULL向量，或在知识入库时同步向量化
   
2. **模型API额度**: 需要DashScope API Key
   - 缓解：测试时使用mock

3. **性能问题**: 大规模数据检索可能慢
   - 缓解：添加索引、限制top_k

### 依赖关系
```
Day2-DevB (测试) ← 独立
    ↓
Day3-DevB (检索) ← 依赖模型服务
    ↓
Day4-DevB (问答) ← 依赖检索模块
    ↓
Day5-DevB (评测) ← 依赖问答API
```

---

## 成功标准

### Issue #4 (Day2-DevB)
- ✅ PR创建并合并
- ✅ 测试覆盖率 > 80%

### Issue #6 (Day3-DevB)
- ✅ 向量检索可用（返回相关片段）
- ✅ 混合检索融合实现
- ✅ 重排模型集成
- ✅ 测试通过

### Issue #8 (Day4-DevB)
- ✅ `/api/v1/qa/ask` 接口可用
- ✅ 端到端问答流程通过
- ✅ 引用核验生效
- ✅ 权限控制正确

### Issue #10 (Day5-DevB)
- ✅ 评测样本准备完成
- ✅ 评测脚本可运行
- ✅ API文档完善
- ✅ 演示数据准备

---

## 注意事项

### 代码风格
- 遵循现有架构模式（分层、依赖注入）
- 使用类型标注
- 添加docstring
- 日志记录（structlog）

### 安全性
- 所有查询必须包含租户过滤
- 数据级别由后端推导，不接受前端传入
- 敏感数据通过闸门拦截

### 性能
- 检索添加合理的top_k限制
- 使用数据库索引
- 考虑缓存（会话、配置）

### 测试
- 单元测试使用mock
- 集成测试需要真实DB/Redis
- 评测脚本可独立运行

---

**计划制定完成，等待审批后开始实施**
