import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BASE_DIR / "data"
UPLOADS_DIR: Path = DATA_DIR / "uploads"
DB_PATH: Path = DATA_DIR / "giveaways.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()

_guild_id_raw: str = os.getenv("TEST_GUILD_ID", "").strip()
TEST_GUILD_ID: int | None = int(_guild_id_raw) if _guild_id_raw.isdigit() else None

COLOR_BLURPLE: int = 0x5865F2
COLOR_DARK: int = 0x2B2D31
COLOR_GREEN: int = 0x57F287
COLOR_RED: int = 0xED4245
COLOR_YELLOW: int = 0xFEE75C

COLOR_PREVIEW: int = COLOR_BLURPLE
COLOR_ACTIVE: int = COLOR_BLURPLE
COLOR_ENDED: int = COLOR_DARK
COLOR_NO_WINNERS: int = COLOR_DARK
COLOR_ERROR: int = COLOR_RED

MAX_IMAGE_SIZE_BYTES: int = 8 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp", ".gif")
ALLOWED_MIME_TYPES: tuple[str, ...] = (
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
)
