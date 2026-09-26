import asyncio
import json
import logging
import math
import os
import secrets
from datetime import datetime, timezone
from typing import Any
import aiosqlite
import disnake

from bot.config import DB_PATH
from bot.giveaway.models import (
    GiveawayDraft,
    GiveawayRecord,
    GiveawayTemplate,
    ParticipantData,
)
from bot.giveaway.builder import GiveawayBuilder
from bot.utils.time_parser import parse_duration

logger = logging.getLogger("GiveawayManager")


async def resolve_partner_server(
    bot: disnake.Client,
    server_input: str,
) -> tuple[disnake.Guild | None, str | None, str]:
    raw_input = server_input.strip()
    if not raw_input:
        return None, None, "Не указан сервер или ссылка-приглашение."

    if raw_input.isdigit():
        guild_id = int(raw_input)
        target_guild = bot.get_guild(guild_id)
        if not target_guild:
            try:
                target_guild = await bot.fetch_guild(guild_id)
            except Exception:
                target_guild = None
        if not target_guild:
            return None, None, f"Бот не находится на сервере с ID `{guild_id}`. Сначала добавьте бота на этот сервер."

        target_invite_url = None
        if target_guild.vanity_url_code:
            target_invite_url = f"https://discord.gg/{target_guild.vanity_url_code}"
        else:
            for ch in target_guild.text_channels:
                try:
                    inv = await ch.create_invite(max_age=0, max_uses=0, reason="Giveaway partner invite")
                    target_invite_url = inv.url
                    break
                except Exception:
                    continue
            if not target_invite_url:
                target_invite_url = f"https://discord.com/channels/{target_guild.id}"
        return target_guild, target_invite_url, ""

    invite_code = raw_input
    for prefix in [
        "https://discord.gg/",
        "http://discord.gg/",
        "discord.gg/",
        "https://discord.com/invite/",
        "http://discord.com/invite/",
        "discord.com/invite/",
    ]:
        if invite_code.startswith(prefix):
            invite_code = invite_code[len(prefix):].split("/")[0].split("?")[0]
            break

    try:
        invite = await bot.fetch_invite(invite_code)
        if invite.guild:
            target_guild = bot.get_guild(invite.guild.id)
            if not target_guild:
                try:
                    target_guild = await bot.fetch_guild(invite.guild.id)
                except Exception:
                    target_guild = None
            if not target_guild:
                return None, None, f"Бот не находится на сервере «{invite.guild.name}». Сначала добавьте бота на этот сервер."
            target_invite_url = invite.url or f"https://discord.gg/{invite.code}"
            return target_guild, target_invite_url, ""
        else:
            return None, None, "Не удалось определить сервер по указанному приглашению."
    except Exception as exc:
        return None, None, f"Не удалось получить информацию по приглашению: {exc}"


