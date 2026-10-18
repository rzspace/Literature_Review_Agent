# SciencePRO 文献综述 Agent Demo

这是一个先跑通“检索—证据—生成—核对”闭环的 Streamlit Demo。

## 当前阶段

第 1 步：项目初始化、配置读取和 SQLite 初始化。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

启动后打开 Streamlit 输出的本地地址。

## 目录说明

```text
app.py                 Streamlit 入口
src/config.py          环境变量与配置
src/db.py              SQLite 初始化与基础操作
src/llm/               DeepSeek/OpenAI 兼容客户端
src/search/            OpenAlex、Crossref、Unpaywall 客户端
src/papers/            文献入库与 PDF 管理
src/notes/             PDF 解析与精读笔记
src/review/            综述生成与引文核对
data/                  SQLite、PDF 和导出文件
```

## 安全提醒

不要提交 `.env`，也不要把 API Key 写入代码或提交到 Git。

## 部署到 Streamlit Community Cloud

1. 将项目上传到 GitHub，确认 `.env`、`data/app.db` 和 `data/pdfs/` 没有进入仓库。
2. 在 Streamlit Community Cloud 中选择仓库，入口文件填写 `app.py`。
3. 在应用的 **Settings → Secrets** 中填写：

```toml
LLM_PROVIDER = "deepseek"
DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

OPENALEX_API_KEY = "你的 OpenAlex API Key"
OPENALEX_EMAIL = "你的邮箱"
UNPAYWALL_EMAIL = "你的邮箱"
CROSSREF_EMAIL = "你的邮箱"

# 强烈建议公开演示时设置，避免陌生人消耗 API 额度
APP_PASSWORD = "你设置的访问密码"
```

根级 Secrets 会作为环境变量提供给应用，因此不需要在云端创建 `.env`。

### 云端限制

- SQLite 和上传的 PDF 位于临时磁盘，应用重启后可能丢失。
- DeepSeek 调用费用由 API Key 所属账户承担。
- 当前版本适合作品集和小范围体验，不适合作为多用户生产系统。

