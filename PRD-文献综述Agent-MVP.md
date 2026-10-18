# SciencePRO 文献综述 Agent：Demo PRD 与技术方案

## 1. Demo 目标

在不做埋点、不追求生产级并发的前提下，先跑通一条可演示、可追溯的闭环：

> 主题输入 → 关键词确认 → OpenAlex 检索 → 文献入库 → PDF/摘要精读 → 带引用综述 → 引文核对表

Demo 的核心不是“写得像人”，而是证明两件事：

1. 综述中的每个观点都能回指到文献和原文证据。
2. 生成、核对和失败状态都可被用户看见，而不是黑盒等待。

## 2. MVP 范围

### 2.1 必须实现

- 中文主题输入。
- LLM 生成标题、中文关键词、英文检索词，并允许用户编辑。
- 调 OpenAlex 获取命中数和前 N 篇结果，默认 N=10，最多 25。
- 按 DOI、OpenAlex ID、标题去重。
- 文献元数据入库；支持导出 BibTeX/CSL-JSON。
- 通过 Unpaywall 获取开放获取 PDF；无 PDF 时保留摘要并标记“仅摘要”。
- 对每篇文献生成结构化笔记：研究问题、数据/样本、方法、主要结论、局限性、证据句、页码/定位信息。
- 只基于结构化笔记生成综述，引用格式为 `[@Hu_2024]`。
- 逐条核对综述中的引用，输出“支持 / 部分支持 / 不支持 / 需人工复核”。
- 展示任务进度、失败原因、重试按钮和最终核对表。

### 2.2 Demo 暂不实现

- 埋点、神策、A/B 实验和用户增长看板。
- 复杂权限、多租户、计费。
- 自动购买或绕过付费墙获取全文。
- 大规模向量数据库和跨项目知识库。
- 自动修改 Zotero 桌面端库。
- 论文全文的完美 OCR、表格/公式理解。

### 2.3 Zotero 的 Demo 处理建议

把“文献入库”抽象成 `LiteratureLibrary` 接口：

- Demo 默认实现：本地 SQLite + 文件目录，提供 BibTeX/CSL-JSON 导出。
- 可选实现：Zotero Web API，把元数据和 PDF 附件同步到用户的 Zotero 库。

这样不被 Zotero token、附件权限和网络波动卡住，同时保留后续接入点。作品集展示时可以说“采用适配器设计，Demo 用本地库，生产环境切换 Zotero Adapter”。

## 3. 用户流程与页面

### 页面 A：创建综述

输入：研究主题、年份范围、文献数量、是否只要开放获取文献。

点击“生成关键词”后展示：

- 建议标题。
- 中文关键词和英文关键词标签。
- 预估命中数。
- 命中数提示：少于 10 篇建议放宽，超过 500 篇建议收窄。

Demo 可以先不做 5 分钟自动执行；如果希望体现 HITL，可保留 60 秒可配置倒计时，超时后使用当前关键词继续。

### 页面 B：检索与入库

以步骤进度条展示：

1. 查询 OpenAlex。
2. 去重与排序。
3. 查找开放获取 PDF。
4. 写入本地文献库。

每篇文献展示标题、年份、期刊、被引数、DOI、全文状态和失败原因。

### 页面 C：精读与生成

展示每篇文献的笔记卡片，并允许查看证据句。综述生成时使用流式文本或阶段性状态更新。

### 页面 D：结果与核对

- 综述正文。
- 引用数量和唯一文献数。
- 引文核对表。
- 支持率、部分支持率、不支持率、人工复核率。
- “重新生成”“重新核对”“导出 Markdown/BibTeX”。

## 4. 功能需求

### FR-01 关键词生成与确认

输入主题后，模型输出结构化 JSON：

```json
{
  "title": "钙钛矿太阳能电池稳定性提升策略的研究综述",
  "keywords_zh": ["钙钛矿太阳能电池", "稳定性提升", "界面修饰"],
  "keywords_en": ["perovskite solar cells", "stability enhancement", "interface engineering"],
  "query": "TITLE_AND_ABSTRACT:(perovskite solar cell AND stability)"
}
```

