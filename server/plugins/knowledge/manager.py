"""Knowledge Manager — 协调 schema / chunking / embedding / hybrid / mmr / decay"""

import asyncio
import hashlib
import json
import sqlite3
import struct
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from server.config import DATA_DIR
from server.plugins.knowledge import schema, chunking, hybrid, mmr, temporal_decay
from server.plugins.knowledge.chunking import Chunk, chunk_markdown, chunk_id, split_by_byte_limit
from server.plugins.knowledge.embeddings import EmbeddingManager
from server.plugins.knowledge.hybrid import HybridResult, cosine_distance_to_similarity, bm25_rank_to_score


_SOURCE_FILE_MAP = {
    "memory": "data/memory/memory_detail.md",
    "projects": "data/memory/projects_detail.md",
}


def _vec_to_bytes(vec: list[float]) -> bytes:
    """sqlite-vec FLOAT[N] 期望的二进制格式 = 小端 float32 数组"""
    return struct.pack(f"{len(vec)}f", *vec)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:24]


def _try_load_sqlite_vec(conn) -> bool:
    """加载 sqlite-vec extension"""
    try:
        import sqlite_vec
    except ImportError:
        print("[Knowledge] sqlite-vec 未安装（pip install sqlite-vec）— 向量检索不可用")
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception as e:
        print(f"[Knowledge] 加载 sqlite-vec 失败: {e}")
        return False


