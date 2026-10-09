-- 数据库初始化脚本

-- 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 启用 UUID 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 创建中文全文检索配置（基于 simple）
-- 生产环境需要安装 zhparser 等中文分词扩展
