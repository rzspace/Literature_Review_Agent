import csv
import hmac
import io
import json
import streamlit as st
from uuid import uuid4

from src.config import get_settings
from src.db import (
    create_review_run,
    get_paper_id,
    get_paper_chunks,
    get_chunks_for_citations,
    get_run_notes,
    init_db,
    replace_paper_chunks,
    save_papers,
    save_paper_note,
    save_citation_check,
    update_paper_download,
    update_paper_status,
)
from src.llm.client import LLMError, generate_keyword_suggestion
from src.papers.download import download_open_access_pdf
from src.notes.parser import parse_pdf
from src.notes.generator import generate_paper_note
from src.review.generator import generate_review
from src.review.checker import check_claim, extract_claims
from src.papers.keys import build_citation_keys
from src.search.openalex import OpenAlexError, search_works


st.set_page_config(
    page_title="SciencePRO 文献综述 Agent",
    page_icon="📚",
    layout="wide",
)


settings = get_settings()

if settings.app_password:
    st.title("📚 SciencePRO 文献综述 Agent")
    password = st.text_input("请输入访问密码", type="password")
    if not password:
        st.info("该在线 Demo 已设置访问密码。")
        st.stop()
    if not hmac.compare_digest(password, settings.app_password):
        st.error("访问密码不正确。")
        st.stop()

init_db()

workflow_steps = [
    "主题与关键词",
    "OpenAlex 检索",
    "文献选择与入库",
    "PDF 获取",
    "PDF 解析",
    "精读笔记",
    "综述与引文核对",
]
completed_steps = 0
if "keyword_suggestion" in st.session_state:
    completed_steps = 1
if "openalex_result" in st.session_state:
    completed_steps = 2
if "selected_papers" in st.session_state:
    completed_steps = 3
if "download_results" in st.session_state:
    completed_steps = 4
if "parse_results" in st.session_state:
    completed_steps = 5
if "note_results" in st.session_state:
    completed_steps = 6
if "review_result" in st.session_state:
    completed_steps = 7

st.title("📚 SciencePRO 文献综述 Agent")
st.caption("Demo 第 1 步：项目初始化与基础配置")

with st.sidebar:
    st.subheader("流程进度")
    st.progress(completed_steps / len(workflow_steps))
    for index, step in enumerate(workflow_steps, start=1):
        marker = "✅" if index <= completed_steps else ("▶️" if index == completed_steps + 1 else "○")
        st.write(f"{marker} {index}. {step}")
    st.divider()
    st.subheader("运行状态")
    st.success("SQLite 已初始化")
    st.write(f"数据目录：`{settings.data_path}`")
    st.write(f"模型提供方：`{settings.llm_provider}`")
    st.info("下一步将接入 DeepSeek，完成关键词生成。")

st.subheader("创建一篇文献综述")
topic = st.text_area(
    "研究主题",
    placeholder="例如：钙钛矿太阳能电池稳定性提升策略",
    height=120,
)

col1, col2 = st.columns(2)
with col1:
    year_from = st.number_input("起始年份", min_value=1900, max_value=2100, value=2018)
with col2:
    year_to = st.number_input("结束年份", min_value=1900, max_value=2100, value=2025)

if st.button("开始创建", type="primary", disabled=not topic.strip()):
    run_id = uuid4().hex[:12]
    st.session_state["topic"] = topic.strip()
    st.session_state["year_range"] = (year_from, year_to)
    st.session_state["run_id"] = run_id
    create_review_run(run_id, topic.strip())
    st.success("主题已记录。下一步将生成中英文关键词。")

if "topic" in st.session_state:
    st.divider()
    st.write("当前主题：", st.session_state["topic"])
    st.write("年份范围：", st.session_state["year_range"])

    if st.button("生成标题和关键词", type="primary"):
        with st.spinner("正在调用 DeepSeek 生成检索方案..."):
            try:
                result = generate_keyword_suggestion(
                    st.session_state["topic"],
                    st.session_state["year_range"][0],
                    st.session_state["year_range"][1],
                )
                st.session_state["keyword_suggestion"] = result
            except LLMError as exc:
                st.error(str(exc))