用户可增删关键词并重新预估命中数。确认后生成 `ReviewRun`。

### FR-02 OpenAlex 检索

- 按标题/摘要检索。
- 默认年份范围近 10 年，可修改。
- 默认过滤 `type=article|review`，有 DOI 优先。
- 按 `cited_by_count desc` 排序。
- 保存原始响应，便于复现。

### FR-03 文献入库

引用 key 规则：`FirstAuthorSurname_Year`；冲突时追加 `a/b` 或短哈希。

文献状态：`discovered`、`metadata_saved`、`pdf_found`、`pdf_missing`、`parsed`、`failed`。

### FR-04 全文解析与笔记

优先级：

1. Open-access PDF。
2. HTML 全文。
3. OpenAlex/Crossref 摘要。

PDF 解析后按页或段落切块，每个 chunk 保留 `page_number`、`char_start`、`char_end`。

笔记必须是结构化 JSON，而不是直接生成一段自然语言：

```json
{
  "research_question": {"text": "...", "evidence": [{"quote": "...", "page": 2}]},
  "data_and_sample": {"text": "...", "evidence": []},
  "method": {"text": "...", "evidence": []},
  "findings": [{"text": "...", "evidence": [{"quote": "...", "page": 5}]}],
  "limitations": {"text": "...", "evidence": []},
  "source_quality": "full_text|abstract_only"
}
```

### FR-05 综述生成

写作 Agent 只能读取已确认的笔记和文献元数据，不直接读取检索结果列表中的未验证摘要。

输出要求：

- 有标题、摘要、主题分段、结论、参考文献。
- 每个可验证事实后放至少一个 `[@citation_key]`。
- 不允许编造 DOI、页码、实验数值。
- 无证据的内容标记为“证据不足，需人工补充”，而不是自行补全。

### FR-06 双 Agent 引文核对

为每条引用生成一个 `Claim`，例如：

```json
{
  "claim_text": "界面钝化可以降低非辐射复合损失",
  "citation_keys": ["Hu_2024"],
  "location_in_review": "section_2.paragraph_3"
}
```

核对 Agent 只访问原始 PDF/文本 chunk 和元数据，不访问写作 Agent 的笔记。判定：

- `supported`：原文明确支持。
- `partially_supported`：方向支持，但范围、条件或强度不完全一致。
- `unsupported`：原文不支持或引用错配。
- `needs_human_review`：全文缺失、证据冲突或模型置信度不足。

## 5. 非功能需求（Demo 版）

- 单次任务支持 10–25 篇文献。
- 页面在任务运行期间可刷新，并能通过 `run_id` 恢复状态。
- 每个阶段失败可单独重试。
- 所有外部 API 请求保存请求参数、响应时间和错误信息。
- 结果可导出为 Markdown、JSON、BibTeX。
- 不把全文 PDF 或 API key 直接提交到 Git。

## 6. 推荐技术栈

### 最小可行组合

| 层 | 推荐 | 用途 |
|---|---|---|
| 前端 | Next.js 14/15 + TypeScript + Tailwind CSS | 表单、进度、笔记和核对表 |
| UI | shadcn/ui | 快速做卡片、标签、表格、步骤条 |
| 后端 | Python 3.11 + FastAPI | API、任务编排、文件下载 |
| Agent 编排 | LangGraph | 把 7 步流程做成可恢复状态图 |
| LLM | OpenAI Responses API；封装 provider interface | 关键词、笔记、写作、核对 |
| 数据库 | SQLite + SQLAlchemy/SQLModel | Demo 元数据、状态、笔记、核对结果 |
| 文件存储 | 本地 `storage/` 目录 | PDF、解析文本、导出文件 |
| PDF 解析 | PyMuPDF（fitz） | 页码级文本提取 |
| 元数据/检索 | OpenAlex + Crossref | 检索、DOI 和元数据补全 |
| 全文发现 | Unpaywall | 获取合法开放获取链接 |
| 实时进度 | SSE（Server-Sent Events） | 前端接收阶段状态和日志 |
| 测试 | pytest + Playwright | API、工作流和关键页面验收 |

### Demo 阶段不建议引入

