import sqlite3
import json
from contextlib import contextmanager
from typing import Iterator

from .config import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS review_runs (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    openalex_id TEXT,
    doi TEXT,
    title TEXT NOT NULL,
    abstract TEXT,
    year INTEGER,
    cited_by_count INTEGER DEFAULT 0,
    authors_json TEXT,
    oa_url TEXT,
    pdf_path TEXT,
    citation_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'discovered',
    UNIQUE(run_id, citation_key),
    FOREIGN KEY(run_id) REFERENCES review_runs(id)
);

CREATE TABLE IF NOT EXISTS paper_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    page_number INTEGER,
    text TEXT NOT NULL,
    char_start INTEGER,
    char_end INTEGER,
    FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE TABLE IF NOT EXISTS paper_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL UNIQUE,
    note_json TEXT NOT NULL,
    source_quality TEXT NOT NULL,
    model_name TEXT,
    FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    markdown TEXT NOT NULL,
    word_count INTEGER DEFAULT 0,
    citation_count INTEGER DEFAULT 0,
    FOREIGN KEY(run_id) REFERENCES review_runs(id)
);

CREATE TABLE IF NOT EXISTS citation_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL,
    claim_text TEXT NOT NULL,
    citation_keys_json TEXT NOT NULL,
    verdict TEXT NOT NULL,
    evidence_json TEXT,
    confidence REAL,
    needs_human_review INTEGER DEFAULT 0,
    FOREIGN KEY(review_id) REFERENCES reviews(id)
);
"""


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(get_settings().database_path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(SCHEMA)


def create_review_run(run_id: str, topic: str, title: str | None = None) -> None:
    with get_connection() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO review_runs (id, topic, title, status) VALUES (?, ?, ?, ?)",
            (run_id, topic, title, "created"),
        )


def save_papers(run_id: str, papers: list[dict]) -> None:
    with get_connection() as connection:
        for paper in papers:
            connection.execute(
                """
                INSERT OR IGNORE INTO papers
                (run_id, openalex_id, doi, title, abstract, year, cited_by_count,
                 authors_json, oa_url, citation_key, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    paper.get("openalex_id"),
                    paper.get("doi"),
                    paper.get("title", "未命名论文"),
                    paper.get("abstract", ""),
                    paper.get("year"),
                    paper.get("cited_by_count", 0),
                    json.dumps(paper.get("authors", []), ensure_ascii=False),
                    paper.get("oa_url"),
                    paper["citation_key"],
                    "discovered",
                ),
            )


def update_paper_download(
    run_id: str,
    citation_key: str,
    status: str,
    pdf_path: str | None = None,
    oa_url: str | None = None,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE papers
            SET status = ?, pdf_path = COALESCE(?, pdf_path), oa_url = COALESCE(?, oa_url)
            WHERE run_id = ? AND citation_key = ?
            """,
            (status, pdf_path, oa_url, run_id, citation_key),
        )


def get_paper_id(run_id: str, citation_key: str) -> int | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id FROM papers WHERE run_id = ? AND citation_key = ?",
            (run_id, citation_key),
        ).fetchone()
    return int(row["id"]) if row else None


def replace_paper_chunks(paper_id: int, chunks: list[dict]) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM paper_chunks WHERE paper_id = ?", (paper_id,))
        connection.executemany(
            """
            INSERT INTO paper_chunks (paper_id, page_number, text, char_start, char_end)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    paper_id,
                    chunk["page_number"],
                    chunk["text"],
                    chunk["char_start"],
                    chunk["char_end"],
                )
                for chunk in chunks
            ],
        )


def update_paper_status(run_id: str, citation_key: str, status: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE papers SET status = ? WHERE run_id = ? AND citation_key = ?",
            (status, run_id, citation_key),
        )


def get_paper_chunks(paper_id: int) -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT page_number, text, char_start, char_end
            FROM paper_chunks
            WHERE paper_id = ?
            ORDER BY page_number, char_start
            """,
            (paper_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def save_paper_note(
    paper_id: int,
    note_json: str,
    source_quality: str,
    model_name: str,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO paper_notes (paper_id, note_json, source_quality, model_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(paper_id) DO UPDATE SET
                note_json = excluded.note_json,
                source_quality = excluded.source_quality,
                model_name = excluded.model_name
            """,
            (paper_id, note_json, source_quality, model_name),
        )


def get_run_notes(run_id: str) -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT p.citation_key, p.title, p.year, p.authors_json, n.note_json
            FROM papers p
            JOIN paper_notes n ON n.paper_id = p.id
            WHERE p.run_id = ?
            ORDER BY p.citation_key
            """,
            (run_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["authors"] = json.loads(item.pop("authors_json") or "[]")
        return_note = item["note_json"]
        item["note_json"] = return_note
        result.append(item)
    return result


def save_review(run_id: str, markdown: str, citation_count: int) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO reviews (run_id, markdown, word_count, citation_count)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, markdown, len(markdown.split()), citation_count),
        )
        return int(cursor.lastrowid)


def get_chunks_for_citations(run_id: str, citation_keys: list[str]) -> list[dict]:
    if not citation_keys:
        return []
    placeholders = ",".join("?" for _ in citation_keys)
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT p.citation_key, c.page_number, c.text, c.char_start, c.char_end
            FROM papers p
            JOIN paper_chunks c ON c.paper_id = p.id
            WHERE p.run_id = ? AND p.citation_key IN ({placeholders})
            ORDER BY p.citation_key, c.page_number, c.char_start
            """,
            [run_id, *citation_keys],
        ).fetchall()
    return [dict(row) for row in rows]


def save_citation_check(
    review_id: int,
    claim_text: str,
    citation_keys: list[str],
    result: dict,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO citation_checks
            (review_id, claim_text, citation_keys_json, verdict, evidence_json,
             confidence, needs_human_review)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                claim_text,
                json.dumps(citation_keys, ensure_ascii=False),
                result.get("verdict", "needs_human_review"),
                json.dumps(result.get("evidence", []), ensure_ascii=False),
                float(result.get("confidence", 0.0)),
                int(bool(result.get("needs_human_review", False))),
            ),
        )

