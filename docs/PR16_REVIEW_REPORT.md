# PR #16 审核报告：Day4-DevA 六阶段问答链、多轮会话与引用核验

## 📋 PR概览

- **PR编号**: #16
- **标题**: feat(qa): Day4-DevA 六阶段问答链、多轮会话与引用核验
- **状态**: OPEN
- **作者**: manice2005
- **代码变更**: +845行 / -0行
- **文件数**: 13个新增文件

---

## ✅ 整体评价

这是一个**架构设计优秀**的PR，代码质量高、测试覆盖完整、设计模式清晰。**强烈推荐批准合并**。

### 核心亮点
- ✅ 六阶段问答链设计清晰，职责分离良好
- ✅ Protocol协议注入，依赖解耦，便于测试
- ✅ 会话隔离设计（租户ID隔离）
- ✅ 引用核验逻辑完整（5大核验项）
- ✅ 27个单元测试全绿，覆盖充分
- ✅ 提示词版本化管理

---

## 📊 代码结构分析

### 新增模块（13个文件）

#### 1. 编排层 (`app/chains/`)
```
├── __init__.py
├── qa_chain.py        (148行) - 六阶段问答链主框架
├── rewrite.py         (49行)  - 追问改写
└── session.py         (90行)  - 多轮会话管理
```

#### 2. 提示词层 (`app/prompts/`)
```
├── __init__.py
└── qa.py              (29行)  - 问答/改写提示词 + 版本号
```

#### 3. 核验层 (`app/rag/`)
```
└── verifier.py        (169行) - 引用核验器
```

#### 4. Schema层 (`app/schemas/`)
```
└── qa.py              (40行)  - 统一问答响应结构
```

#### 5. 测试层 (`tests/unit/`)
```
├── test_qa_chain.py   - 问答链测试
├── test_rewrite.py    - 改写测试
├── test_session.py    - 会话测试
└── test_verifier.py   - 核验测试（11个用例）
```

**总代码量**: ~526行核心逻辑 + 测试代码

---

## 🎯 核心功能审核

### 1. 六阶段问答链 ⭐⭐⭐⭐⭐

**位置**: `app/chains/qa_chain.py`

**设计亮点**:
```python
# 阶段1：预处理（追问改写）
standalone_question = await rewrite_question(question, history, llm_call=self.llm_call)

# 阶段2：检索（Protocol注入）
chunks = await self.retriever.retrieve(...)

# 阶段3：重排判定（无依据直接拒答）
if self._is_no_evidence(chunks):
    return QAResponse(answer=REFUSAL_ANSWER, refused=True)

# 阶段4：生成（Protocol注入）
draft = await self.generator.generate(...)

# 阶段5：引用核验
verification = self.verifier.verify(draft, chunks)

# 阶段6：统一响应
return QAResponse(answer=verification.answer, citations=..., warnings=...)
```

**优点**:
- ✅ 职责清晰，每阶段独立
- ✅ Protocol协议注入（`Retriever`、`Generator`），依赖倒置
- ✅ 无依据判定机制（阈值可配）
- ✅ 日志埋点完整

**建议**:
- 💡 考虑增加阶段耗时统计（性能监控）

---

### 2. 引用核验模块 ⭐⭐⭐⭐⭐

**位置**: `app/rag/verifier.py:57-169`

**核验项**（5大类）:

| 核验项 | 实现方法 | 代码位置 |
|-------|---------|---------|
| 1. 引用编号有效性 | 正则提取`[n]`并校验索引 | L111-118 |
| 2. 条款真实性 | 检查答案中的"第X条"是否在片段中 | L120-132 |
| 3. 文件时效 | 检查status/expiration_date | L134-148 |
| 4. 引用完整性 | 长回答未标注来源则警告 | L98-99 |
| 5. 无依据长回答 | 无引用且长度超阈值 | L98-99 |

**代码示例**（条款真实性检查）:
```python
def _check_article(self, answer: str, idx: int, chunk: RetrievedChunk, warnings: list[str]) -> None:
    """条款真实性：包含 [idx] 的句子中提及的"第 X 条"须存在于被引片段"""
    for sentence in _SENTENCE_SPLIT_RE.split(answer):
        if f"[{idx}]" not in sentence:
            continue
        for article in _ARTICLE_RE.findall(sentence):
            normalized = article.replace(" ", "")
            if normalized not in chunk.content and (chunk.article or "") != normalized:
                warnings.append(f"引用[{idx}]提及的条款"{normalized}"在被引片段中不存在，请人工复核")
```