if "keyword_suggestion" in st.session_state:
    suggestion = st.session_state["keyword_suggestion"]
    st.subheader("关键词确认")
    title = st.text_input("综述标题", value=suggestion["title"])
    keywords_zh = st.text_input(
        "中文关键词（用逗号分隔）",
        value="，".join(suggestion["keywords_zh"]),
    )
    keywords_en = st.text_input(
        "英文关键词（用逗号分隔）",
        value=", ".join(suggestion["keywords_en"]),
    )
    st.code(suggestion["search_query"], language="text")

    if st.button("确认关键词，进入检索"):
        st.session_state["confirmed_keywords"] = {
            "title": title,
            "keywords_zh": [item.strip() for item in keywords_zh.replace("，", ",").split(",") if item.strip()],
            "keywords_en": [item.strip() for item in keywords_en.split(",") if item.strip()],
            "search_query": suggestion["search_query"],
        }
        st.success("关键词已确认。下一步将接入 OpenAlex 检索。")

if "confirmed_keywords" in st.session_state:
    confirmed = st.session_state["confirmed_keywords"]
    st.divider()
    st.subheader("OpenAlex 学术检索")
    st.write("当前检索词：", ", ".join(confirmed["keywords_en"]))
    per_page = st.select_slider("返回文献数量", options=[5, 10, 15, 20, 25], value=10)

    if st.button("开始检索 OpenAlex", type="primary"):
        search_query = " AND ".join(confirmed["keywords_en"][:4])
        with st.spinner("正在检索 OpenAlex..."):
            try:
                hit_count, papers = search_works(
                    query=search_query,
                    year_from=st.session_state["year_range"][0],
                    year_to=st.session_state["year_range"][1],
                    per_page=per_page,
                )
                st.session_state["openalex_result"] = {
                    "hit_count": hit_count,
                    "papers": [paper.to_dict() for paper in papers],
                }
            except OpenAlexError as exc:
                st.error(str(exc))

if "openalex_result" in st.session_state:
    result = st.session_state["openalex_result"]
    hit_count = result["hit_count"]
    papers = result["papers"]
    st.success(f"OpenAlex 命中约 {hit_count:,} 篇，已返回 {len(papers)} 篇。")
    if hit_count < 10:
        st.warning("命中数量较少，可以考虑放宽关键词或年份范围。")
    elif hit_count > 500:
        st.warning("命中数量较多，可以增加限定词或缩小年份范围。")

    st.write("请选择要进入文献库和后续精读流程的论文（最多 10 篇）。")
    selected_indexes: list[int] = []
    for index, paper in enumerate(papers, start=1):
        default_selected = index <= min(5, len(papers))
        selected = st.checkbox(
            f"选择：{paper['title']}",
            value=default_selected,
            key=f"paper_selected_{st.session_state.get('run_id', 'run')}_{index}",
        )
        if selected:
            selected_indexes.append(index - 1)
        with st.expander(f"{index}. {paper['title']}（被引 {paper['cited_by_count']} 次）"):
            authors = ", ".join(paper["authors"][:5])
            if len(paper["authors"]) > 5:
                authors += " 等"
            st.write(f"作者：{authors or '未知'}")
            st.write(f"年份：{paper['year'] or '未知'} · 类型：{paper['type'] or '未知'}")
            st.write(f"DOI：{paper['doi'] or '无'}")
            st.write(f"开放获取：{paper['oa_url'] or '未找到开放获取链接'}")
            if paper["abstract"]:
                st.caption(paper["abstract"][:800] + ("..." if len(paper["abstract"]) > 800 else ""))

    if len(selected_indexes) > 10:
        st.warning("最多只能选择 10 篇文献，请取消部分选择。")
    if st.button(
        "确认选中文献，写入文献库",
        type="primary",
        disabled=not selected_indexes or len(selected_indexes) > 10,
    ):
        selected_papers = [papers[index] for index in selected_indexes]
        citation_keys = build_citation_keys(selected_papers)
        for paper, citation_key in zip(selected_papers, citation_keys):
            paper["citation_key"] = citation_key
        save_papers(st.session_state["run_id"], selected_papers)
        st.session_state["selected_papers"] = selected_papers
        st.success(f"已将 {len(selected_papers)} 篇文献写入本地文献库。")

