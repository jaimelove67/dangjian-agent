"""三会一课现场图片的格式、尺寸与数量边界。

图片只作为会议记录佐证保存在本地加密文件存储中，不送云端识别；这里只读取
文件头并校验真实图片格式，避免把改了扩展名的任意文件当作图片下发。
"""

from __future__ import annotations

import io
from pathlib import PurePath

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

MEETING_IMAGE_LIMIT = 9
MEETING_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
MEETING_IMAGE_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
# 手机照片通常在一千多万像素；超过四千万像素既不便于留存，也容易拖慢预览。
MEETING_IMAGE_MAX_PIXELS = 40_000_000


def inspect_meeting_image(content: bytes, file_name: str) -> str:
    """校验并返回真实 MIME 类型；失败时给出可执行的修复提示。"""
    if not content:
        raise HTTPException(422, "图片不能为空，请重新选择")
    name = file_name or ""
    if not name or len(name) > 255 or any(ord(char) < 32 or char in "/\\:" for char in name):
        raise HTTPException(422, "图片文件名无效，请修改文件名后重试")
    if PurePath(name).suffix.lower() not in MEETING_IMAGE_EXTENSIONS:
        raise HTTPException(415, "仅支持 JPG、PNG 或 WebP 格式的现场图片")

    try:
        with Image.open(io.BytesIO(content)) as image:
            image_format = (image.format or "").upper()
            width, height = image.size
            if width < 1 or height < 1:
                raise HTTPException(422, "图片尺寸无效，请重新选择")
            if width * height > MEETING_IMAGE_MAX_PIXELS:
                raise HTTPException(413, "图片像素过大，请压缩或缩小后重新上传")
            image.verify()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(415, "图片内容无法识别，请上传有效的 JPG、PNG 或 WebP 图片") from None

    mime = MEETING_IMAGE_FORMATS.get(image_format)
    if mime is None:
        raise HTTPException(415, "仅支持 JPG、PNG 或 WebP 格式的现场图片")
    return mime
