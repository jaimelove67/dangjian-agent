"""RAG模块异常定义"""
from __future__ import annotations


class UnsupportedFormatError(Exception):
    """不支持的文件格式"""


class ParseError(Exception):
    """文件解析失败"""