if "selected_papers" in st.session_state:
    st.subheader("已入库文献")
    for paper in st.session_state["selected_papers"]:
        st.write(f"`{paper['citation_key']}` — {paper['title']}")

    if st.button("查找并下载开放获取 PDF", type="primary"):
        download_results = []
        progress = st.progress(0)
        selected_papers = st.session_state["selected_papers"]
        for index, paper in enumerate(selected_papers, start=1):
            result = download_open_access_pdf(paper)
            update_paper_download(
                st.session_state["run_id"],
                result.citation_key,
                result.status,
                result.pdf_path,
                result.source_url,
            )
            download_results.append(result)
            paper["pdf_path"] = result.pdf_path
            paper["status"] = result.status
            progress.progress(index / len(selected_papers))
        st.session_state["download_results"] = download_results

if "download_results" in st.session_state:
    st.subheader("PDF 获取结果")
    result_by_key = {result.citation_key: result for result in st.session_state["download_results"]}
    for result in st.session_state["download_results"]:
        if result.status == "pdf_found":
            st.success(f"{result.citation_key}：{result.message}")
            st.caption(result.pdf_path or "")
        elif result.status == "pdf_missing":
            st.warning(f"{result.citation_key}：{result.message}")
        else:
            st.error(f"{result.citation_key}：{result.message}")

    failed_papers = [
        paper
        for paper in st.session_state.get("selected_papers", [])
        if result_by_key.get(paper["citation_key"]) and not paper.get("pdf_path")
    ]
    if failed_papers:
        st.markdown("#### 手动补充 PDF")
        st.caption("出版社可能拒绝自动下载；你可以从浏览器或 Zotero 导出 PDF 后上传。")
        for paper in failed_papers:
            result = result_by_key[paper["citation_key"]]
            if result.source_url:
                st.link_button(f"打开 {paper['citation_key']} 的来源链接", result.source_url)
            uploaded = st.file_uploader(
                f"上传 {paper['citation_key']} PDF",
                type=["pdf"],
                key=f"manual_pdf_{st.session_state['run_id']}_{paper['citation_key']}",
            )
            if uploaded is not None:
                target = settings.data_path / "pdfs" / f"{paper['citation_key']}_manual.pdf"
                target.write_bytes(uploaded.getvalue())
                paper["pdf_path"] = str(target)
                paper["status"] = "pdf_found"
                result.status = "pdf_found"
                result.pdf_path = str(target)
                result.message = "PDF 已手动上传"
                update_paper_download(
                    st.session_state["run_id"],
                    paper["citation_key"],
                    "pdf_found",
                    str(target),
                    result.source_url,
                )
                st.success(f"{paper['citation_key']}：PDF 已上传，可以继续解析。")

if "download_results" in st.session_state:
    downloadable_papers = [
        paper
        for paper in st.session_state["selected_papers"]
        if paper.get("pdf_path")
    ]
    if downloadable_papers and st.button("解析已下载 PDF，建立文本片段"):
        parse_results = []
        progress = st.progress(0)
        for index, paper in enumerate(downloadable_papers, start=1):
            try:
                chunks = parse_pdf(paper["pdf_path"])
                paper_id = get_paper_id(st.session_state["run_id"], paper["citation_key"])
                if paper_id is None:
                    raise RuntimeError("数据库中找不到对应文献")
                chunk_dicts = [chunk.__dict__ for chunk in chunks]
                replace_paper_chunks(paper_id, chunk_dicts)
                update_paper_status(st.session_state["run_id"], paper["citation_key"], "parsed")
                parse_results.append(
                    {
                        "citation_key": paper["citation_key"],
                        "status": "parsed",
                        "chunk_count": len(chunks),
                    }
                )
            except Exception as exc:
                update_paper_status(st.session_state["run_id"], paper["citation_key"], "parse_failed")
                parse_results.append(
                    {
                        "citation_key": paper["citation_key"],
                        "status": "parse_failed",
                        "message": str(exc),
                    }
                )
            progress.progress(index / len(downloadable_papers))
        st.session_state["parse_results"] = parse_results

