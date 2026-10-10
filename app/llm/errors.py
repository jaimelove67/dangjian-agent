"""模型依赖故障，与无依据拒答分开处理。"""


class ModelUnavailableError(RuntimeError):
    """配置缺失、超时或提供商故障，不应包装成 HTTP 200 的业务答案。"""
