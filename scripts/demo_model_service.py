"""模型服务演示脚本

演示如何使用模型服务进行文本生成和向量化。
"""

import asyncio
import os
from app.llm.service import get_model_service
from app.llm.init_models import init_models
from app.llm.base import DataLevel, TaskType
from app.llm.gateway import GatewayError
from app.llm.router import RouterError
import structlog

# 配置日志
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)

logger = structlog.get_logger(__name__)


async def demo_text_generation():
    """演示文本生成"""
    print("\n" + "="*60)
    print("演示1: 文本生成（根据数据级别自动路由）")
    print("="*60)

    service = get_model_service()

    # 测试场景1: 公开数据（如果配置了外部模型则使用外部模型）
    try:
        print("\n场景1: 公开数据问答")
        response = await service.generate(
            prompt="请简单介绍一下中国共产党的成立时间。",
            data_level=DataLevel.PUBLIC,
            task_type=TaskType.QA,
            context={"demo": "public_qa"}
        )
        print(f"✓ 使用模型: {response.model_id}")
        print(f"✓ 回答: {response.content[:100]}...")
    except (RouterError, GatewayError) as e:
        print(f"✗ 错误: {e}")

    # 测试场景2: 敏感数据（强制使用本地模型）
    try:
        print("\n场景2: 敏感数据处理")
        response = await service.generate(
            prompt="分析党员发展材料的完整性。",
            data_level=DataLevel.SENSITIVE,
            task_type=TaskType.ARCHIVE_CHECK,
            context={"demo": "sensitive_archive"}
        )
        print(f"✓ 使用模型: {response.model_id}")
        print(f"✓ 回答: {response.content[:100]}...")
    except RouterError as e:
        print(f"✗ 路由错误（可能没有配置本地LLM）: {e}")
    except GatewayError as e:
        print(f"✗ 闸门拦截: {e}")


async def demo_embedding():
    """演示文本向量化"""
    print("\n" + "="*60)
    print("演示2: 文本向量化")
    print("="*60)

    service = get_model_service()

    texts = [
        "中国共产党的宗旨是全心全意为人民服务。",
        "入党积极分子需要经过至少一年的培养考察期。",
        "党员发展必须坚持个别吸收的原则。",
    ]

    try:
        print(f"\n向量化 {len(texts)} 条文本...")
        response = await service.embed(
            texts=texts,
            data_level=DataLevel.PUBLIC,
            context={"demo": "embedding"}
        )
        print(f"✓ 使用模型: {response.model_id}")
        print(f"✓ 向量维度: {response.dimensions}")
        print(f"✓ 向量数量: {len(response.embeddings)}")
        print(f"✓ 第一个向量前5维: {response.embeddings[0][:5]}")
    except Exception as e:
        print(f"✗ 错误: {e}")


async def demo_gateway_protection():
    """演示闸门保护机制"""
    print("\n" + "="*60)
    print("演示3: 数据级别出网闸门保护")
    print("="*60)

    service = get_model_service()

    # 场景1: 尝试用外部模型处理敏感数据（应被拦截）
    print("\n场景1: 尝试用外部模型处理敏感数据")
    try:
        # 手动注册一个错误的路由规则
        from app.llm.router import get_model_router
        router = get_model_router()
        router.register_route(
            data_level=DataLevel.SENSITIVE,
            task_type=TaskType.QA,
            model_id="qwen-turbo"  # 外部模型
        )

        response = await service.generate(
            prompt="处理敏感党员信息",
            data_level=DataLevel.SENSITIVE,
            task_type=TaskType.QA,
        )
        print(f"✗ 不应该执行到这里: {response.model_id}")

    except GatewayError as e:
        print(f"✓ 闸门成功拦截: {e}")

    except RouterError as e:
        print(f"✓ 路由器阻止（没有外部模型）: {e}")

    # 场景2: 涉密数据应直接拒绝
    print("\n场景2: 处理涉密数据")
    try:
        response = await service.generate(
            prompt="处理涉密文件",
            data_level=DataLevel.CLASSIFIED,
            task_type=TaskType.QA,
        )
        print(f"✗ 不应该执行到这里: {response.model_id}")

    except GatewayError as e:
        print(f"✓ 涉密数据被拒绝: {e}")


async def demo_health_check():
    """演示健康检查"""
    print("\n" + "="*60)
    print("演示4: 模型健康检查")
    print("="*60)

    service = get_model_service()

    results = await service.health_check()

    print(f"\n共有 {len(results)} 个模型:")
    for model_id, is_healthy in results.items():
        status = "✓ 健康" if is_healthy else "✗ 不健康"
        print(f"  {model_id}: {status}")


async def main():
    """主函数"""
    print("\n" + "="*60)
    print("党建工作智能体 - 模型服务演示")
    print("="*60)

    # 初始化模型
    print("\n初始化模型...")
    init_models()

    # 运行演示
    await demo_embedding()
    await demo_gateway_protection()
    await demo_health_check()

    # 如果配置了通义千问API Key，演示文本生成
    if os.getenv("QWEN_API_KEY"):
        await demo_text_generation()
    else:
        print("\n提示: 设置 QWEN_API_KEY 环境变量可以演示文本生成功能")

    print("\n" + "="*60)
    print("演示完成！")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