- Celery/Redis：单用户 Demo 先用 LangGraph + FastAPI 后台任务即可。
- Elasticsearch/向量数据库：25 篇以内，按文献和 chunk 过滤足够。
- Kubernetes：本地 Docker Compose 即可。
- 多模型路由平台：先留一个 `LLMProvider` 抽象。

## 7. 系统架构

```text
Next.js
  │ REST + SSE
FastAPI
  ├── ReviewRun API
  ├── LangGraph Workflow
  │     ├── keyword_node
  │     ├── openalex_search_node
  │     ├── library_import_node
  │     ├── pdf_parse_node
  │     ├── note_node
  │     ├── review_writer_node
  │     └── citation_checker_node
  ├── LiteratureLibrary (Local / Zotero Adapter)
  ├── OpenAlex / Crossref / Unpaywall Clients
  ├── PyMuPDF Parser
  └── SQLite + storage/
```

工作流状态建议包含：`run_id`、当前节点、进度、文献列表、笔记、综述草稿、核对结果、错误列表。每个节点幂等：重复执行不会产生重复文献或重复笔记。

## 8. 核心数据模型

```text
review_runs
- id, topic, title, year_from, year_to, status, created_at, updated_at

review_keywords
- run_id, keyword_zh, keyword_en, selected, source(ai/user)

papers
- id, run_id, openalex_id, doi, title, abstract, year, cited_by_count
- authors_json, oa_url, pdf_path, citation_key, status

paper_chunks
- id, paper_id, page_number, text, char_start, char_end

paper_notes
- id, paper_id, note_json, source_quality, model_name

reviews
- id, run_id, markdown, word_count, citation_count

citation_checks
- id, review_id, claim_text, citation_keys_json, verdict
- evidence_json, confidence, needs_human_review
```

## 9. API 草案

```text
POST /api/runs
POST /api/runs/{run_id}/keywords/generate
POST /api/runs/{run_id}/keywords/estimate
POST /api/runs/{run_id}/search
POST /api/runs/{run_id}/papers/{paper_id}/retry
POST /api/runs/{run_id}/notes/generate
POST /api/runs/{run_id}/review/generate
POST /api/runs/{run_id}/citations/check
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/events   # SSE
GET  /api/runs/{run_id}/export?format=md|json|bibtex
```

## 10. 关键验收标准

一次成功 Demo 至少满足：

1. 输入一个中文主题，能生成并编辑中英文关键词。
2. 能显示 OpenAlex 命中数，并拉取至少 5 篇结果。
3. 每篇结果有唯一 citation key，且可以导出 BibTeX。
4. 至少 3 篇文献成功得到带页码证据的结构化笔记。
5. 综述正文中每个主要段落都有 `[@key]` 引用。
6. 引文核对表至少能返回支持/部分支持/不支持三类中的两类，并展示证据。
7. 删除一个 PDF 或让一次外部请求失败时，页面能显示失败原因并支持重试。

## 11. 建议开发顺序

### Sprint 1：先做可运行骨架

- Next.js 页面和 FastAPI。
- SQLite 数据模型。
- `ReviewRun` 状态和 SSE 进度。
- OpenAlex 检索与结果列表。

### Sprint 2：打通证据链

- Unpaywall 下载 PDF。
- PyMuPDF 按页解析。
- 结构化笔记和证据句。
- 本地文献库导出 BibTeX。

### Sprint 3：生成与核对

- 基于笔记的综述生成。
- Claim 抽取。
- 基于原文 chunk 的引文核对。
- 核对表、指标和 Markdown 导出。

### Sprint 4：演示打磨

- 失败重试、空结果提示、加载状态。
- 预置一个稳定主题作为 Demo fixture。
- 增加提示词版本、模型名和运行日志。
- Docker Compose 一键启动。

## 12. 主要风险与应对

