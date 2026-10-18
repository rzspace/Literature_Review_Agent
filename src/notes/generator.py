from typing import Any

from ..config import get_settings
from ..llm.client import LLMError, _extract_json, _get_client


def generate_paper_note(
    paper: dict[str, Any],
    chunks: list[dict[str, Any]],
    max_chars: int = 14000,
) -> dict[str, Any]:
    """Generate an evidence-backed, structured note for one paper."""

    if not chunks:
        raise LLMError("该文献没有可用的 PDF 文本片段")

    source_parts: list[str] = []
    used_chars = 0
    for chunk in chunks:
        part = f"[PAGE {chunk['page_number']}]\n{chunk['text']}"
        if used_chars + len(part) > max_chars:
            break
        source_parts.append(part)
        used_chars += len(part)

    client, model = _get_client()
    settings = get_settings()
    prompt = f"""
你是一名严谨的学术文献精读助手。请只根据下面提供的论文原文片段生成结构化笔记。

论文标题：{paper.get('title', '')}
作者：{', '.join(paper.get('authors', []))}
年份：{paper.get('year') or ''}
DOI：{paper.get('doi') or ''}

原文片段：
{chr(10).join(source_parts)}

只返回 JSON，不要 Markdown，不要补充原文中没有的信息。必须包含：
{{
  "research_question": {{"text": "", "evidence": [{{"quote": "", "page": 1}}]}},
  "data_and_sample": {{"text": "", "evidence": [{{"quote": "", "page": 1}}]}},
  "method": {{"text": "", "evidence": [{{"quote": "", "page": 1}}]}},
  "findings": [{{"text": "", "evidence": [{{"quote": "", "page": 1}}]}}],
  "limitations": {{"text": "", "evidence": [{{"quote": "", "page": 1}}]}},
  "source_quality": "full_text"
}}

要求：
- evidence.quote 必须是上面原文片段中的连续原文，不能改写；
- page 必须使用原文片段的 PAGE 编号；
- 找不到证据时，text 写“原文未明确说明”，evidence 返回空数组；
- 不要编造实验数据、样本数量、结论强度或局限性；
- findings 至少输出 1 条，最多输出 5 条。
""".strip()

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.1,
            messages=[
                {"role": "system", "content": "你只输出合法 JSON，并严格保留证据原文。"},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as exc:
        raise LLMError(f"DeepSeek 精读调用失败：{exc}") from exc

    content = response.choices[0].message.content or ""
    note = _extract_json(content)
    required = (
        "research_question",
        "data_and_sample",
        "method",
        "findings",
        "limitations",
        "source_quality",
    )
    missing = [field for field in required if field not in note]
    if missing:
        raise LLMError(f"精读笔记缺少字段：{', '.join(missing)}")
    note["model_name"] = settings.deepseek_model
    note["truncated_source"] = len(source_parts) < len(chunks)
    return note