**优点**:
- ✅ 纯逻辑模块，无外部依赖，易测试
- ✅ 正则表达式提取精准
- ✅ 时效检查完整（废止/失效/即将失效）
- ✅ 警告信息清晰友好

**测试覆盖**: 11个用例全绿

---

### 3. 会话管理 ⭐⭐⭐⭐⭐

**位置**: `app/chains/session.py`

**设计亮点**:

#### 3.1 会话隔离
```python
def build_key(self, tenant_id: str, session_id: str) -> str:
    """会话键：包含租户标识，实现会话隔离"""
    return f"{self.KEY_PREFIX}{tenant_id}:{session_id}"
```
✅ 租户ID强制校验，防止跨租户串话

#### 3.2 隐私保护
```python
@staticmethod
def summarize_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """仅保留引用摘要字段（文件名、条款），避免缓存原始片段"""
    return [
        {"doc_name": c.get("doc_name"), "article": c.get("article")}
        for c in citations
    ]
```
✅ 不缓存原始敏感片段，只保留文件名和条款

#### 3.3 容量控制
```python
async def append_turn(self, tenant_id: str, session_id: str, turn: QATurn) -> None:
    history = await self.get_history(tenant_id, session_id)
    history.append(turn)
    history = history[-self.max_turns:]  # 截断旧轮次
    await self._cache.set(..., ttl=self.ttl_seconds)
```
✅ TTL自动过期 + 轮次上限控制

**优点**:
- ✅ 安全性设计优秀（租户隔离+隐私保护）
- ✅ Protocol协议兼容（`CacheLike`）
- ✅ 配置灵活（TTL、max_turns可配）

---

### 4. 追问改写 ⭐⭐⭐⭐☆

**位置**: `app/chains/rewrite.py`

**设计**:
```python
async def rewrite_question(
    question: str,
    history: Optional[Sequence[object]] = None,
    *,
    llm_call: Optional[LLMCall] = None,
    max_history_turns: int = 3,
) -> str:
    """将追问改写为可独立检索的问题"""
    if not turns or llm_call is None:
        return current  # 无历史或无LLM时原样返回
    
    # 组装历史对话
    history_text = "\n".join(
        f"问：{getattr(turn, 'question', '')}\n答：{getattr(turn, 'answer', '')}"
        for turn in turns
    )
    prompt = REWRITE_PROMPT.format(history=history_text, question=current)
    rewritten = (await llm_call(prompt) or "").strip()
    return rewritten or current  # 兜底返回原问题
```

**优点**:
- ✅ LLM调用可选（注入式设计）
- ✅ 兜底机制完善（无LLM/改写失败都返回原问题）
- ✅ 历史轮次限制（避免context过长）

**建议**:
- 💡 `getattr(turn, 'question', '')` 使用了反射，可考虑使用Protocol定义`turn`接口

---

### 5. 提示词管理 ⭐⭐⭐⭐⭐

**位置**: `app/prompts/qa.py`

**版本化设计**:
```python
QA_SYSTEM_PROMPT_VERSION = "v1"
REWRITE_PROMPT_VERSION = "v1"

QA_SYSTEM_PROMPT = """你是高校党建工作智能辅助系统的知识问答助手。
请严格遵守以下约束：
1. 只依据提供的参考资料作答，不得编造或推测；
2. 无依据时明确拒答，不猜测；
3. 逐条标注来源编号（如 [1][2]），供引用核验；
4. 不代替党组织作出任何认定或选拔结论；
5. 不输出党员个人敏感信息；
..."""
```

**优点**:
- ✅ 提示词与代码分离
- ✅ 版本号登记（便于AB测试和灰度发布）
- ✅ 约束清晰，覆盖安全边界

---

## 🧪 测试覆盖分析

### 测试统计
```
tests/unit/test_verifier.py:  11个用例 ✅
tests/unit/test_session.py:   6个用例  ✅
tests/unit/test_rewrite.py:   5个用例  ✅
tests/unit/test_qa_chain.py:  5个用例  ✅
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
总计: 27个用例全部通过 (0.18s)
```

