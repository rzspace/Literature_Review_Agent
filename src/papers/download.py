from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings


class PaperDownloadError(RuntimeError):
    """Raised when metadata lookup or PDF download fails."""


@dataclass
class DownloadResult:
    citation_key: str
    status: str
    pdf_path: str | None = None
    source_url: str | None = None
    message: str = ""


def _safe_filename(citation_key: str, doi: str | None) -> str:
    if doi:
        suffix = doi.replace("/", "_").replace(".", "_")
        return f"{citation_key}_{suffix}.pdf"
    return f"{citation_key}.pdf"


def _find_pdf_urls(doi: str) -> list[str]:
    settings = get_settings()
    if not settings.unpaywall_email:
        raise PaperDownloadError("未配置 UNPAYWALL_EMAIL，无法查询开放获取链接")

    try:
        response = httpx.get(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": settings.unpaywall_email},
            headers={"User-Agent": "SciencePRO-Literature-Review-Demo/0.1"},
            timeout=30,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return []
        raise PaperDownloadError(
            f"Unpaywall 请求失败（HTTP {exc.response.status_code}）"
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise PaperDownloadError(f"Unpaywall 请求失败：{exc}") from exc

    urls: list[str] = []
    best_location = payload.get("best_oa_location") or {}
    if best_location.get("url_for_pdf"):
        urls.append(best_location["url_for_pdf"])
    if best_location.get("url"):  # Some repositories expose a landing page only.
        urls.append(best_location["url"])
    for location in payload.get("oa_locations") or []:
        if location.get("url_for_pdf"):
            urls.append(location["url_for_pdf"])
        elif location.get("url"):
            urls.append(location["url"])
    return list(dict.fromkeys(urls))


def download_open_access_pdf(paper: dict[str, Any]) -> DownloadResult:
    citation_key = paper["citation_key"]
    doi = paper.get("doi")
    if not doi:
        return DownloadResult(citation_key, "pdf_missing", message="没有 DOI")

    try:
        pdf_urls = _find_pdf_urls(doi)
    except PaperDownloadError as exc:
        return DownloadResult(citation_key, "failed", message=str(exc))

    if not pdf_urls:
        return DownloadResult(citation_key, "pdf_missing", message="未找到开放获取 PDF")

    settings = get_settings()
    target = settings.data_path / "pdfs" / _safe_filename(citation_key, doi)
    last_message = "未找到可下载的 PDF"
    for pdf_url in pdf_urls:
        try:
            with httpx.stream(
                "GET",
                pdf_url,
                headers={
                    "User-Agent": "Mozilla/5.0 SciencePRO-Literature-Review-Demo/0.1",
                    "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
                },
                follow_redirects=True,
                timeout=60,
            ) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                content_iterator = response.iter_bytes(8192)
                first_chunk = next(content_iterator, b"")
                if "pdf" not in content_type and not first_chunk.startswith(b"%PDF"):
                    last_message = "开放获取链接不是可识别的 PDF 文件"
                    continue
                with target.open("wb") as output:
                    output.write(first_chunk)
                    for chunk in content_iterator:
                        output.write(chunk)
            return DownloadResult(
                citation_key,
                "pdf_found",
                pdf_path=str(target),
                source_url=pdf_url,
                message="PDF 下载成功",
            )
        except httpx.HTTPStatusError as exc:
            last_message = f"PDF 下载失败（HTTP {exc.response.status_code}）"
        except httpx.HTTPError as exc:
            last_message = f"PDF 下载失败：{exc}"

    return DownloadResult(
        citation_key,
        "failed" if "403" in last_message else "pdf_missing",
        source_url=pdf_urls[0],
        message=last_message + "；可打开来源链接或手动上传 PDF",
    )

