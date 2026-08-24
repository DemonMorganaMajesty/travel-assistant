"""配置管理模块"""

import os
from pathlib import Path
from typing_extensions import List
from pydantic_settings import BaseSettings
from pydantic import field_validator
from dotenv import load_dotenv

# 加载环境变量（相对于 config.py 所在目录的 ../.env）
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# 然后尝试加载HelloAgents的.env(如果存在)
helloagents_env = Path(__file__).parent.parent.parent.parent / "HelloAgents" / ".env"
if helloagents_env.exists():
    load_dotenv(helloagents_env, override=False)


class Settings(BaseSettings):
    """应用配置"""

    # 应用基本配置
    app_name: str = "智能旅行助手"
    app_version: str = "1.0.0"
    debug: bool = False

    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS配置
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"

    # 高德地图API配置
    amap_api_key: str = os.getenv("AMAP_API_KEY")

    # Unsplash API配置
    unsplash_access_key: str = os.getenv("UNSPLASH_ACCESS_KEY")
    unsplash_secret_key: str = os.getenv("UNSPLASH_SECRET_KEY")

    # LLM配置 兜底的 防止llm 每有填写而报错
    llm_api_key: str = os.getenv("LLM_API_KEY")
    llm_base_url: str = os.getenv("LLM_BASE_URL")
    llm_model: str = os.getenv("LLM_MODEL")

    # ============新增 Embedding 配置字段============
    embedding_model: str = os.getenv("EMBEDDING_MODEL")
    embedding_api_key: str = os.getenv("EMBEDDING_API_KEY")
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL")

    # LangFuse 追踪配置
    langfuse_public_key: str = os.getenv("LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = os.getenv("LANGFUSE_SECRET_KEY")
    langfuse_host: str = "https://us.cloud.langfuse.com"

    # Tavily搜索
    tavily_api_key: str = os.getenv("TAVILY_API_KEY")

    # 日志配置
    log_level: str = "INFO"

    # ============ JWT 登录鉴权配置 ============
    jwt_secret: str = "dev-secret-change-me"  # 生产环境务必通过 .env 覆盖
    jwt_expire_hours: int = 24  # token 有效期（小时）

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, v):
        """处理 debug 的字符串到布尔值转换（如 'release' -> False）。"""
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return bool(v)

    class Config:
        #env_file = ".env"
        case_sensitive = False   # 大小写敏感，严格匹配EMBEDDING_*
        extra = "ignore"

    def get_cors_origins_list(self) -> List[str]:
        """获取CORS origins列表"""
        return [origin.strip() for origin in self.cors_origins.split(",")]


# 创建全局配置实例
settings = Settings()


def get_settings() -> Settings:
    """获取配置实例"""
    return settings


def validate_config():
    """验证配置是否完整"""
    errors = []
    warnings = []

    if not settings.amap_api_key:
        errors.append("AMAP_API_KEY未配置")

    llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not llm_api_key:
        warnings.append("LLM_API_KEY或OPENAI_API_KEY未配置,LLM功能可能无法使用")

    # Embedding校验
    emb_key = os.getenv("EMBEDDING_API_KEY")
    if not emb_key:
        warnings.append("EMBEDDING_API_KEY未配置，RAG向量功能将被禁用")

    if errors:
        error_msg = "配置错误:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)

    if warnings:
        print("\n配置警告:")
        for w in warnings:
            print(f"  - {w}")

    return True


def print_config():
    """打印当前配置(隐藏敏感信息)"""
    print(f"应用名称: {settings.app_name}")
    print(f"版本: {settings.app_version}")
    print(f"服务器: {settings.host}:{settings.port}")
    print(f"高德地图API Key: {'已配置' if settings.amap_api_key else '未配置'}")

    llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or settings.openai_api_key
    llm_base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or settings.openai_base_url
    llm_model = os.getenv("LLM_MODEL_ID") or os.getenv("OPENAI_MODEL") or settings.openai_model

    print(f"LLM API Key: {'已配置' if llm_api_key else '未配置'}")
    print(f"LLM Base URL: {llm_base_url}")
    print(f"LLM Model: {llm_model}")

    # =========打印Embedding信息=========
    emb_model = os.getenv("EMBEDDING_MODEL")
    emb_base = os.getenv("EMBEDDING_BASE_URL")
    emb_key = os.getenv("EMBEDDING_API_KEY")
    print(f"Embedding Model: {emb_model}")
    print(f"Embedding BaseUrl: {emb_base}")
    print(f"Embedding API Key: {'已配置' if emb_key else '未配置'}")

    print(f"日志级别: {settings.log_level}")