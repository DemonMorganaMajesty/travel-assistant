"""网页抓取工具，用于提取网页文本内容。
LangChain异步Tool，Agent可调用，抓取网页并清洗噪声标签，输出网页文本。
适合抓取旅游攻略、景点详情、交通资讯网页。
"""
import json
import logging
from langchain_core.tools import tool

# 模块日志对象
logger = logging.getLogger(__name__)


@tool
async def fetch_webpage(url: str, max_length: int = 4000) -> str:
    """抓取并提取网页的文本内容。

    适用场景：
    - 阅读完整的旅行攻略和文章
    - 获取交通时刻表
    - 提取详细的景点信息

    Args:
        url: 要抓取的网页 URL。
        max_length: 返回的最大字符数（默认 4000），防止大网页消耗过多LLM token。

    Returns:
        json字符串，包含url与清洗后的content；出错返回带error字段的json。
    """
    # ==========参数校验优化==========
    if not url:
        err_msg = "参数错误：url不能为空"
        logger.warning(f"[fetch_webpage] {err_msg}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    if not (url.startswith("http://") or url.startswith("https://")):
        err_msg = f"参数错误：仅支持http/https链接，传入url={url}"
        logger.warning(f"[fetch_webpage] {err_msg}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    # 限制max_length范围，防止传入超大值
    max_length = max(100, min(max_length, 8000))

    try:
        # 延迟导入：只有调用工具时才加载依赖，项目启动不会强制依赖httpx/bs4
        import httpx
        from bs4 import BeautifulSoup

        logger.info(f"[fetch_webpage] 开始抓取网页 url={url}, max_length={max_length}")

        # 异步http客户端：超时30秒；自动跟随重定向(301/302跳转)
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            # 请求网页，模拟浏览器UA，防止部分网站拦截爬虫
            response = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/120.0.0.0 TripPlanner-Bot/1.0"
                },
            )
            # 如果状态码为4xx/5xx，抛出HTTPError异常
            response.raise_for_status()
            logger.info(f"[fetch_webpage] 请求成功 status_code={response.status_code} url={url}")

        # 使用bs4解析HTML文档
        soup = BeautifulSoup(response.text, "html.parser")

        # 移除不需要的标签：脚本、样式、导航栏、页头页脚，减少噪声内容
        useless_tags = ["script", "style", "nav", "footer", "header", "aside"]
        for tag in soup(useless_tags):
            tag.decompose()  # decompose：直接从DOM树删除该节点以及子节点

        # 获取纯文本，标签之间用换行分隔；strip=True去除首尾空白
        raw_text = soup.get_text(separator="\n", strip=True)

        # 优化：压缩连续多行空白，减少token消耗
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        clean_text = "\n".join(lines)

        # 截断文本，超出最大长度末尾追加省略标记
        if len(clean_text) > max_length:
            clean_text = clean_text[:max_length] + "\n......【内容已截断】"

        result_data = {
            "url": url,
            "content": clean_text
        }
        logger.info(f"[fetch_webpage] 网页解析完成，文本长度={len(clean_text)} url={url}")

        # 调试阶段保留indent=2；生产环境删掉indent=2节省token
        return json.dumps(result_data, ensure_ascii=False, indent=2)

    except httpx.TimeoutException:
        err_msg = f"网页抓取超时，url={url}"
        logger.error(f"[fetch_webpage] {err_msg}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    except httpx.HTTPStatusError as e:
        err_msg = f"网页返回异常状态码:{e.response.status_code}, url={url}"
        logger.error(f"[fetch_webpage] {err_msg}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    except ImportError:
        err_msg = "缺少依赖库：需要安装 httpx beautifulsoup4"
        logger.error(f"[fetch_webpage] {err_msg}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    except Exception as e:
        err_msg = f"网页抓取发生未知异常: {str(e)}"
        logger.error(f"[fetch_webpage] {err_msg}", exc_info=True)
        return json.dumps({"error": err_msg}, ensure_ascii=False)
