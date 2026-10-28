-- 数据卷首次初始化时执行（连接的是主库 agent）。
-- 为 LiteLLM 网关建独立的库；为主库启用 pgvector（M3 知识库使用）。
CREATE DATABASE litellm;
CREATE EXTENSION IF NOT EXISTS vector;
