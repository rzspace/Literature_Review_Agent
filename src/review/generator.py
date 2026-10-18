from typing import Any

from ..llm.client import LLMError, _extract_json, _get_client


def generate_review(notes: list[dict[str, Any]], topic: str, title: str) -> str:
    if not notes:
        raise LLMError("没有可用于生成综述的精读笔记")

    source_parts = []
    for item in notes:
        source_parts.append(
            f"Citation key: {item['citation_key']}\n"
            f"Title: {item['title']}\n"
            f"Year: {item.get('year') or ''}\n"
            f"Authors: {', '.join(item.get('authors', []))}\n"
            f"Structured note:\n{item['note_json']}"
        )

    client, model = _get_client()
    prompt = f"""
你是一名严谨的学术综述写作助手。请根据下面提供的结构化精读笔记，撰写一篇中文文献综述。

研究主题：{topic}
综述标题：{title}

可用文献笔记：
{chr(10).join(source_parts)}

写作要求：
1. 输出 Markdown，包含标题、摘要、主题分节、综合讨论、研究不足与结论；
2. 只能使用提供的精读笔记，不得补充笔记中没有的事实、数值、作者观点或 DOI；
3. 每个可验证的观点后必须添加一个或多个引用，格式严格为 [@citation_key]；
4. 引用 key 只能使用输入笔记中出现过的 key；
5. 如果证据不足，明确写“现有笔记证据不足，需人工补充”，不要猜测；
6. 不要单独输出参考文献列表以外的虚构信息；
7. 末尾根据输入元数据生成“参考文献”部分，使用 citation key、作者、年份和标题。
""".strip()

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": "你只依据提供的结构化笔记写作，并严格保留引用 key。"},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as exc:
        raise LLMError(f"综述生成调用失败：{exc}") from exc

    content = response.choices[0].message.content or ""
    if not content.strip():
        raise LLMError("模型返回了空综述")
    return content.strip()

