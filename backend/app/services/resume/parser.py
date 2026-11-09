"""简历正文抽取：白名单 / 体积上限 / 中文错误映射（AC-1）。

规则：原文件不落盘，只把抽取到的正文入库；任何失败都不写库，因此不会产生画像数据。
"""

import io
import re
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.errors import (
    EMPTY_FILE,
    ENCRYPTED_PDF,
    FILE_TOO_LARGE,
    PARSE_FAILED,
    UNSUPPORTED_TYPE,
    AppError,
)

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt"}
#: r41：图片后缀单独一份（图片走视觉抽取端点，不进 PDF/DOCX 解析分支）。
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
SECTION_KEYWORDS = (
    "教育",
    "工作经历",
    "工作经验",
    "项目经历",
    "项目经验",
    "技能",
    "个人简介",
    "自我评价",
    "实习",
    "证书",
    "荣誉",
)


@dataclass(frozen=True)
class ParsedResume:
    text: str
    chars: int
    sections: int


def max_upload_bytes() -> int:
    """上传体积上限（字节）：路由层只用它给读取设硬边界，体积校验仍在本模块发生一次。"""
    return get_settings().max_upload_mb * 1024 * 1024


def ensure_upload_size(size: int, *, message: str) -> None:
    """体积上限的**唯一判断点**（r43）：文档 / 单张图片 / 图片合计都走这里。

    `message` 由调用方给（三种超限文案不同），其中 `{mb}` 占位符在这里替换成配置值，
    避免路由层各自拼阈值文案、配置调整后出现两份不同数字。
    """
    limit = max_upload_bytes()
    if size > limit:
        raise AppError(FILE_TOO_LARGE, message.format(mb=limit // (1024 * 1024)), status=413)


def is_image_name(file_name: str) -> bool:
    """后缀是否为图片（仅用于给旧文档端点一条明确指引，不做真实格式判断）。"""
    return _suffix_of(file_name) in IMAGE_SUFFIXES


def build_parsed(text: str) -> ParsedResume:
    """把已抽取正文包装成 `ParsedResume`：图片入口复用同一套字数 / 章节统计口径。"""
    return ParsedResume(text=text, chars=_count_chars(text), sections=_count_sections(text))


def parse_resume(file_name: str, raw: bytes) -> ParsedResume:
    if is_image_name(file_name):
        raise AppError(
            UNSUPPORTED_TYPE,
            "图片简历请用「拍照 / 相册上传」入口（支持 JPG / PNG / WebP）",
            status=415,
        )
    suffix = _suffix_of(file_name)
    if suffix not in SUPPORTED_SUFFIXES:
        raise AppError(UNSUPPORTED_TYPE, "仅支持 PDF / DOCX / TXT 文件", status=415)
    if not raw:
        raise AppError(EMPTY_FILE, "文件内容为空，请换一份", status=400)
    ensure_upload_size(len(raw), message="文件超过 {mb}MB，请压缩或分卷")

    text = _extract(suffix, raw)
    if not text.strip():
        raise AppError(
            EMPTY_FILE,
            "没有抽取到正文，请上传含文本层的 PDF，或改用 TXT / DOCX",
            status=400,
        )
    return build_parsed(text)


def _suffix_of(file_name: str) -> str:
    return f".{file_name.rsplit('.', 1)[-1].lower()}" if "." in file_name else ""


def _extract(suffix: str, raw: bytes) -> str:
    if suffix == ".txt":
        return _decode_text(raw)
    if suffix == ".pdf":
        return _extract_pdf(raw)
    return _extract_docx(raw)


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise AppError(
            PARSE_FAILED,
            "服务端缺少 PDF 解析依赖，请先安装 backend/requirements.txt",
            status=500,
        ) from exc
    try:
        reader = PdfReader(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001 - 第三方库异常形态不固定，统一降级为中文提示
        raise AppError(PARSE_FAILED, "PDF 解析失败，请确认文件完整后重试", status=400) from exc
    if reader.is_encrypted:
        raise AppError(ENCRYPTED_PDF, "PDF 已加密，请解密后重试", status=400)
    try:
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # noqa: BLE001
        raise AppError(PARSE_FAILED, "PDF 正文读取失败，请换一份文本版简历", status=400) from exc
    return "\n".join(pages)


def _extract_docx(raw: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise AppError(
            PARSE_FAILED,
            "服务端缺少 DOCX 解析依赖，请先安装 backend/requirements.txt",
            status=500,
        ) from exc
    try:
        document = Document(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001
        raise AppError(PARSE_FAILED, "DOCX 解析失败，请确认文件完整后重试", status=400) from exc
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def _count_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _count_sections(text: str) -> int:
    hits = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) > 24:
            continue
        if any(keyword in stripped for keyword in SECTION_KEYWORDS):
            hits += 1
    return min(99, hits)
