"""LLM 模型接入模块

提供统一的模型调用接口，支持：
- 模型注册表机制
- 模型路由（按数据级别和任务类型）
- 出网闸门（敏感数据拦截）
- 多供应商接入
"""

from app.llm.router import ModelRouter, get_model_router
from app.llm.registry import ModelRegistry, get_model_registry
from app.llm.gateway import DataLevelGateway, get_gateway
from app.llm.base import BaseModelProvider, ModelConfig

__all__ = [
    "ModelRouter",
    "get_model_router",
    "ModelRegistry",
    "get_model_registry",
    "DataLevelGateway",
    "get_gateway",
    "BaseModelProvider",
    "ModelConfig",
]
