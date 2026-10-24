"""模型路由配置文件

定义数据级别和任务类型到模型的映射关系。
使用阿里云DashScope服务（DeepSeek和Qwen向量化）。
"""

# 模型路由配置
# 格式: (数据级别, 任务类型) -> 模型ID

ROUTING_RULES = {
    # ==================== 公开数据 ====================
    # 公开数据使用DeepSeek（通过阿里云DashScope）
    ("public", "qa"): "deepseek-flash",
    ("public", "summarize"): "deepseek-flash",
    ("public", "extract"): "deepseek-flash",
    ("public", "rewrite"): "deepseek-flash",

    # ==================== 内部数据 ====================
    # 内部数据优先本地模型（如果有）
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
        "model_id": "deepseek-flash",
        "model_name": "deepseek-v4.1-flash",
        "model_type": "llm",
        "deployment_type": "external",
        "provider": "dashscope",
        "api_key_env": "DASHSCOPE_API_KEY",
        "max_tokens": 4096,
        "temperature": 0.7,
        "description": "DeepSeek V4.1 Flash - 高性价比推理模型",
    },
    {
        "model_id": "qwen-embedding",
        "model_name": "qwen3.7-text-embedding-flash",
        "model_type": "embedding",
        "deployment_type": "external",
        "provider": "dashscope",
        "api_key_env": "DASHSCOPE_API_KEY",
        "description": "Qwen 3.7 Text Embedding Flash - 快速向量化模型",
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
        "description": "本地部署的大语言模型（用于敏感数据）",
    },
    {
        "model_id": "qwen-reranker",
        "model_name": "qwen3.7-text-rerank",
        "model_type": "reranker",
        "deployment_type": "external",
        "provider": "dashscope",
        "api_key_env": "DASHSCOPE_API_KEY",
        "description": "Qwen 3.7 Text Rerank - 文本重排模型",
    },
]

# 出网闸门配置
GATEWAY_CONFIG = {
    "enabled": True,
    "allowed_external_domains": [
        "dashscope.aliyuncs.com",  # 阿里云DashScope
    ],
}
