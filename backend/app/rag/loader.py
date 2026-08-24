"""RAG 知识库文档加载、编码兼容处理、文本分块、构建 Chroma 向量库。
流程：读取data/下.txt/.md攻略文档 → 兼容 utf‑8/gbk 编码加载 → 递归字符分块 → 清空旧向量库，写入新分块到 ChromaDB；无文档时自动生成占位旅游知识库。
对外入口：build_knowledge_base()，项目启动 / 手动调用重建知识库。
依赖：langchain文档加载器、文本分割器、内部vector_store向量库模块。

RAG数据导入入口，磁盘文档读取、编码兼容、文本切分、初始化 Chroma 向量库。
对外主函数：build_knowledge_base()，项目启动时调用，重建整个知识库。

build_knowledge_base()
    ↓
load_documents()：读取data/**/*.txt、**.md
    ├ 优先utf‑8读取；解码报错自动切换gbk
    └ Document带上元数据 source(文件名)、file_path
    ↓
如果没有读到任何文档 → _create_placeholder_docs() 自动生成内置旅游占位文档
    ↓
RecursiveCharacterTextSplitter 递归字符分块（chunk_size=512，overlap=50）
    ↓
过滤空白chunk，防止无效向量
    ↓
reset_vector_store() 清空旧Chroma向量库
    ↓
store.add_documents() 将分块写入向量数据库持久化


"""

import os
import logging
from pathlib import Path
from typing_extensions import List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader
from .vector_store import get_vector_store, reset_vector_store
# 模块日志
logger = logging.getLogger(__name__)

# 文本分割器常量，统一管理分隔符
TEXT_SEPARATORS = ["\n\n", "\n", "。", ".", "!", "?", "，", ",", " ", ""]

def get_data_dir() -> Path:
    """获取知识库数据目录，不存在自动创建。
    :return: data文件夹Path对象，位于当前py文件同级data目录
    """
    # __file__ 当前脚本路径；parent拿到当前脚本所在文件夹，拼接data子目录
    data_dir = Path(__file__).parent / "data"
    # parents=True递归创建多层目录；exist_ok=True目录存在不抛异常
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def load_documents() -> List[Document]:
    """从数据目录加载所有文档，兼容utf‑8/gbk编码
    只会读取 *.txt *.md；自动给document添加source元数据（文件名）

    Returns:
        LangChain Document 对象列表
    """
    data_dir = get_data_dir()
    documents: List[Document] = []

    # glob("**/*") 开启递归，读取data下子文件夹内txt/md；原版只读取一级目录
    for ext in ["**/*.txt", "**/*.md"]:
        for file_path in data_dir.glob(ext):
            # 跳过目录，只处理普通文件
            if not file_path.is_file():
                continue
            try:
                # 优先utf‑8打开
                loader = TextLoader(str(file_path), encoding="utf-8")
                docs = loader.load()
                for doc in docs:
                    doc.metadata["source"] = file_path.name
                    doc.metadata["file_path"] = str(file_path)
                documents.extend(docs)
                logger.debug(f"[load_documents] 加载文件成功 {file_path.name}")
            except UnicodeDecodeError:
                logger.debug(f"[load_documents] {file_path.name} utf‑8解码失败，尝试gbk")
                try:
                    loader = TextLoader(str(file_path), encoding="gbk")
                    docs = loader.load()
                    for doc in docs:
                        doc.metadata["source"] = file_path.name
                        doc.metadata["file_path"] = str(file_path)
                    documents.extend(docs)
                    logger.debug(f"[load_documents] {file_path.name} 使用gbk编码加载成功")
                except Exception as e:
                    logger.error(f"[load_documents] 文件加载失败 {file_path.name}", exc_info=True)

    return documents


def _create_placeholder_docs():
    """为常见景点创建 占位知识库文本文件。
    当data目录完全没有文档的时候调用，生成 _placeholder.txt
    """
    data_dir = get_data_dir()
    placeholder_file = data_dir / "_placeholder.txt"

    if not placeholder_file.exists():
        content = """# 中国旅游知识库

## 故宫
故宫位于北京市中心，是明清两代的皇家宫殿（1420-1912）。
它是世界上最大的宫殿建筑群，占地72公顷，拥有9000多间房间。
主要景点包括太和殿、乾清宫和御花园。故宫博物院藏有超过180万件文物。
门票价格：旺季60元（4月-10月），淡季40元（11月-3月）。
建议游览时间：3-4小时。

## 长城
长城横跨中国北方，全长超21000公里。
北京附近最受欢迎的段落有八达岭（保存完好，人流密集）、
慕田峪（风景优美，人流较少）和司马台（险峻原始，体验真实）。
八达岭距北京市中心约70公里，车程约1.5小时。
门票：根据季节40-45元不等。
最佳游览时间：4月-10月。

## 颐和园
颐和园位于北京海淀区，是一座规模宏大的皇家园林，
堪称中国园林设计的杰作。主要景点包括昆明湖、万寿山和长廊。
始建于1750年，1886年重建。门票：30元。建议游览时间：2-3小时。
"""
        placeholder_file.write_text(content, encoding="utf-8")
        logger.info(f"[_create_placeholder_docs] 创建占位知识库文件 {placeholder_file}")


def build_knowledge_base(chunk_size: int = 512, chunk_overlap: int = 50) -> int:
    """从数据文件构建/重建 ChromaDB 知识库。
    若data目录无文档，先生成占位文档再构建向量库

    Args:
        chunk_size: 每个分块最大字符长度
        chunk_overlap: 相邻分块重叠字符，保障上下文连续性

    Returns:
        int: 成功写入向量库的文档分块数量
    """
    logger.info("[build_knowledge_base] 开始构建RAG知识库")

    documents = load_documents()

    # =========无文档时，先生成占位文件，再重新加载文档=========
    if not documents:
        logger.warning("[build_knowledge_base] data目录未找到txt/md文档，生成占位知识库")
        _create_placeholder_docs()
        # 生成完占位文件，重新加载文档
        documents = load_documents()

    logger.info(f"[build_knowledge_base] 总共加载 {len(documents)} 份原始文档")

    # 文本分块
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=TEXT_SEPARATORS,
    )

    chunks = text_splitter.split_documents(documents)

    # 过滤完全空白的chunk，避免无效向量存入Chroma
    valid_chunks: List[Document] = []
    for chunk in chunks:
        if chunk.page_content.strip():
            valid_chunks.append(chunk)
    logger.info(f"[build_knowledge_base] 原始分块 {len(chunks)}，过滤空白后有效分块 {len(valid_chunks)}")

    # reset_vector_store：清空旧向量，返回全新Chroma对象
    store = reset_vector_store()
    if valid_chunks:
        store.add_documents(valid_chunks)
        # add_documents自动落盘
        logger.info(f"[build_knowledge_base] 向量库写入完成，有效分块数量：{len(valid_chunks)}")
    else:
        logger.warning("[build_knowledge_base] 没有有效文档分块，向量库为空")

    return len(valid_chunks)