"""r105 教程语料种子：后端可离线获取的教程正文（由前端导出）。

为什么要有这份种子：教程正文只住在前端 `frontend/src/content/tutorials/`（TS 模块），
后端重建 RAG 索引时拿不到——此前只能靠浏览器点「推送教程正文」。导出成
`app/seed/tutorials_rag.json` 后，后端启动/重建可以自行摄取全量语料（离线也能做）。

**单一来源**：文件由 `scripts/export_tutorials.mjs` 生成，脚本通过 esbuild 打包后
直接调用前端同一个 `buildTutorialChunks()`——不在 Node 侧另写一份切分逻辑。
改教程后必须重新导出（CI 的 `--check` 门禁会比对）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.rag.tutorial_seed")

#: `app/seed/tutorials_rag.json`（本文件位于 app/services/retrieval/ 下，parents[2] = app）
SEED_PATH = Path(__file__).resolve().parents[2] / "seed" / "tutorials_rag.json"


def load_items() -> list[dict[str, Any]]:
    """读种子并做最小校验：缺 `chapter_id` / 正文的条目直接丢弃（不拿脏数据灌索引）。"""
    if not SEED_PATH.exists():
        logger.warning("rag.tutorial_seed.missing path=%s", SEED_PATH.name)
        return []
    try:
        payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("rag.tutorial_seed.unreadable error=%s", type(exc).__name__)
        return []
    raw_items = payload.get("items") or []
    items = [
        item
        for item in raw_items
        if isinstance(item, dict) and item.get("chapter_id") and item.get("content")
    ]
    if len(items) != len(raw_items):
        logger.warning(
            "rag.tutorial_seed.invalid_items dropped=%d", len(raw_items) - len(items)
        )
    return items
