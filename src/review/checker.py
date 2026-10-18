import re
from typing import Any

from ..llm.client import LLMError, _extract_json, _get_client


CITATION_PATTERN = re.compile(r"\[@([A-Za-z0-9_]+)\]")


def extract_claims(markdown: str) -> list[dict[str, Any]]:
    """Extract one claim per Markdown line containing one or more citation keys."""

    claims: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for line in markdown.splitlines():
        matches = CITATION_PATTERN.findall(line)
        if not matches:
            continue
        claim_text = re.sub(r"\[@[A-Za-z0-9_]+\]", "", line)
        claim_text = re.sub(r"^[#>*\-\s]+", "", claim_text).strip()
        claim_text = re.sub(r"\s+", " ", claim_text)
        if not claim_text:
            continue
        key = (claim_text, tuple(sorted(set(matches))))
        if key in seen:
            continue
        seen.add(key)
        claims.append({"claim_text": claim_text, "citation_keys": list(key[1])})
    return claims


def check_claim(
    claim_text: str,
    citation_keys: list[str],
    evidence_chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    if not evidence_chunks:
        return {
            "verdict": "needs_human_review",
            "evidence": [],
            "confidence": 0.0,
            "needs_human_review": True,
            "reason": "没有找到对应论文的原始文本片段",
        }

    source_text = "\n".join(
        f"[CITATION {chunk['citation_key']} | PAGE {chunk['page_number']}]\n{chunk['text']}"
        for chunk in evidence_chunks[:12]
    )
    client, model = _get_client()
    prompt = f"""
你是独立的学术引文核对员。不要使用任何精读笔记，只根据下面的综述观点和原始论文文本片段进行判断。

综述观点：{claim_text}
引用 key：{', '.join(citation_keys)}

原始论文文本片段：
{source_text}

只返回 JSON：
{{
  "verdict": "supported|partially_supported|unsupported|needs_human_review",
  "evidence": [{{"citation_key": "", "quote": "", "page": 1}}],
  "confidence": 0.0,
  "needs_human_review": false,
  "reason": "简短说明"
}}

判定标准：
- supported：原文明确支持观点，且引用匹配；
- partially_supported：方向基本支持，但范围、条件或强度有差异；
- unsupported：原文不支持、相反或引用错配；
- needs_human_review：证据不足、文本冲突或无法可靠判断；
- evidence.quote 必须是输入片段中的连续原文，不得改写；
- 没有证据时 evidence 必须为空数组。
""".strip()

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.0,
            messages=[
                {"role": "system", "content": "你只输出合法 JSON，并且不能使用未提供的资料。"},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as exc:
        raise LLMError(f"引文核对调用失败：{exc}") from exc

    result = _extract_json(response.choices[0].message.content or "")
    required = ("verdict", "evidence", "confidence", "needs_human_review", "reason")
    missing = [field for field in required if field not in result]
    if missing:
        raise LLMError(f"核对结果缺少字段：{', '.join(missing)}")
    return result