class KnowledgeManager:
    def __init__(self, config):
        self.config = config
        self.db_path = DATA_DIR / "knowledge.db"
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._vec_available = _try_load_sqlite_vec(self.conn)

        schema.init_schema(self.conn)
        self.embedder = EmbeddingManager(config, self.conn)
        self._vec_table_ready = False

        self._indexing_lock = asyncio.Lock()

    async def _ensure_vec_table(self, dims: int):
        if self._vec_table_ready:
            return
        if not self._vec_available:
            raise RuntimeError(
                "sqlite-vec 不可用 — 请 pip install sqlite-vec，否则无法使用向量检索"
            )
        ok = schema.try_init_vec_table(self.conn, dims)
        if not ok:
            raise RuntimeError(f"创建 chunks_vec 失败（dims={dims}）")
        self._vec_table_ready = True

    async def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    # ============== Index ==============

    def _default_source_paths(self) -> list[tuple[str, Path]]:
        """返回所有默认索引源文件列表 [(source, absolute_path), ...]"""
        from server.config import PROJECT_ROOT
        out = []
        for source, rel in _SOURCE_FILE_MAP.items():
            p = PROJECT_ROOT / rel
            if p.exists():
                out.append((source, p))
        # 知识库目录 (多文件)
        kb_dir = self.config.get("knowledge", "knowledge_dir", default="data/knowledge")
        kb = PROJECT_ROOT / kb_dir
        if kb.is_dir():
            for md in kb.rglob("*.md"):
                out.append(("knowledge", md))
            for txt in kb.rglob("*.txt"):
                out.append(("knowledge", txt))
        return out

    async def _index_file(self, source: str, path: Path):
        """索引单个文件 — 基于 content_hash 跳过已索引"""
        if not path.exists():
            return {"skipped": True, "reason": "file not found"}

        current_hash = _file_hash(path)
        mtime = path.stat().st_mtime
        size = path.stat().st_size
        rel_path = str(path)

        # 检查 files 表
        cur = self.conn.execute(
            "SELECT content_hash FROM files WHERE path=?", (rel_path,)
        )
        row = cur.fetchone()
        if row and row[0] == current_hash:
            return {"skipped": True, "reason": "unchanged"}

        text = path.read_text(encoding="utf-8", errors="replace")
        target_tokens = self.config.get("knowledge", "chunk_tokens", default=1024)
        overlap_tokens = self.config.get("knowledge", "chunk_overlap", default=160)
        chunks = chunk_markdown(text, target_tokens, overlap_tokens)

        if not chunks:
            # 空文件 — 仍记录
            now = int(time.time())
            self.conn.execute(
                "INSERT INTO files(path, source, content_hash, mtime, size, chunk_count, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?) ON CONFLICT(path) DO UPDATE SET "
                "content_hash=excluded.content_hash, mtime=excluded.mtime, size=excluded.size, "
                "chunk_count=0, updated_at=excluded.updated_at",
                (rel_path, source, current_hash, mtime, size, 0, now),
            )
            self._delete_chunks_for_path(rel_path)
            self.conn.commit()
            return {"chunks": 0}

        # 获取 embeddings（批量 + cache）
        texts_for_embed = []
        for ch in chunks:
            for sub in split_by_byte_limit(ch.text):
                texts_for_embed.append(sub)

        # 简化：每个 chunk 只 embed 第一片（足够表示）
        chunk_first_texts = [chunks[i].text[:32000] for i in range(len(chunks))]
        vecs, provider_name, dims = await self.embedder.embed_cached(chunk_first_texts)
        await self._ensure_vec_table(dims)
        model_tag = f"{provider_name}:{self.embedder.active.model}"

        now = int(time.time())

        # 先删除此 path 的旧 chunks（含 vec + fts）
        self._delete_chunks_for_path(rel_path)

        # 批量插入
        for ch, vec in zip(chunks, vecs):
            cid = chunk_id(source, rel_path, ch)
            self.conn.execute(
                "INSERT INTO chunks(id, source, path, start_line, end_line, text, text_hash, "
                "model, embedding_fallback, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, source, rel_path, ch.start_line, ch.end_line, ch.text, ch.text_hash,
                 model_tag, json.dumps(vec), now),
            )
            if self._vec_available and self._vec_table_ready:
                try:
                    self.conn.execute(
                        "INSERT INTO chunks_vec(id, embedding) VALUES(?, ?)",
                        (cid, _vec_to_bytes(vec)),
                    )
                except Exception as e:
                    # sqlite-vec 的 dims 不匹配等错误
                    print(f"[Knowledge] chunks_vec 插入失败（dims={dims}）: {e}")
            self.conn.execute(
                "INSERT INTO chunks_fts(text, id, source, path) VALUES(?, ?, ?, ?)",
                (ch.text, cid, source, rel_path),
            )

        # 更新 files
        self.conn.execute(
            "INSERT INTO files(path, source, content_hash, mtime, size, chunk_count, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?) ON CONFLICT(path) DO UPDATE SET "
            "content_hash=excluded.content_hash, mtime=excluded.mtime, size=excluded.size, "
            "chunk_count=excluded.chunk_count, updated_at=excluded.updated_at",
            (rel_path, source, current_hash, mtime, size, len(chunks), now),
        )
        self.conn.commit()
        return {"chunks": len(chunks), "provider": provider_name}

    def _delete_chunks_for_path(self, path: str):
        cur = self.conn.execute("SELECT id FROM chunks WHERE path=?", (path,))
        ids = [r[0] for r in cur.fetchall()]
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        self.conn.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", ids)
        if self._vec_available and self._vec_table_ready:
            try:
                self.conn.execute(f"DELETE FROM chunks_vec WHERE id IN ({placeholders})", ids)
            except Exception:
                pass
        self.conn.execute(f"DELETE FROM chunks_fts WHERE id IN ({placeholders})", ids)

    async def reindex(self, source: Optional[str] = None, path: Optional[str] = None) -> dict:
        async with self._indexing_lock:
            if path:
                # 单文件
                p = Path(path)
                if not p.is_absolute():
                    from server.config import PROJECT_ROOT
                    p = (PROJECT_ROOT / path).resolve()
                # 尝试从 files 表推断 source
                row = self.conn.execute("SELECT source FROM files WHERE path=?", (str(p),)).fetchone()
                src = source or (row[0] if row else "knowledge")
                res = await self._index_file(src, p)
                return {"indexed": [str(p)], "result": res}

            results = {}
            targets = self._default_source_paths()
            if source:
                targets = [(s, p) for s, p in targets if s == source]
            for src, p in targets:
                try:
                    r = await self._index_file(src, p)
                    results[str(p)] = r
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    results[str(p)] = {"error": str(e)}
            return {"indexed": len(results), "details": results}

    # ============== Search ==============

    async def search(
        self,
        query: str,
        top_k: int = 5,
        source: Optional[str] = None,
        min_score: Optional[float] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> list[dict]:
        if not query or not query.strip():
            return []

        candidate_mult = 4
        candidates_limit = min(200, max(top_k * candidate_mult, 20))

        vec_results: list[HybridResult] = []
        bm25_results: list[HybridResult] = []

        # 向量检索（如果可用）
        if self._vec_available and self._vec_table_ready:
            try:
                qvecs, _, dims = await self.embedder.embed_cached([query])
                qvec = qvecs[0]
                vec_results = await asyncio.to_thread(
                    self._vec_search, qvec, candidates_limit, source, date_start, date_end
                )
            except Exception as e:
                print(f"[Knowledge/search] 向量检索失败: {e}")

        # FTS5 检索
        try:
            bm25_results = await asyncio.to_thread(
                self._fts_search, query, candidates_limit, source, date_start, date_end
            )
        except Exception as e:
            print(f"[Knowledge/search] FTS 检索失败: {e}")

        vec_weight = self.config.get("knowledge", "hybrid_vec_weight", default=0.7)
        bm25_weight = self.config.get("knowledge", "hybrid_bm25_weight", default=0.3)

        merged = hybrid.merge_hybrid_results(vec_results, bm25_results, vec_weight, bm25_weight)

        # 时间衰减
        half_life = self.config.get("memory", "temporal_half_life_days", default=30)
        temporal_decay.apply_decay(merged, half_life_days=half_life)
        merged.sort(key=lambda r: r.hybrid_score, reverse=True)

        # 阈值过滤
        threshold = min_score if min_score is not None else self.config.get(
            "knowledge", "min_score", default=0.2
        )
        merged = [r for r in merged if r.hybrid_score >= threshold]

        # MMR 重排
        if self.config.get("knowledge", "mmr_enabled", default=True) and merged:
            lam = self.config.get("knowledge", "mmr_lambda", default=0.6)
            merged = mmr.mmr_rerank(merged, top_k, lambda_=lam)
        else:
            merged = merged[:top_k]

        return [
            {
                "id": r.id,
                "source": r.source,
                "path": r.path,
                "text": r.text,
                "start_line": r.start_line,
                "end_line": r.end_line,
                "score": round(r.hybrid_score, 4),
                "vec_score": round(r.vec_score, 4),
                "bm25_score": round(r.bm25_score, 4),
                "updated_at": r.updated_at,
            }
            for r in merged
        ]

    def _date_filter_sql(
        self, date_start: Optional[str], date_end: Optional[str], prefix: str = "c"
    ) -> tuple[str, list]:
        conds = []
        params = []
        if date_start:
            try:
                ts = int(datetime.fromisoformat(date_start).timestamp())
                conds.append(f"{prefix}.updated_at >= ?")
                params.append(ts)
            except ValueError:
                pass
        if date_end:
            try:
                ts = int(datetime.fromisoformat(date_end).timestamp()) + 86400
                conds.append(f"{prefix}.updated_at <= ?")
                params.append(ts)
            except ValueError:
                pass
        return (" AND ".join(conds) if conds else ""), params

    def _vec_search(self, qvec: list[float], k: int, source, date_start, date_end) -> list[HybridResult]:
        qbytes = _vec_to_bytes(qvec)
        date_sql, date_params = self._date_filter_sql(date_start, date_end)

        where_extra = ""
        extra_params = []
        if source:
            where_extra += " AND c.source = ?"
            extra_params.append(source)
        if date_sql:
            where_extra += f" AND {date_sql}"
            extra_params.extend(date_params)

        sql = f"""
        SELECT c.id, c.source, c.path, c.text, c.start_line, c.end_line, c.updated_at, v.distance
        FROM chunks_vec v
        JOIN chunks c ON c.id = v.id
        WHERE v.embedding MATCH ? AND k = ? {where_extra}
        ORDER BY v.distance ASC
        """
        cur = self.conn.execute(sql, (qbytes, k, *extra_params))
        out = []
        for row in cur.fetchall():
            out.append(HybridResult(
                id=row[0], source=row[1], path=row[2], text=row[3],
                start_line=row[4], end_line=row[5], updated_at=row[6],
                vec_score=cosine_distance_to_similarity(row[7]),
                bm25_score=0.0,
            ))
        return out

    def _fts_search(self, query: str, k: int, source, date_start, date_end) -> list[HybridResult]:
        date_sql, date_params = self._date_filter_sql(date_start, date_end)
        where_extra = ""
        extra_params = []
        if source:
            where_extra += " AND c.source = ?"
            extra_params.append(source)
        if date_sql:
            where_extra += f" AND {date_sql}"
            extra_params.extend(date_params)

        # FTS5 查询语法 — 简单转义引号
        q = query.replace('"', '""')
        sql = f"""
        SELECT c.id, c.source, c.path, c.text, c.start_line, c.end_line, c.updated_at,
               bm25(chunks_fts) AS rank_val
        FROM chunks_fts f
        JOIN chunks c ON c.id = f.id
        WHERE chunks_fts MATCH ? {where_extra}
        ORDER BY rank_val ASC
        LIMIT ?
        """
        try:
            cur = self.conn.execute(sql, (f'"{q}"', *extra_params, k))
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            return []

        out = []
        for row in rows:
            out.append(HybridResult(
                id=row[0], source=row[1], path=row[2], text=row[3],
                start_line=row[4], end_line=row[5], updated_at=row[6],
                vec_score=0.0,
                bm25_score=bm25_rank_to_score(row[7] or 0),
            ))
        return out

    # ============== Stats ==============

    def stats(self) -> dict:
        cur = self.conn.execute("SELECT source, COUNT(*), SUM(LENGTH(text)) FROM chunks GROUP BY source")
        by_source = {row[0]: {"chunks": row[1], "chars": row[2] or 0} for row in cur.fetchall()}
        cur = self.conn.execute("SELECT COUNT(*) FROM chunks")
        total_chunks = cur.fetchone()[0]
        cur = self.conn.execute("SELECT COUNT(*) FROM files")
        total_files = cur.fetchone()[0]
        cur = self.conn.execute("SELECT COUNT(*) FROM embedding_cache")
        cache_size = cur.fetchone()[0]
        return {
            "total_chunks": total_chunks,
            "total_files": total_files,
            "embedding_cache_size": cache_size,
            "by_source": by_source,
            "vec_available": self._vec_available,
            "db_path": str(self.db_path),
            "db_size_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0,
        }
