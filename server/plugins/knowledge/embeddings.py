"""多 provider embedding 抽象 — auto fallback + 缓存

支持：
- local (llama-cpp-python + embeddinggemma GGUF)
- openai (text-embedding-3-small)
- voyage
- mistral
- google

依赖是 lazy import，没装对应库时只是跳过该 provider。
"""

import asyncio
import hashlib
import json
import time
from typing import Protocol


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dims: int

    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...


# ============== 本地 GGUF ==============

class LocalGGUFProvider:
    name = "local"

    def __init__(self, model_path: str, dims: int = 768):
        self.model_path = model_path
        self.model = model_path.split("/")[-1] if "/" in model_path else model_path
        self.dims = dims
        self._llama = None
        self._lock = asyncio.Lock()

    async def _ensure_loaded(self):
        if self._llama is not None:
            return
        async with self._lock:
            if self._llama is not None:
                return
            try:
                from llama_cpp import Llama
            except ImportError as e:
                raise RuntimeError(
                    "llama-cpp-python 未安装。请运行 pip install llama-cpp-python"
                ) from e
            from pathlib import Path
            if not Path(self.model_path).exists():
                raise RuntimeError(
                    f"本地 embedding 模型不存在: {self.model_path}\n"
                    f"请从 HuggingFace 下载到该路径。"
                )
            loop = asyncio.get_running_loop()
            self._llama = await loop.run_in_executor(
                None,
                lambda: Llama(
                    model_path=self.model_path,
                    embedding=True,
                    n_ctx=2048,
                    verbose=False,
                ),
            )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        await self._ensure_loaded()
        loop = asyncio.get_running_loop()

        def _sync():
            out = []
            for t in texts:
                r = self._llama.create_embedding(t)
                vec = r["data"][0]["embedding"]
                out.append(vec)
            return out

        return await loop.run_in_executor(None, _sync)


# ============== OpenAI ==============

class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str = "text-embedding-3-small", dims: int = 1536):
        self.api_key = api_key
        self.model = model
        self.dims = dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("OpenAI API key 未配置")
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError("httpx 未安装") from e

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self.model, "input": texts}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers=headers, json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return [item["embedding"] for item in data["data"]]


# ============== Voyage ==============

class VoyageProvider:
    name = "voyage"

    def __init__(self, api_key: str, model: str = "voyage-3", dims: int = 1024):
        self.api_key = api_key
        self.model = model
        self.dims = dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("Voyage API key 未配置")
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError("httpx 未安装") from e
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self.model, "input": texts}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.voyageai.com/v1/embeddings",
                headers=headers, json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return [item["embedding"] for item in data["data"]]


# ============== Mistral ==============

class MistralProvider:
    name = "mistral"

    def __init__(self, api_key: str, model: str = "mistral-embed", dims: int = 1024):
        self.api_key = api_key
        self.model = model
        self.dims = dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("Mistral API key 未配置")
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError("httpx 未安装") from e
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self.model, "input": texts}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/embeddings",
                headers=headers, json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return [item["embedding"] for item in data["data"]]


# ============== Google ==============

class GoogleProvider:
    name = "google"

    def __init__(self, api_key: str, model: str = "text-embedding-004", dims: int = 768):
        self.api_key = api_key
        self.model = model
        self.dims = dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("Google API key 未配置")
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError("httpx 未安装") from e
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents?key={self.api_key}"
        body = {"requests": [{"content": {"parts": [{"text": t}]}, "model": f"models/{self.model}"} for t in texts]}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
        return [item["values"] for item in data["embeddings"]]


# ============== 工厂 + Auto Fallback ==============

