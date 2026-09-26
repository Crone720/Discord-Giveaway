import re
from datetime import datetime, timedelta, timezone

_UNIT_PATTERN = re.compile(r"(\d+)\s*([mhdMHD])")


def parse_duration(text: str) -> timedelta:
    text = text.strip()
    if not text:
        raise ValueError("Строка длительности не может быть пустой.")

    matches = _UNIT_PATTERN.findall(text)

    cleaned = _UNIT_PATTERN.sub("", text).strip()
    if cleaned or not matches:
        raise ValueError(
            "Неверный формат времени! Разрешены только числа с m (минуты), h (часы), d (дни).\n"
            "Примеры: `10m`, `2h`, `30d` или составные `1d 5h 30m`."
        )

    total_minutes = 0
    for value_str, unit in matches:
        val = int(value_str)
        u = unit.lower()
        if u == "m":
            total_minutes += val
        elif u == "h":
            total_minutes += val * 60
        elif u == "d":
            total_minutes += val * 1440

    if total_minutes <= 0:
        raise ValueError("Длительность должна быть строго больше 0 минут.")

    if total_minutes > 365 * 1440:
        raise ValueError("Длительность не может превышать 365 дней.")

    return timedelta(minutes=total_minutes)


def to_discord_timestamp(dt: datetime, style: str = "R") -> str:
    ts = int(dt.replace(tzinfo=timezone.utc).timestamp() if dt.tzinfo is None else dt.timestamp())
    return f"<t:{ts}:{style}>"


def format_duration_human(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts: list[str] = []
    if days > 0:
        parts.append(f"{days} дн.")
    if hours > 0:
        parts.append(f"{hours} ч.")
    if minutes > 0:
        parts.append(f"{minutes} мин.")

    return " ".join(parts) if parts else "0 мин."
