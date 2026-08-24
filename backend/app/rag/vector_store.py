"""RAG 系统的 ChromaDB 向量存储管理。
职责：封装 ChromaDB 持久化向量库，实现全局单例管理；提供获取实例
完整重置清空向量库能力；给上层loader.py、hybrid.py调用
"""

import os
from pathlib import Path
from chromadb import PersistentClient
from .embeddings import get_embeddings
from typing_extensions import Optional
from langchain_chroma import Chroma
import logging
import shutil


logger = logging.getLogger(__name__)

# 全局存储实例
_vector_store: Optional[Chroma] = None


def _get_chroma_dir() -> str:
    """获取 ChromaDB 持久化目录
    目标：backend/data/chromadb
    """
    # vector_store.py: backend/app/rag
    # parent.parent.parent 向上3层到达 backend/
    db_dir = Path(__file__).parent.parent.parent / "data" / "chromadb"
    #如果上级目录不存在，会递归把父目录一起创建。
    #目标文件夹已经存在，不报错，直接跳过。
    db_dir.mkdir(parents=True, exist_ok=True)
    abs_path = str(db_dir.absolute())
    logger.info(f"[_get_chroma_dir] ChromaDB向量库路径 = {abs_path}")
    return abs_path


def get_vector_store() -> Chroma:
    """获取或创建 ChromaDB 向量存储全局单例。

    Returns:
        Chroma 向量存储实例。
    """
    global _vector_store
    if _vector_store is None:
        embeddings = get_embeddings()
        chroma_dir = _get_chroma_dir()
        logger.info("[get_vector_store] 初始化ChromaDB实例, collection=travel_knowledge")

        _vector_store = Chroma(
            collection_name="travel_knowledge",
            embedding_function=embeddings,
            persist_directory=chroma_dir,
        )
    return _vector_store


def reset_vector_store() -> Chroma:
    """重置向量存储：物理删除全部向量文件，返回全新空向量库实例。
    重建知识库 build_knowledge_base 时调用
    """
    global _vector_store
    chroma_dir = _get_chroma_dir()

    if os.path.exists(chroma_dir):
        logger.warning(f"[reset_vector_store] 即将清空向量库目录：{chroma_dir}")
        try:
            shutil.rmtree(chroma_dir)
            logger.info("[reset_vector_store] chromadb目录删除成功")
        except Exception as e:
            logger.error("[reset_vector_store] 删除向量库目录失败，文件可能被占用", exc_info=True)
            raise RuntimeError(f"重置向量库失败: {e}") from e

    _vector_store = None
    return get_vector_store()