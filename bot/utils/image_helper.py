import os
import re
import uuid
from pathlib import Path
import disnake

from bot.config import (
    UPLOADS_DIR,
    MAX_IMAGE_SIZE_BYTES,
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_MIME_TYPES,
)

_IMAGE_URL_PATTERN = re.compile(
    r"^https?://[^\s/$.?#].[^\s]*\.(png|jpg|jpeg|webp|gif)(\?.*)?$",
    re.IGNORECASE,
)


def is_valid_image_url(url: str) -> bool:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return False
    return bool(_IMAGE_URL_PATTERN.match(url))


def is_valid_attachment(attachment: disnake.Attachment) -> tuple[bool, str]:
    if attachment.size > MAX_IMAGE_SIZE_BYTES:
        mb = MAX_IMAGE_SIZE_BYTES // (1024 * 1024)
        return False, f"Размер файла превышает лимит {mb} МБ."

    ext = Path(attachment.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        allowed = ", ".join(ALLOWED_IMAGE_EXTENSIONS)
        return False, f"Недопустимый формат файла '{ext}'. Разрешены: {allowed}."

    if attachment.content_type and not (
        attachment.content_type.startswith("image/")
        or attachment.content_type in ALLOWED_MIME_TYPES
    ):
        return False, f"Файл не является изображением (тип: {attachment.content_type})."

    return True, ""


async def save_attachment(attachment: disnake.Attachment, prefix: str = "img") -> str:
    ext = Path(attachment.filename).suffix.lower()
    if not ext:
        ext = ".png"

    filename = f"{prefix}_{uuid.uuid4().hex[:12]}{ext}"
    target_path = UPLOADS_DIR / filename

    await attachment.save(target_path)
    return str(target_path)


def delete_local_file(path_str: str | None) -> None:
    if not path_str:
        return
    try:
        p = Path(path_str)
        if p.exists() and p.is_file():
            p.unlink()
    except OSError:
        pass
