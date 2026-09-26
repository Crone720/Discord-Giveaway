from typing import Any
import disnake

from bot.giveaway.models import GiveawayDraft, GiveawayRecord
from bot.giveaway.parser import format_prizes_display
from bot.utils.time_parser import to_discord_timestamp


def format_title_header(prefix: str, title: str | None, default_no_title: str | None = None) -> str:
    clean_title = (title or "").strip()
    is_custom = bool(clean_title and clean_title.lower() not in ("розыгрыш", "новый розыгрыш"))
    if is_custom:
        return f"{prefix}: {clean_title}"
    return default_no_title if default_no_title is not None else prefix


class GiveawayBuilder:
    @staticmethod
    def build_preview_embed(draft: GiveawayDraft) -> disnake.Embed:
        embed = disnake.Embed(
            title=f"GIVEAWAY: {draft.display_title}",
            description=draft.display_description,
            color=None,
        )

        prizes_val = format_prizes_display(draft.prizes) if draft.prizes else "*Не указаны (необязательно)*"
        embed.add_field(
            name="Призы",
            value=prizes_val,
            inline=False,
        )

        embed.add_field(
            name="Победителей",
            value=f"`{draft.winners_count}`",
            inline=True,
        )

        if draft.duration_str:
            time_val = f"Длительность: {draft.duration_str}"
        else:
            time_val = "*Не указано (нажмите кнопку 'Время')*"

        embed.add_field(name="Время", value=time_val, inline=True)

        req_parts: list[str] = []
        if draft.require_stage:
            req_parts.append("Трибуна: Обязательно")
        elif draft.require_voice:
            req_parts.append("Голосовой канал: Обязательно")

        if draft.enabled_points:
            req_parts.append("Баллы за голосовой канал: Включены (0.1/мин)")
        if draft.require_server:
            req_parts.append("Сервер-партнер: Обязательно")

        req_text = "\n".join(req_parts) if req_parts else "Без ограничений"
        embed.add_field(name="Условия участия", value=req_text, inline=True)

        if draft.channel_id:
            embed.add_field(
                name="Канал публикации",
                value=f"<#{draft.channel_id}>",
                inline=True,
            )
        else:
            embed.add_field(
                name="Канал публикации",
                value="*Будет выбран при создании*",
                inline=True,
            )

        if draft.image_path:
            embed.set_image(url="attachment://preview.png")
        elif draft.image_url:
            embed.set_image(url=draft.image_url)

        embed.set_footer(text="Embed Builder")
        return embed

    @staticmethod
    def build_active_embed(
        record: GiveawayRecord,
        participant_count: int = 0,
    ) -> disnake.Embed:
        embed = disnake.Embed(
            title=format_title_header("Розыгрыш", record.title),
            description=record.description or "Примите участие в розыгрыше, нажав кнопку ниже.",
            color=None,
        )

        embed.add_field(
            name="Призы",
            value=format_prizes_display(record.prizes),
            inline=False,
        )

        time_val = f"{to_discord_timestamp(record.end_time, 'R')} ({to_discord_timestamp(record.end_time, 'f')})"
        embed.add_field(name="Завершение", value=time_val, inline=True)
        embed.add_field(name="Участников", value=f"`{participant_count}`", inline=True)

        req_parts: list[str] = []
        if record.require_stage:
            req_parts.append("Требуется находиться на трибуне")
        elif record.require_voice:
            req_parts.append("Требуется находиться в голосовом канале")

        if record.enabled_points:
            req_parts.append("Баллы за войс активны (+0.1 балла/мин)")
        if record.require_server:
            req_parts.append("Требуется вступить на сервер-партнер")

        if req_parts:
            embed.add_field(name="Условия", value="\n".join(req_parts), inline=False)

        if record.image_path:
            embed.set_image(url="attachment://giveaway.png")
        elif record.image_url:
            embed.set_image(url=record.image_url)

        embed.set_footer(text="Нажмите кнопку 'Участвовать' ниже, чтобы принять участие.")
        return embed

    @staticmethod
    def build_ended_embed(
        record: GiveawayRecord,
        participant_count: int,
        winners: list[dict[str, Any]] | None,
    ) -> disnake.Embed:
        winner_lines: list[str] = []
        if winners:
            for w in winners:
                user_id = w.get("user_id")
                pts = float(w.get("points", 0.0) or 0.0)
                chance = float(w.get("chance_percent", 0.0) or 0.0)
                desc = w.get("prize_description", "")
                prize_str = f" — Приз: {desc}" if desc else ""
                if record.enabled_points:
                    winner_lines.append(f"<@{user_id}> — {pts:.1f} баллов ({chance:.1f}% шанс){prize_str}")
                else:
                    winner_lines.append(f"<@{user_id}>{prize_str}")
            winners_desc = "\n".join(winner_lines)
        else:
            winners_desc = "*Победители не выбраны (участников не было)*"

        full_desc = f"### Победители:\n{winners_desc}\n\n{record.description or ''}".strip()

        embed = disnake.Embed(
            title=format_title_header("РОЗЫГРЫШ ЗАВЕРШЕН", record.title),
            description=full_desc,
            color=None,
        )

        if record.prizes:
            embed.add_field(
                name="Призы",
                value=format_prizes_display(record.prizes),
                inline=False,
            )

        embed.add_field(name="Всего участников", value=f"`{participant_count}`", inline=True)
        embed.add_field(name="Завершился", value=to_discord_timestamp(record.end_time, "f"), inline=True)

        if record.image_path:
            embed.set_image(url="attachment://giveaway.png")
        elif record.image_url:
            embed.set_image(url=record.image_url)

        embed.set_footer(text="Розыгрыш завершен.")
        return embed

    @staticmethod
    def build_active_container(
        record: GiveawayRecord,
        participant_count: int = 0,
    ) -> disnake.ui.Container:
        from disnake.ui import Container, MediaGallery, TextDisplay, Separator, ActionRow, Button
        from disnake.ui.media_gallery import MediaGalleryItem

        children = []

        if record.image_path:
            children.append(MediaGallery(MediaGalleryItem("attachment://giveaway.png")))
        elif record.image_url:
            try:
                children.append(MediaGallery(MediaGalleryItem(record.image_url)))
            except Exception:
                pass

        children.append(TextDisplay(format_title_header("# Розыгрыш", record.title)))
        children.append(Separator())

        if record.description:
            children.append(TextDisplay(record.description))
            children.append(Separator())

        info_lines = [
            f"**Победителей:** {record.winners_count}",
        ]
        if record.prizes:
            info_lines.append(f"**Призы:**\n{format_prizes_display(record.prizes)}")
        info_lines.append(f"**Завершение:** {to_discord_timestamp(record.end_time, 'R')} ({to_discord_timestamp(record.end_time, 'f')})")
        info_lines.append(f"**Участников:** `{participant_count}`")

        req_parts: list[str] = []
        if record.require_stage:
            req_parts.append("Требуется находиться на трибуне")
        elif record.require_voice:
            req_parts.append("Требуется находиться в голосовом канале")
        if record.enabled_points:
            req_parts.append("Баллы за войс активны (+0.1 балла/мин)")
        if record.require_server:
            req_parts.append("Требуется вступить на сервер-партнер")

        if req_parts:
            info_lines.append(f"**Условия участия:**\n" + "\n".join(f"-# • {p}" for p in req_parts))

        children.append(TextDisplay("\n".join(info_lines)))
        children.append(Separator())

        act_buttons = [
            Button(
                label=f"Участвовать ({participant_count})",
                style=disnake.ButtonStyle.primary,
                custom_id=f"giveaway_enter:{record.id}",
            ),
            Button(
                label="Участники",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"giveaway_participants:{record.id}",
            ),
        ]
        if record.require_server and record.server_invite_url:
            act_buttons.append(
                Button(
                    label="Приглашение",
                    style=disnake.ButtonStyle.link,
                    url=record.server_invite_url,
                )
            )

        children.append(ActionRow(*act_buttons))
        return Container(*children)

    @staticmethod
    def build_ended_container(
        record: GiveawayRecord,
        participant_count: int,
        winners: list[dict[str, Any]] | None,
    ) -> disnake.ui.Container:
        from disnake.ui import Container, MediaGallery, TextDisplay, Separator, ActionRow, Button
        from disnake.ui.media_gallery import MediaGalleryItem

        children = []

        if record.image_path:
            children.append(MediaGallery(MediaGalleryItem("attachment://giveaway.png")))
        elif record.image_url:
            try:
                children.append(MediaGallery(MediaGalleryItem(record.image_url)))
            except Exception:
                pass

        children.append(TextDisplay(format_title_header("# РОЗЫГРЫШ ЗАВЕРШЕН", record.title)))
        children.append(Separator())

        winner_lines: list[str] = []
        if winners:
            for w in winners:
                uid = w.get("user_id")
                pts = float(w.get("points", 0.0) or 0.0)
                chance = float(w.get("chance_percent", 0.0) or 0.0)
                desc = w.get("prize_description", "")
                prize_str = f" — Приз: {desc}" if desc else ""
                if record.enabled_points:
                    winner_lines.append(f"<@{uid}> — {pts:.1f} баллов ({chance:.1f}% шанс){prize_str}")
                else:
                    winner_lines.append(f"<@{uid}>{prize_str}")
            winners_text = "### Победители:\n" + "\n".join(winner_lines)
        else:
            winners_text = "### Победители:\n*Победители не выбраны (участников не было)*"

        children.append(TextDisplay(winners_text))
        children.append(Separator())

        if record.description:
            children.append(TextDisplay(record.description))
            children.append(Separator())

        stats_text = (
            f"-# Всего участников: {participant_count} • Завершился: {to_discord_timestamp(record.end_time, 'f')}"
        )
        children.append(TextDisplay(stats_text))
        children.append(Separator())

        ended_buttons = [
            Button(
                label="Участники",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"giveaway_participants:{record.id}",
            )
        ]
        if record.require_server and record.server_invite_url:
            ended_buttons.append(
                Button(
                    label="Приглашение",
                    style=disnake.ButtonStyle.link,
                    url=record.server_invite_url,
                )
            )

        children.append(ActionRow(*ended_buttons))
        return Container(*children)

    @staticmethod
    def build_preview_container(
        draft: GiveawayDraft,
        include_controls: bool = False,
        author_id: int | None = None,
    ) -> disnake.ui.Container:
        from disnake.ui import Container, MediaGallery, TextDisplay, Separator, ActionRow, Button
        from disnake.ui.media_gallery import MediaGalleryItem

        children = []

        if draft.image_path:
            children.append(MediaGallery(MediaGalleryItem("attachment://preview.png")))
        elif draft.image_url:
            try:
                children.append(MediaGallery(MediaGalleryItem(draft.image_url)))
            except Exception:
                pass

        children.append(TextDisplay(format_title_header("# Конструктор розыгрыша", draft.title)))
        children.append(Separator())

        if draft.description:
            children.append(TextDisplay(f"### Описание:\n{draft.description}"))
            children.append(Separator())

        info_lines = [
            f"**Количество победителей:** `{draft.winners_count}`",
        ]
        if draft.prizes:
            info_lines.append(f"**Призы:**\n{format_prizes_display(draft.prizes)}")
        else:
            info_lines.append("**Призы:** *Не указаны (победители без фиксированных призов)*")

        if draft.duration_str:
            info_lines.append(f"**Длительность:** `{draft.duration_str}`")
        else:
            info_lines.append("**Длительность:** *Не указана (нажмите 'Время')*")

        req_parts: list[str] = []
        if draft.require_stage:
            req_parts.append("Трибуна: Обязательно")
        elif draft.require_voice:
            req_parts.append("Голосовой канал: Обязательно")
        if draft.enabled_points:
            req_parts.append("Баллы за голосовой канал: Включены (0.1/мин)")
        if draft.require_server:
            req_parts.append("Сервер-партнер: Обязательно")

        req_text = "\n".join(f"-# • {p}" for p in req_parts) if req_parts else "Без ограничений"
        info_lines.append(f"**Условия участия:**\n{req_text}")

        children.append(TextDisplay("\n".join(info_lines)))

        if include_controls:
            aid = author_id if author_id is not None else draft.creator_id
            children.append(Separator())
            children.append(
                ActionRow(
                    Button(
                        label="Тайтл",
                        style=disnake.ButtonStyle.secondary,
                        custom_id=f"builder_title:{draft.draft_id}:{aid}",
                    ),
                    Button(
                        label="Описание",
                        style=disnake.ButtonStyle.secondary,
                        custom_id=f"builder_desc:{draft.draft_id}:{aid}",
                    ),
                    Button(
                        label="Призы",
                        style=disnake.ButtonStyle.secondary,
                        custom_id=f"builder_prizes:{draft.draft_id}:{aid}",
                    ),
                )
            )
            children.append(
                ActionRow(
                    Button(
                        label="Время",
                        style=disnake.ButtonStyle.secondary,
                        custom_id=f"builder_duration:{draft.draft_id}:{aid}",
                    ),
                    Button(
                        label="Победители",
                        style=disnake.ButtonStyle.secondary,
                        custom_id=f"builder_winners:{draft.draft_id}:{aid}",
                    ),
                    Button(
                        label="Большая картинка",
                        style=disnake.ButtonStyle.secondary,
                        custom_id=f"builder_image:{draft.draft_id}:{aid}",
                    ),
                )
            )
            children.append(
                ActionRow(
                    Button(
                        label="Создать розыгрыш",
                        style=disnake.ButtonStyle.secondary,
                        custom_id=f"builder_create:{draft.draft_id}:{aid}",
                    ),
                    Button(
                        label="Назад",
                        style=disnake.ButtonStyle.secondary,
                        custom_id=f"builder_back:{draft.draft_id}:{aid}",
                    ),
                )
            )

        return Container(*children)

    @staticmethod
    def build_announcement_container(
        record: GiveawayRecord,
        winners: list[dict[str, Any]],
        message_jump_url: str | None = None,
        is_reroll: bool = False,
    ) -> disnake.ui.Container:
        from disnake.ui import Container, TextDisplay, Separator, ActionRow, Button

        children = []
        prefix = "## РЕРОЛЛ РОЗЫГРЫША" if is_reroll else "## РОЗЫГРЫШ ЗАВЕРШЕН"
        title_text = format_title_header(prefix, record.title)
        children.append(TextDisplay(title_text))
        children.append(Separator())

        mentions = ", ".join(f"<@{w['user_id']}>" for w in winners)
        content_parts = [f"**Победители:** {mentions}"]

        has_prizes = any(bool(w.get("prize_description")) for w in winners)
        if has_prizes:
            content_parts.append("\n**Призы:**")
            for w in winners:
                p_desc = f" — **{w['prize_description']}**" if w.get("prize_description") else ""
                content_parts.append(f"{w.get('place', 1)} место: <@{w['user_id']}>{p_desc}")
        elif winners:
            content_parts.append("\n**Список победителей:**")
            for w in winners:
                content_parts.append(f"{w.get('place', 1)} место: <@{w['user_id']}>")

        content_parts.append("\nПоздравляем победителей! Спасибо всем за участие.")

        children.append(TextDisplay("\n".join(content_parts)))

        buttons: list[Button] = []
        if not is_reroll and message_jump_url:
            buttons.append(
                Button(
                    label="Перейти к розыгрышу",
                    style=disnake.ButtonStyle.link,
                    url=message_jump_url,
                )
            )

        buttons.append(
            Button(
                label="Участники",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"giveaway_participants:{record.id}",
            )
        )

        if record.require_server and record.server_invite_url:
            buttons.append(
                Button(
                    label="Приглашение",
                    style=disnake.ButtonStyle.link,
                    url=record.server_invite_url,
                )
            )

        if buttons:
            children.append(Separator())
            children.append(ActionRow(*buttons))

        return Container(*children)

    @staticmethod
    def build_reroll_embed(
        record: GiveawayRecord,
        winners: list[dict[str, Any]],
    ) -> disnake.Embed:
        embed = disnake.Embed(
            title=format_title_header("РЕРОЛЛ РОЗЫГРЫША", record.title),
            description="Проведен повторный выбор победителей.",
            color=None,
        )

        winner_lines: list[str] = []
        for w in winners:
            place = w.get("place", 1)
            user_id = w.get("user_id")
            desc = w.get("prize_description", "")
            winner_lines.append(f"**{place} место**: <@{user_id}> — {desc}")

        embed.add_field(
            name="Новые победители",
            value="\n".join(winner_lines) if winner_lines else "Участников нет",
            inline=False,
        )
        embed.set_footer(text="Победители перевыбраны.")
        return embed

    @staticmethod
    def build_management_embed(
        record: GiveawayRecord,
        unique_count: int,
        participant_count: int,
    ) -> disnake.Embed:
        embed = disnake.Embed(
            title=format_title_header("Управление розыгрышем", record.title),
            color=None,
        )

        embed.add_field(name="Создатель розыгрыша", value=f"<@{record.creator_id}>", inline=True)
        embed.add_field(name="Статус", value="Активен" if record.status == "active" else "Завершен", inline=True)

        if record.status == "active":
            time_val = to_discord_timestamp(record.end_time, "R")
        else:
            time_val = "Завершен"

        embed.add_field(name="До завершения", value=time_val, inline=True)
        embed.add_field(name="Всего участников", value=f"`{participant_count}`", inline=True)
        embed.add_field(name="Уникальных участников", value=f"`{unique_count}`", inline=True)

        reqs: list[str] = []
        if record.require_stage:
            reqs.append("Трибуна: Да")
        if record.require_voice:
            reqs.append("Голосовой канал: Да")
        if record.enabled_points:
            reqs.append("Баллы: Включены")
        if record.require_server:
            reqs.append("Сервер-партнер: Да")
        embed.add_field(name="Параметры", value="\n".join(reqs) if reqs else "По умолчанию", inline=False)

        embed.set_footer(text="Меню управления розыгрышем")
        return embed

    @staticmethod
    def build_partner_server_required_container(
        server_title: str,
        server_invite_url: str | None,
        icon_url: str | None = None,
    ) -> disnake.ui.Container:
        from disnake.ui import Container, TextDisplay, Section, Thumbnail, Separator, ActionRow, Button

        children = []

        content = (
            f"# Требуется сервер-партнер\n"
            f"Для участия необходимо быть участником сервера **{server_title}**."
        )
        if server_invite_url:
            content += f"\nВступите на сервер: {server_invite_url}"

        if icon_url:
            children.append(
                Section(
                    TextDisplay(content),
                    accessory=Thumbnail(icon_url),
                )
            )
        else:
            children.append(TextDisplay(content))

        if server_invite_url:
            children.append(Separator())
            children.append(
                ActionRow(
                    Button(
                        label="Вступить на сервер",
                        style=disnake.ButtonStyle.link,
                        url=server_invite_url,
                    )
                )
            )

        return Container(*children)