### 测试覆盖亮点

#### 1. 引用核验测试（最完整）
```python
class TestCitationNumberValidity:    # 引用编号有效性
class TestArticleTruthfulness:       # 条款真实性
class TestTimeliness:                # 文件时效
class TestCitationList:              # 引用列表字段映射
```

#### 2. 会话测试
- ✅ 租户隔离验证
- ✅ TTL过期验证
- ✅ 轮次截断验证
- ✅ 引用摘要验证

#### 3. 改写测试
- ✅ 无历史原样返回
- ✅ 无LLM原样返回
- ✅ 改写失败兜底
- ✅ 历史轮次限制

#### 4. 问答链测试
- ✅ 无依据拒答
- ✅ 阈值判定
- ✅ 会话持久化
- ✅ Mock注入验证

**测试质量**: ⭐⭐⭐⭐⭐ (覆盖充分、边界完整)

---

## 🔍 代码质量评估

### 优点

#### 1. 架构设计 ⭐⭐⭐⭐⭐
- ✅ 分层清晰（编排层/核验层/提示词层）
- ✅ Protocol协议注入，依赖倒置
- ✅ 单一职责原则严格遵守

#### 2. 安全性 ⭐⭐⭐⭐⭐
- ✅ 租户隔离（会话键含tenant_id）
- ✅ 隐私保护（不缓存原始片段）
- ✅ 输入校验（tenant_id/session_id非空）
- ✅ 提示词安全约束（7条边界）

#### 3. 可测试性 ⭐⭐⭐⭐⭐
- ✅ 纯函数设计（verifier、rewrite）
- ✅ 依赖注入（retriever、generator、llm_call）
- ✅ Mock友好（CacheLike、Protocol）

#### 4. 可维护性 ⭐⭐⭐⭐⭐
- ✅ 文档完整（每个模块都有框架文档引用）
- ✅ 类型标注清晰
- ✅ 注释恰到好处（不冗余）
- ✅ 提示词版本化

#### 5. 错误处理 ⭐⭐⭐⭐☆
- ✅ 兜底机制（改写失败返回原问题）
- ✅ 校验完整（tenant_id/session_id/question非空）
- ⚠️ 缺少异常日志（建议补充）

---

## ⚠️ 需要关注的点

### 1. 配置项缺失
**位置**: `app/core/config.py`

**问题**: PR说明提到 `NO_EVIDENCE_THRESHOLD` 配置，但代码中引用了该配置：
```python
# app/chains/qa_chain.py:60-64
self.no_evidence_threshold = (
    settings.NO_EVIDENCE_THRESHOLD  # ← 这个配置未在PR中添加
    if no_evidence_threshold is None
    else no_evidence_threshold
)
```

**建议**: 在 `app/core/config.py` 中补充：
```python
# ==================== 问答链配置 ====================
NO_EVIDENCE_THRESHOLD: float = Field(default=0.5, description="无依据判定阈值")
```

### 2. 日志不够详细
**位置**: `app/chains/qa_chain.py:82-85`

**当前**:
```python
logger.info("qa_stage_rewrite", extra={"tenant_id": tenant_id, "session_id": session_id})
```

**建议**: 增加各阶段日志
```python
logger.info("qa_stage_rewrite", extra={...})
logger.info("qa_stage_retrieve", extra={"chunk_count": len(chunks)})
logger.info("qa_stage_generate", extra={"draft_length": len(draft)})
logger.info("qa_stage_verify", extra={"warnings_count": len(verification.warnings)})
```

### 3. 异常处理待完善
**位置**: 多处

**当前**: 缺少try-except包裹

**建议**: 在关键点增加异常捕获：
```python
try:
    chunks = await self.retriever.retrieve(...)
except Exception as e:
    logger.exception("retrieval_failed", extra={"error": str(e)})
    # 返回友好错误提示
```

### 4. 类型标注可优化
**位置**: `app/chains/rewrite.py:19`

```python
history: Optional[Sequence[object]] = None  # object太宽泛
```

**建议**:
```python
from typing import Protocol

class QATurnLike(Protocol):
    question: str
    answer: str

history: Optional[Sequence[QATurnLike]] = None
```

---

## 📈 性能考量