def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def build_provider(name: str, config) -> EmbeddingProvider | None:
    """根据 name + config 构造 provider，失败返回 None（不抛异常）"""
    keys = config.get("api_keys", default={}) or {}
    emb = config.get("embedding", default={}) or {}

    try:
        if name == "local":
            from pathlib import Path
            from server.config import DATA_DIR
            custom = emb.get("local_model_path")
            default_name = emb.get("local_model", "embeddinggemma-300m-qat-Q8_0.gguf")
            path = custom or str(DATA_DIR / "models" / default_name)
            return LocalGGUFProvider(path, dims=emb.get("local_dims", 768))
        if name == "openai":
            key = keys.get("openai", "")
            if not key:
                return None
            return OpenAIProvider(key, emb.get("openai_model", "text-embedding-3-small"),
                                  emb.get("openai_dims", 1536))
        if name == "voyage":
            key = keys.get("voyage", "")
            if not key:
                return None
            return VoyageProvider(key, emb.get("voyage_model", "voyage-3"),
                                  emb.get("voyage_dims", 1024))
        if name == "mistral":
            key = keys.get("mistral", "")
            if not key:
                return None
            return MistralProvider(key, emb.get("mistral_model", "mistral-embed"),
                                   emb.get("mistral_dims", 1024))
        if name == "google":
            key = keys.get("google", "")
            if not key:
                return None
            return GoogleProvider(key, emb.get("google_model", "text-embedding-004"),
                                  emb.get("google_dims", 768))
    except Exception as e:
        print(f"[Knowledge/embed] 构造 {name} 失败: {e}")
    return None


class EmbeddingManager:
    """封装 auto fallback + cache 读写"""

    def __init__(self, config, conn):
        self.config = config
        self.conn = conn
        self._providers: list[EmbeddingProvider] = []
        self._active: EmbeddingProvider | None = None

    def _ensure_providers(self):
        if self._providers:
            return
        priority = self.config.get("embedding", "auto_priority",
                                    default=["local", "openai", "voyage", "mistral", "google"])
        for name in priority:
            p = build_provider(name, self.config)
            if p is not None:
                self._providers.append(p)
        if not self._providers:
            raise RuntimeError(
                "没有可用的 embedding provider。请在设置面板配置 API key，"
                "或下载本地 GGUF 模型到 data/models/。"
            )

    @property
    def active(self) -> EmbeddingProvider:
        self._ensure_providers()
        if self._active is None:
            self._active = self._providers[0]
        return self._active

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self._ensure_providers()
        last_err = None
        for p in self._providers:
            try:
                vecs = await p.embed(texts)
                self._active = p
                return vecs
            except Exception as e:
                last_err = e
                print(f"[Knowledge/embed] {p.name} 失败，尝试下一个: {e}")
                continue
        raise RuntimeError(f"所有 embedding provider 失败: {last_err}")

    async def embed_cached(self, texts: list[str]) -> tuple[list[list[float]], str, int]:
        """带 cache 的 embed — 返回 (vectors, provider_name, dims)

        每个 text 先查 embedding_cache 表（按 provider+model+text_hash），miss 的批量调用 API。
        """
        self._ensure_providers()
        # 按 active provider + model 查 cache（active 决定后再批量）
        provider = self.active
        model = provider.model

        hashes = [_text_hash(t) for t in texts]
        placeholders = ",".join("?" * len(hashes))
        cur = self.conn.execute(
            f"SELECT text_hash, embedding, dims FROM embedding_cache "
            f"WHERE provider=? AND model=? AND text_hash IN ({placeholders})",
            [provider.name, model, *hashes],
        )
        cached = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

        missing_idx = [i for i, h in enumerate(hashes) if h not in cached]
        missing_texts = [texts[i] for i in missing_idx]

        if missing_texts:
            new_vecs = await self.embed(missing_texts)
            # 切 provider 后 model 可能变（fallback 了）
            provider = self.active
            model = provider.model
            now = int(time.time())
            for i, vec in zip(missing_idx, new_vecs):
                h = hashes[i]
                cached[h] = (json.dumps(vec), provider.dims)
                self.conn.execute(
                    "INSERT INTO embedding_cache(provider, model, text_hash, embedding, dims, updated_at) "
                    "VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT(provider, model, text_hash) "
                    "DO UPDATE SET embedding=excluded.embedding, dims=excluded.dims, updated_at=excluded.updated_at",
                    (provider.name, model, h, json.dumps(vec), provider.dims, now),
                )
            self.conn.commit()

        vecs = []
        for h in hashes:
            emb_json, dims = cached[h]
            vecs.append(json.loads(emb_json))
        return vecs, provider.name, provider.dims
