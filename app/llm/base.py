"""模型提供者基类和数据模型定义"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DataLevel(str, Enum):
    """数据级别枚举

    决定是否允许使用外部模型
    """

    PUBLIC = "public"  # 公开数据，可以使用外部模型
    INTERNAL = "internal"  # 内部数据，优先本地模型
    SENSITIVE = "sensitive"  # 敏感数据，强制本地模型
    CLASSIFIED = "classified"  # 涉密数据，禁止处理


class TaskType(str, Enum):
    """任务类型枚举

    不同任务可能需要不同的模型
    """

    QA = "qa"  # 知识问答
    SUMMARIZE = "summarize"  # 摘要生成
    EXTRACT = "extract"  # 信息抽取
    CLASSIFY = "classify"  # 分类
    REWRITE = "rewrite"  # 改写
    SCORING = "scoring"  # 评分
    ARCHIVE_CHECK = "archive_check"  # 档案检查


class ModelType(str, Enum):
    """模型类型"""

    LLM = "llm"  # 大语言模型
    EMBEDDING = "embedding"  # 向量化模型
    RERANKER = "reranker"  # 重排模型


class DeploymentType(str, Enum):
    """部署类型"""

    LOCAL = "local"  # 本地部署
    EXTERNAL = "external"  # 外部服务


@dataclass
class ModelConfig:
    """模型配置"""

    model_id: str  # 模型唯一标识
    model_name: str  # 模型名称
    model_type: ModelType  # 模型类型
    deployment_type: DeploymentType  # 部署类型
    provider: str  # 供应商名称
    endpoint: Optional[str] = None  # API 端点
    api_key: Optional[str] = None  # API Key
    model_path: Optional[str] = None  # 本地模型路径
    max_tokens: int = 4096  # 最大token数
    temperature: float = 0.7  # 温度参数
    extra_params: Dict[str, Any] = None  # 额外参数

    def __post_init__(self):
        if self.extra_params is None:
            self.extra_params = {}


class ModelResponse(BaseModel):
    """模型响应"""

    content: str = Field(..., description="生成的内容")
    model_id: str = Field(..., description="使用的模型ID")
    usage: Optional[Dict[str, Any]] = Field(None, description="Token用量及供应商的嵌套统计")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class EmbeddingResponse(BaseModel):
    """向量化响应"""

    embeddings: List[List[float]] = Field(..., description="向量列表")
    model_id: str = Field(..., description="使用的模型ID")
    dimensions: int = Field(..., description="向量维度")


class RerankResult(BaseModel):
    index: int
    relevance_score: float


class RerankResponse(BaseModel):
    model_id: str
    results: List[RerankResult]


class BaseModelProvider(ABC):
    """模型提供者基类

    所有模型供应商都需要实现此接口
    """

    def __init__(self, config: ModelConfig):
        """初始化模型提供者

        Args:
            config: 模型配置
        """
        self.config = config

    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> ModelResponse:
        """生成文本

        Args:
            prompt: 输入提示词
            **kwargs: 额外参数

        Returns:
            模型响应
        """
        pass

    @abstractmethod
    async def embed(self, texts: List[str], **kwargs) -> EmbeddingResponse:
        """文本向量化

        Args:
            texts: 文本列表
            **kwargs: 额外参数

        Returns:
            向量化响应
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查

        Returns:
            是否健康
        """
        pass

    def get_model_id(self) -> str:
        """获取模型ID"""
        return self.config.model_id

    def get_deployment_type(self) -> DeploymentType:
        """获取部署类型"""
        return self.config.deployment_type