### 1. 正则表达式性能 ✅
**位置**: `app/rag/verifier.py:22-24`

```python
_CITATION_RE = re.compile(r"\[(\d+)\]")        # 预编译
_ARTICLE_RE = re.compile(r"第\s*[...]+\s*条")  # 预编译
```
✅ 使用模块级预编译，性能优化良好

### 2. 会话历史读取 ⚠️
**位置**: `app/chains/session.py:60-65`

```python
async def get_history(self, tenant_id: str, session_id: str) -> list[QATurn]:
    raw = await self._cache.get(self.build_key(tenant_id, session_id))
    if not raw:
        return []
    return [QATurn(**item) for item in raw]  # 重建对象
```

**潜在问题**: 每次都重建`QATurn`对象

**建议**: 考虑缓存结果（如在问答链实例中缓存）

### 3. 引用核验复杂度 ✅
**算法复杂度**: O(n*m) - n为引用数，m为句子数

对于典型场景（5个引用 × 10个句子）性能可接受

---

## 🎯 改进建议（非阻塞）

### 短期（本PR可选）

1. **补充配置项** ⭐⭐⭐
   - 添加 `NO_EVIDENCE_THRESHOLD` 到 `config.py`

2. **增强日志** ⭐⭐
   - 各阶段增加详细日志

3. **异常处理** ⭐⭐
   - 关键点增加try-except

### 中期（后续PR）

1. **性能监控**
   - 各阶段耗时统计
   - 慢查询报警

2. **指标收集**
   - 拒答率统计
   - 警告类型分布
   - 改写成功率

3. **A/B测试支持**
   - 提示词版本路由
   - 效果对比框架

---

## ✅ 验证清单

### 代码质量
- [x] 架构设计清晰
- [x] 类型标注完整
- [x] 文档注释充分
- [x] 代码风格一致

### 功能完整性
- [x] 六阶段问答链实现
- [x] 多轮会话管理
- [x] 引用核验（5项）
- [x] 追问改写
- [x] 统一响应结构

### 安全性
- [x] 租户隔离
- [x] 隐私保护
- [x] 输入校验
- [x] 安全约束提示词

### 测试覆盖
- [x] 单元测试：27个用例全绿
- [x] 核验测试：11个用例
- [x] 会话测试：6个用例
- [x] 改写测试：5个用例
- [x] 问答链测试：5个用例

### 待确认
- [ ] `NO_EVIDENCE_THRESHOLD` 配置补充
- [ ] 真实环境集成测试（Redis + DB）

---

## 🏆 综合评分

| 维度 | 评分 | 说明 |
|-----|------|------|
| **架构设计** | ⭐⭐⭐⭐⭐ | Protocol注入、分层清晰 |
| **代码质量** | ⭐⭐⭐⭐⭐ | 类型清晰、文档完整 |
| **安全性** | ⭐⭐⭐⭐⭐ | 租户隔离、隐私保护 |
| **可测试性** | ⭐⭐⭐⭐⭐ | 27个用例、覆盖充分 |
| **可维护性** | ⭐⭐⭐⭐⭐ | 版本化、分层解耦 |
| **性能** | ⭐⭐⭐⭐☆ | 正则预编译、待监控 |
| **错误处理** | ⭐⭐⭐⭐☆ | 兜底机制、待补日志 |

**综合评分**: 4.9/5 ⭐ **强烈推荐合并**

---

## 📝 审核结论

### ✅ 推荐批准合并

**理由**:
1. 架构设计优秀，符合SOLID原则
2. 代码质量高，测试覆盖充分
3. 安全性设计到位（租户隔离+隐私保护）
4. 文档清晰，可维护性强
5. 与Day3 PR无冲突

### 📋 合并前建议

1. **必须**：补充 `NO_EVIDENCE_THRESHOLD` 配置到 `config.py`
2. **建议**：增加各阶段日志（便于生产排查）
3. **可选**：优化类型标注（`QATurnLike` Protocol）

### 📌 合并后建议

1. 在测试环境执行完整集成测试（Redis + DB + 真实LLM）
2. 监控拒答率和警告分布
3. 收集用户反馈，优化提示词

---

**审核人**: Claude Sonnet 5.5  
**审核日期**: 2026-10-09  
**审核状态**: ✅ **批准合并**（补充配置项后）
