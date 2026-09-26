from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from typing import Any


@dataclass


class PrizeItem:
    place: int
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {"place": self.place, "description": self.description}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PrizeItem":
        return cls(place=int(data["place"]), description=str(data["description"]))


@dataclass


class GiveawayTemplate:
    id: int
    guild_id: int
    creator_id: int
    name: str
    title: str | None = None
    description: str | None = None
    prizes: list[PrizeItem] = field(default_factory=list)
    winners_count: int = 1
    duration_str: str | None = None
    image_url: str | None = None
    image_path: str | None = None
    require_stage: bool = False
    require_voice: bool = False
    enabled_points: bool = False
    require_server: bool = False
    required_guild_id: int | None = None
    server_invite_url: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "GiveawayTemplate":
        created_at = datetime.fromisoformat(row["created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        raw_prizes = json.loads(row["prizes"]) if row.get("prizes") else []
        prizes = [PrizeItem.from_dict(p) for p in raw_prizes]

        return cls(
            id=row["id"],
            guild_id=row["guild_id"],
            creator_id=row["creator_id"],
            name=row["name"],
            title=row.get("title"),
            description=row.get("description"),
            prizes=prizes,
            winners_count=int(row.get("winners_count", 1) or 1),
            duration_str=row.get("duration_str"),
            image_url=row.get("image_url"),
            image_path=row.get("image_path"),
            require_stage=bool(row.get("require_stage", 0)),
            require_voice=bool(row.get("require_voice", 0)),
            enabled_points=bool(row.get("enabled_points", 0)),
            require_server=bool(row.get("require_server", 0)),
            required_guild_id=row.get("required_guild_id"),
            server_invite_url=row.get("server_invite_url"),
            created_at=created_at,
        )


@dataclass


class GiveawayDraft:
    draft_id: str
    creator_id: int
    guild_id: int
    channel_id: int | None = None

    title: str | None = None
    description: str | None = None
    prizes: list[PrizeItem] = field(default_factory=list)
    winners_count: int = 1
    duration_str: str | None = None
    duration_delta: timedelta | None = None

    image_url: str | None = None
    image_path: str | None = None

    require_stage: bool = False
    require_voice: bool = False
    enabled_points: bool = False
    require_server: bool = False
    required_guild_id: int | None = None
    server_invite_url: str | None = None
    template_id: int | None = None

    @property
    def display_title(self) -> str:
        return self.title or "Новый розыгрыш"

    @property
    def display_description(self) -> str:
        return self.description or "Настройте розыгрыш с помощью кнопок ниже."

    @property
    def total_winners(self) -> int:
        return max(len(self.prizes), self.winners_count)

    def is_ready_to_publish(self) -> tuple[bool, str]:
        if not self.duration_delta:
            return False, "Необходимо указать длительность розыгрыша (кнопка Время)."
        if self.winners_count < 1:
            return False, "Количество победителей должно быть не менее 1."
        return True, ""


@dataclass


class ParticipantData:
    giveaway_id: int
    user_id: int
    joined_at: datetime
    voice_seconds: float = 0.0
    points: float = 0.0
    chance_percent: float = 0.0


@dataclass


class GiveawayRecord:
    id: int
    guild_id: int
    channel_id: int
    message_id: int
    title: str
    description: str | None = None
    prizes: list[PrizeItem] = field(default_factory=list)
    winners_count: int = 1
    image_url: str | None = None
    image_path: str | None = None
    creator_id: int = 0
    end_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_str: str | None = None
    status: str = "active"
    winners: list[dict[str, Any]] | None = None
    require_stage: bool = False
    require_voice: bool = False
    enabled_points: bool = False
    require_server: bool = False
    required_guild_id: int | None = None
    server_invite_url: str | None = None
    template_id: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "GiveawayRecord":
        raw_prizes = json.loads(row["prizes"]) if row.get("prizes") else []
        prizes = [PrizeItem.from_dict(p) for p in raw_prizes]

        raw_winners = json.loads(row["winners"]) if row.get("winners") else None

        end_time = datetime.fromisoformat(row["end_time"])
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)

        created_at = datetime.fromisoformat(row["created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        return cls(
            id=row["id"],
            guild_id=row["guild_id"],
            channel_id=row["channel_id"],
            message_id=row["message_id"],
            title=row["title"],
            description=row["description"],
            prizes=prizes,
            winners_count=int(row.get("winners_count", 1) or 1),
            image_url=row["image_url"],
            image_path=row["image_path"],
            creator_id=row["creator_id"],
            end_time=end_time,
            duration_str=row.get("duration_str"),
            status=row["status"],
            winners=raw_winners,
            require_stage=bool(row.get("require_stage", 0)),
            require_voice=bool(row.get("require_voice", 0)),
            enabled_points=bool(row.get("enabled_points", 0)),
            require_server=bool(row.get("require_server", 0)),
            required_guild_id=row.get("required_guild_id"),
            server_invite_url=row.get("server_invite_url"),
            template_id=row.get("template_id"),
            created_at=created_at,
        )