if "parse_results" in st.session_state:
    st.subheader("PDF 解析结果")
    for result in st.session_state["parse_results"]:
        if result["status"] == "parsed":
            st.success(f"{result['citation_key']}：解析出 {result['chunk_count']} 个文本片段")
        else:
            st.error(f"{result['citation_key']}：{result['message']}")

if "parse_results" in st.session_state:
    parsed_keys = {
        result["citation_key"]
        for result in st.session_state["parse_results"]
        if result["status"] == "parsed"
    }
    parsed_papers = [
        paper
        for paper in st.session_state.get("selected_papers", [])
        if paper["citation_key"] in parsed_keys
    ]
    if parsed_papers and st.button("生成逐篇精读笔记", type="primary"):
        note_results = []
        progress = st.progress(0)
        for index, paper in enumerate(parsed_papers, start=1):
            try:
                paper_id = get_paper_id(st.session_state["run_id"], paper["citation_key"])
                if paper_id is None:
                    raise RuntimeError("数据库中找不到对应文献")
                chunks = get_paper_chunks(paper_id)
                note = generate_paper_note(paper, chunks)
                save_paper_note(
                    paper_id,
                    json.dumps(note, ensure_ascii=False),
                    note.get("source_quality", "full_text"),
                    note.get("model_name", ""),
                )
                note_results.append(
                    {
                        "citation_key": paper["citation_key"],
                        "status": "generated",
                        "note": note,
                    }
                )
            except Exception as exc:
                note_results.append(
                    {
                        "citation_key": paper["citation_key"],
                        "status": "failed",
                        "message": str(exc),
                    }
                )
            progress.progress(index / len(parsed_papers))
        st.session_state["note_results"] = note_results

if "note_results" in st.session_state:
    st.subheader("精读笔记")
    for result in st.session_state["note_results"]:
        if result["status"] == "failed":
            st.error(f"{result['citation_key']}：{result['message']}")
            continue
        note = result["note"]
        with st.expander(f"{result['citation_key']} 精读笔记", expanded=False):
            st.write("**研究问题**：", note["research_question"]["text"])
            st.write("**数据/样本**：", note["data_and_sample"]["text"])
            st.write("**方法**：", note["method"]["text"])
            st.write("**主要发现**：")
            for finding in note["findings"]:
                st.write(f"- {finding['text']}")
                for evidence in finding.get("evidence", []):
                    st.caption(f"原文（第 {evidence.get('page')} 页）：{evidence.get('quote')}")
            st.write("**局限性**：", note["limitations"]["text"])

if "note_results" in st.session_state:
    generated_notes = [
        result for result in st.session_state["note_results"] if result["status"] == "generated"
    ]
    if generated_notes and st.button("基于精读笔记生成综述", type="primary"):
        with st.spinner("正在根据精读笔记生成综述..."):
            try:
                notes = get_run_notes(st.session_state["run_id"])
                review_markdown = generate_review(
                    notes,
                    st.session_state["topic"],
                    st.session_state.get("keyword_suggestion", {}).get("title", "文献综述"),
                )
                citation_count = review_markdown.count("[@")
                from src.db import save_review

                review_id = save_review(
                    st.session_state["run_id"], review_markdown, citation_count
                )
                st.session_state["review_result"] = {
                    "id": review_id,
                    "markdown": review_markdown,
                    "citation_count": citation_count,
                }
            except Exception as exc:
                st.error(str(exc))

