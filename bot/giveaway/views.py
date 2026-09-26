import asyncio
import inspect
import math
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING
import disnake
from disnake.ui import (
    View,
    Button,
    button,
    ChannelSelect,
    Container,
    Section,
    TextDisplay,
    Separator,
    MediaGallery,
    ActionRow,
    StringSelect,
    TextInput,
    Modal,
    FileUpload,
    Label,
)

from bot.giveaway.models import GiveawayDraft, GiveawayRecord, GiveawayTemplate, PrizeItem
from bot.giveaway.builder import GiveawayBuilder
from bot.giveaway.parser import parse_prizes_input, format_prizes_display
from bot.utils.time_parser import parse_duration, to_discord_timestamp
from bot.utils.image_helper import delete_local_file, is_valid_image_url, save_attachment, is_valid_attachment
from bot.giveaway.modals import (
    TitleModal,
    DescriptionModal,
    PrizesModal,
    DurationModal,
    WinnersCountModal,
    ImageModal,
    TemplateNameModal,
)

if TYPE_CHECKING:
    from bot.giveaway.manager import GiveawayManager


class MainGiveawayPanelView(View):
    def __init__(self, manager: "GiveawayManager", author_id: int) -> None:
        super().__init__(timeout=300.0)
        self.manager = manager
        self.author_id = author_id

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.user.id != self.author_id:
            await inter.response.send_message(
                "Только автор команды может управлять этой панелью.",
                ephemeral=True,
            )
            return False
        return True

    @button(label="Создать розыгрыш", style=disnake.ButtonStyle.primary, row=0)
    async def create_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        draft = GiveawayDraft(
            draft_id=disnake.utils.utcnow().strftime("%f")[:8],
            creator_id=self.author_id,
            guild_id=inter.guild_id,
        )
        self.manager.drafts[draft.draft_id] = draft
        await render_builder_container(inter, draft, self.manager, self.author_id)

    @button(label="Шаблоны", style=disnake.ButtonStyle.secondary, row=0)
    async def templates_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        await render_templates_list_container(inter, self.manager, self.author_id)


