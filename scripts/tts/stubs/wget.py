"""`wget` 的本地 stub（r150）：CosyVoice 的 flow 模块在 import 时会 `import wget`，
但推理路径不用它（只用于训练期下载资源）。PyPI 的 wget 3.2 在本机反复校验失败，
与其改环境或绕过校验，不如提供一个显式 stub —— 真调用时直接报错，不静默。

用法：由 `scripts/tts/synthesize.py` 把本目录加进 sys.path。
"""


def download(url: str, out: str | None = None, **_kwargs):  # pragma: no cover - 推理不会走到
    raise RuntimeError(
        f'wget.download 在本环境被 stub 掉了（url={url}）。'
        '推理链路不需要它；若确需下载资源，请用 modelscope / 官方脚本。'
    )
