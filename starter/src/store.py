"""PostgreSQL + pgvector store, one row per (strategy, chunk)."""
from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .models import Chunk

# Metadata keys a caller may filter on, mapped to their SQL column. Only these
# column names are ever interpolated into SQL; all values are parameters.
FILTERABLE = {"chapter": "chapter"}


def _vec(v: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is empty")
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError("dimensions must be a positive int")
        self.database_url = database_url
        self.dimensions = dimensions

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, connect_timeout=5)

    def create_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    strategy      text    NOT NULL,
                    chunk_id      text    NOT NULL,
                    document_id   text    NOT NULL,
                    source        text    NOT NULL,
                    page          int     NOT NULL,
                    chapter       int,
                    section       text,
                    text          text    NOT NULL,
                    content_hash  text    NOT NULL,
                    metadata      jsonb   NOT NULL DEFAULT '{{}}',
                    embedding     vector({self.dimensions}) NOT NULL,
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            row = conn.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'").fetchone()
            if row[0] != f"vector({self.dimensions})":
                raise RuntimeError(f"existing chunks.embedding is {row[0]}, model needs "
                                   f"vector({self.dimensions}); drop the table to change model")

    def existing_hashes(self, strategy: str) -> dict[str, str]:
        """chunk_id -> content_hash currently stored for this strategy."""
        with self._connect() as conn:
            rows = conn.execute("SELECT chunk_id, content_hash FROM chunks WHERE strategy = %s",
                                (strategy,)).fetchall()
        return dict(rows)

    def vectors_by_hash(self, hashes: list[str]) -> dict[str, list[float]]:
        """Reuse stored vectors for identical text (e.g. strategy C reuses B)."""
        if not hashes:
            return {}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT ON (content_hash) content_hash, embedding::text "
                "FROM chunks WHERE content_hash = ANY(%s)", (list(hashes),)).fetchall()
        return {h: json.loads(v) for h, v in rows}

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Insert or update rows keyed by (strategy, chunk_id); never duplicates."""
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        if any(len(v) != self.dimensions for v in vectors):
            raise ValueError(f"every vector must have {self.dimensions} dimensions")
        if len({c.chunk_id for c in chunks}) != len(chunks):
            raise ValueError("duplicate chunk_id in batch")
        rows = [(strategy, c.chunk_id, c.document_id, c.source, c.page,
                 c.metadata.get("chapter"), "; ".join(c.metadata.get("sections", [])),
                 c.text, c.metadata["content_hash"], Jsonb(c.metadata), _vec(v))
                for c, v in zip(chunks, vectors)]
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO chunks (strategy, chunk_id, document_id, source, page, chapter,
                                    section, text, content_hash, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id, source = EXCLUDED.source,
                    page = EXCLUDED.page, chapter = EXCLUDED.chapter,
                    section = EXCLUDED.section, text = EXCLUDED.text,
                    content_hash = EXCLUDED.content_hash, metadata = EXCLUDED.metadata,
                    embedding = EXCLUDED.embedding""", rows)

    def delete_obsolete(self, strategy: str, document_ids: list[str], keep: set[str]) -> int:
        """Remove rows of these documents that are no longer produced by the chunker."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM chunks WHERE strategy = %s AND document_id = ANY(%s) "
                "AND NOT (chunk_id = ANY(%s))", (strategy, document_ids, list(keep)))
            return cur.rowcount

    def count(self) -> dict[str, int]:
        with self._connect() as conn:
            return dict(conn.execute(
                "SELECT strategy, count(*) FROM chunks GROUP BY 1 ORDER BY 1").fetchall())

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Exact cosine search (no ANN index) within one strategy, optional filters."""
        if len(query_vector) != self.dimensions:
            raise ValueError(f"query vector must have {self.dimensions} dimensions")
        where, params = ["strategy = %s"], [strategy]
        for key, value in (filters or {}).items():
            if key not in FILTERABLE:
                raise ValueError(f"filter key {key!r} not allowed; allowed: {sorted(FILTERABLE)}")
            where.append(f"{FILTERABLE[key]} = %s")
            params.append(value)
        qv = _vec(query_vector)
        sql = (f"SELECT chunk_id, document_id, source, page, chapter, section, text, metadata, "
               f"1 - (embedding <=> %s::vector) AS score FROM chunks "
               f"WHERE {' AND '.join(where)} ORDER BY embedding <=> %s::vector, chunk_id LIMIT %s")
        with self._connect() as conn:
            rows = conn.execute(sql, [qv, *params, qv, top_k]).fetchall()
        return [{"chunk_id": r[0], "document_id": r[1], "source": r[2], "page": r[3],
                 "chapter": r[4], "section": r[5], "text": r[6], "metadata": r[7],
                 "score": float(r[8])} for r in rows]
