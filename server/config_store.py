"""全局运行时配置 data/config.json — 由前端设置面板读写。

分工：
- server/config.py load_instance_config  → 实例级（instances/*.json），启动时加载
- server/config_store.py get_config()    → 系统级（data/config.json），运行时热读写

敏感字段（API key / token）存明文 + chmod 600（同 OpenClaw / Hermes / Claude Code CLI）。
GET 时默认打码，POST 时打码回写会被自动忽略（防止覆盖真实值）。
"""

import json
import os
import stat
from pathlib import Path
from threading import Lock

from server.config import DATA_DIR

_CONFIG_FILE = DATA_DIR / "config.json"

# 敏感字段路径（打码用）
_SENSITIVE_PATHS: list[tuple[str, ...]] = [
    ("api_keys", "openai"),
    ("api_keys", "voyage"),
    ("api_keys", "mistral"),
    ("api_keys", "google"),
    ("api_keys", "cohere"),
    ("channels", "qq", "napcat_token"),
    ("auth", "password_hash"),
]

_DEFAULT_CONFIG = {
    "plugins": {
        "knowledge": False,
    },
    "memory": {
        "recall_strategy": "triggered",  # off | triggered | light
        "recall_trigger_keywords_zh": [
            "上次", "之前", "以前", "曾经", "记得", "那次",
            "上周", "昨天", "前天", "过去", "那时", "回忆",
        ],
        "recall_trigger_keywords_en": [
            "last time", "before", "previously", "earlier",
            "remember", "recall", "back then",
        ],
        "recall_top_k": 3,
        "recall_min_score": 0.3,
        "temporal_half_life_days": 30,
    },
    "embedding": {
        "auto_priority": ["local", "openai", "voyage", "mistral", "google"],
        "local_model": "embeddinggemma-300m-qat-Q8_0.gguf",
        "local_dims": 768,
        "openai_model": "text-embedding-3-small",
        "openai_dims": 1536,
        "voyage_model": "voyage-3",
        "voyage_dims": 1024,
        "mistral_model": "mistral-embed",
        "mistral_dims": 1024,
        "google_model": "text-embedding-004",
        "google_dims": 768,
    },
    "api_keys": {
        "openai": "",
        "voyage": "",
        "mistral": "",
        "google": "",
        "cohere": "",
    },
    "knowledge": {
        "chunk_tokens": 1024,
        "chunk_overlap": 160,
        "hybrid_vec_weight": 0.7,
        "hybrid_bm25_weight": 0.3,
        "mmr_enabled": True,
        "mmr_lambda": 0.6,
        "default_top_k": 5,
        "min_score": 0.2,
        "index_sources": ["knowledge", "memory_detail", "projects_detail"],
        "knowledge_dir": "data/knowledge",
    },
    "channels": {
        "qq": {
            "enabled": False,
            "napcat_url": "http://localhost:3000",
            "napcat_token": "",
            "allowed_users": [],
            "allowed_groups": [],
            "group_at_only": True,
        },
    },
    "service": {
        "host": "0.0.0.0",
        "port": 6790,
        "idle_timeout_minutes": 60,
    },
    "daily_digest": {
        "enabled": True,
        "trigger_hour": 2,
        "model": "claude-sonnet-4-6",
        "per_message_threshold": 20000,
        "total_limit": 50000,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class ConfigStore:
    def __init__(self):
        self._lock = Lock()
        self._data: dict = {}
        self._load()

    def _load(self):
        if _CONFIG_FILE.exists():
            try:
                with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self._data = _deep_merge(_DEFAULT_CONFIG, loaded)
            except Exception as e:
                print(f"[ConfigStore] 加载失败 {_CONFIG_FILE}: {e}，使用默认")
                self._data = json.loads(json.dumps(_DEFAULT_CONFIG))
        else:
            self._data = json.loads(json.dumps(_DEFAULT_CONFIG))
            self._save_unlocked()
            print(f"[ConfigStore] 已创建默认配置 {_CONFIG_FILE}")

    def _save_unlocked(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _CONFIG_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _CONFIG_FILE)
        try:
            os.chmod(_CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)
        except Exception as e:
            print(f"[ConfigStore] chmod 失败: {e}")

    def reload(self):
        with self._lock:
            self._load()

    def get(self, *path, default=None):
        """路径式访问：config.get('memory', 'recall_strategy')"""
        with self._lock:
            node = self._data
            for key in path:
                if not isinstance(node, dict) or key not in node:
                    return default
                node = node[key]
            return node

    def set(self, *path_and_value):
        """路径式写入：config.set('memory', 'recall_strategy', 'light')"""
        if len(path_and_value) < 2:
            raise ValueError("set requires path + value")
        path = path_and_value[:-1]
        value = path_and_value[-1]
        with self._lock:
            node = self._data
            for key in path[:-1]:
                if key not in node or not isinstance(node[key], dict):
                    node[key] = {}
                node = node[key]
            node[path[-1]] = value
            self._save_unlocked()

    def patch(self, changes: dict):
        """批量深度合并"""
        with self._lock:
            self._data = _deep_merge(self._data, changes)
            self._save_unlocked()

    def snapshot(self, mask_sensitive: bool = True) -> dict:
        with self._lock:
            data = json.loads(json.dumps(self._data))
        if mask_sensitive:
            for path in _SENSITIVE_PATHS:
                node = data
                valid = True
                for k in path[:-1]:
                    if not isinstance(node, dict) or k not in node:
                        valid = False
                        break
                    node = node[k]
                if not valid:
                    continue
                leaf = path[-1]
                if isinstance(node, dict) and leaf in node and node[leaf]:
                    val = str(node[leaf])
                    node[leaf] = _mask_value(val)
        return data

    def is_plugin_enabled(self, name: str, default: bool = False) -> bool:
        v = self.get("plugins", name, default=None)
        return default if v is None else bool(v)


def _mask_value(val: str) -> str:
    if len(val) > 8:
        return "•" * (len(val) - 4) + val[-4:]
    return "•" * max(1, len(val))


_store: ConfigStore | None = None


def get_config() -> ConfigStore:
    global _store
    if _store is None:
        _store = ConfigStore()
    return _store
