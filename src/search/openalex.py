from dataclasses import asdict, dataclass
from typing import Any

import httpx

from ..config import get_settings


class OpenAlexError(RuntimeError):
    """Raised when OpenAlex cannot return a usable response."""


@dataclass
class PaperResult:
    openalex_id: str
    doi: str | None
    title: str
    abstract: str
    year: int | None
    cited_by_count: int
    authors: list[str]
    oa_url: str | None
    type: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    if not inverted_index:
        return ""

    words: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for position in positions:
            words[position] = word
    return " ".join(words[index] for index in sorted(words))


def _normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    return doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")


def _to_paper(item: dict[str, Any]) -> PaperResult:
    authors = [
        authorship.get("author", {}).get("display_name", "")
        for authorship in item.get("authorships", [])
    ]
    authors = [author for author in authors if author]
    open_access = item.get("open_access") or {}
    primary_location = item.get("primary_location") or {}
    best_oa_location = item.get("best_oa_location") or {}

    return PaperResult(
        openalex_id=item.get("id", ""),
        doi=_normalize_doi(item.get("doi")),
        title=item.get("title") or "未命名论文",
        abstract=_reconstruct_abstract(item.get("abstract_inverted_index")),
        year=item.get("publication_year"),
        cited_by_count=item.get("cited_by_count", 0),
        authors=authors,
        oa_url=(
            best_oa_location.get("pdf_url")
            or best_oa_location.get("landing_page_url")
            or primary_location.get("landing_page_url")
            if open_access.get("is_oa")
            else None
        ),
        type=item.get("type"),
    )


def build_filter(year_from: int, year_to: int) -> str:
    return f"publication_year:{year_from}-{year_to},type:article|review"


def search_works(
    query: str,
    year_from: int,
    year_to: int,
    per_page: int = 10,
) -> tuple[int, list[PaperResult]]:
    """Search OpenAlex and return total hits plus citation-sorted papers."""

    settings = get_settings()
    params: dict[str, str | int] = {
        "search": query,
        "filter": build_filter(year_from, year_to),
        "sort": "cited_by_count:desc",
        "per-page": min(max(per_page, 1), 25),
    }
    if settings.openalex_api_key:
        params["api_key"] = settings.openalex_api_key
    if settings.openalex_email:
        params["mailto"] = settings.openalex_email

    try:
        response = httpx.get(
            "https://api.openalex.org/works",
            params=params,
            headers={"User-Agent": "SciencePRO-Literature-Review-Demo/0.1"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise OpenAlexError(
                "OpenAlex 请求被限流（429）。请稍后重试；如果频繁出现，"
                "可以申请 OpenAlex 免费 API Key 并填写 OPENALEX_API_KEY。"
            ) from exc
        raise OpenAlexError(
            f"OpenAlex 请求失败（HTTP {exc.response.status_code}）"
        ) from exc
    except httpx.HTTPError as exc:
        raise OpenAlexError(f"OpenAlex 网络请求失败：{exc}") from exc
    except ValueError as exc:
        raise OpenAlexError("OpenAlex 返回内容不是合法 JSON") from exc

    meta = payload.get("meta") or {}
    results = payload.get("results") or []
    return int(meta.get("count", 0)), [_to_paper(item) for item in results]