class GiveawayManager:
    def __init__(self, bot: disnake.Client) -> None:
        self.bot = bot
        self._ticker_task: asyncio.Task | None = None
        self._db_lock = asyncio.Lock()
        self.drafts: dict[str, GiveawayDraft] = {}
        self._handled_deleted_messages: set[int] = set()

    async def initialize(self) -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS giveaways (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    prizes TEXT NOT NULL,
                    winners_count INTEGER NOT NULL DEFAULT 1,
                    image_url TEXT,
                    image_path TEXT,
                    creator_id INTEGER NOT NULL,
                    end_time TEXT NOT NULL,
                    duration_str TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    winners TEXT,
                    require_stage INTEGER DEFAULT 0,
                    require_voice INTEGER DEFAULT 0,
                    enabled_points INTEGER DEFAULT 0,
                    require_server INTEGER DEFAULT 0,
                    required_guild_id INTEGER,
                    server_invite_url TEXT,
                    template_id INTEGER,
                    created_at TEXT NOT NULL
                );
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS participants (
                    giveaway_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    joined_at TEXT NOT NULL,
                    voice_seconds REAL DEFAULT 0.0,
                    voice_joined_at TEXT,
                    points REAL DEFAULT 0.0,
                    PRIMARY KEY (giveaway_id, user_id),
                    FOREIGN KEY (giveaway_id) REFERENCES giveaways (id) ON DELETE CASCADE
                );
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    creator_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    title TEXT,
                    description TEXT,
                    prizes TEXT,
                    winners_count INTEGER NOT NULL DEFAULT 1,
                    duration_str TEXT,
                    image_url TEXT,
                    image_path TEXT,
                    require_stage INTEGER DEFAULT 0,
                    require_voice INTEGER DEFAULT 0,
                    enabled_points INTEGER DEFAULT 0,
                    require_server INTEGER DEFAULT 0,
                    required_guild_id INTEGER,
                    server_invite_url TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            await db.commit()

            columns_to_add = [
                ("giveaways", "duration_str", "TEXT"),
                ("giveaways", "winners_count", "INTEGER NOT NULL DEFAULT 1"),
                ("giveaways", "require_stage", "INTEGER DEFAULT 0"),
                ("giveaways", "require_voice", "INTEGER DEFAULT 0"),
                ("giveaways", "enabled_points", "INTEGER DEFAULT 0"),
                ("giveaways", "require_server", "INTEGER DEFAULT 0"),
                ("giveaways", "required_guild_id", "INTEGER"),
                ("giveaways", "server_invite_url", "TEXT"),
                ("giveaways", "template_id", "INTEGER"),
                ("participants", "voice_seconds", "REAL DEFAULT 0.0"),
                ("participants", "voice_joined_at", "TEXT"),
                ("participants", "points", "REAL DEFAULT 0.0"),
                ("templates", "title", "TEXT"),
                ("templates", "description", "TEXT"),
                ("templates", "prizes", "TEXT"),
                ("templates", "winners_count", "INTEGER NOT NULL DEFAULT 1"),
                ("templates", "duration_str", "TEXT"),
                ("templates", "image_url", "TEXT"),
                ("templates", "image_path", "TEXT"),
                ("templates", "require_server", "INTEGER DEFAULT 0"),
                ("templates", "required_guild_id", "INTEGER"),
                ("templates", "server_invite_url", "TEXT"),
            ]
            for table, col, col_type in columns_to_add:
                try:
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type};")
                    await db.commit()
                except aiosqlite.OperationalError:
                    pass

        await self._restore_active_giveaways()

        if self._ticker_task is None or self._ticker_task.done():
            self._ticker_task = asyncio.create_task(self._ticker_loop())
            logger.info("Фоновый воркер проверки розыгрышей запущен.")

    async def close(self) -> None:
        if self._ticker_task and not self._ticker_task.done():
            self._ticker_task.cancel()
            try:
                await self._ticker_task
            except asyncio.CancelledError:
                pass

    async def _restore_active_giveaways(self) -> None:
        from bot.giveaway.views import GiveawayParticipationView

        active_giveaways = await self.get_active_giveaways()
        now = datetime.now(timezone.utc)

        for gw in active_giveaways:
            count = await self.get_participant_count(gw.id)
            view = GiveawayParticipationView(
                giveaway_id=gw.id,
                manager=self,
                participant_count=count,
            )
            self.bot.add_view(view)

            if gw.end_time <= now:
                asyncio.create_task(self.end_giveaway(gw.id))

        logger.info("Восстановлено активных розыгрышей: %d", len(active_giveaways))

    async def get_active_giveaways(self, guild_id: int | None = None) -> list[GiveawayRecord]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            if guild_id is not None:
                cursor = await db.execute(
                    "SELECT * FROM giveaways WHERE status = 'active' AND guild_id = ?",
                    (guild_id,),
                )
            else:
                cursor = await db.execute("SELECT * FROM giveaways WHERE status = 'active'")
            rows = await cursor.fetchall()
            return [GiveawayRecord.from_row(dict(r)) for r in rows]

    async def get_giveaway_by_id(self, giveaway_id: int) -> GiveawayRecord | None:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM giveaways WHERE id = ?", (giveaway_id,))
            row = await cursor.fetchone()
            if row:
                return GiveawayRecord.from_row(dict(row))
            return None

    async def get_giveaway_by_message_id(self, message_id: int) -> GiveawayRecord | None:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM giveaways WHERE message_id = ?", (message_id,))
            row = await cursor.fetchone()
            if row:
                return GiveawayRecord.from_row(dict(row))
            return None

    async def create_template(
        self,
        guild_id: int,
        creator_id: int,
        name: str,
        title: str | None = None,
        description: str | None = None,
        prizes: list | None = None,
        winners_count: int = 1,
        duration_str: str | None = None,
        image_url: str | None = None,
        image_path: str | None = None,
        require_stage: bool = False,
        require_voice: bool = False,
        enabled_points: bool = False,
        require_server: bool = False,
        required_guild_id: int | None = None,
        server_invite_url: str | None = None,
    ) -> GiveawayTemplate:
        created_at_iso = datetime.now(timezone.utc).isoformat()
        prizes_json = json.dumps([p.to_dict() if hasattr(p, "to_dict") else p for p in (prizes or [])], ensure_ascii=False) if prizes else None

        async with self._db_lock:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    """
                    INSERT INTO templates (
                        guild_id, creator_id, name, title, description, prizes,
                        winners_count, duration_str, image_url, image_path, require_stage,
                        require_voice, enabled_points, require_server, required_guild_id,
                        server_invite_url, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        creator_id,
                        name,
                        title,
                        description,
                        prizes_json,
                        winners_count,
                        duration_str,
                        image_url,
                        image_path,
                        1 if require_stage else 0,
                        1 if require_voice else 0,
                        1 if enabled_points else 0,
                        1 if require_server else 0,
                        required_guild_id,
                        server_invite_url,
                        created_at_iso,
                    ),
                )
                await db.commit()
                template_id = cursor.lastrowid

        return GiveawayTemplate(
            id=template_id,
            guild_id=guild_id,
            creator_id=creator_id,
            name=name,
            title=title,
            description=description,
            prizes=prizes or [],
            winners_count=winners_count,
            duration_str=duration_str,
            image_url=image_url,
            image_path=image_path,
            require_stage=require_stage,
            require_voice=require_voice,
            enabled_points=enabled_points,
            require_server=require_server,
            required_guild_id=required_guild_id,
            server_invite_url=server_invite_url,
            created_at=datetime.fromisoformat(created_at_iso),
        )

    async def update_template(
        self,
        template_id: int,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        prizes: list | None = None,
        winners_count: int | None = None,
        duration_str: str | None = None,
        image_url: str | None = None,
        image_path: str | None = None,
        require_stage: bool | None = None,
        require_voice: bool | None = None,
        enabled_points: bool | None = None,
        require_server: bool | None = None,
        required_guild_id: int | None = None,
        server_invite_url: str | None = None,
        clear_image: bool = False,
    ) -> bool:
        tpl = await self.get_template(template_id)
        if not tpl:
            return False

        new_name = name if name is not None else tpl.name
        new_title = title if title is not None else tpl.title
        new_desc = description if description is not None else tpl.description
        new_prizes = prizes if prizes is not None else tpl.prizes
        new_winners = winners_count if winners_count is not None else tpl.winners_count
        new_dur = duration_str if duration_str is not None else tpl.duration_str
        if clear_image:
            from bot.utils.image_helper import delete_local_file
            delete_local_file(tpl.image_path)
            new_img = None
            new_img_path = None
        elif image_url is not None:
            from bot.utils.image_helper import delete_local_file
            delete_local_file(tpl.image_path)
            new_img = image_url
            new_img_path = None
        else:
            new_img = tpl.image_url
            new_img_path = image_path if image_path is not None else tpl.image_path
        new_stage = require_stage if require_stage is not None else tpl.require_stage
        new_voice = require_voice if require_voice is not None else tpl.require_voice
        new_pts = enabled_points if enabled_points is not None else tpl.enabled_points
        new_server = require_server if require_server is not None else tpl.require_server
        new_req_gid = required_guild_id if required_guild_id is not None else tpl.required_guild_id
        new_inv_url = server_invite_url if server_invite_url is not None else tpl.server_invite_url

        prizes_json = json.dumps([p.to_dict() if hasattr(p, "to_dict") else p for p in new_prizes], ensure_ascii=False) if new_prizes else None

        async with self._db_lock:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """
                    UPDATE templates
                    SET name = ?, title = ?, description = ?, prizes = ?,
                        winners_count = ?, duration_str = ?, image_url = ?, image_path = ?,
                        require_stage = ?, require_voice = ?, enabled_points = ?,
                        require_server = ?, required_guild_id = ?, server_invite_url = ?
                    WHERE id = ?
                    """,
                    (
                        new_name,
                        new_title,
                        new_desc,
                        prizes_json,
                        new_winners,
                        new_dur,
                        new_img,
                        new_img_path,
                        1 if new_stage else 0,
                        1 if new_voice else 0,
                        1 if new_pts else 0,
                        1 if new_server else 0,
                        new_req_gid,
                        new_inv_url,
                        template_id,
                    ),
                )
                await db.commit()
                return True

    async def get_templates(self, guild_id: int) -> list[GiveawayTemplate]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM templates WHERE guild_id = ? ORDER BY id DESC",
                (guild_id,),
            )
            rows = await cursor.fetchall()
            return [GiveawayTemplate.from_row(dict(r)) for r in rows]

    async def get_template(self, template_id: int) -> GiveawayTemplate | None:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM templates WHERE id = ?", (template_id,))
            row = await cursor.fetchone()
            if row:
                return GiveawayTemplate.from_row(dict(row))
            return None

    async def delete_template(self, template_id: int) -> bool:
        async with self._db_lock:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute("DELETE FROM templates WHERE id = ?", (template_id,))
                await db.commit()
                return cursor.rowcount > 0

    async def publish_giveaway(
        self,
        draft: GiveawayDraft,
        target_channel: disnake.TextChannel,
    ) -> tuple[bool, str, disnake.Message | None]:
        from bot.giveaway.views import GiveawayParticipationView

        bot_member = target_channel.guild.me
        if not bot_member:
            try:
                bot_member = await target_channel.guild.fetch_member(self.bot.user.id)
            except disnake.HTTPException:
                bot_member = None

        if bot_member:
            perms = target_channel.permissions_for(bot_member)
            if not (perms.send_messages and perms.embed_links):
                return False, f"У бота нет прав отправлять сообщения и ссылки в канале {target_channel.mention}!", None

        now = datetime.now(timezone.utc)
        duration_delta = draft.duration_delta or parse_duration(draft.duration_str or "10m")
        end_time = now + duration_delta

        prizes_json = json.dumps([p.to_dict() for p in draft.prizes], ensure_ascii=False)
        created_at_iso = now.isoformat()
        end_time_iso = end_time.isoformat()

        async with self._db_lock:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    """
                    INSERT INTO giveaways (
                        guild_id, channel_id, message_id, title, description,
                        prizes, winners_count, image_url, image_path, creator_id, end_time,
                        duration_str, status, winners, require_stage, require_voice,
                        enabled_points, require_server, required_guild_id, server_invite_url,
                        template_id, created_at
                    ) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        draft.guild_id,
                        target_channel.id,
                        draft.title.strip() if draft.title and draft.title.strip() else "Розыгрыш",
                        draft.description,
                        prizes_json,
                        draft.winners_count,
                        draft.image_url,
                        draft.image_path,
                        draft.creator_id,
                        end_time_iso,
                        draft.duration_str,
                        1 if draft.require_stage else 0,
                        1 if draft.require_voice else 0,
                        1 if draft.enabled_points else 0,
                        1 if draft.require_server else 0,
                        draft.required_guild_id,
                        draft.server_invite_url,
                        draft.template_id,
                        created_at_iso,
                    ),
                )
                await db.commit()
                giveaway_id = cursor.lastrowid

        record = await self.get_giveaway_by_id(giveaway_id)
        if not record:
            return False, "Не удалось создать запись розыгрыша.", None

        active_container = GiveawayBuilder.build_active_container(record, participant_count=0)

        file_to_send = None
        if draft.image_path:
            file_to_send = disnake.File(draft.image_path, filename="giveaway.png")

        try:
            giveaway_message = await target_channel.send(
                content=None,
                embed=None,
                components=[active_container],
                file=file_to_send,
            )
        except disnake.HTTPException as exc:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM giveaways WHERE id = ?", (giveaway_id,))
                await db.commit()
            return False, f"Ошибка отправки сообщения: {exc}", None

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE giveaways SET message_id = ? WHERE id = ?",
                (giveaway_message.id, giveaway_id),
            )
            await db.commit()

        return True, "", giveaway_message

    async def add_participant(
        self,
        giveaway_id: int,
        member: disnake.Member,
    ) -> tuple[bool, int, str]:
        record = await self.get_giveaway_by_id(giveaway_id)
        if not record:
            return False, 0, "Розыгрыш не найден."
        if record.status != "active":
            return False, 0, "Этот розыгрыш уже завершен."

        voice_state = member.voice
        channel = voice_state.channel if voice_state else None
        if record.require_stage:
            if not self.is_channel_valid_for_giveaway(channel, record, voice_state):
                return False, 0, "Для участия в этом розыгрыше необходимо находиться на трибуне (Stage channel) этого сервера."
        elif record.require_voice:
            if not self.is_channel_valid_for_giveaway(channel, record, voice_state):
                return False, 0, "Для участия в этом розыгрыше необходимо находиться в голосовом канале этого сервера."

        if record.require_server and record.required_guild_id:
            partner_guild = self.bot.get_guild(record.required_guild_id)
            if not partner_guild:
                try:
                    partner_guild = await self.bot.fetch_guild(record.required_guild_id)
                except Exception:
                    partner_guild = None

            is_partner_member = False
            if partner_guild:
                p_member = partner_guild.get_member(member.id)
                if not p_member:
                    try:
                        p_member = await partner_guild.fetch_member(member.id)
                    except Exception:
                        p_member = None
                if p_member and not isinstance(p_member, Exception):
                    is_partner_member = True

            if not is_partner_member:
                server_title = partner_guild.name if partner_guild else "сервер-партнер"
                invite_text = f"\nВступите на сервер: {record.server_invite_url}" if record.server_invite_url else ""
                return (
                    False,
                    0,
                    f"Для участия необходимо быть участником сервера **{server_title}**.{invite_text}",
                )

        now_iso = datetime.now(timezone.utc).isoformat()
        is_voice_valid = self.is_channel_valid_for_giveaway(channel, record, voice_state)
        voice_joined_at = now_iso if is_voice_valid else None

        async with self._db_lock:
            async with aiosqlite.connect(DB_PATH) as db:
                try:
                    await db.execute(
                        """
                        INSERT INTO participants (
                            giveaway_id, user_id, joined_at, voice_seconds, voice_joined_at, points
                        ) VALUES (?, ?, ?, 0.0, ?, 0.0)
                        """,
                        (giveaway_id, member.id, now_iso, voice_joined_at),
                    )
                    await db.commit()
                except aiosqlite.IntegrityError:
                    count_cur = await db.execute(
                        "SELECT COUNT(*) FROM participants WHERE giveaway_id = ?",
                        (giveaway_id,),
                    )
                    current_count = (await count_cur.fetchone())[0]
                    return False, current_count, "Вы уже участвуете в этом розыгрыше."

                count_cur = await db.execute(
                    "SELECT COUNT(*) FROM participants WHERE giveaway_id = ?",
                    (giveaway_id,),
                )
                new_count = (await count_cur.fetchone())[0]
                return True, new_count, ""

    async def kick_participant(self, giveaway_id: int, user_id: int) -> bool:
        async with self._db_lock:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    "DELETE FROM participants WHERE giveaway_id = ? AND user_id = ?",
                    (giveaway_id, user_id),
                )
                await db.commit()
                success = cursor.rowcount > 0

        if success:
            await self.update_giveaway_message_count(giveaway_id)
        return success

    async def is_participant(self, giveaway_id: int, user_id: int) -> bool:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT 1 FROM participants WHERE giveaway_id = ? AND user_id = ?",
                (giveaway_id, user_id),
            )
            row = await cursor.fetchone()
            return row is not None

    async def update_giveaway(
        self,
        giveaway_id: int,
        title: str | None = None,
        image_url: str | None = None,
        image_path: str | None = None,
        require_stage: bool | None = None,
        require_voice: bool | None = None,
        enabled_points: bool | None = None,
        require_server: bool | None = None,
        required_guild_id: int | None = None,
        server_invite_url: str | None = None,
        clear_image: bool = False,
    ) -> GiveawayRecord | None:
        record = await self.get_giveaway_by_id(giveaway_id)
        if not record:
            return None

        new_title = title if title is not None else record.title
        if clear_image:
            from bot.utils.image_helper import delete_local_file
            delete_local_file(record.image_path)
            new_img_url = None
            new_img_path = None
        elif image_url is not None:
            from bot.utils.image_helper import delete_local_file
            delete_local_file(record.image_path)
            new_img_url = image_url
            new_img_path = None
        else:
            new_img_url = record.image_url
            new_img_path = image_path if image_path is not None else record.image_path
        new_stage = require_stage if require_stage is not None else record.require_stage
        new_voice = require_voice if require_voice is not None else record.require_voice
        new_points = enabled_points if enabled_points is not None else record.enabled_points
        new_server = require_server if require_server is not None else record.require_server
        new_req_gid = required_guild_id if required_guild_id is not None else record.required_guild_id
        new_inv_url = server_invite_url if server_invite_url is not None else record.server_invite_url

        async with self._db_lock:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """
                    UPDATE giveaways
                    SET title = ?, image_url = ?, image_path = ?,
                        require_stage = ?, require_voice = ?, enabled_points = ?,
                        require_server = ?, required_guild_id = ?, server_invite_url = ?
                    WHERE id = ?
                    """,
                    (
                        new_title,
                        new_img_url,
                        new_img_path,
                        1 if new_stage else 0,
                        1 if new_voice else 0,
                        1 if new_points else 0,
                        1 if new_server else 0,
                        new_req_gid,
                        new_inv_url,
                        giveaway_id,
                    ),
                )
                await db.commit()

        updated_record = await self.get_giveaway_by_id(giveaway_id)
        if updated_record and updated_record.status == "active":
            channel = self.bot.get_channel(updated_record.channel_id)
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(updated_record.channel_id)
                except Exception:
                    channel = None
            if isinstance(channel, disnake.TextChannel):
                try:
                    msg = await channel.fetch_message(updated_record.message_id)
                    p_count = await self.get_participant_count(giveaway_id)
                    active_container = GiveawayBuilder.build_active_container(
                        record=updated_record,
                        participant_count=p_count,
                    )
                    edit_kwargs: dict[str, Any] = {
                        "content": None,
                        "embed": None,
                        "components": [active_container],
                    }
                    if clear_image:
                        edit_kwargs["attachments"] = []
                    elif image_path is not None:
                        if updated_record.image_path and os.path.exists(updated_record.image_path):
                            edit_kwargs["file"] = disnake.File(updated_record.image_path, filename="giveaway.png")
                            edit_kwargs["attachments"] = []
                        else:
                            edit_kwargs["attachments"] = []
                    elif image_url is not None and not updated_record.image_path:
                        edit_kwargs["attachments"] = []
                    elif updated_record.image_path and os.path.exists(updated_record.image_path):
                        has_attachment = any(a.filename == "giveaway.png" for a in getattr(msg, "attachments", []))
                        if not has_attachment:
                            edit_kwargs["file"] = disnake.File(updated_record.image_path, filename="giveaway.png")
                            edit_kwargs["attachments"] = []
                    else:
                        edit_kwargs["attachments"] = []

                    await msg.edit(**edit_kwargs)
                except Exception as exc:
                    logger.warning("Не удалось обновить активное сообщение розыгрыша #%s: %s", giveaway_id, exc)

        return updated_record

    async def get_participant_count(self, giveaway_id: int) -> int:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM participants WHERE giveaway_id = ?",
                (giveaway_id,),
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def count_unique_participants(self, giveaway_id: int) -> int:
        async with aiosqlite.connect(DB_PATH) as db:
            query = """
                SELECT COUNT(DISTINCT p.user_id)
                FROM participants p
                JOIN giveaways g ON p.giveaway_id = g.id
                WHERE p.giveaway_id = ?
                  AND p.user_id NOT IN (
                      SELECT prev_p.user_id
                      FROM participants prev_p
                      JOIN giveaways prev_g ON prev_p.giveaway_id = prev_g.id
                      WHERE prev_g.guild_id = g.guild_id
                        AND prev_g.id != g.id
                        AND prev_g.created_at < g.created_at
                  )
            """
            cursor = await db.execute(query, (giveaway_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0

    def is_channel_valid_for_giveaway(
        self,
        channel: disnake.abc.GuildChannel | None,
        gw: GiveawayRecord,
        voice_state: disnake.VoiceState | None = None,
    ) -> bool:
        if not channel or not hasattr(channel, "guild") or channel.guild.id != gw.guild_id:
            return False
        if voice_state and getattr(voice_state, "afk", False) is True:
            return False
        guild = channel.guild
        afk_ch = getattr(guild, "afk_channel", None)
        if afk_ch is not None and afk_ch is channel:
            return False

        if gw.require_stage:
            return isinstance(channel, disnake.StageChannel)
        if gw.require_voice:
            return not isinstance(channel, disnake.StageChannel)
        if gw.enabled_points:
            return True
        return False

    async def update_voice_state(
        self,
        member: disnake.Member,
        before: disnake.VoiceState,
        after: disnake.VoiceState,
    ) -> None:
        active_giveaways = await self.get_active_giveaways(member.guild.id)
        if not active_giveaways:
            return

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        for gw in active_giveaways:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM participants WHERE giveaway_id = ? AND user_id = ?",
                    (gw.id, member.id),
                )
                participant = await cursor.fetchone()
                if not participant:
                    continue

                was_valid = self.is_channel_valid_for_giveaway(before.channel, gw, before)
                is_valid = self.is_channel_valid_for_giveaway(after.channel, gw, after)
                prev_joined_at = participant["voice_joined_at"]

                if is_valid and not prev_joined_at:
                    await db.execute(
                        "UPDATE participants SET voice_joined_at = ? WHERE giveaway_id = ? AND user_id = ?",
                        (now_iso, gw.id, member.id),
                    )
                    await db.commit()

                elif not is_valid and prev_joined_at:
                    try:
                        joined_dt = datetime.fromisoformat(prev_joined_at)
                        if joined_dt.tzinfo is None:
                            joined_dt = joined_dt.replace(tzinfo=timezone.utc)
                        delta_sec = max(0.0, (now - joined_dt).total_seconds())
                    except Exception:
                        delta_sec = 0.0

                    new_voice_sec = (participant["voice_seconds"] or 0.0) + delta_sec
                    new_points = participant["points"] or 0.0
                    if gw.enabled_points:
                        new_points += (delta_sec / 60.0) * 0.1

                    await db.execute(
                        """
                        UPDATE participants
                        SET voice_seconds = ?, voice_joined_at = NULL, points = ?
                        WHERE giveaway_id = ? AND user_id = ?
                        """,
                        (new_voice_sec, new_points, gw.id, member.id),
                    )
                    await db.commit()

                elif is_valid and prev_joined_at and before.channel != after.channel:
                    try:
                        joined_dt = datetime.fromisoformat(prev_joined_at)
                        if joined_dt.tzinfo is None:
                            joined_dt = joined_dt.replace(tzinfo=timezone.utc)
                        delta_sec = max(0.0, (now - joined_dt).total_seconds())
                    except Exception:
                        delta_sec = 0.0

                    new_voice_sec = (participant["voice_seconds"] or 0.0) + delta_sec
                    new_points = participant["points"] or 0.0
                    if gw.enabled_points:
                        new_points += (delta_sec / 60.0) * 0.1

                    await db.execute(
                        """
                        UPDATE participants
                        SET voice_seconds = ?, voice_joined_at = ?, points = ?
                        WHERE giveaway_id = ? AND user_id = ?
                        """,
                        (new_voice_sec, now_iso, new_points, gw.id, member.id),
                    )
                    await db.commit()

    async def get_participant_data(self, giveaway_id: int, user_id: int) -> ParticipantData | None:
        gw = await self.get_giveaway_by_id(giveaway_id)
        if not gw:
            return None

        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM participants WHERE giveaway_id = ? AND user_id = ?",
                (giveaway_id, user_id),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            joined_at = datetime.fromisoformat(row["joined_at"])
            if joined_at.tzinfo is None:
                joined_at = joined_at.replace(tzinfo=timezone.utc)

            voice_sec = row["voice_seconds"] or 0.0
            points = row["points"] or 0.0

            if row["voice_joined_at"]:
                try:
                    v_joined = datetime.fromisoformat(row["voice_joined_at"])
                    if v_joined.tzinfo is None:
                        v_joined = v_joined.replace(tzinfo=timezone.utc)
                    end_ref = gw.end_time if gw.status == "ended" else now
                    delta = max(0.0, (min(now, end_ref) - v_joined).total_seconds())
                    voice_sec += delta
                    if gw.enabled_points:
                        points += (delta / 60.0) * 0.1
                except Exception:
                    pass

        participants = await self.get_all_participants_sorted(giveaway_id)
        chance = 0.0
        for p in participants:
            if p.user_id == user_id:
                chance = p.chance_percent
                break

        return ParticipantData(
            giveaway_id=giveaway_id,
            user_id=user_id,
            joined_at=joined_at,
            voice_seconds=voice_sec,
            points=points,
            chance_percent=chance,
        )

    async def get_all_participants_sorted(self, giveaway_id: int) -> list[ParticipantData]:
        gw = await self.get_giveaway_by_id(giveaway_id)
        if not gw:
            return []

        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM participants WHERE giveaway_id = ?",
                (giveaway_id,),
            )
            rows = await cursor.fetchall()

        if not rows:
            return []

        data_list: list[ParticipantData] = []
        weights: list[float] = []

        for r in rows:
            joined_at = datetime.fromisoformat(r["joined_at"])
            if joined_at.tzinfo is None:
                joined_at = joined_at.replace(tzinfo=timezone.utc)

            voice_sec = r["voice_seconds"] or 0.0
            points = r["points"] or 0.0

            if r["voice_joined_at"]:
                try:
                    v_joined = datetime.fromisoformat(r["voice_joined_at"])
                    if v_joined.tzinfo is None:
                        v_joined = v_joined.replace(tzinfo=timezone.utc)
                    end_ref = gw.end_time if gw.status == "ended" else now
                    delta = max(0.0, (min(now, end_ref) - v_joined).total_seconds())
                    voice_sec += delta
                    if gw.enabled_points:
                        points += (delta / 60.0) * 0.1
                except Exception:
                    pass

            if gw.enabled_points:
                w = 1.0 + min(math.sqrt(max(0.0, points)) * 0.5, 2.0)
            else:
                w = 1.0
            weights.append(w)
            data_list.append(
                ParticipantData(
                    giveaway_id=giveaway_id,
                    user_id=r["user_id"],
                    joined_at=joined_at,
                    voice_seconds=voice_sec,
                    points=points,
                )
            )

        total_weight = sum(weights)
        for idx, item in enumerate(data_list):
            item.chance_percent = (weights[idx] / total_weight) * 100.0 if total_weight > 0 else 0.0

        data_list.sort(key=lambda p: (p.chance_percent, p.points), reverse=True)
        return data_list

    async def end_giveaway(self, giveaway_id: int) -> None:
        async with self._db_lock:
            record = await self.get_giveaway_by_id(giveaway_id)
            if not record or record.status != "active":
                return

            now = datetime.now(timezone.utc)
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM participants WHERE giveaway_id = ? AND voice_joined_at IS NOT NULL",
                    (giveaway_id,),
                )
                voice_participants = await cursor.fetchall()
                for vp in voice_participants:
                    try:
                        v_joined = datetime.fromisoformat(vp["voice_joined_at"])
                        if v_joined.tzinfo is None:
                            v_joined = v_joined.replace(tzinfo=timezone.utc)
                        delta_sec = max(0.0, (now - v_joined).total_seconds())
                    except Exception:
                        delta_sec = 0.0

                    new_voice_sec = (vp["voice_seconds"] or 0.0) + delta_sec
                    new_points = vp["points"] or 0.0
                    if record.enabled_points:
                        new_points += (delta_sec / 60.0) * 0.1

                    await db.execute(
                        """
                        UPDATE participants
                        SET voice_seconds = ?, voice_joined_at = NULL, points = ?
                        WHERE giveaway_id = ? AND user_id = ?
                        """,
                        (new_voice_sec, new_points, giveaway_id, vp["user_id"]),
                    )

                await db.execute(
                    "UPDATE giveaways SET status = 'ended' WHERE id = ?",
                    (giveaway_id,),
                )
                await db.commit()

        participants = await self.get_all_participants_sorted(giveaway_id)
        participant_count = len(participants)

        winners_data: list[dict] = []
        num_winners_to_pick = max(len(record.prizes), record.winners_count)
        if participants and num_winners_to_pick > 0:
            sample_size = min(num_winners_to_pick, participant_count)

            pool = list(participants)
            for place_idx in range(sample_size):
                if record.enabled_points:
                    pool_weights = [1.0 + min(math.sqrt(max(0.0, p.points)) * 0.5, 2.0) for p in pool]
                else:
                    pool_weights = [1.0 for _ in pool]
                chosen = secrets.SystemRandom().choices(pool, weights=pool_weights, k=1)[0]
                pool.remove(chosen)

                prize_desc = record.prizes[place_idx].description if place_idx < len(record.prizes) else ""
                place_num = record.prizes[place_idx].place if place_idx < len(record.prizes) else (place_idx + 1)
                winners_data.append(
                    {
                        "place": place_num,
                        "user_id": chosen.user_id,
                        "prize_description": prize_desc,
                        "points": chosen.points,
                        "chance_percent": chosen.chance_percent,
                    }
                )

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE giveaways SET winners = ? WHERE id = ?",
                (
                    json.dumps(winners_data, ensure_ascii=False) if winners_data else None,
                    giveaway_id,
                ),
            )
            await db.commit()

        await self._render_ended_message(record, participant_count, winners_data, is_reroll=False)

    async def reroll_giveaway(self, giveaway_id: int) -> tuple[bool, str, list[dict]]:
        record = await self.get_giveaway_by_id(giveaway_id)
        if not record:
            return False, "Розыгрыш не найден.", []
        if record.status != "ended":
            return False, "Розыгрыш еще не завершен.", []

        participants = await self.get_all_participants_sorted(giveaway_id)
        if not participants:
            return False, "Участников нет, реролл невозможен.", []

        num_winners_to_pick = max(len(record.prizes), record.winners_count)
        winners_data: list[dict] = []
        pool = list(participants)
        sample_size = min(num_winners_to_pick, len(participants))
        for place_idx in range(sample_size):
            if record.enabled_points:
                pool_weights = [1.0 + min(math.sqrt(max(0.0, p.points)) * 0.5, 2.0) for p in pool]
            else:
                pool_weights = [1.0 for _ in pool]
            chosen = secrets.SystemRandom().choices(pool, weights=pool_weights, k=1)[0]
            pool.remove(chosen)

            prize_desc = record.prizes[place_idx].description if place_idx < len(record.prizes) else ""
            place_num = record.prizes[place_idx].place if place_idx < len(record.prizes) else (place_idx + 1)
            winners_data.append(
                {
                    "place": place_num,
                    "user_id": chosen.user_id,
                    "prize_description": prize_desc,
                    "points": chosen.points,
                    "chance_percent": chosen.chance_percent,
                }
            )

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE giveaways SET winners = ? WHERE id = ?",
                (
                    json.dumps(winners_data, ensure_ascii=False),
                    giveaway_id,
                ),
            )
            await db.commit()

        await self._render_ended_message(record, len(participants), winners_data, is_reroll=True)
        return True, "", winners_data

    async def _render_ended_message(
        self,
        record: GiveawayRecord,
        participant_count: int,
        winners_data: list[dict],
        is_reroll: bool = False,
    ) -> None:
        channel = self.bot.get_channel(record.channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(record.channel_id)
            except Exception:
                channel = None

        if not channel or not hasattr(channel, "send"):
            return

        message: disnake.Message | None = None
        try:
            message = await channel.fetch_message(record.message_id)
        except Exception:
            pass

        ended_container = GiveawayBuilder.build_ended_container(
            record=record,
            participant_count=participant_count,
            winners=winners_data,
        )

        if message:
            try:
                edit_kwargs: dict[str, Any] = {"content": None, "embed": None, "components": [ended_container]}
                if record.image_path and os.path.exists(record.image_path):
                    has_attachment = any(a.filename == "giveaway.png" for a in getattr(message, "attachments", []))
                    if not has_attachment:
                        edit_kwargs["file"] = disnake.File(record.image_path, filename="giveaway.png")
                        edit_kwargs["attachments"] = []
                await message.edit(**edit_kwargs)
            except disnake.HTTPException:
                pass

        if winners_data:
            announcement_container = GiveawayBuilder.build_announcement_container(
                record=record,
                winners=winners_data,
                message_jump_url=message.jump_url if (message and not is_reroll) else None,
                is_reroll=is_reroll,
            )
            allowed_mentions = disnake.AllowedMentions(replied_user=False, users=True)
            try:
                if message:
                    await message.reply(
                        components=[announcement_container],
                        allowed_mentions=allowed_mentions,
                    )
                else:
                    await channel.send(
                        components=[announcement_container],
                        allowed_mentions=allowed_mentions,
                    )
            except Exception as exc:
                logger.error("Ошибка при отправке анонса победителей: %s", exc)
                try:
                    await channel.send(
                        components=[announcement_container],
                        allowed_mentions=allowed_mentions,
                    )
                except Exception:
                    pass
        else:
            try:
                from disnake.ui import Container, TextDisplay
                disp_title = record.title.strip() if (record.title and record.title.strip() and record.title.strip().lower() not in ("розыгрыш", "новый розыгрыш")) else ""
                end_text = f"Розыгрыш **{disp_title}** завершен, но участников нет." if disp_title else "Розыгрыш завершен, но участников нет."
                no_participants_container = Container(
                    TextDisplay(f"## Розыгрыш завершен\n{end_text}")
                )
                if message:
                    await message.reply(
                        components=[no_participants_container],
                        allowed_mentions=disnake.AllowedMentions(replied_user=False),
                    )
                else:
                    await channel.send(components=[no_participants_container])
            except Exception:
                pass

    async def update_giveaway_message_count(self, giveaway_id: int) -> None:
        record = await self.get_giveaway_by_id(giveaway_id)
        if not record or record.status != "active":
            return

        count = await self.get_participant_count(giveaway_id)
        channel = self.bot.get_channel(record.channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(record.channel_id)
            except Exception:
                channel = None

        if not isinstance(channel, disnake.TextChannel):
            return

        try:
            message = await channel.fetch_message(record.message_id)
            if message:
                active_container = GiveawayBuilder.build_active_container(record, participant_count=count)
                edit_kwargs: dict[str, Any] = {"content": None, "embed": None, "components": [active_container]}
                if record.image_path and os.path.exists(record.image_path):
                    has_attachment = any(a.filename == "giveaway.png" for a in getattr(message, "attachments", []))
                    if not has_attachment:
                        edit_kwargs["file"] = disnake.File(record.image_path, filename="giveaway.png")
                        edit_kwargs["attachments"] = []
                await message.edit(**edit_kwargs)
        except Exception:
            pass

    async def handle_message_deleted(self, message_id: int, channel_id: int) -> None:
        if message_id in self._handled_deleted_messages:
            return

        record = await self.get_giveaway_by_message_id(message_id)
        if not record:
            return

        self._handled_deleted_messages.add(message_id)

        if record.status == "active":
            logger.info("Сообщение активного розыгрыша #%s было удалено. Завершаем розыгрыш и отправляем V2 результаты.", record.id)
            await self.end_giveaway(record.id)
        elif record.status == "ended":
            logger.info("Сообщение завершенного розыгрыша #%s было удалено. Отправляем V2 компонент с результатами.", record.id)
            channel = self.bot.get_channel(channel_id)
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    channel = None
            if not channel or not hasattr(channel, "send"):
                return

            if record.winners:
                announcement_container = GiveawayBuilder.build_announcement_container(
                    record=record,
                    winners=record.winners,
                    message_jump_url=None,
                    is_reroll=False,
                )
                try:
                    await channel.send(
                        components=[announcement_container],
                        allowed_mentions=disnake.AllowedMentions(replied_user=False, users=True),
                    )
                except Exception as exc:
                    logger.error("Не удалось отправить результаты удаленного розыгрыша #%s: %s", record.id, exc)
            else:
                from disnake.ui import Container, TextDisplay
                disp_title = record.title.strip() if (record.title and record.title.strip() and record.title.strip().lower() not in ("розыгрыш", "новый розыгрыш")) else ""
                end_text = f"Розыгрыш **{disp_title}** завершен, но участников нет." if disp_title else "Розыгрыш завершен, но участников нет."
                no_participants_container = Container(
                    TextDisplay(f"## Розыгрыш завершен\n{end_text}")
                )
                try:
                    await channel.send(
                        components=[no_participants_container],
                        allowed_mentions=disnake.AllowedMentions(replied_user=False),
                    )
                except Exception as exc:
                    logger.error("Не удалось отправить сообщение об отсутствии участников: %s", exc)

    async def _ticker_loop(self) -> None:
        res = self.bot.wait_until_ready()
        if asyncio.iscoroutine(res):
            await res
        while not self.bot.is_closed():
            try:
                now = datetime.now(timezone.utc)
                active_giveaways = await self.get_active_giveaways()
                for gw in active_giveaways:
                    if gw.end_time <= now:
                        logger.info("Срок розыгрыша #%s истек. Завершаем...", gw.id)
                        await self.end_giveaway(gw.id)
            except Exception as exc:
                logger.error("Ошибка в цикле проверки: %s", exc)

            await asyncio.sleep(5)
