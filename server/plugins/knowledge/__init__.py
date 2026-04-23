"""Knowledge Plugin — 混合向量 + FTS5 检索（默认禁用，设置面板启用）"""

from server.plugins.knowledge.manager import KnowledgeManager

_manager: KnowledgeManager | None = None


def register(mcp, config, context):
    """由 plugin loader 调用"""
    global _manager
    _manager = KnowledgeManager(config)

    @mcp.tool()
    async def jarvis_memory_search(
        query: str,
        top_k: int = 5,
        source: str = None,
        min_score: float = None,
        date_start: str = None,
        date_end: str = None,
    ) -> dict:
        """搜索 memory 细化摘要 / 项目细化归档 / 知识库（混合 向量 + FTS5）。

        Args:
            query: 查询文本（自然语言）
            top_k: 最多返回几条，默认 5
            source: 过滤来源，可选 "memory" | "projects" | "knowledge"。不传搜全部
            min_score: 最低相关性阈值 (0-1)，不传用默认
            date_start: 时间过滤起点 "YYYY-MM-DD"
            date_end: 时间过滤终点 "YYYY-MM-DD"
        """
        if _manager is None:
            return {"status": "error", "message": "Knowledge plugin 未加载"}
        try:
            results = await _manager.search(
                query=query, top_k=top_k, source=source, min_score=min_score,
                date_start=date_start, date_end=date_end,
            )
            return {"status": "ok", "results": results, "count": len(results)}
        except Exception as e:
            import traceback; traceback.print_exc()
            return {"status": "error", "message": str(e)}

    @mcp.tool()
    async def jarvis_knowledge_reindex(source: str = None, path: str = None) -> dict:
        """重建索引。

        Args:
            source: "memory" | "projects" | "knowledge"；不传全部重建
            path: 单个文件路径（相对 data/ 或绝对），仅重建此文件
        """
        if _manager is None:
            return {"status": "error", "message": "Knowledge plugin 未加载"}
        try:
            return {"status": "ok", **await _manager.reindex(source=source, path=path)}
        except Exception as e:
            import traceback; traceback.print_exc()
            return {"status": "error", "message": str(e)}

    @mcp.tool()
    async def jarvis_knowledge_stats() -> dict:
        """查看知识库统计（chunks / files / cache / 向量可用性）"""
        if _manager is None:
            return {"status": "error", "message": "Knowledge plugin 未加载"}
        return {"status": "ok", **_manager.stats()}

    print("[Plugin:knowledge] 工具已注册：jarvis_memory_search / jarvis_knowledge_reindex / jarvis_knowledge_stats")


async def shutdown():
    global _manager
    if _manager:
        await _manager.close()
        _manager = None


def get_manager() -> KnowledgeManager | None:
    """供 hook / 其他模块直接使用（例如 UserPromptSubmit 自动召回）"""
    return _manager
