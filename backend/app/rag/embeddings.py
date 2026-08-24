"""RAG 的 Embedding 模型封装。"""

import os
from langchain_openai import OpenAIEmbeddings


def get_embeddings():
    """获取 OpenAI 兼容格式 Embeddings 实例（硅流 BAAI/bge‑m3）。

    模型可通过环境变量配置：
    - EMBEDDING_MODEL: 模型名称（默认: BAAI/bge‑m3）
    - EMBEDDING_API_KEY: API 密钥（回退到 LLM_API_KEY，再回退到 OPENAI_API_KEY）
    - EMBEDDING_BASE_URL: 基础 URL（回退到 LLM_BASE_URL，再回退到 OPENAI_BASE_URL）

    Returns:
        OpenAIEmbeddings 实例，或 None（未配置 API 密钥时）。
    """
    # 修改默认模型为硅流免费 BAAI/bge‑m3
    model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    api_key = (
        os.getenv("EMBEDDING_API_KEY")
        or os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    base_url = (
        os.getenv("EMBEDDING_BASE_URL")
        or os.getenv("LLM_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
    )

    if not api_key:
        print("警告: 未配置 Embedding API 密钥，RAG 将被禁用。")
        return None

    kwargs = {
        "model": model,
        "api_key": api_key,
    }
    if base_url:
        kwargs["base_url"] = base_url

    return OpenAIEmbeddings(**kwargs)