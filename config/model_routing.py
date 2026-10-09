"""模型路由配置文件

定义数据级别和任务类型到模型的映射关系。
"""

# 模型路由配置
# 格式: (数据级别, 任务类型) -> 模型ID

ROUTING_RULES = {
    # ==================== 公开数据 ====================
    # 公开数据优先使用外部模型降低成本
    ("public", "qa"): "qwen-turbo",
    ("public", "summarize"): "qwen-turbo",
    ("public", "extract"): "qwen-turbo",
    ("public", "rewrite"): "qwen-turbo",

    # ==================== 内部数据 ====================
    # 内部数据优先本地模型
    ("internal", "qa"): "local-llm",
    ("internal", "summarize"): "local-llm",
    ("internal", "extract"): "local-llm",
    ("internal", "rewrite"): "local-llm",

    # ==================== 敏感数据 ====================
    # 敏感数据强制本地模型
    ("sensitive", "qa"): "local-llm",
    ("sensitive", "summarize"): "local-llm",
    ("sensitive", "extract"): "local-llm",
    ("sensitive", "scoring"): "local-llm",
    ("sensitive", "archive_check"): "local-llm",
}

# 模型配置列表
MODELS = [
    {
        "model_id": "qwen-turbo",
        "model_name": "qwen-turbo",
        "model_type": "llm",
        "deployment_type": "external",
        "provider": "qwen",
        "api_key_env": "QWEN_API_KEY",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    {
        "model_id": "local-llm",
        "model_name": "Qwen-14B-Chat",
        "model_type": "llm",
        "deployment_type": "local",
        "provider": "local",
        "model_path": "/models/Qwen-14B-Chat",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    {
        "model_id": "bge-large-zh",
        "model_name": "bge-large-zh-v1.5",
        "model_type": "embedding",
        "deployment_type": "local",
        "provider": "sentence-transformers",
        "model_path": "/models/bge-large-zh-v1.5",
    },
    {
        "model_id": "bge-reranker",
        "model_name": "bge-reranker-large",
        "model_type": "reranker",
        "deployment_type": "local",
        "provider": "sentence-transformers",
        "model_path": "/models/bge-reranker-large",
    },
]

# 出网闸门配置
GATEWAY_CONFIG = {
    "enabled": True,
    "allowed_external_domains": [
        "dashscope.aliyuncs.com",  # 通义千问
    ],
}