class TemplateSelectionView(View):
    def __init__(
        self,
        manager: "GiveawayManager",
        author_id: int,
        templates: list[GiveawayTemplate],
    ) -> None:
        super().__init__(timeout=300.0)
        self.manager = manager
        self.author_id = author_id
        self.templates = templates

        options = [
            disnake.SelectOption(
                label="Без шаблона (по умолчанию)",
                value="none",
                description="Создать обычный розыгрыш с нуля",
            )
        ]
        for t in templates[:24]:
            attrs = []
            if t.require_stage:
                attrs.append("Трибуна")
            elif t.require_voice:
                attrs.append("Войс")
            if t.enabled_points:
                attrs.append("Баллы")
            desc = ", ".join(attrs) if attrs else "Без ограничений"
            options.append(
                disnake.SelectOption(
                    label=t.name[:100],
                    value=str(t.id),
                    description=desc[:100],
                )
            )

        self.select_menu = StringSelect(
            custom_id="select_template_for_draft",
            placeholder="Выберите шаблон...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )
        self.select_menu.callback = self.on_template_selected
        self.add_item(self.select_menu)

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.user.id != self.author_id:
            await inter.response.send_message("Доступ ограничен.", ephemeral=True)
            return False
        return True

    async def on_template_selected(self, inter: disnake.MessageInteraction) -> None:
        val = self.select_menu.values[0]
        draft = GiveawayDraft(
            draft_id=disnake.utils.utcnow().strftime("%f")[:8],
            creator_id=self.author_id,
            guild_id=inter.guild_id,
        )

        if val != "none":
            t = await self.manager.get_template(int(val))
            if t:
                draft.template_id = t.id
                draft.title = t.title
                draft.description = t.description
                draft.prizes = list(t.prizes)
                draft.duration_str = t.duration_str
                if t.duration_str:
                    try:
                        draft.duration_delta = parse_duration(t.duration_str)
                    except Exception:
                        pass
                draft.image_url = t.image_url
                draft.require_stage = t.require_stage
                draft.require_voice = t.require_voice
                draft.enabled_points = t.enabled_points

        embed = GiveawayBuilder.build_preview_embed(draft)
        view = BuilderControlView(draft=draft, manager=self.manager)
        await inter.response.edit_message(embed=embed, view=view)
        view.message = await inter.original_response()

    @button(label="Назад", style=disnake.ButtonStyle.secondary, row=1)
    async def back_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        view = MainGiveawayPanelView(self.manager, self.author_id)
        embed = disnake.Embed(
            title="Панель розыгрышей",
            description="Выберите действие для продолжения:",
            color=None,
        )
        await inter.response.edit_message(embed=embed, view=view)


class BuilderControlView(View):
    def __init__(
        self,
        draft: GiveawayDraft,
        manager: "GiveawayManager",
        timeout: float = 900.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.draft = draft
        self.manager = manager
        self.message: disnake.Message | None = None

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.user.id != self.draft.creator_id:
            await inter.response.send_message(
                "Только автор черновика может изменять настройки.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        delete_local_file(self.draft.image_path)
        if self.message:
            try:
                for child in self.children:
                    if isinstance(child, Button):
                        child.disabled = True
                await self.message.edit(view=self)
            except Exception:
                pass

    @button(label="Тайтл", style=disnake.ButtonStyle.secondary, row=0)
    async def title_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        await inter.response.send_modal(TitleModal(self.draft))

    @button(label="Описание", style=disnake.ButtonStyle.secondary, row=0)
    async def desc_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        await inter.response.send_modal(DescriptionModal(self.draft))

    @button(label="Призы", style=disnake.ButtonStyle.secondary, row=0)
    async def prizes_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        await inter.response.send_modal(PrizesModal(self.draft))

    @button(label="Время", style=disnake.ButtonStyle.secondary, row=1)
    async def duration_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        await inter.response.send_modal(DurationModal(self.draft))

    @button(label="Победители", style=disnake.ButtonStyle.secondary, row=1)
    async def winners_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        await inter.response.send_modal(WinnersCountModal(self.draft))

    @button(label="Большая картинка", style=disnake.ButtonStyle.secondary, row=1)
    async def image_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        await inter.response.send_modal(ImageModal(self.draft))

    @button(label="Создать розыгрыш", style=disnake.ButtonStyle.secondary, row=2)
    async def create_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        is_ready, error_msg = self.draft.is_ready_to_publish()
        if not is_ready:
            container = Container(TextDisplay(error_msg))
            await inter.response.send_message(components=[container], ephemeral=True)
            return

        view = AttributesSelectionView(self.draft, self.manager)
        embed = disnake.Embed(
            title="Настройка условий розыгрыша",
            description="Выберите от 0 до 3 атрибутов в выпадающем списке, затем нажмите 'Продолжить'.",
            color=None,
        )
        await inter.response.edit_message(embed=embed, view=view, attachments=[])

    @button(label="Отмена", style=disnake.ButtonStyle.secondary, row=2)
    async def cancel_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        delete_local_file(self.draft.image_path)
        self.stop()
        await inter.response.edit_message(
            content="Создание розыгрыша отменено.",
            embed=None,
            view=None,
            attachments=[],
        )


class AttributesSelectionView(View):
    def __init__(self, draft: GiveawayDraft, manager: "GiveawayManager") -> None:
        super().__init__(timeout=300.0)
        self.draft = draft
        self.manager = manager

        current_attrs = set()
        if draft.require_stage:
            current_attrs.add("require_stage")
        if draft.require_voice:
            current_attrs.add("require_voice")
        if draft.enabled_points:
            current_attrs.add("enabled_points")
        self.selected_attrs: set[str] = current_attrs

        options = [
            disnake.SelectOption(
                label="RequireStage (Трибуна)",
                value="require_stage",
                description="Обязательно находиться на трибуне (Stage channel)",
                default="require_stage" in current_attrs,
            ),
            disnake.SelectOption(
                label="RequireVoice (Голосовой канал)",
                value="require_voice",
                description="Обязательно находиться в голосовом канале",
                default="require_voice" in current_attrs,
            ),
            disnake.SelectOption(
                label="EnabledPoints (Система баллов)",
                value="enabled_points",
                description="Начисление 0.1 балла за минуту в войсе/трибуне",
                default="enabled_points" in current_attrs,
            ),
        ]

        self.select_menu = StringSelect(
            custom_id="select_giveaway_attrs",
            placeholder="Выберите атрибуты (0-3)...",
            min_values=0,
            max_values=3,
            options=options,
            row=0,
        )
        self.select_menu.callback = self.on_attrs_changed
        self.add_item(self.select_menu)

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.user.id != self.draft.creator_id:
            await inter.response.send_message("Доступ ограничен.", ephemeral=True)
            return False
        return True

    async def on_attrs_changed(self, inter: disnake.MessageInteraction) -> None:
        self.selected_attrs = set(self.select_menu.values)
        for opt in self.select_menu.options:
            opt.default = opt.value in self.selected_attrs
        await inter.response.edit_message(view=self)

    @button(label="Продолжить", style=disnake.ButtonStyle.primary, row=1)
    async def continue_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        if "require_stage" in self.selected_attrs and "require_voice" in self.selected_attrs:
            view = ResolveConflictView(self)
            await inter.response.send_message(
                "Нельзя одновременно выбрать RequireStage и RequireVoice.\n"
                "Пожалуйста, выберите один вариант:",
                view=view,
                ephemeral=True,
            )
            return

        self.draft.require_stage = "require_stage" in self.selected_attrs
        self.draft.require_voice = "require_voice" in self.selected_attrs
        self.draft.enabled_points = "enabled_points" in self.selected_attrs

        view = ChannelSelectView(self.draft, self.manager, back_view=self)
        embed = disnake.Embed(
            title="Выбор канала для публикации",
            description="Выберите текстовый канал из списка ниже, в который будет отправлен розыгрыш.",
            color=None,
        )
        await inter.response.edit_message(embed=embed, view=view)

    @button(label="Назад", style=disnake.ButtonStyle.secondary, row=1)
    async def back_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        view = BuilderControlView(self.draft, self.manager)
        embed = GiveawayBuilder.build_preview_embed(self.draft)
        await inter.response.edit_message(embed=embed, view=view)
        view.message = await inter.original_response()


class ResolveConflictView(View):
    def __init__(self, parent_view: AttributesSelectionView) -> None:
        super().__init__(timeout=60.0)
        self.parent_view = parent_view

    @button(label="Оставить только Трибуну", style=disnake.ButtonStyle.primary)
    async def keep_stage(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        self.parent_view.selected_attrs.discard("require_voice")
        for opt in self.parent_view.select_menu.options:
            opt.default = opt.value in self.parent_view.selected_attrs
        await self.parent_view.continue_button.callback(inter)

    @button(label="Оставить только Войс", style=disnake.ButtonStyle.primary)
    async def keep_voice(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        self.parent_view.selected_attrs.discard("require_stage")
        for opt in self.parent_view.select_menu.options:
            opt.default = opt.value in self.parent_view.selected_attrs
        await self.parent_view.continue_button.callback(inter)


class ChannelSelectView(View):
    def __init__(
        self,
        draft: GiveawayDraft,
        manager: "GiveawayManager",
        back_view: View | None = None,
    ) -> None:
        super().__init__(timeout=300.0)
        self.draft = draft
        self.manager = manager
        self.back_view = back_view

        self.channel_select = ChannelSelect(
            channel_types=[disnake.ChannelType.text],
            placeholder="Выберите текстовый канал...",
            min_values=1,
            max_values=1,
            row=0,
        )
        self.channel_select.callback = self.on_channel_selected
        self.add_item(self.channel_select)

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.user.id != self.draft.creator_id:
            await inter.response.send_message("Доступ ограничен.", ephemeral=True)
            return False
        return True

    async def on_channel_selected(self, inter: disnake.MessageInteraction) -> None:
        selected = self.channel_select.values[0]
        if isinstance(selected, disnake.TextChannel):
            channel = selected
        else:
            channel_id = int(getattr(selected, "id", selected))
            channel = inter.guild.get_channel(channel_id)
            if not channel:
                try:
                    channel = await inter.guild.fetch_channel(channel_id)
                except Exception:
                    channel = None

        if not isinstance(channel, disnake.TextChannel):
            await inter.response.send_message("Выберите корректный текстовый канал.", ephemeral=True)
            return

        success, err, msg = await self.manager.publish_giveaway(self.draft, channel)
        if not success or not msg:
            await inter.response.send_message(f"Ошибка публикации: {err}", ephemeral=True)
            return

        self.stop()
        await inter.response.edit_message(
            content=(
                f"Розыгрыш успешно создан в канале {channel.mention}!\n"
                f"[Перейти к розыгрышу]({msg.jump_url})"
            ),
            embed=None,
            view=None,
        )

    @button(label="Назад", style=disnake.ButtonStyle.secondary, row=1)
    async def back_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        if self.back_view:
            embed = disnake.Embed(
                title="Настройка условий розыгрыша",
                description="Выберите от 0 до 3 атрибутов в выпадающем списке, затем нажмите 'Продолжить'.",
                color=None,
            )
            await inter.response.edit_message(embed=embed, view=self.back_view)
        else:
            view = BuilderControlView(self.draft, self.manager)
            embed = GiveawayBuilder.build_preview_embed(self.draft)
            await inter.response.edit_message(embed=embed, view=view)


async def _safe_get_giveaway(manager, giveaway_id: int):
    if not hasattr(manager, "get_giveaway_by_id"):
        return None
    res = manager.get_giveaway_by_id(giveaway_id)
    if inspect.isawaitable(res):
        return await res
    if isinstance(res, GiveawayRecord):
        return res
    return None


async def _send_or_edit_container(
    inter: disnake.Interaction,
    container: Container,
    ephemeral: bool = True,
    file: disnake.File | None = None,
) -> None:
    if inter.response.is_done():
        kwargs = {"content": None, "embed": None, "components": [container]}
        if file is not None:
            kwargs["file"] = file
        else:
            kwargs["attachments"] = []
        try:
            await inter.edit_original_response(**kwargs)
        except (disnake.NotFound, disnake.HTTPException):
            try:
                send_kwargs = {"components": [container], "ephemeral": ephemeral}
                if file is not None:
                    send_kwargs["file"] = file
                await inter.followup.send(**send_kwargs)
            except Exception:
                pass
        except Exception:
            pass
    elif isinstance(inter, (disnake.MessageCommandInteraction, disnake.ApplicationCommandInteraction)):
        kwargs = {"components": [container], "ephemeral": ephemeral}
        if file is not None:
            kwargs["file"] = file
        try:
            await inter.response.send_message(**kwargs)
        except (disnake.NotFound, disnake.HTTPException):
            pass
    else:
        kwargs = {"content": None, "embed": None, "components": [container]}
        if file is not None:
            kwargs["file"] = file
        else:
            kwargs["attachments"] = []
        try:
            await inter.response.edit_message(**kwargs)
        except (disnake.InteractionNotEditable, disnake.NotFound, disnake.HTTPException):
            try:
                send_kwargs = {"components": [container], "ephemeral": ephemeral}
                if file is not None:
                    send_kwargs["file"] = file
                if not inter.response.is_done():
                    await inter.response.send_message(**send_kwargs)
                else:
                    await inter.followup.send(**send_kwargs)
            except Exception:
                pass


def build_builder_attributes_container(draft: GiveawayDraft, author_id: int) -> Container:
    stage_style = disnake.ButtonStyle.success if draft.require_stage else disnake.ButtonStyle.secondary
    stage_text = "RequireStage: ВКЛ" if draft.require_stage else "RequireStage: ВЫКЛ"

    voice_style = disnake.ButtonStyle.success if draft.require_voice else disnake.ButtonStyle.secondary
    voice_text = "RequireVoice: ВКЛ" if draft.require_voice else "RequireVoice: ВЫКЛ"

    pts_style = disnake.ButtonStyle.success if draft.enabled_points else disnake.ButtonStyle.secondary
    pts_text = "EnabledPoints: ВКЛ" if draft.enabled_points else "EnabledPoints: ВЫКЛ"

    server_style = disnake.ButtonStyle.success if draft.require_server else disnake.ButtonStyle.secondary
    server_text = "RequireServer: ВКЛ" if draft.require_server else "RequireServer: ВЫКЛ"

    extra_info = []
    if draft.require_server and draft.server_invite_url:
        extra_info.append(f"-# Сервер-партнер: {draft.server_invite_url}")
    extra_text = ("\n" + "\n".join(extra_info)) if extra_info else ""

    return Container(
        TextDisplay(f"# Настройка условий розыгрыша: {draft.display_title}"),
        TextDisplay(f"-# RequireStage и RequireVoice не могут быть включены одновременно.{extra_text}"),
        Separator(),
        ActionRow(
            Button(label=stage_text, style=stage_style, custom_id=f"builder_attr_stage:{draft.draft_id}:{author_id}"),
            Button(label=voice_text, style=voice_style, custom_id=f"builder_attr_voice:{draft.draft_id}:{author_id}"),
            Button(label=pts_text, style=pts_style, custom_id=f"builder_attr_points:{draft.draft_id}:{author_id}"),
            Button(label=server_text, style=server_style, custom_id=f"builder_attr_server:{draft.draft_id}:{author_id}"),
        ),
        Separator(),
        ActionRow(
            Button(
                label="Продолжить (Выбор канала)",
                style=disnake.ButtonStyle.primary,
                custom_id=f"builder_proceed_channel:{draft.draft_id}:{author_id}",
            ),
            Button(
                label="Назад к настройкам",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"builder_back_builder:{draft.draft_id}:{author_id}",
            ),
        ),
    )


async def render_builder_attributes_container(
    inter: disnake.Interaction,
    draft: GiveawayDraft,
    manager: "GiveawayManager",
    author_id: int,
) -> None:
    container = build_builder_attributes_container(draft, author_id)
    await _send_or_edit_container(inter, container, ephemeral=True)


def build_builder_channel_container(draft: GiveawayDraft, author_id: int) -> Container:
    return Container(
        TextDisplay(f"# Выбор канала для публикации\nВыберите текстовый канал из списка ниже, в который будет отправлен розыгрыш **{draft.display_title}**:"),
        Separator(),
        ActionRow(
            ChannelSelect(
                custom_id=f"builder_channel:{draft.draft_id}:{author_id}",
                placeholder="Выберите текстовый канал...",
                channel_types=[disnake.ChannelType.text],
                min_values=1,
                max_values=1,
            )
        ),
        Separator(),
        ActionRow(
            Button(
                label="Назад к условиям",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"builder_back_attrs:{draft.draft_id}:{author_id}",
            )
        ),
    )


async def render_builder_channel_container(
    inter: disnake.Interaction,
    draft: GiveawayDraft,
    manager: "GiveawayManager",
    author_id: int,
) -> None:
    container = build_builder_channel_container(draft, author_id)
    await _send_or_edit_container(inter, container, ephemeral=True)


async def render_builder_container(
    inter: disnake.Interaction,
    draft: GiveawayDraft,
    manager: "GiveawayManager | None",
    author_id: int,
) -> None:
    container = GiveawayBuilder.build_preview_container(draft, include_controls=True, author_id=author_id)
    file = disnake.File(draft.image_path, filename="preview.png") if draft.image_path else None
    await _send_or_edit_container(inter, container, ephemeral=True, file=file)


async def render_main_panel_container(
    inter: disnake.Interaction,
    manager: "GiveawayManager",
    author_id: int | None = None,
) -> None:
    aid = author_id if author_id is not None else inter.user.id
    container = Container(
        TextDisplay("# Панель розыгрышей\nВыберите действие для продолжения:"),
        Separator(),
        ActionRow(
            Button(
                label="Создать розыгрыш",
                style=disnake.ButtonStyle.primary,
                custom_id=f"panel_create:{aid}",
            ),
            Button(
                label="Шаблоны",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"panel_templates:{aid}",
            ),
        ),
    )
    await _send_or_edit_container(inter, container, ephemeral=True)


async def render_templates_list_container(
    inter: disnake.Interaction,
    manager: "GiveawayManager",
    author_id: int,
) -> None:
    templates = await manager.get_templates(inter.guild_id)
    children = []
    children.append(TextDisplay("# Шаблоны розыгрышей"))
    children.append(Separator())

    if not templates:
        children.append(TextDisplay("Шаблоны пока не созданы.\nНажмите кнопку ниже, чтобы создать свой первый шаблон:"))
        children.append(Separator())
        children.append(
            ActionRow(
                Button(
                    label="Создать шаблон",
                    style=disnake.ButtonStyle.primary,
                    custom_id=f"tpl_create:{author_id}",
                ),
                Button(
                    label="Назад в меню",
                    style=disnake.ButtonStyle.secondary,
                    custom_id=f"tpl_back_main:{author_id}",
                ),
            )
        )
    else:
        for t in templates:
            attrs = []
            if t.require_stage:
                attrs.append("RequireStage: True")
            elif t.require_voice:
                attrs.append("RequireVoice: True")
            else:
                attrs.append("RequireVoice: False, RequireStage: False")

            if t.enabled_points:
                attrs.append("EnabledPoints: True")
            else:
                attrs.append("EnabledPoints: False")

            attr_str = " | ".join(attrs)
            ts = int(t.created_at.timestamp())
            children.append(
                TextDisplay(
                    f"### {t.name}\n"
                    f"-# Создатель: <@{t.creator_id}> • Создан: <t:{ts}:f>\n"
                    f"-# Атрибуты: {attr_str} • Победителей: `{t.winners_count}`"
                )
            )
            children.append(
                ActionRow(
                    Button(
                        label="Использовать",
                        style=disnake.ButtonStyle.primary,
                        custom_id=f"tpl_use:{t.id}:{author_id}",
                    ),
                    Button(
                        label="Редактировать",
                        style=disnake.ButtonStyle.secondary,
                        custom_id=f"tpl_edit:{t.id}:{author_id}",
                    ),
                )
            )
            children.append(Separator())

        children.append(
            ActionRow(
                Button(
                    label="Создать шаблон",
                    style=disnake.ButtonStyle.success,
                    custom_id=f"tpl_create:{author_id}",
                ),
                Button(
                    label="Назад в меню",
                    style=disnake.ButtonStyle.secondary,
                    custom_id=f"tpl_back_main:{author_id}",
                ),
            )
        )

    container = Container(*children)
    await _send_or_edit_container(inter, container, ephemeral=True)


class TemplateManagementView(View):
    def __init__(self, manager: "GiveawayManager", author_id: int) -> None:
        super().__init__(timeout=300.0)
        self.manager = manager
        self.author_id = author_id

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.user.id != self.author_id:
            await inter.response.send_message("Доступ ограничен.", ephemeral=True)
            return False
        return True

    async def build_overview_embed(self, guild_id: int) -> disnake.Embed:
        templates = await self.manager.get_templates(guild_id)
        embed = disnake.Embed(
            title="Шаблоны розыгрышей",
            color=None,
        )
        if not templates:
            embed.description = "Шаблоны не найдены. Нажмите 'Создать шаблон', чтобы добавить новый шаблон."
            return embed

        lines = []
        for idx, t in enumerate(templates, 1):
            attrs = []
            if t.require_stage:
                attrs.append("Трибуна")
            elif t.require_voice:
                attrs.append("Войс")
            if t.enabled_points:
                attrs.append("Баллы")
            attr_str = ", ".join(attrs) if attrs else "Без ограничений"
            lines.append(f"**{idx}. {t.name}**\n-# Автор: <@{t.creator_id}> | {attr_str}")

        embed.description = "\n\n".join(lines)
        return embed

    @button(label="Создать шаблон", style=disnake.ButtonStyle.primary, row=0)
    async def create_template_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        async def on_name_submitted(modal_inter: disnake.ModalInteraction, name: str) -> None:
            clean_name = name.strip() if name else "Новый шаблон"
            tpl = await self.manager.create_template(
                guild_id=modal_inter.guild_id,
                creator_id=self.author_id,
                name=clean_name,
            )
            await render_template_container(modal_inter, self.manager, tpl.id, self.author_id)

        await inter.response.send_modal(TemplateNameModal(on_name_submitted))

    @button(label="Редактировать / Удалить", style=disnake.ButtonStyle.secondary, row=0)
    async def edit_template_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        templates = await self.manager.get_templates(inter.guild_id)
        if not templates:
            await inter.response.send_message("Нет шаблонов для редактирования.", ephemeral=True)
            return

        view = SelectTemplateToEditView(self.manager, self.author_id, templates)
        embed = disnake.Embed(
            title="Выбор шаблона",
            description="Выберите шаблон для просмотра и редактирования в контейнере:",
            color=None,
        )
        await inter.response.edit_message(embed=embed, view=view)

    @button(label="Назад", style=disnake.ButtonStyle.secondary, row=1)
    async def back_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        view = MainGiveawayPanelView(self.manager, self.author_id)
        embed = disnake.Embed(
            title="Панель розыгрышей",
            description="Выберите действие для продолжения:",
            color=None,
        )
        await inter.response.edit_message(embed=embed, view=view)


class SelectTemplateToEditView(View):
    def __init__(self, manager: "GiveawayManager", author_id: int, templates: list[GiveawayTemplate]) -> None:
        super().__init__(timeout=300.0)
        self.manager = manager
        self.author_id = author_id

        options = [
            disnake.SelectOption(label=t.name[:100], value=str(t.id), description=f"Автор: <@{t.creator_id}>"[:100])
            for t in templates[:25]
        ]
        self.select_menu = StringSelect(placeholder="Выберите шаблон...", options=options, row=0)
        self.select_menu.callback = self.on_selected
        self.add_item(self.select_menu)

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        return inter.user.id == self.author_id

    async def on_selected(self, inter: disnake.MessageInteraction) -> None:
        tpl_id = int(self.select_menu.values[0])
        await render_template_container(inter, self.manager, tpl_id, self.author_id)

    @button(label="Назад", style=disnake.ButtonStyle.secondary, row=1)
    async def back_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        view = TemplateManagementView(self.manager, self.author_id)
        embed = await view.build_overview_embed(inter.guild_id)
        await inter.response.edit_message(embed=embed, view=view)


async def render_template_container(
    inter: disnake.MessageInteraction,
    manager: "GiveawayManager",
    template_id: int,
    author_id: int,
) -> None:
    tpl = await manager.get_template(template_id)
    if not tpl:
        await inter.response.send_message("Шаблон не найден.", ephemeral=True)
        return

    children = []
    file = None

    if tpl.image_path and os.path.exists(tpl.image_path):
        children.append(MediaGallery(disnake.MediaGalleryItem("attachment://template.png")))
        file = disnake.File(tpl.image_path, filename="template.png")
    elif tpl.image_url:
        try:
            children.append(MediaGallery(disnake.MediaGalleryItem(tpl.image_url)))
        except Exception:
            pass

    created_ts = int(tpl.created_at.timestamp())
    children.append(
        Section(
            TextDisplay(f"# Шаблон: {tpl.name}\n-# Создатель: <@{tpl.creator_id}> • Создан: <t:{created_ts}:f>"),
            accessory=Button(label="Изменить", style=disnake.ButtonStyle.secondary, custom_id=f"tpledit_name:{tpl.id}:{author_id}"),
        )
    )
    children.append(Separator())

    children.append(
        Section(
            TextDisplay(f"### Заголовок:\n{tpl.title or '*Не указан (по умолчанию)*'}"),
            accessory=Button(label="Изменить", style=disnake.ButtonStyle.secondary, custom_id=f"tpledit_title:{tpl.id}:{author_id}"),
        )
    )
    children.append(Separator())

    desc_short = (tpl.description[:100] + "...") if tpl.description and len(tpl.description) > 100 else (tpl.description or "*Не указано*")
    children.append(
        Section(
            TextDisplay(f"### Описание:\n{desc_short}"),
            accessory=Button(label="Изменить", style=disnake.ButtonStyle.secondary, custom_id=f"tpledit_desc:{tpl.id}:{author_id}"),
        )
    )
    children.append(Separator())

    children.append(
        Section(
            TextDisplay(f"### Призы:\n{format_prizes_display(tpl.prizes)}"),
            accessory=Button(label="Изменить", style=disnake.ButtonStyle.secondary, custom_id=f"tpledit_prizes:{tpl.id}:{author_id}"),
        )
    )
    children.append(Separator())

    children.append(
        Section(
            TextDisplay(f"### Длительность:\n{tpl.duration_str or '*Не указана*'}"),
            accessory=Button(label="Изменить", style=disnake.ButtonStyle.secondary, custom_id=f"tpledit_time:{tpl.id}:{author_id}"),
        )
    )
    children.append(Separator())

    children.append(
        Section(
            TextDisplay(f"### Картинка (URL):\n{tpl.image_url or '*Не указана*'}"),
            accessory=Button(label="Изменить", style=disnake.ButtonStyle.secondary, custom_id=f"tpledit_img:{tpl.id}:{author_id}"),
        )
    )
    children.append(Separator())

    req_list = []
    if tpl.require_stage:
        req_list.append("Трибуна")
    elif tpl.require_voice:
        req_list.append("Войс")
    if tpl.require_server:
        req_list.append("Сервер-партнер")
    req_str = ", ".join(req_list) if req_list else "Нет"
    pts_str = "Включены (+0.1/мин)" if tpl.enabled_points else "Выключены"
    children.append(
        Section(
            TextDisplay(f"### Атрибуты:\n-# Требование: {req_str}\n-# Баллы: {pts_str}"),
            accessory=Button(label="Настроить", style=disnake.ButtonStyle.secondary, custom_id=f"tpledit_attrs:{tpl.id}:{author_id}"),
        )
    )
    children.append(Separator())

    children.append(
        Section(
            TextDisplay(f"### Количество победителей:\n`{tpl.winners_count}`"),
            accessory=Button(label="Изменить", style=disnake.ButtonStyle.secondary, custom_id=f"tpledit_winners:{tpl.id}:{author_id}"),
        )
    )
    children.append(Separator())

    children.append(
        ActionRow(
            Button(label="Использовать шаблон", style=disnake.ButtonStyle.primary, custom_id=f"tpledit_use:{tpl.id}:{author_id}"),
            Button(label="Удалить шаблон", style=disnake.ButtonStyle.danger, custom_id=f"tpledit_del:{tpl.id}:{author_id}"),
            Button(label="Назад к списку", style=disnake.ButtonStyle.secondary, custom_id=f"tpledit_back:{author_id}"),
        )
    )

    container = Container(*children)
    await _send_or_edit_container(inter, container, ephemeral=True, file=file)


async def render_template_delete_confirm_container(
    inter: disnake.Interaction,
    manager: "GiveawayManager",
    template_id: int,
    author_id: int,
) -> None:
    tpl = await manager.get_template(template_id)
    if not tpl:
        await inter.response.send_message("Шаблон не найден.", ephemeral=True)
        return

    container = Container(
        TextDisplay(f"# Подтверждение удаления\nВы уверены, что хотите удалить шаблон **«{tpl.name}»**? Это действие необратимо."),
        Separator(),
        ActionRow(
            Button(
                label="Удалить",
                style=disnake.ButtonStyle.danger,
                custom_id=f"tpl_confirm_del:{tpl.id}:{author_id}",
            ),
            Button(
                label="Отмена",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"tpl_cancel_del:{tpl.id}:{author_id}",
            ),
        ),
    )
    await _send_or_edit_container(inter, container, ephemeral=True)


async def render_template_attributes_container(
    inter: disnake.MessageInteraction,
    manager: "GiveawayManager",
    template_id: int,
    author_id: int,
) -> None:
    tpl = await manager.get_template(template_id)
    if not tpl:
        await inter.response.send_message("Шаблон не найден.", ephemeral=True)
        return

    stage_style = disnake.ButtonStyle.success if tpl.require_stage else disnake.ButtonStyle.secondary
    stage_text = "RequireStage: ВКЛ" if tpl.require_stage else "RequireStage: ВЫКЛ"

    voice_style = disnake.ButtonStyle.success if tpl.require_voice else disnake.ButtonStyle.secondary
    voice_text = "RequireVoice: ВКЛ" if tpl.require_voice else "RequireVoice: ВЫКЛ"

    pts_style = disnake.ButtonStyle.success if tpl.enabled_points else disnake.ButtonStyle.secondary
    pts_text = "EnabledPoints: ВКЛ" if tpl.enabled_points else "EnabledPoints: ВЫКЛ"

    server_style = disnake.ButtonStyle.success if tpl.require_server else disnake.ButtonStyle.secondary
    server_text = "RequireServer: ВКЛ" if tpl.require_server else "RequireServer: ВЫКЛ"

    extra_info = []
    if tpl.require_server and tpl.server_invite_url:
        extra_info.append(f"-# Сервер-партнер: {tpl.server_invite_url}")
    extra_text = ("\n" + "\n".join(extra_info)) if extra_info else ""

    container = Container(
        TextDisplay(f"# Настройка атрибутов: {tpl.name}"),
        TextDisplay(f"-# RequireStage и RequireVoice не могут быть включены одновременно.{extra_text}"),
        Separator(),
        ActionRow(
            Button(label=stage_text, style=stage_style, custom_id=f"tpltog_stage:{tpl.id}:{author_id}"),
            Button(label=voice_text, style=voice_style, custom_id=f"tpltog_voice:{tpl.id}:{author_id}"),
            Button(label=pts_text, style=pts_style, custom_id=f"tpltog_pts:{tpl.id}:{author_id}"),
            Button(label=server_text, style=server_style, custom_id=f"tpltog_server:{tpl.id}:{author_id}"),
        ),
        Separator(),
        ActionRow(
            Button(label="Назад к шаблону", style=disnake.ButtonStyle.primary, custom_id=f"tpltog_done:{tpl.id}:{author_id}"),
        ),
    )
    await _send_or_edit_container(inter, container, ephemeral=True)


class TemplateRenameModal(Modal):
    def __init__(self, manager: "GiveawayManager", template_id: int, author_id: int, current_name: str) -> None:
        self.manager = manager
        self.template_id = template_id
        self.author_id = author_id
        components = [
            TextInput(
                style=disnake.TextInputStyle.short,
                label="Название шаблона",
                custom_id="name",
                placeholder="Например: Розыгрыш на трибуне",
                required=True,
                max_length=64,
                value=current_name,
            )
        ]
        super().__init__(
            title="Переименование шаблона",
            custom_id=f"tpl_modal_name_{template_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        new_name = inter.text_values.get("name", "").strip()
        if new_name:
            await self.manager.update_template(self.template_id, name=new_name)
        await render_template_container(inter, self.manager, self.template_id, self.author_id)


class TemplateTitleModal(Modal):
    def __init__(self, manager: "GiveawayManager", template_id: int, author_id: int, current_title: str | None = None) -> None:
        self.manager = manager
        self.template_id = template_id
        self.author_id = author_id
        components = [
            TextInput(
                style=disnake.TextInputStyle.short,
                label="Заголовок розыгрыша",
                custom_id="title",
                placeholder="Например: Еженедельный розыгрыш",
                required=False,
                max_length=256,
                value=current_title or "",
            )
        ]
        super().__init__(
            title="Заголовок шаблона",
            custom_id=f"tpl_modal_title_{template_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        new_title = inter.text_values.get("title", "").strip() or None
        await self.manager.update_template(self.template_id, title=new_title)
        await render_template_container(inter, self.manager, self.template_id, self.author_id)


class TemplateDescModal(Modal):
    def __init__(self, manager: "GiveawayManager", template_id: int, author_id: int, current_desc: str | None = None) -> None:
        self.manager = manager
        self.template_id = template_id
        self.author_id = author_id
        components = [
            TextInput(
                style=disnake.TextInputStyle.paragraph,
                label="Описание розыгрыша",
                custom_id="description",
                placeholder="Введите описание, правила или условия...",
                required=False,
                max_length=4000,
                value=current_desc or "",
            )
        ]
        super().__init__(
            title="Описание шаблона",
            custom_id=f"tpl_modal_desc_{template_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        new_desc = inter.text_values.get("description", "").strip() or None
        await self.manager.update_template(self.template_id, description=new_desc)
        await render_template_container(inter, self.manager, self.template_id, self.author_id)


class TemplatePrizesModal(Modal):
    def __init__(self, manager: "GiveawayManager", template_id: int, author_id: int, prizes: list[PrizeItem]) -> None:
        self.manager = manager
        self.template_id = template_id
        self.author_id = author_id
        initial_value = ""
        if prizes:
            initial_value = "\n".join(f"{p.place} место — {p.description}" for p in prizes)

        components = [
            TextInput(
                style=disnake.TextInputStyle.paragraph,
                label="Призы (каждый приз с новой строки)",
                custom_id="prizes",
                placeholder="1 место — 1000 ₽\n2 место — 500 ₽\n3 место — Discord Nitro",
                required=False,
                max_length=1500,
                value=initial_value,
            )
        ]
        super().__init__(
            title="Призы шаблона",
            custom_id=f"tpl_modal_prizes_{template_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        raw_text = inter.text_values.get("prizes", "").strip()
        parsed = parse_prizes_input(raw_text) if raw_text else []
        await self.manager.update_template(self.template_id, prizes=parsed)
        await render_template_container(inter, self.manager, self.template_id, self.author_id)


class TemplateDurationModal(Modal):
    def __init__(self, manager: "GiveawayManager", template_id: int, author_id: int, current_dur: str | None = None) -> None:
        self.manager = manager
        self.template_id = template_id
        self.author_id = author_id
        components = [
            TextInput(
                style=disnake.TextInputStyle.short,
                label="Длительность (10m, 20h, 30d или 1d 5h)",
                custom_id="duration",
                placeholder="Например: 10m, 2h, 30d или составное 1d 5h 30m",
                required=False,
                max_length=50,
                value=current_dur or "",
            )
        ]
        super().__init__(
            title="Время шаблона",
            custom_id=f"tpl_modal_dur_{template_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        raw = inter.text_values.get("duration", "").strip()
        if raw:
            try:
                parse_duration(raw)
            except ValueError as exc:
                await inter.response.send_message(f"Ошибка формата времени: {exc}", ephemeral=True)
                return
        await self.manager.update_template(self.template_id, duration_str=raw or None)
        await render_template_container(inter, self.manager, self.template_id, self.author_id)


class TemplateImageModal(Modal):
    def __init__(self, manager: "GiveawayManager", template_id: int, author_id: int, current_img: str | None = None) -> None:
        self.manager = manager
        self.template_id = template_id
        self.author_id = author_id
        components = [
            TextInput(
                style=disnake.TextInputStyle.short,
                label="URL изображения (необязательно)",
                custom_id="image_url",
                placeholder="https://example.com/banner.png",
                required=False,
                max_length=500,
                value=current_img or "",
            ),
            Label(
                text="Загрузить файл изображения",
                description="Поддерживаются форматы PNG, JPG, JPEG, WEBP, GIF",
                component=FileUpload(
                    custom_id="template_image",
                    min_values=0,
                    max_values=1,
                    required=False,
                ),
            ),
        ]
        super().__init__(
            title="Картинка шаблона",
            custom_id=f"tpl_modal_img_{template_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        uploaded_attachments = inter.resolved_values.get("template_image")
        if uploaded_attachments and len(uploaded_attachments) > 0:
            attachment = uploaded_attachments[0]
            is_valid, error_msg = is_valid_attachment(attachment)
            if not is_valid:
                await inter.response.send_message(
                    f"Ошибка вложения: {error_msg}",
                    ephemeral=True,
                )
                return

            saved_path = await save_attachment(attachment, prefix=f"tpl_{self.template_id}")
            await self.manager.update_template(
                self.template_id,
                image_url=attachment.url,
                image_path=saved_path,
            )
            await render_template_container(inter, self.manager, self.template_id, self.author_id)
            return

        url = inter.text_values.get("image_url", "").strip()
        if url:
            if not is_valid_image_url(url):
                await inter.response.send_message(
                    "Некорректный URL изображения!\n"
                    "Ссылка должна начинаться с http:// или https:// и указывать на файл .png, .jpg, .jpeg, .webp или .gif.",
                    ephemeral=True,
                )
                return
            await self.manager.update_template(self.template_id, image_url=url, image_path=None)
        else:
            await self.manager.update_template(self.template_id, clear_image=True)

        await render_template_container(inter, self.manager, self.template_id, self.author_id)


class TemplateWinnersModal(Modal):
    def __init__(self, manager: "GiveawayManager", template_id: int, author_id: int, current_winners: int = 1) -> None:
        self.manager = manager
        self.template_id = template_id
        self.author_id = author_id
        components = [
            TextInput(
                style=disnake.TextInputStyle.short,
                label="Количество победителей",
                custom_id="winners_count",
                placeholder="Например: 1, 3, 5...",
                required=True,
                max_length=5,
                value=str(current_winners),
            )
        ]
        super().__init__(
            title="Победители шаблона",
            custom_id=f"tpl_modal_winners_{template_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        raw = inter.text_values.get("winners_count", "").strip()
        try:
            val = int(raw)
            if val < 1:
                raise ValueError
        except ValueError:
            await inter.response.send_message("Укажите корректное положительное число (минимум 1).", ephemeral=True)
            return

        await self.manager.update_template(self.template_id, winners_count=val)
        await render_template_container(inter, self.manager, self.template_id, self.author_id)


class GiveawayParticipationView(View):
    def __init__(
        self,
        giveaway_id: int,
        manager: "GiveawayManager",
        participant_count: int = 0,
    ) -> None:
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        self.manager = manager

        self.enter_button = Button(
            label=f"Участвовать ({participant_count})",
            style=disnake.ButtonStyle.primary,
            custom_id=f"giveaway_enter:{giveaway_id}",
            row=0,
        )
        self.enter_button.callback = self.on_enter_click
        self.add_item(self.enter_button)

        self.participants_button = Button(
            label="Участники",
            style=disnake.ButtonStyle.secondary,
            custom_id=f"giveaway_participants:{giveaway_id}",
            row=0,
        )
        self.participants_button.callback = self.on_participants_click
        self.add_item(self.participants_button)

    async def on_enter_click(self, inter: disnake.MessageInteraction) -> None:
        await inter.response.defer(ephemeral=True)

        added, new_count, err_msg = await self.manager.add_participant(
            giveaway_id=self.giveaway_id,
            member=inter.author,
        )

        if not added:
            record = await self.manager.get_giveaway_by_id(self.giveaway_id)
            if record and record.require_server and "Для участия необходимо быть участником сервера" in err_msg:
                from bot.giveaway.builder import GiveawayBuilder
                partner_guild = None
                if record.required_guild_id:
                    partner_guild = self.manager.bot.get_guild(record.required_guild_id)
                    if not partner_guild:
                        try:
                            partner_guild = await self.manager.bot.fetch_guild(record.required_guild_id)
                        except Exception:
                            partner_guild = None
                server_title = partner_guild.name if partner_guild else "сервер-партнер"
                icon_url = partner_guild.icon.url if (partner_guild and partner_guild.icon) else None
                container = GiveawayBuilder.build_partner_server_required_container(
                    server_title=server_title,
                    server_invite_url=record.server_invite_url,
                    icon_url=icon_url,
                )
                await inter.followup.send(components=[container], ephemeral=True)
            else:
                container = Container(TextDisplay(err_msg))
                await inter.followup.send(components=[container], ephemeral=True)
            return

        container = Container(TextDisplay("Вы успешно участвуете в розыгрыше! Желаем удачи!"))
        await inter.followup.send(components=[container], ephemeral=True)

        self.enter_button.label = f"Участвовать ({new_count})"
        try:
            if inter.message and inter.message.embeds:
                embed = inter.message.embeds[0]
                for idx, field in enumerate(embed.fields):
                    if "Участников" in field.name:
                        embed.set_field_at(
                            idx,
                            name=field.name,
                            value=f"`{new_count}`",
                            inline=field.inline,
                        )
                        break
                await inter.message.edit(embed=embed, view=self)
        except Exception:
            pass

    async def on_participants_click(self, inter: disnake.MessageInteraction) -> None:
        await render_participants_paginator_container(
            inter=inter,
            manager=self.manager,
            giveaway_id=self.giveaway_id,
            page=0,
            user_id=inter.user.id,
        )


class EndedGiveawayView(View):
    def __init__(self, giveaway_id: int, participant_count: int = 0) -> None:
        super().__init__(timeout=None)
        btn = Button(
            label=f"Розыгрыш завершен ({participant_count})",
            style=disnake.ButtonStyle.secondary,
            disabled=True,
            custom_id=f"giveaway_ended_disabled_{giveaway_id}",
            row=0,
        )
        self.add_item(btn)


class ParticipantsPaginatorView(View):
    def __init__(self, manager: "GiveawayManager", giveaway_id: int, user_id: int) -> None:
        super().__init__(timeout=180.0)
        self.manager = manager
        self.giveaway_id = giveaway_id
        self.user_id = user_id
        self.page = 0
        self.page_size = 10

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.user.id != self.user_id:
            await inter.response.send_message("Доступ ограничен.", ephemeral=True)
            return False
        return True

    async def build_page_embed(self) -> disnake.Embed:
        participants = await self.manager.get_all_participants_sorted(self.giveaway_id)
        gw = await _safe_get_giveaway(self.manager, self.giveaway_id)
        winner_ids = set()
        winner_order = {}
        if gw and gw.winners:
            for idx, w in enumerate(gw.winners):
                uid = int(w["user_id"]) if isinstance(w, dict) and "user_id" in w else int(w)
                winner_ids.add(uid)
                winner_order[uid] = w.get("place", idx + 1) if isinstance(w, dict) else idx + 1

        participants.sort(
            key=lambda p: (
                0 if p.user_id in winner_ids else 1,
                winner_order.get(p.user_id, 0),
                -p.chance_percent,
                -p.points,
            )
        )

        total = len(participants)
        total_pages = max(1, math.ceil(total / self.page_size))
        self.page = max(0, min(self.page, total_pages - 1))

        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= total_pages - 1
        self.page_indicator.label = f"Страница {self.page + 1}/{total_pages}"

        embed = disnake.Embed(
            title="Список участников",
            color=None,
        )

        if not participants:
            embed.description = "В розыгрыше пока нет участников."
            return embed

        start_idx = self.page * self.page_size
        end_idx = start_idx + self.page_size
        page_items = participants[start_idx:end_idx]

        lines = []
        for p in page_items:
            prefix = "👑 " if p.user_id in winner_ids else ""
            if gw and gw.enabled_points:
                lines.append(f"{prefix}<@{p.user_id}> — {p.points:.1f} баллов ({p.chance_percent:.1f}% шанс выигрыша)")
            else:
                lines.append(f"{prefix}<@{p.user_id}>")

        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Всего участников: {total}")
        return embed

    @button(label="Назад", style=disnake.ButtonStyle.secondary, row=0)
    async def prev_btn(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        self.page -= 1
        await inter.response.edit_message(embed=await self.build_page_embed(), view=self)

    @button(label="Страница 1/1", style=disnake.ButtonStyle.secondary, disabled=True, row=0)
    async def page_indicator(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        pass

    @button(label="Вперед", style=disnake.ButtonStyle.secondary, row=0)
    async def next_btn(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        self.page += 1
        await inter.response.edit_message(embed=await self.build_page_embed(), view=self)


class GiveawayManagementView(View):
    def __init__(
        self,
        record: GiveawayRecord,
        manager: "GiveawayManager",
        admin_user_id: int,
    ) -> None:
        super().__init__(timeout=300.0)
        self.record = record
        self.manager = manager
        self.admin_user_id = admin_user_id
        self._update_buttons()

    def _update_buttons(self) -> None:
        is_active = self.record.status == "active"
        self.end_early_button.disabled = not is_active
        self.reroll_button.disabled = is_active

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.user.id != self.admin_user_id:
            await inter.response.send_message("Доступ к панели управления ограничен.", ephemeral=True)
            return False
        return True

    @button(label="Закончить досрочно", style=disnake.ButtonStyle.danger, row=0)
    async def end_early_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        view = ConfirmEarlyEndView(self.record, self.manager, self.admin_user_id)
        time_rem = to_discord_timestamp(self.record.end_time, "R")
        embed = disnake.Embed(
            description=f"Вы уверены что хотите досрочно закончить розыгрыш? До конца осталось: {time_rem}",
            color=None,
        )
        await inter.response.edit_message(embed=embed, view=view)

    @button(label="Список участников", style=disnake.ButtonStyle.secondary, row=0)
    async def list_people_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        await render_admin_people_paginator(
            inter=inter,
            manager=self.manager,
            giveaway_id=self.record.id,
            admin_user_id=self.admin_user_id,
            page=0,
        )

    @button(label="Реролл", style=disnake.ButtonStyle.secondary, row=0)
    async def reroll_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        success, err, winners = await self.manager.reroll_giveaway(self.record.id)
        if not success:
            await inter.response.send_message(f"Ошибка реролла: {err}", ephemeral=True)
            return

        winner_mentions = ", ".join(f"<@{w['user_id']}>" for w in winners)
        embed = disnake.Embed(
            title="Реролл успешно выполнен",
            description=f"Новые победители:\n{winner_mentions}",
            color=None,
        )
        await inter.response.edit_message(embed=embed, view=self)


class ConfirmEarlyEndView(View):
    def __init__(
        self,
        record: GiveawayRecord,
        manager: "GiveawayManager",
        admin_user_id: int,
    ) -> None:
        super().__init__(timeout=60.0)
        self.record = record
        self.manager = manager
        self.admin_user_id = admin_user_id

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.user.id != self.admin_user_id:
            await inter.response.send_message("Доступ ограничен.", ephemeral=True)
            return False
        return True

    @button(label="Подтвердить", style=disnake.ButtonStyle.danger)
    async def confirm_btn(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        gw = await self.manager.get_giveaway_by_id(self.record.id)
        if not gw or gw.status != "active":
            await inter.response.edit_message(
                content="Розыгрыш уже завершен или не найден.",
                embed=None,
                view=None,
            )
            return

        await self.manager.end_giveaway(self.record.id)
        embed = disnake.Embed(
            title="Розыгрыш завершен досрочно",
            description="Розыгрыш был успешно остановлен, победители определены.",
            color=None,
        )
        await inter.response.edit_message(embed=embed, view=None)

    @button(label="Отмена", style=disnake.ButtonStyle.secondary)
    async def cancel_btn(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        unique_count = await self.manager.count_unique_participants(self.record.id)
        total_count = await self.manager.get_participant_count(self.record.id)
        embed = GiveawayBuilder.build_management_embed(self.record, unique_count, total_count)
        view = GiveawayManagementView(self.record, self.manager, self.admin_user_id)
        await inter.response.edit_message(embed=embed, view=view)


async def render_admin_people_paginator(
    inter: disnake.MessageInteraction,
    manager: "GiveawayManager",
    giveaway_id: int,
    admin_user_id: int,
    page: int = 0,
) -> None:
    participants = await manager.get_all_participants_sorted(giveaway_id)
    page_size = 5
    total = len(participants)
    total_pages = max(1, math.ceil(total / page_size))
    page = max(0, min(page, total_pages - 1))

    gw_record = await _safe_get_giveaway(manager, giveaway_id)
    winner_ids = set()
    winner_order = {}
    if gw_record and gw_record.winners:
        for idx, w in enumerate(gw_record.winners):
            uid = int(w["user_id"]) if isinstance(w, dict) and "user_id" in w else int(w)
            winner_ids.add(uid)
            winner_order[uid] = w.get("place", idx + 1) if isinstance(w, dict) else idx + 1

    participants.sort(
        key=lambda p: (
            0 if p.user_id in winner_ids else 1,
            winner_order.get(p.user_id, 0),
            -p.chance_percent,
            -p.points,
        )
    )

    if not participants:
        container = Container(
            TextDisplay("# Список участников\nВ розыгрыше нет участников."),
            ActionRow(
                Button(
                    label="Назад в меню",
                    style=disnake.ButtonStyle.secondary,
                    custom_id=f"manage_back_menu:{giveaway_id}:{admin_user_id}",
                )
            ),
        )
        if inter.response.is_done():
            await inter.edit_original_response(content=None, embed=None, components=[container])
        else:
            await inter.response.edit_message(content=None, embed=None, components=[container])
        return

    start_idx = page * page_size
    end_idx = start_idx + page_size
    page_users = participants[start_idx:end_idx]

    sections = []
    for p in page_users:
        prefix = "👑 " if p.user_id in winner_ids else ""
        if gw_record and gw_record.enabled_points:
            text_line = f"{prefix}<@{p.user_id}> — {p.points:.1f} баллов ({p.chance_percent:.1f}%)"
        else:
            text_line = f"{prefix}<@{p.user_id}>"
        sec = Section(
            TextDisplay(text_line),
            accessory=Button(
                label="Управлять",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"manage_user:{giveaway_id}:{p.user_id}:{admin_user_id}",
            ),
        )
        sections.append(sec)

    nav_row = ActionRow(
        Button(
            label="Назад",
            style=disnake.ButtonStyle.secondary,
            custom_id=f"manage_page_prev:{giveaway_id}:{page}:{admin_user_id}",
            disabled=(page <= 0),
        ),
        Button(
            label=f"Страница {page + 1}/{total_pages}",
            style=disnake.ButtonStyle.secondary,
            disabled=True,
            custom_id="manage_page_indicator",
        ),
        Button(
            label="Вперед",
            style=disnake.ButtonStyle.secondary,
            custom_id=f"manage_page_next:{giveaway_id}:{page}:{admin_user_id}",
            disabled=(page >= total_pages - 1),
        ),
        Button(
            label="В меню",
            style=disnake.ButtonStyle.secondary,
            custom_id=f"manage_back_menu:{giveaway_id}:{admin_user_id}",
        ),
    )

    container = Container(*sections, nav_row)
    await _send_or_edit_container(inter, container, ephemeral=True)


async def render_admin_user_card(
    inter: disnake.MessageInteraction,
    manager: "GiveawayManager",
    giveaway_id: int,
    target_user_id: int,
    admin_user_id: int,
) -> None:
    p = await manager.get_participant_data(giveaway_id, target_user_id)
    if not p:
        container = Container(
            TextDisplay("# Управление участником\nУчастник не найден или уже покинул розыгрыш."),
            ActionRow(
                Button(
                    label="Назад к списку",
                    style=disnake.ButtonStyle.secondary,
                    custom_id=f"manage_back_list:{giveaway_id}:{admin_user_id}",
                )
            ),
        )
        await _send_or_edit_container(inter, container, ephemeral=True)
        return

    v_mins = int(p.voice_seconds // 60)
    v_secs = int(p.voice_seconds % 60)
    voice_str = f"{v_mins} мин. {v_secs} сек."
    try:
        joined_dt = datetime.fromisoformat(p.joined_at) if isinstance(p.joined_at, str) else p.joined_at
        joined_ts = int(joined_dt.timestamp())
        joined_str = f"<t:{joined_ts}:f>"
    except Exception:
        joined_str = str(p.joined_at)

    gw = await _safe_get_giveaway(manager, giveaway_id)
    winner_ids = set()
    if gw and gw.winners:
        for w in gw.winners:
            uid = int(w["user_id"]) if isinstance(w, dict) and "user_id" in w else int(w)
            winner_ids.add(uid)

    is_winner = p.user_id in winner_ids
    user_str = f"👑 <@{p.user_id}> (Победитель)" if is_winner else f"<@{p.user_id}>"
    info_lines = [
        f"**Участник:** {user_str}",
        f"**Присоединился:** {joined_str}",
    ]
    if gw and (gw.require_voice or gw.require_stage or gw.enabled_points):
        info_lines.append(f"**Время в Voice/Stage:** {voice_str}")
    if gw and gw.enabled_points:
        info_lines.append(f"**Накоплено баллов:** `{p.points:.1f}`")
        info_lines.append(f"**Шанс выигрыша:** `{p.chance_percent:.1f}%`")

    title_user_str = f"👑 <@{p.user_id}>" if is_winner else f"<@{p.user_id}>"
    container = Container(
        TextDisplay(f"# Управление участником: {title_user_str}"),
        Separator(),
        TextDisplay("\n".join(info_lines)),
        Separator(),
        ActionRow(
            Button(
                label="Выгнать из розыгрыша",
                style=disnake.ButtonStyle.danger,
                custom_id=f"manage_kick:{giveaway_id}:{p.user_id}:{admin_user_id}",
            ),
            Button(
                label="Назад к списку",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"manage_back_list:{giveaway_id}:{admin_user_id}",
            ),
        ),
    )
    await _send_or_edit_container(inter, container, ephemeral=True)


async def render_admin_management_container(
    inter: disnake.Interaction,
    manager: "GiveawayManager",
    giveaway_id: int,
    admin_user_id: int,
) -> None:
    record = await _safe_get_giveaway(manager, giveaway_id)
    if not record:
        container = Container(TextDisplay("# Ошибка\nРозыгрыш не найден."))
        await _send_or_edit_container(inter, container, ephemeral=True)
        return

    unique_count = await manager.count_unique_participants(record.id)
    total_count = await manager.get_participant_count(record.id)
    is_active = record.status == "active"
    status_str = "Активен" if is_active else "Завершен"
    end_ts = int(record.end_time.timestamp())
    time_info = f"<t:{end_ts}:R> (<t:{end_ts}:f>)"

    disp_title = record.title.strip() if (record.title and record.title.strip() and record.title.strip().lower() not in ("розыгрыш", "новый розыгрыш")) else ""
    title_text = f"# Управление розыгрышем: {disp_title}" if disp_title else "# Управление розыгрышем"

    container = Container(
        TextDisplay(title_text),
        Separator(),
        TextDisplay(
            f"**Статус:** {status_str}\n"
            f"**Участников:** `{unique_count}` уникальных (всего: `{total_count}`)\n"
            f"**Завершение:** {time_info}\n"
            f"**Победителей:** {record.winners_count}"
        ),
        Separator(),
        ActionRow(
            Button(
                label="Настройки",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"manage_settings:{record.id}:{admin_user_id}",
                disabled=not is_active,
            ),
            Button(
                label="Список участников",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"manage_list_people:{record.id}:{admin_user_id}",
            ),
        ),
        ActionRow(
            Button(
                label="Закончить досрочно",
                style=disnake.ButtonStyle.danger,
                custom_id=f"manage_end_early:{record.id}:{admin_user_id}",
                disabled=not is_active,
            ),
            Button(
                label="Реролл",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"manage_reroll:{record.id}:{admin_user_id}",
                disabled=is_active,
            ),
        ),
    )
    await _send_or_edit_container(inter, container, ephemeral=True)


async def render_admin_settings_container(
    inter: disnake.Interaction,
    manager: "GiveawayManager",
    giveaway_id: int,
    admin_user_id: int,
) -> None:
    record = await _safe_get_giveaway(manager, giveaway_id)
    if not record:
        container = Container(TextDisplay("# Ошибка\nРозыгрыш не найден."))
        await _send_or_edit_container(inter, container, ephemeral=True)
        return

    disp_title = record.title.strip() if (record.title and record.title.strip() and record.title.strip().lower() not in ("розыгрыш", "новый розыгрыш")) else ""
    title_text = f"# Настройки розыгрыша: {disp_title}" if disp_title else "# Настройки розыгрыша"

    children = [
        TextDisplay(title_text),
        Separator(),
        TextDisplay(
            f"**Заголовок:** {disp_title or 'Розыгрыш (по умолчанию)'}\n"
            f"**Картинка:** {'Установлена' if (record.image_url or record.image_path) else 'Отсутствует'}\n"
            f"**Требовать трибуну:** {'Да' if record.require_stage else 'Нет'}\n"
            f"**Требовать войс:** {'Да' if record.require_voice else 'Нет'}\n"
            f"**Баллы за войс:** {'Включены' if record.enabled_points else 'Выключены'}"
        ),
        Separator(),
        ActionRow(
            Button(
                label="Тайтл",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"manage_edit_title:{record.id}:{admin_user_id}",
            ),
            Button(
                label="Картинка",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"manage_edit_image:{record.id}:{admin_user_id}",
            ),
            Button(
                label="Условия",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"manage_edit_conditions:{record.id}:{admin_user_id}",
            ),
        ),
        ActionRow(
            Button(
                label="Назад в управление",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"manage_back_menu:{record.id}:{admin_user_id}",
            ),
        ),
    ]
    container = Container(*children)
    await _send_or_edit_container(inter, container, ephemeral=True)


class RequireServerModal(Modal):
    def __init__(
        self,
        manager: "GiveawayManager",
        context: str,
        target_id: str,
        author_id: int,
        current_value: str = "",
    ) -> None:
        self.manager = manager
        self.context = context
        self.target_id = target_id
        self.author_id = author_id

        components = [
            TextInput(
                style=disnake.TextInputStyle.short,
                label="ID сервера или ссылка-приглашение",
                custom_id="server_input",
                placeholder="Например: 1198697363028574368 или discord.gg/xyz",
                required=True,
                max_length=200,
                value=current_value or "",
            )
        ]
        super().__init__(
            title="Сервер-партнер",
            custom_id=f"req_server_modal_{context}_{target_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        from bot.giveaway.manager import resolve_partner_server

        server_input = inter.text_values.get("server_input", "").strip()
        guild, invite_url, err_msg = await resolve_partner_server(self.manager.bot, server_input)
        if err_msg or not guild:
            err_text = err_msg or "Не удалось разрешить сервер."
            container = Container(TextDisplay(f"# Ошибка\n{err_text}"))
            await inter.response.send_message(
                components=[container],
                ephemeral=True,
            )
            return

        if self.context == "builder":
            draft = self.manager.drafts.get(self.target_id)
            if draft:
                draft.require_server = True
                draft.required_guild_id = guild.id
                draft.server_invite_url = invite_url
                await render_builder_attributes_container(inter, draft, self.manager, self.author_id)
            else:
                container = Container(TextDisplay("# Ошибка\nЧерновик не найден."))
                await inter.response.send_message(components=[container], ephemeral=True)

        elif self.context == "template":
            try:
                tpl_id = int(self.target_id)
                await self.manager.update_template(
                    template_id=tpl_id,
                    require_server=True,
                    required_guild_id=guild.id,
                    server_invite_url=invite_url,
                )
                await render_template_attributes_container(inter, self.manager, tpl_id, self.author_id)
            except Exception as exc:
                container = Container(TextDisplay(f"# Ошибка\nОшибка сохранения шаблона: {exc}"))
                await inter.response.send_message(components=[container], ephemeral=True)

        elif self.context == "giveaway":
            try:
                gw_id = int(self.target_id)
                await self.manager.update_giveaway(
                    giveaway_id=gw_id,
                    require_server=True,
                    required_guild_id=guild.id,
                    server_invite_url=invite_url,
                )
                await render_admin_conditions_container(inter, self.manager, gw_id, self.author_id)
            except Exception as exc:
                container = Container(TextDisplay(f"# Ошибка\nОшибка обновления розыгрыша: {exc}"))
                await inter.response.send_message(components=[container], ephemeral=True)


async def render_admin_conditions_container(
    inter: disnake.Interaction,
    manager: "GiveawayManager",
    giveaway_id: int,
    admin_user_id: int,
) -> None:
    record = await _safe_get_giveaway(manager, giveaway_id)
    if not record:
        return

    stage_label = f"Трибуна: {'ВКЛ' if record.require_stage else 'ВЫКЛ'}"
    voice_label = f"Войс: {'ВКЛ' if record.require_voice else 'ВЫКЛ'}"
    points_label = f"Баллы: {'ВКЛ' if record.enabled_points else 'ВЫКЛ'}"
    server_label = f"Сервер: {'ВКЛ' if record.require_server else 'ВЫКЛ'}"

    disp_title = record.title.strip() if (record.title and record.title.strip() and record.title.strip().lower() not in ("розыгрыш", "новый розыгрыш")) else ""
    title_text = f"# Условия розыгрыша: {disp_title}\n" if disp_title else "# Условия розыгрыша\n"

    extra_info = []
    if record.require_server and record.server_invite_url:
        extra_info.append(f"-# Сервер-партнер: {record.server_invite_url}")
    extra_text = ("\n" + "\n".join(extra_info)) if extra_info else ""

    container = Container(
        TextDisplay(f"{title_text}Нажмите на кнопку для изменения условия:{extra_text}"),
        Separator(),
        ActionRow(
            Button(
                label=stage_label,
                style=disnake.ButtonStyle.primary if record.require_stage else disnake.ButtonStyle.secondary,
                custom_id=f"manage_toggle_stage:{record.id}:{admin_user_id}",
            ),
            Button(
                label=voice_label,
                style=disnake.ButtonStyle.primary if record.require_voice else disnake.ButtonStyle.secondary,
                custom_id=f"manage_toggle_voice:{record.id}:{admin_user_id}",
            ),
            Button(
                label=points_label,
                style=disnake.ButtonStyle.primary if record.enabled_points else disnake.ButtonStyle.secondary,
                custom_id=f"manage_toggle_points:{record.id}:{admin_user_id}",
            ),
            Button(
                label=server_label,
                style=disnake.ButtonStyle.primary if record.require_server else disnake.ButtonStyle.secondary,
                custom_id=f"manage_toggle_server:{record.id}:{admin_user_id}",
            ),
        ),
        ActionRow(
            Button(
                label="Назад в настройки",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"manage_settings:{record.id}:{admin_user_id}",
            ),
        ),
    )
    await _send_or_edit_container(inter, container, ephemeral=True)


class ActiveGiveawayTitleModal(Modal):
    def __init__(self, manager: "GiveawayManager", giveaway_id: int, admin_user_id: int, current_title: str) -> None:
        self.manager = manager
        self.giveaway_id = giveaway_id
        self.admin_user_id = admin_user_id
        is_default = (not current_title) or (current_title.strip().lower() in ("розыгрыш", "новый розыгрыш"))
        components = [
            TextInput(
                style=disnake.TextInputStyle.short,
                label="Новый заголовок",
                custom_id="giveaway_title",
                value="" if is_default else current_title,
                placeholder="Оставьте пустым для стандартного 'Розыгрыш'",
                required=False,
                max_length=256,
            )
        ]
        super().__init__(
            title="Заголовок розыгрыша",
            custom_id=f"manage_modal_title_{giveaway_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        new_title = inter.text_values.get("giveaway_title", "").strip() or "Розыгрыш"
        await self.manager.update_giveaway(self.giveaway_id, title=new_title)
        await render_admin_settings_container(inter, self.manager, self.giveaway_id, self.admin_user_id)


class ActiveGiveawayImageModal(Modal):
    def __init__(self, manager: "GiveawayManager", giveaway_id: int, admin_user_id: int, current_url: str | None = None) -> None:
        self.manager = manager
        self.giveaway_id = giveaway_id
        self.admin_user_id = admin_user_id
        components = [
            TextInput(
                style=disnake.TextInputStyle.short,
                label="URL изображения (необязательно)",
                custom_id="image_url",
                placeholder="https://example.com/banner.png",
                required=False,
                max_length=500,
                value=current_url or "",
            ),
            Label(
                text="Загрузить файл изображения",
                description="Поддерживаются форматы PNG, JPG, JPEG, WEBP, GIF",
                component=FileUpload(
                    custom_id="active_giveaway_image",
                    min_values=0,
                    max_values=1,
                    required=False,
                ),
            ),
        ]
        super().__init__(
            title="Картинка розыгрыша",
            custom_id=f"manage_modal_img_{giveaway_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        uploaded_attachments = inter.resolved_values.get("active_giveaway_image")
        if uploaded_attachments and len(uploaded_attachments) > 0:
            attachment = uploaded_attachments[0]
            is_valid, error_msg = is_valid_attachment(attachment)
            if not is_valid:
                container = Container(TextDisplay(f"# Ошибка\nОшибка вложения: {error_msg}"))
                await inter.response.send_message(components=[container], ephemeral=True)
                return

            saved_path = await save_attachment(attachment, prefix=f"active_{self.giveaway_id}")
            await self.manager.update_giveaway(
                self.giveaway_id,
                image_url=attachment.url,
                image_path=saved_path,
            )
            await render_admin_settings_container(inter, self.manager, self.giveaway_id, self.admin_user_id)
            return

        url = inter.text_values.get("image_url", "").strip()
        if url:
            if not is_valid_image_url(url):
                container = Container(
                    TextDisplay(
                        "# Ошибка\nНекорректный URL изображения!\n"
                        "Ссылка должна начинаться с http:// или https:// и указывать на файл .png, .jpg, .jpeg, .webp или .gif."
                    )
                )
                await inter.response.send_message(components=[container], ephemeral=True)
                return
            await self.manager.update_giveaway(self.giveaway_id, image_url=url, image_path=None)
        else:
            await self.manager.update_giveaway(self.giveaway_id, clear_image=True)

        await render_admin_settings_container(inter, self.manager, self.giveaway_id, self.admin_user_id)


async def render_admin_confirm_end_container(
    inter: disnake.Interaction,
    manager: "GiveawayManager",
    giveaway_id: int,
    admin_user_id: int,
) -> None:
    record = await _safe_get_giveaway(manager, giveaway_id)
    if not record:
        return
    end_ts = int(record.end_time.timestamp())
    container = Container(
        TextDisplay(f"# Досрочное завершение\nВы уверены, что хотите досрочно закончить розыгрыш?\nДо конца осталось: <t:{end_ts}:R>"),
        Separator(),
        ActionRow(
            Button(
                label="Подтвердить",
                style=disnake.ButtonStyle.danger,
                custom_id=f"manage_end_confirm:{record.id}:{admin_user_id}",
            ),
            Button(
                label="Отмена",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"manage_back_menu:{record.id}:{admin_user_id}",
            ),
        ),
    )
    await _send_or_edit_container(inter, container, ephemeral=True)


async def render_participants_paginator_container(
    inter: disnake.Interaction,
    manager: "GiveawayManager",
    giveaway_id: int,
    page: int = 0,
    user_id: int | None = None,
    is_edit: bool = False,
) -> None:
    uid = user_id or inter.user.id
    participants = await manager.get_all_participants_sorted(giveaway_id)
    gw_record = await _safe_get_giveaway(manager, giveaway_id)
    winner_ids = set()
    winner_order = {}
    if gw_record and gw_record.winners:
        for idx, w in enumerate(gw_record.winners):
            uid = int(w["user_id"]) if isinstance(w, dict) and "user_id" in w else int(w)
            winner_ids.add(uid)
            winner_order[uid] = w.get("place", idx + 1) if isinstance(w, dict) else idx + 1

    participants.sort(
        key=lambda p: (
            0 if p.user_id in winner_ids else 1,
            winner_order.get(p.user_id, 0),
            -p.chance_percent,
            -p.points,
        )
    )

    page_size = 10
    total = len(participants)
    total_pages = max(1, math.ceil(total / page_size))
    page = max(0, min(page, total_pages - 1))

    children = [TextDisplay("# Список участников"), Separator()]

    if not participants:
        children.append(TextDisplay("В розыгрыше пока нет участников."))
    else:
        start_idx = page * page_size
        end_idx = start_idx + page_size
        page_items = participants[start_idx:end_idx]

        lines = []
        for p in page_items:
            prefix = "👑 " if p.user_id in winner_ids else ""
            if gw_record and gw_record.enabled_points:
                lines.append(f"{prefix}<@{p.user_id}> — {p.points:.1f} баллов ({p.chance_percent:.1f}% шанс)")
            else:
                lines.append(f"{prefix}<@{p.user_id}>")
        children.append(TextDisplay("\n".join(lines)))
        children.append(Separator())
        children.append(TextDisplay(f"-# Всего участников: {total}"))

    children.append(
        ActionRow(
            Button(
                label="Назад",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"user_page_prev:{giveaway_id}:{page}:{uid}",
                disabled=(page <= 0),
            ),
            Button(
                label=f"Страница {page + 1}/{total_pages}",
                style=disnake.ButtonStyle.secondary,
                disabled=True,
                custom_id="user_page_indicator",
            ),
            Button(
                label="Вперед",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"user_page_next:{giveaway_id}:{page}:{uid}",
                disabled=(page >= total_pages - 1),
            ),
        )
    )

    container = Container(*children)
    if is_edit or inter.response.is_done():
        if inter.response.is_done():
            await inter.edit_original_response(content=None, embed=None, components=[container])
        else:
            await inter.response.edit_message(content=None, embed=None, components=[container])
    else:
        await inter.response.send_message(components=[container], ephemeral=True)


async def render_leave_giveaway_container(
    inter: disnake.Interaction,
    manager: "GiveawayManager",
    giveaway_id: int,
    user_id: int,
) -> None:
    record = await _safe_get_giveaway(manager, giveaway_id)
    lines = ["## Вы уверены, что хотите покинуть розыгрыш?"]
    if record and record.enabled_points:
        lines.append("При выходе вы потеряете все баллы.")

    container = Container(
        TextDisplay("\n".join(lines)),
        Separator(),
        ActionRow(
            Button(
                label="Уверен",
                style=disnake.ButtonStyle.danger,
                custom_id=f"giveaway_leave_confirm:{giveaway_id}:{user_id}",
            ),
            Button(
                label="Отмена",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"giveaway_leave_cancel:{giveaway_id}:{user_id}",
            ),
        ),
    )
    if inter.response.is_done():
        await inter.followup.send(components=[container], ephemeral=True)
    else:
        await inter.response.send_message(components=[container], ephemeral=True)


class AdminUserManagementView(View):
    def __init__(
        self,
        manager: "GiveawayManager",
        giveaway_id: int,
        target_user_id: int,
        admin_user_id: int,
    ) -> None:
        super().__init__(timeout=300.0)
        self.manager = manager
        self.giveaway_id = giveaway_id
        self.target_user_id = target_user_id
        self.admin_user_id = admin_user_id

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        return inter.user.id == self.admin_user_id

    async def build_user_embed(self) -> disnake.Embed:
        p = await self.manager.get_participant_data(self.giveaway_id, self.target_user_id)
        embed = disnake.Embed(title="Управление участником", color=None)
        if not p:
            embed.description = "Участник не найден или уже покинул розыгрыш."
            return embed

        v_mins = int(p.voice_seconds // 60)
        v_secs = int(p.voice_seconds % 60)
        voice_str = f"{v_mins} мин. {v_secs} сек."

        gw = await _safe_get_giveaway(self.manager, self.giveaway_id)
        embed.add_field(name="Участник", value=f"<@{p.user_id}>", inline=True)
        embed.add_field(name="Присоединился", value=to_discord_timestamp(p.joined_at, "f"), inline=True)
        if gw and (gw.require_voice or gw.require_stage or gw.enabled_points):
            embed.add_field(name="Время в Voice/Stage", value=voice_str, inline=False)
        if gw and gw.enabled_points:
            embed.add_field(name="Накоплено баллов", value=f"`{p.points:.1f}`", inline=True)
            embed.add_field(name="Шанс выигрыша", value=f"`{p.chance_percent:.1f}%`", inline=True)
        return embed

    @button(label="Выгнать из розыгрыша", style=disnake.ButtonStyle.danger, row=0)
    async def kick_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        await self.manager.kick_participant(self.giveaway_id, self.target_user_id)
        await render_admin_people_paginator(inter, self.manager, self.giveaway_id, self.admin_user_id, 0)

    @button(label="Назад", style=disnake.ButtonStyle.secondary, row=0)
    async def back_button(self, btn: Button, inter: disnake.MessageInteraction) -> None:
        await render_admin_people_paginator(inter, self.manager, self.giveaway_id, self.admin_user_id, 0)


async def render_admin_people_paginator_message(
    msg: disnake.Message,
    manager: "GiveawayManager",
    giveaway_id: int,
    admin_user_id: int,
    page: int = 0,
) -> None:
    participants = await manager.get_all_participants_sorted(giveaway_id)
    page_size = 5
    total = len(participants)
    total_pages = max(1, math.ceil(total / page_size))
    page = max(0, min(page, total_pages - 1))

    gw_record = await _safe_get_giveaway(manager, giveaway_id)
    winner_ids = set()
    winner_order = {}
    if gw_record and gw_record.winners:
        for idx, w in enumerate(gw_record.winners):
            uid = int(w["user_id"]) if isinstance(w, dict) and "user_id" in w else int(w)
            winner_ids.add(uid)
            winner_order[uid] = w.get("place", idx + 1) if isinstance(w, dict) else idx + 1

    participants.sort(
        key=lambda p: (
            0 if p.user_id in winner_ids else 1,
            winner_order.get(p.user_id, 0),
            -p.chance_percent,
            -p.points,
        )
    )

    if not participants:
        container = Container(
            TextDisplay("# Список участников\nВ розыгрыше нет участников."),
            ActionRow(
                Button(
                    label="Назад в меню",
                    style=disnake.ButtonStyle.secondary,
                    custom_id=f"manage_back_menu:{giveaway_id}:{admin_user_id}",
                )
            ),
        )
        await msg.edit(content=None, embed=None, components=[container])
        return

    start_idx = page * page_size
    end_idx = start_idx + page_size
    page_users = participants[start_idx:end_idx]

    sections = []
    for p in page_users:
        prefix = "👑 " if p.user_id in winner_ids else ""
        if gw_record and gw_record.enabled_points:
            text_line = f"{prefix}<@{p.user_id}> — {p.points:.1f} баллов ({p.chance_percent:.1f}%)"
        else:
            text_line = f"{prefix}<@{p.user_id}>"
        sec = Section(
            TextDisplay(text_line),
            accessory=Button(
                label="Управлять",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"manage_user:{giveaway_id}:{p.user_id}:{admin_user_id}",
            ),
        )
        sections.append(sec)

    nav_row = ActionRow(
        Button(
            label="Назад",
            style=disnake.ButtonStyle.secondary,
            custom_id=f"manage_page_prev:{giveaway_id}:{page}:{admin_user_id}",
            disabled=(page <= 0),
        ),
        Button(
            label=f"Страница {page + 1}/{total_pages}",
            style=disnake.ButtonStyle.secondary,
            disabled=True,
            custom_id="manage_page_indicator",
        ),
        Button(
            label="Вперед",
            style=disnake.ButtonStyle.secondary,
            custom_id=f"manage_page_next:{giveaway_id}:{page}:{admin_user_id}",
            disabled=(page >= total_pages - 1),
        ),
        Button(
            label="В меню",
            style=disnake.ButtonStyle.secondary,
            custom_id=f"manage_back_menu:{giveaway_id}:{admin_user_id}",
        ),
    )

    container = Container(*sections, nav_row)
    await msg.edit(content=None, embed=None, components=[container])
