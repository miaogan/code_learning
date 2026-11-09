"""图片简历正文抽取（r41 AC A-1 ~ A-10）。

图片字节只在内存中流转：路由层 `await file.read()` → 本模块转 data URL → 视觉模型 → 丢弃。
这里不写临时文件、不落库、不打印 data URL；只返回抽取正文，由路由层交给 `repository`。

质量口径：多图按上传顺序拼成**一份**简历（共用同一个 `resume_id`），汇总字数 < 60 判识别不足。
"""

import base64
import logging
from collections.abc import Callable

from app.core.config import get_settings
from app.core.errors import AI_UNAVAILABLE, UNSUPPORTED_TYPE, VALIDATION_ERROR, AppError
from app.services.ai.ai import AIClient
from app.services.resume.parser import ParsedResume, build_parsed

logger = logging.getLogger("app.resume.image")

#: 单次最多 3 张（D2）：再多的照片识别收益低、等待长，超出直接拒绝。
MAX_IMAGE_COUNT = 3
#: 识别正文的最少字数：低于此值按「识别不足」给重拍指引，而不是把垃圾正文带进画像。
MIN_IMAGE_CHARS = 60

#: HEIF / HEIC 家族品牌（iPhone 默认相机格式）。`ftyp` 的 major brand 常见 `heic` / `mif1`，
#: 兼容品牌里也可能出现其余几项，因此两处都要看。
HEIF_BRANDS: frozenset[bytes] = frozenset(
    {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}
)

#: HEIC 的专用中文提示（r42）：不说「格式不支持」这种死胡同，直接给可行替代路径。
HEIC_UNSUPPORTED_MESSAGE = (
    "iPhone 的 HEIC 照片暂不支持直接上传。"
    "请在「设置 → 相机 → 格式」里选择「兼容性最佳」后重新拍摄，"
    "或在相册里导出为 JPG / PNG 再上传。"
)

#: 只认 JPG / PNG / WebP（DeepSeek 视觉支持格式的子集；GIF 简历不现实，不放行）。
SYSTEM_PROMPT = (
    "你是严谨的简历转写员。任务是把图片中的文字逐字转写为纯文本，"
    "不做总结、不做改写、不做推测。"
)

USER_PROMPT = (
    "请把这张简历图片中的文字完整转写出来，遵守以下规则：\n"
    "1. 保留原始换行与段落顺序，不要合并行；\n"
    "2. 表格按「标签：内容」逐行输出；\n"
    "3. 无法辨认的文字用 [无法辨认] 占位，不要猜；\n"
    "4. 禁止补写图片中不存在的内容，禁止改写措辞；\n"
    "5. 只输出转写正文，不要任何解释或前后缀。"
)


def sniff_image_mime(raw: bytes) -> str | None:
    """按**文件真实内容**判断格式（不看文件名 / MIME，手机相册改名不会误判）。"""
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def is_heif(raw: bytes) -> bool:
    """是否为 HEIF / HEIC（iPhone 默认格式）：看 `ftyp` 的 major brand 与兼容品牌。

    iOS Safari 在「拍照 / 从相册选」上传时通常会转码成 JPEG，但走「文件」入口或部分
    Android / 桌面浏览器会原样送出 HEIC —— 后端不能假设前端一定转码成功，必须能识别。
    """
    if len(raw) < 12 or raw[4:8] != b"ftyp":
        return False
    box_size = int.from_bytes(raw[0:4], "big")
    if raw[8:12] in HEIF_BRANDS:
        return True
    end = min(len(raw), box_size if 0 < box_size <= len(raw) else len(raw))
    return any(raw[offset : offset + 4] in HEIF_BRANDS for offset in range(16, max(16, end - 3), 4))


def sniff_or_raise(raw: bytes) -> str:
    """格式校验的唯一出口：JPEG / PNG / WebP 返回 mime，HEIC 与其它给各自的中文原因。"""
    mime = sniff_image_mime(raw)
    if mime is not None:
        return mime
    if is_heif(raw):
        raise AppError(UNSUPPORTED_TYPE, HEIC_UNSUPPORTED_MESSAGE, status=415)
    raise AppError(UNSUPPORTED_TYPE, "仅支持 JPG / PNG / WebP 图片", status=415)


def _data_url(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _page_prompt(index: int, total: int) -> str:
    if total == 1:
        return USER_PROMPT
    return f"这是同一份简历的第 {index} 页（共 {total} 页），请只转写本页内容。\n{USER_PROMPT}"


async def extract_resume_text(
    images: list[bytes],
    client: AIClient | None = None,
    *,
    on_page_done: Callable[[int], None] | None = None,
) -> ParsedResume:
    """逐张视觉抽取 → 按顺序拼接 → 汇总质量判定（失败时不产生任何入库数据）。

    `on_page_done(index)` 是 r42 的任务心跳：每完成一页就推进一次任务行 `updated_at`，
    惰性清扫因此按「无进展」而不是「总耗时」判死（3 张图合法耗时可远超 10 分钟）。
    """
    if not images:
        raise AppError(VALIDATION_ERROR, "请至少上传 1 张图片", status=400)
    if len(images) > MAX_IMAGE_COUNT:
        raise AppError(
            VALIDATION_ERROR, f"一次最多上传 {MAX_IMAGE_COUNT} 张图片", status=400
        )
    mimes = [sniff_or_raise(raw) for raw in images]

    if client is None:
        runtime = get_settings().resolve_vision()
        if not runtime.ready:
            # 未开通视觉：明确提示改用 PDF，绝不静默降级、也不返回含糊错误。
            raise AppError(AI_UNAVAILABLE, runtime.reason, status=503)
        client = AIClient(runtime=runtime)

    total = len(images)
    parts: list[str] = []
    for index, raw in enumerate(images, start=1):
        text = await client.complete_vision(
            SYSTEM_PROMPT,
            _page_prompt(index, total),
            [_data_url(raw, mimes[index - 1])],
            retry_unavailable=True,
        )
        cleaned = text.strip()
        parts.append(f"【第 {index} 页】\n{cleaned}" if total > 1 else cleaned)
        if on_page_done is not None:
            on_page_done(index)

    parsed = build_parsed("\n\n".join(parts))
    if parsed.chars < MIN_IMAGE_CHARS:
        raise AppError(
            VALIDATION_ERROR,
            "识别到的文字太少，请重拍（正对、光线充足）或改用 PDF",
            status=400,
        )
    logger.info("resume.image_extract images=%s chars=%s", total, parsed.chars)
    return parsed
