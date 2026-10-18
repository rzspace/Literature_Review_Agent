import json
import re
from typing import Any

from openai import OpenAI

from ..config import get_settings


class LLMError(RuntimeError):
    """Raised when the configured LLM cannot return a usable response."""


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)

    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMError("模型返回的内容不是合法 JSON") from exc

    if not isinstance(value, dict):
        raise LLMError("模型返回的 JSON 不是对象")
    return value


def _get_client() -> tuple[OpenAI, str]:
    settings = get_settings()
    if settings.llm_provider.lower() != "deepseek":
        raise LLMError(f"当前 Demo 暂只支持 deepseek，当前配置为 {settings.llm_provider}")
    if not settings.deepseek_api_key:
        raise LLMError("未配置 DEEPSEEK_API_KEY，请检查 .env 文件")

    client = OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )
    return client, settings.deepseek_model


def generate_keyword_suggestion(topic: str, year_from: int, year_to: int) -> dict[str, Any]:
    """Generate a structured title and bilingual search keywords."""

    client, model = _get_client()
    prompt = f"""
你是一名学术检索策略专家。请为下面的中文研究主题生成文献综述检索方案。

研究主题：{topic}
年份范围：{year_from}-{year_to}

只返回 JSON，不要 Markdown，不要解释。JSON 必须严格包含以下字段：
{{
  "title": "中文综述标题",
  "keywords_zh": ["中文关键词1", "中文关键词2"],
  "keywords_en": ["English keyword 1", "English keyword 2"],
  "search_query": "用于 OpenAlex 的英文检索词",
  "outline": ["综述第一部分", "综述第二部分", "综述第三部分"]
}}

要求：
- title 是适合作为综述标题的完整中文标题；
- keywords_zh 输出 4-8 个关键词；
- keywords_en 输出与中文关键词对应的 4-8 个英文关键词或短语；
- search_query 使用英文关键词组合，不要包含年份和 OpenAlex 专用语法；
- outline 输出 4-6 个适合本主题的综述章节标题；
- 不要虚构具体论文、作者、数据或结论。
""".strip()

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": "你只输出合法 JSON。"},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as exc:  # SDK exceptions vary by provider/version.
        raise LLMError(f"DeepSeek API 调用失败：{exc}") from exc

    content = response.choices[0].message.content or ""
    result = _extract_json(content)
    required = ("title", "keywords_zh", "keywords_en", "search_query", "outline")
    missing = [field for field in required if field not in result]
    if missing:
        raise LLMError(f"模型返回缺少字段：{', '.join(missing)}")

    for field in ("keywords_zh", "keywords_en"):
        if not isinstance(result[field], list) or not all(
            isinstance(item, str) and item.strip() for item in result[field]
        ):
            raise LLMError(f"模型返回字段 {field} 格式不正确")
    if not isinstance(result["outline"], list) or not all(isinstance(item, str) for item in result["outline"]):
        raise LLMError("模型返回字段 outline 格式不正确")

    return result

