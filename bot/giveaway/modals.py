from datetime import timedelta
from typing import Any
import disnake
from disnake.ui import Modal, TextInput, FileUpload, Label

from bot.giveaway.models import GiveawayDraft
from bot.giveaway.builder import GiveawayBuilder
from bot.giveaway.parser import parse_prizes_input
from bot.utils.time_parser import parse_duration
from bot.utils.image_helper import (
    is_valid_image_url,
    is_valid_attachment,
    save_attachment,
    delete_local_file,
)


async def _apply_and_edit_preview(
    inter: disnake.ModalInteraction,
    draft: GiveawayDraft,
    author_id: int | None = None,
    manager: Any | None = None,
) -> None:
    aid = author_id or draft.creator_id
    from bot.giveaway.views import render_builder_container
    await render_builder_container(inter, draft, manager, aid)


class TitleModal(Modal):
    def __init__(self, draft: GiveawayDraft, author_id: int | None = None, manager: Any | None = None) -> None:
        self.draft = draft
        self.author_id = author_id or draft.creator_id
        self.manager = manager
        components = [
            TextInput(
                style=disnake.TextInputStyle.short,
                label="Название розыгрыша",
                custom_id="title",
                placeholder="Например: Розыгрыш Discord Nitro",
                required=False,
                max_length=256,
                value=draft.title or "",
            )
        ]
        super().__init__(
            title="Настройка заголовка",
            custom_id=f"giveaway_modal_title_{draft.draft_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        new_title = inter.text_values.get("title", "").strip()
        self.draft.title = new_title if new_title else None
        await _apply_and_edit_preview(inter, self.draft, self.author_id, self.manager)


class DescriptionModal(Modal):
    def __init__(self, draft: GiveawayDraft, author_id: int | None = None, manager: Any | None = None) -> None:
        self.draft = draft
        self.author_id = author_id or draft.creator_id
        self.manager = manager
        components = [
            TextInput(
                style=disnake.TextInputStyle.paragraph,
                label="Описание розыгрыша",
                custom_id="description",
                placeholder="Введите описание, правила участия или подробности...",
                required=False,
                max_length=4000,
                value=draft.description or "",
            )
        ]
        super().__init__(
            title="Настройка описания",
            custom_id=f"giveaway_modal_desc_{draft.draft_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        new_desc = inter.text_values.get("description", "").strip()
        self.draft.description = new_desc if new_desc else None
        await _apply_and_edit_preview(inter, self.draft, self.author_id, self.manager)


class PrizesModal(Modal):
    def __init__(self, draft: GiveawayDraft, author_id: int | None = None, manager: Any | None = None) -> None:
        self.draft = draft
        self.author_id = author_id or draft.creator_id
        self.manager = manager

        initial_value = ""
        if draft.prizes:
            initial_value = "\n".join(
                f"{p.place} место — {p.description}" for p in draft.prizes
            )

        components = [
            TextInput(
                style=disnake.TextInputStyle.paragraph,
                label="Призы (каждый приз с новой строки)",
                custom_id="prizes",
                placeholder=(
                    "1 место — 1000 ₽\n"
                    "2 место — 500 ₽\n"
                    "3 место — Discord Nitro"
                ),
                required=False,
                max_length=1500,
                value=initial_value,
            )
        ]
        super().__init__(
            title="Настройка призов",
            custom_id=f"giveaway_modal_prizes_{draft.draft_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        raw_text = inter.text_values.get("prizes", "").strip()
        if raw_text:
            parsed = parse_prizes_input(raw_text)
            self.draft.prizes = parsed
        else:
            self.draft.prizes = []

        await _apply_and_edit_preview(inter, self.draft, self.author_id, self.manager)


class DurationModal(Modal):
    def __init__(self, draft: GiveawayDraft, author_id: int | None = None, manager: Any | None = None) -> None:
        self.draft = draft
        self.author_id = author_id or draft.creator_id
        self.manager = manager
        components = [
            TextInput(
                style=disnake.TextInputStyle.short,
                label="Длительность (10m, 20h, 30d или 1d 5h)",
                custom_id="duration",
                placeholder="Например: 10m, 2h, 30d или составное 1d 5h 30m",
                required=True,
                max_length=50,
                value=draft.duration_str or "",
            )
        ]
        super().__init__(
            title="Настройка времени",
            custom_id=f"giveaway_modal_duration_{draft.draft_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        raw_duration = inter.text_values.get("duration", "").strip()
        try:
            delta = parse_duration(raw_duration)
        except ValueError as exc:
            await inter.response.send_message(f"Ошибка: {exc}", ephemeral=True)
            return

        self.draft.duration_str = raw_duration
        self.draft.duration_delta = delta
        await _apply_and_edit_preview(inter, self.draft, self.author_id, self.manager)


class WinnersCountModal(Modal):
    def __init__(self, draft: GiveawayDraft, author_id: int | None = None, manager: Any | None = None) -> None:
        self.draft = draft
        self.author_id = author_id or draft.creator_id
        self.manager = manager
        components = [
            TextInput(
                style=disnake.TextInputStyle.short,
                label="Количество победителей",
                custom_id="winners_count",
                placeholder="Например: 1, 3, 5...",
                required=True,
                max_length=5,
                value=str(draft.winners_count) if draft.winners_count else "1",
            )
        ]
        super().__init__(
            title="Количество победителей",
            custom_id=f"giveaway_modal_winners_{draft.draft_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        raw_val = inter.text_values.get("winners_count", "").strip()
        try:
            val = int(raw_val)
            if val < 1:
                raise ValueError
        except ValueError:
            await inter.response.send_message(
                "Ошибка: укажите целое положительное число (минимум 1).",
                ephemeral=True,
            )
            return

        self.draft.winners_count = val
        await _apply_and_edit_preview(inter, self.draft, self.author_id, self.manager)


class ImageModal(Modal):
    def __init__(self, draft: GiveawayDraft, author_id: int | None = None, manager: Any | None = None) -> None:
        self.draft = draft
        self.author_id = author_id or draft.creator_id
        self.manager = manager
        components = [
            TextInput(
                style=disnake.TextInputStyle.short,
                label="URL изображения (необязательно)",
                custom_id="image_url",
                placeholder="https://example.com/banner.png",
                required=False,
                max_length=500,
                value=draft.image_url or "",
            ),
            Label(
                text="Загрузить файл изображения",
                description="Поддерживаются форматы PNG, JPG, JPEG, WEBP, GIF",
                component=FileUpload(
                    custom_id="giveaway_image",
                    min_values=0,
                    max_values=1,
                    required=False,
                ),
            ),
        ]
        super().__init__(
            title="Большая картинка",
            custom_id=f"giveaway_modal_image_{draft.draft_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        uploaded_attachments = inter.resolved_values.get("giveaway_image")

        if uploaded_attachments and len(uploaded_attachments) > 0:
            attachment = uploaded_attachments[0]
            is_valid, error_msg = is_valid_attachment(attachment)
            if not is_valid:
                await inter.response.send_message(
                    f"Ошибка вложения: {error_msg}",
                    ephemeral=True,
                )
                return

            delete_local_file(self.draft.image_path)
            saved_path = await save_attachment(attachment, prefix=self.draft.draft_id)
            self.draft.image_path = saved_path
            self.draft.image_url = None

            await _apply_and_edit_preview(inter, self.draft, self.author_id, self.manager)
            return

        url_input = inter.text_values.get("image_url", "").strip()
        if url_input:
            if not is_valid_image_url(url_input):
                await inter.response.send_message(
                    "Некорректный URL изображения!\n"
                    "Ссылка должна начинаться с http:// или https:// и указывать на файл "
                    ".png, .jpg, .jpeg, .webp или .gif.",
                    ephemeral=True,
                )
                return

            delete_local_file(self.draft.image_path)
            self.draft.image_path = None
            self.draft.image_url = url_input

            await _apply_and_edit_preview(inter, self.draft, self.author_id, self.manager)
            return

        delete_local_file(self.draft.image_path)
        self.draft.image_path = None
        self.draft.image_url = None
        await _apply_and_edit_preview(inter, self.draft, self.author_id, self.manager)


class TemplateNameModal(Modal):
    def __init__(self, callback_handler, current_name: str = "") -> None:
        self.callback_handler = callback_handler
        components = [
            TextInput(
                style=disnake.TextInputStyle.short,
                label="Название шаблона",
                custom_id="template_name",
                placeholder="Например: Розыгрыш с трибуной",
                required=True,
                max_length=64,
                value=current_name,
            )
        ]
        super().__init__(
            title="Название шаблона",
            custom_id="giveaway_modal_template_name",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        name = inter.text_values.get("template_name", "").strip()
        await self.callback_handler(inter, name)
