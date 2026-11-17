"""r104 eval_rag --live 的守卫：不联网、不连库，只验证「不该跑的时候绝不跑」。

这些守卫比指标更重要：`--live` 会真实调用 embedding 端点并消耗配额，
误触发（比如 CI 里顺手加了 --live）比数字不好看严重得多。
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("eval_rag_script", ROOT / "scripts" / "eval_rag.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_live_requires_explicit_ai_live(monkeypatch):
    """没有 AI_LIVE=1：直接退出 2，不做任何评测。"""
    module = _load_script()
    monkeypatch.delenv("AI_LIVE", raising=False)
    assert module.main(["--live"]) == 2


def test_live_and_check_are_mutually_exclusive(monkeypatch):
    """--check 是 CI 门禁（只读、零网络），不允许与 --live 混用。"""
    module = _load_script()
    monkeypatch.setenv("AI_LIVE", "1")
    assert module.main(["--check", "--live"]) == 2


def test_live_without_endpoint_config_fails_fast(monkeypatch):
    """AI_LIVE=1 但没给端点配置：在连库之前就失败退出 2（缺什么就说缺什么）。"""
    module = _load_script()
    monkeypatch.setenv("AI_LIVE", "1")
    for name in ("AI_EMBED_BASE_URL", "AI_EMBED_MODEL", "AI_EMBED_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert module.main(["--live"]) == 2
