"""SQLite schema — chunks / chunks_vec (sqlite-vec) / chunks_fts (FTS5) / embedding_cache / files / meta

设计来自 OpenClaw memory-core：
- chunk ID = sha256(path + start_line + end_line + text) 确保幂等 upsert
- chunks.model 字段标注 embedding 模型，切模型时 WHERE model != ? 识别过期 chunks
- embedding_cache 以 (provider, model, text_hash) 为 key，重建索引零 API 调用
"""


def init_schema(conn):
    """创建所有非向量表（向量表需单独用 try_init_vec_table）"""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS chunks (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        path TEXT NOT NULL,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        text TEXT NOT NULL,
        text_hash TEXT NOT NULL,
        model TEXT NOT NULL,
        embedding_fallback TEXT,
        updated_at INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source);
    CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
    CREATE INDEX IF NOT EXISTS idx_chunks_updated ON chunks(updated_at);
    CREATE INDEX IF NOT EXISTS idx_chunks_model ON chunks(model);

    CREATE TABLE IF NOT EXISTS files (
        path TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        mtime REAL NOT NULL,
        size INTEGER NOT NULL,
        chunk_count INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS embedding_cache (
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        text_hash TEXT NOT NULL,
        embedding TEXT NOT NULL,
        dims INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY (provider, model, text_hash)
    );

    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)

    # FTS5
    conn.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        text,
        id UNINDEXED,
        source UNINDEXED,
        path UNINDEXED,
        tokenize = 'trigram'
    )
    """)

    conn.commit()


def try_init_vec_table(conn, dims: int) -> bool:
    """尝试创建 sqlite-vec 虚拟表。失败返回 False — 调用方应硬失败而非静默降级。"""
    try:
        conn.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
            id TEXT PRIMARY KEY,
            embedding FLOAT[{dims}]
        )
        """)
        conn.commit()
        return True
    except Exception as e:
        print(f"[Knowledge/schema] 无法创建 chunks_vec（dims={dims}）: {e}")
        return False


def get_meta(conn, key: str) -> str | None:
    cur = conn.execute("SELECT value FROM meta WHERE key = ?", (key,))
    row = cur.fetchone()
    return row[0] if row else None


def set_meta(conn, key: str, value: str):
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
