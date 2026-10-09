-- 数据库初始化脚本
-- 由 docker-entrypoint-initdb.d 在容器首次启动时执行。
-- 注意：核心表结构由 Alembic 迁移创建（alembic upgrade head），此处只准备扩展与检索配置。

-- 启用 pgvector 扩展（向量检索）
CREATE EXTENSION IF NOT EXISTS vector;

-- 启用 UUID 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 启用 pg_trgm 扩展（中文子串/模糊检索兜底）
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 创建中文全文检索配置（默认基于 simple）
-- 说明：开发/默认环境使用 simple，配合 pg_trgm 兜底即可检索中文；
--       生产环境安装 zhparser 后，执行下句切换为中文分词：
--   ALTER TEXT SEARCH CONFIGURATION chinese_zh ALTER MAPPING FOR n,v,a,i,e,l WITH zhparser;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'chinese_zh') THEN
        CREATE TEXT SEARCH CONFIGURATION chinese_zh (COPY = simple);
    END IF;
END
$$;
