import re
import unicodedata


def _surname(authors: list[str]) -> str:
    if not authors:
        return "Unknown"
    raw_name = unicodedata.normalize("NFKD", authors[0]).strip()
    if "," in raw_name:
        name = raw_name.split(",", 1)[0].strip()
    elif " " in raw_name:
        name = raw_name.split()[-1]
    else:
        name = raw_name
    name = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "_", name)
    return name.strip("_") or "Unknown"


def build_citation_keys(papers: list[dict]) -> list[str]:
    """Create stable, human-readable citation keys with collision handling."""

    used: dict[str, int] = {}
    keys: list[str] = []
    for paper in papers:
        base = f"{_surname(paper.get('authors', []))}_{paper.get('year') or 'nd'}"
        count = used.get(base, 0)
        used[base] = count + 1
        keys.append(base if count == 0 else f"{base}{chr(96 + count + 1)}")
    return keys

