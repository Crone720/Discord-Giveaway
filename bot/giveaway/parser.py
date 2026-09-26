import re
from bot.giveaway.models import PrizeItem

_PRIZE_LINE_RE = re.compile(
    r"^(?:"
    r"(?:(?P<place>[1-9]\d{0,2})\s*(?:место|place|st|nd|rd|th)?|[#№](?P<place_alt>[1-9]\d{0,2}))\s*[-—:.)]\s+"
    r"|"
    r"(?:(?P<place_word>[1-9]\d{0,2})\s+(?:место|place)\s*[-—:.]?\s*)"
    r")?(?P<prize>.+)$",
    re.IGNORECASE,
)


def parse_prizes_input(text: str) -> list[PrizeItem]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    prizes: list[PrizeItem] = []
    current_auto_place = 1

    for line in lines:
        match = _PRIZE_LINE_RE.match(line)
        if not match:
            continue

        place_raw = (
            match.group("place")
            or match.group("place_alt")
            or match.group("place_word")
        )
        prize_desc = match.group("prize").strip()

        if not prize_desc:
            continue

        if place_raw:
            place = int(place_raw)
            current_auto_place = place + 1
        else:
            place = current_auto_place
            current_auto_place += 1

        prizes.append(PrizeItem(place=place, description=prize_desc))

    prizes.sort(key=lambda p: p.place)
    return prizes


def format_prizes_display(prizes: list[PrizeItem]) -> str:
    if not prizes:
        return "*Призы не указаны (нажмите кнопку 'Призы')*"

    lines: list[str] = []
    for prize in prizes:
        lines.append(f"**{prize.place} место** — {prize.description}")

    return "\n".join(lines)