| 风险 | 应对 |
|---|---|
| OpenAlex 有记录但没有全文 | 明确标记摘要模式；不伪造页码；进入人工复核 |
| PDF 是扫描件 | Demo 先提示 OCR 不支持；后续接 PaddleOCR 或 GROBID |
| 模型把多个观点混成一条引用 | 先做 claim 拆分，再逐条核对 |
| 引文 key 冲突 | key 生成器加作者、年份和短哈希 |
| 外部 API 限流/超时 | 指数退避、缓存原始响应、节点级重试 |
| 综述内容过长超出上下文 | 先按主题聚合笔记，再分段写作，最后合并 |
| “核对 Agent 不看笔记”难以证明 | 代码层面给核对节点独立输入，只注入原文 chunk 和元数据 |

## 13. 作品集/面试中的产品表述

> 我没有把它设计成一个“一次调用大模型写文章”的功能，而是把它拆成检索、入库、证据化精读、受约束写作和独立引文核对五个可观测阶段。Demo 阶段先用本地文献库保证闭环，保留 Zotero 适配器；通过页码级证据和独立核对 Agent，把“引用看起来合理”变成“每条引用都有可回溯证据”。

## 14. 对另一版技术栈建议的评估

DeepSeek 给出的方案整体方向是对的，尤其是 LangGraph、FastAPI、SQLite、Streamlit 和分阶段开发路线。但建议按 Demo 和生产两个阶段拆开，不要一次性引入所有组件。

### 14.1 可以直接参考

| 建议 | 结论 | 说明 |
|---|---|---|
| Python | 采纳 | AI、PDF、学术 API 生态成熟 |
| LangGraph | 采纳 | 适合有状态、可重试、可暂停的流程 |
| FastAPI | 采纳 | 后续从 Streamlit 拆前后端时可复用 |
| SQLite | 采纳 | Demo 保存任务状态、文献、笔记和缓存足够 |
| Streamlit | Demo 可采纳 | 最快做出可演示界面，适合个人作品集 |
| 分阶段开发 | 强烈采纳 | 每阶段都有独立验收标准，降低返工风险 |

### 14.2 建议后置

| 组件 | 为什么后置 |
|---|---|
| Qdrant | 25 篇文献以内，结构化笔记和 chunk 过滤足够；真正出现上下文超限时再引入向量检索 |
| LangChain | LangGraph 可以直接调用模型和工具；Demo 阶段同时引入两层抽象会增加调试成本 |
| ARQ + Redis | 适合多任务、长任务和多进程部署；单用户 Demo 先用 FastAPI 后台任务或 LangGraph runner |
| sentence-transformers | 只有在做语义检索、相似文献去重或聚类时才需要 |
| Streamlit Cloud | 先本地 Docker 跑通；PDF、API Key、长任务和持久化存储需要先验证部署限制 |

### 14.3 需要验证后再选

- `oalex`：建议先确认包的维护状态、接口覆盖、异步能力和返回模型。若文档或社区不稳定，直接用 `httpx` 封装 OpenAlex REST API，或使用维护更稳定的 Python 客户端。
- `zotero-bridge`：建议先确认是否支持当前 Zotero Web API、附件上传、去重和失败重试。Demo 可以先做本地 `LiteratureLibrary`，再实现 `ZoteroAdapter`。
- `CLAP`、`OmniCoreAgent`：不是本项目 Demo 的必要依赖。LangGraph 已能覆盖节点、条件分支、状态持久化和人工确认。
- GPT-4o、Claude、Gemini、DeepSeek：不要把模型名写死在业务节点中，统一封装 `LLMProvider`，按“关键词/笔记/写作/核对”分别配置模型。

### 14.4 两种合理的 Demo 路线

#### 路线 A：最快展示型

```text
Streamlit + Python + LangGraph + SQLite
        ├── OpenAlex REST API
        ├── Unpaywall / Crossref
        ├── PyMuPDF
        └── 本地文件库（可导出 BibTeX）
```

适合一到两周内做出可点击演示，部署和调试成本最低。

#### 路线 B：可扩展产品型

```text
Next.js + FastAPI + LangGraph + SQLite/PostgreSQL
        ├── SSE 进度推送
        ├── LiteratureLibrary / ZoteroAdapter
        └── 后续按需加入 Redis、ARQ、Qdrant
```

适合准备继续迭代为正式产品，但第一版开发量更大。

对于当前目标“先实现一个 Demo”，建议选路线 A；如果你希望把项目作为前后端工程能力作品集，再选路线 B。

