"""pytest 配置文件"""
import pytest
import asyncio
from typing import AsyncGenerator

# 配置 asyncio 事件循环
@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