if "review_result" in st.session_state:
    review_result = st.session_state["review_result"]
    st.divider()
    st.subheader("综述结果")
    st.caption(f"引用数量：{review_result['citation_count']}")
    st.markdown(review_result["markdown"])
    st.download_button(
        "下载 Markdown 综述",
        data=review_result["markdown"],
        file_name="literature_review.md",
        mime="text/markdown",
    )

    if st.button("开始独立引文核对", type="primary"):
        claims = extract_claims(review_result["markdown"])
        check_results = []
        progress = st.progress(0)
        for index, claim in enumerate(claims, start=1):
            try:
                chunks = get_chunks_for_citations(
                    st.session_state["run_id"], claim["citation_keys"]
                )
                result = check_claim(
                    claim["claim_text"], claim["citation_keys"], chunks
                )
                save_citation_check(
                    review_result["id"],
                    claim["claim_text"],
                    claim["citation_keys"],
                    result,
                )
                check_results.append({**claim, **result})
            except Exception as exc:
                check_results.append(
                    {
                        **claim,
                        "verdict": "needs_human_review",
                        "evidence": [],
                        "confidence": 0.0,
                        "needs_human_review": True,
                        "reason": str(exc),
                    }
                )
            progress.progress(index / max(len(claims), 1))
        st.session_state["citation_checks"] = check_results

if "citation_checks" in st.session_state:
    checks = st.session_state["citation_checks"]
    st.subheader("引文核对表")
    counts = {
        verdict: sum(1 for item in checks if item.get("verdict") == verdict)
        for verdict in (
            "supported",
            "partially_supported",
            "unsupported",
            "needs_human_review",
        )
    }
    total = len(checks)
    st.write(
        f"总计 {total} 条：支持 {counts['supported']}，部分支持 {counts['partially_supported']}，"
        f"不支持 {counts['unsupported']}，需人工复核 {counts['needs_human_review']}"
    )
    if total:
        support_rate = counts["supported"] / total
        st.metric("引文支持率", f"{support_rate:.1%}")
    for index, item in enumerate(checks, start=1):
        label = f"{index}. [{item['verdict']}] {item['claim_text']}"
        with st.expander(label):
            st.write("引用：", ", ".join(item["citation_keys"]))
            st.write("说明：", item.get("reason", ""))
            for evidence in item.get("evidence", []):
                st.caption(
                    f"{evidence.get('citation_key', '')} · 第 {evidence.get('page', '')} 页："
                    f"{evidence.get('quote', '')}"
                )

    checks_json = json.dumps(checks, ensure_ascii=False, indent=2)
    csv_buffer = io.StringIO()
    csv_writer = csv.DictWriter(
        csv_buffer,
        fieldnames=[
            "claim_text",
            "citation_keys",
            "verdict",
            "confidence",
            "needs_human_review",
            "reason",
            "evidence",
        ],
    )
    csv_writer.writeheader()
    for item in checks:
        csv_writer.writerow(
            {
                "claim_text": item.get("claim_text", ""),
                "citation_keys": ", ".join(item.get("citation_keys", [])),
                "verdict": item.get("verdict", ""),
                "confidence": item.get("confidence", 0),
                "needs_human_review": item.get("needs_human_review", False),
                "reason": item.get("reason", ""),
                "evidence": json.dumps(item.get("evidence", []), ensure_ascii=False),
            }
        )

    export_col1, export_col2, export_col3 = st.columns(3)
    with export_col1:
        st.download_button(
            "下载核对表 JSON",
            data=checks_json,
            file_name="citation_checks.json",
            mime="application/json",
        )
    with export_col2:
        st.download_button(
            "下载核对表 CSV",
            data=csv_buffer.getvalue(),
            file_name="citation_checks.csv",
            mime="text/csv",
        )
    with export_col3:
        complete_export = {
            "run_id": st.session_state.get("run_id"),
            "topic": st.session_state.get("topic"),
            "year_range": st.session_state.get("year_range"),
            "review": review_result,
            "citation_checks": checks,
        }
        st.download_button(
            "下载完整结果 JSON",
            data=json.dumps(complete_export, ensure_ascii=False, indent=2),
            file_name="literature_review_result.json",
            mime="application/json",
        )

