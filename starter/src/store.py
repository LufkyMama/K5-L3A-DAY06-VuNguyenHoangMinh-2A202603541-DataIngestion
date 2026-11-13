"""Store and search vectors using PostgreSQL + pgvector."""
import json
from typing import Any

import psycopg

from .models import Chunk

TABLE = "chunks"
# Only these columns may be used in filters; values are always passed as SQL parameters.
FILTER_COLUMNS = {"document_id", "page", "chapter", "chapter_number"}


def _vector_literal(vector: list[float]) -> str:
    """pgvector text format, e.g. '[0.1,0.2]'; avoids an extra client dependency."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class PgVectorStore:
    """One table for all strategies; (strategy, chunk_id) is the primary key.

    Search is exact (no ANN index): the corpus is small, and exact search keeps filtered
    results complete, which an approximate index does not guarantee.
    """

    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is empty; set it in starter/.env")
        if dimensions <= 0:
            raise ValueError(f"invalid embedding dimensions: {dimensions}")
        self.database_url = database_url
        self.dimensions = dimensions

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, connect_timeout=5)

    def create_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    strategy       text    NOT NULL,
                    chunk_id       text    NOT NULL,
                    document_id    text    NOT NULL,
                    source         text    NOT NULL,
                    page           integer NOT NULL,
                    chapter        text,
                    chapter_number integer,
                    text           text    NOT NULL,
                    metadata       jsonb   NOT NULL DEFAULT '{{}}',
                    embedding      vector({self.dimensions}) NOT NULL,
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            # An existing table built for another model would silently break search; fail instead.
            row = conn.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = %s::regclass AND attname = 'embedding'", (TABLE,)).fetchone()
            if row[0] != f"vector({self.dimensions})":
                raise RuntimeError(f"table {TABLE} has {row[0]}, model needs vector({self.dimensions})")

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Insert or update chunks by stable ID, then delete this strategy's obsolete chunks
        for the same documents (e.g. after a source document or chunk setting changed)."""
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        if any(len(v) != self.dimensions for v in vectors):
            raise ValueError(f"every vector must have {self.dimensions} dimensions")
        ids = [c.chunk_id for c in chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate chunk IDs in one upsert")
        rows = [(strategy, c.chunk_id, c.document_id, c.source, c.page,
                 c.metadata.get("chapter"), c.metadata.get("chapter_number"),
                 c.text, json.dumps(c.metadata), _vector_literal(v))
                for c, v in zip(chunks, vectors)]
        with self._connect() as conn:  # one transaction: all rows or none
            with conn.cursor() as cur:
                cur.executemany(f"""
                    INSERT INTO {TABLE} (strategy, chunk_id, document_id, source, page, chapter,
                                         chapter_number, text, metadata, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector)
                    ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                        document_id = EXCLUDED.document_id, source = EXCLUDED.source,
                        page = EXCLUDED.page, chapter = EXCLUDED.chapter,
                        chapter_number = EXCLUDED.chapter_number, text = EXCLUDED.text,
                        metadata = EXCLUDED.metadata, embedding = EXCLUDED.embedding""", rows)
                cur.execute(
                    f"DELETE FROM {TABLE} WHERE strategy = %s AND document_id = ANY(%s) "
                    "AND NOT (chunk_id = ANY(%s))",
                    (strategy, sorted({c.document_id for c in chunks}), ids))

    def count(self, strategy: str) -> int:
        with self._connect() as conn:
            return conn.execute(f"SELECT count(*) FROM {TABLE} WHERE strategy = %s", (strategy,)).fetchone()[0]

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Rank by cosine distance (<=>); score = cosine similarity = 1 - distance."""
        if len(query_vector) != self.dimensions:
            raise ValueError(f"query vector must have {self.dimensions} dimensions")
        filters = filters or {}
        unknown = set(filters) - FILTER_COLUMNS
        if unknown:
            raise ValueError(f"filter keys not allowed: {sorted(unknown)}")
        where = ["strategy = %s"] + [f"{column} = %s" for column in filters]
        query = _vector_literal(query_vector)
        params = [query, strategy, *filters.values(), query, top_k]
        sql = (f"SELECT chunk_id, document_id, source, page, text, metadata, "
               f"1 - (embedding <=> %s::vector) AS score FROM {TABLE} "
               f"WHERE {' AND '.join(where)} ORDER BY embedding <=> %s::vector LIMIT %s")
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [{"chunk_id": r[0], "document_id": r[1], "source": r[2], "page": r[3],
                 "text": r[4], "metadata": r[5], "score": float(r[6])} for r in rows]
