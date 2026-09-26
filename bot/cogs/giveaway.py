import asyncio
import disnake
from disnake.ext import commands
from disnake.ui import Container, TextDisplay

from bot.giveaway.manager import GiveawayManager
from bot.giveaway.builder import GiveawayBuilder
from bot.giveaway.models import GiveawayDraft, PrizeItem
from bot.utils.time_parser import parse_duration
from bot.giveaway.views import (
    render_main_panel_container,
    render_templates_list_container,
    render_template_container,
    render_template_attributes_container,
    render_builder_container,
    render_builder_attributes_container,
    render_builder_channel_container,
    render_admin_people_paginator,
    render_admin_user_card,
    render_admin_management_container,
    render_admin_confirm_end_container,
    render_participants_paginator_container,
    render_leave_giveaway_container,
    render_admin_settings_container,
    render_admin_conditions_container,
    ActiveGiveawayTitleModal,
    ActiveGiveawayImageModal,
    TitleModal,
    DescriptionModal,
    PrizesModal,
    DurationModal,
    WinnersCountModal,
    ImageModal,
    TemplateRenameModal,
    TemplateTitleModal,
    TemplateDescModal,
    TemplatePrizesModal,
    TemplateDurationModal,
    TemplateImageModal,
    TemplateWinnersModal,
    TemplateNameModal,
    render_template_delete_confirm_container,
    RequireServerModal,
)


class GiveawayCog(commands.Cog, name="Розыгрыши"):
    def __init__(self, bot: commands.Bot, manager: GiveawayManager) -> None:
        self.bot = bot
        self.manager = manager

    @commands.slash_command(
        name="giveaway",
        description="Открыть панель управления розыгрышами",
        default_member_permissions=disnake.Permissions(manage_guild=True),
    )
    @commands.has_permissions(manage_guild=True)
    async def giveaway(self, inter: disnake.ApplicationCommandInteraction) -> None:
        await render_main_panel_container(inter, self.manager, inter.user.id)

    @commands.message_command(
        name="Управление",
        default_member_permissions=disnake.Permissions(manage_guild=True),
    )
    @commands.has_permissions(manage_guild=True)
    async def manage_context_menu(
        self,
        inter: disnake.MessageCommandInteraction,
        message: disnake.Message,
    ) -> None:
        record = await self.manager.get_giveaway_by_message_id(message.id)
        if not record:
            await inter.response.send_message(
                "Это сообщение не является розыгрышем.",
                ephemeral=True,
            )
            return

        has_manage = False
        if isinstance(inter.author, disnake.Member):
            has_manage = inter.author.guild_permissions.manage_guild or inter.author.guild_permissions.administrator

        if not has_manage:
            await inter.response.send_message(
                "У вас нет прав для управления этим розыгрышем. Требуется право 'Управлять сервером'.",
                ephemeral=True,
            )
            return

        await render_admin_management_container(inter, self.manager, record.id, inter.user.id)

    @commands.Cog.listener("on_raw_message_delete")
    async def on_raw_message_delete(self, payload: disnake.RawMessageDeleteEvent) -> None:
        await self.manager.handle_message_deleted(payload.message_id, payload.channel_id)

    @commands.Cog.listener("on_raw_bulk_message_delete")
    async def on_raw_bulk_message_delete(self, payload: disnake.RawBulkMessageDeleteEvent) -> None:
        for mid in payload.message_ids:
            await self.manager.handle_message_deleted(mid, payload.channel_id)

    @commands.Cog.listener("on_button_click")
    async def on_dynamic_button_click(self, inter: disnake.MessageInteraction) -> None:
        cid = inter.data.custom_id
        if not cid:
            return

        if cid.startswith("manage_user:"):
            parts = cid.split(":")
            if len(parts) >= 4:
                gw_id, target_uid, admin_id = int(parts[1]), int(parts[2]), int(parts[3])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await render_admin_user_card(inter, self.manager, gw_id, target_uid, admin_id)

        elif cid.startswith("manage_kick:"):
            parts = cid.split(":")
            if len(parts) >= 4:
                gw_id, target_uid, admin_id = int(parts[1]), int(parts[2]), int(parts[3])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await self.manager.kick_participant(gw_id, target_uid)
                container = disnake.ui.Container(
                    disnake.ui.TextDisplay(f"Участник <@{target_uid}> был выгнан из розыгрыша."),
                )
                await inter.response.edit_message(content=None, embed=None, components=[container])
                await asyncio.sleep(3)
                try:
                    await render_admin_people_paginator(inter, self.manager, gw_id, admin_id, 0)
                except Exception:
                    pass

        elif cid.startswith("manage_back_list:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await render_admin_people_paginator(inter, self.manager, gw_id, admin_id, 0)

        elif cid.startswith("manage_list_people:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await render_admin_people_paginator(inter, self.manager, gw_id, admin_id, 0)

        elif cid.startswith("manage_end_early:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await render_admin_confirm_end_container(inter, self.manager, gw_id, admin_id)

        elif cid.startswith("manage_end_confirm:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                gw = await self.manager.get_giveaway_by_id(gw_id)
                if not gw or gw.status != "active":
                    container = disnake.ui.Container(disnake.ui.TextDisplay("Розыгрыш уже завершен или не найден."))
                    await inter.response.edit_message(content=None, embed=None, components=[container])
                    return
                await self.manager.end_giveaway(gw_id)
                container = disnake.ui.Container(
                    disnake.ui.TextDisplay("# Розыгрыш завершен досрочно\nРозыгрыш был успешно остановлен, победители определены."),
                )
                await inter.response.edit_message(content=None, embed=None, components=[container])

        elif cid.startswith("manage_reroll:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                success, err, winners = await self.manager.reroll_giveaway(gw_id)
                if not success:
                    await inter.response.send_message(f"Ошибка реролла: {err}", ephemeral=True)
                    return
                winner_mentions = ", ".join(f"<@{w['user_id']}>" for w in winners)
                container = disnake.ui.Container(
                    disnake.ui.TextDisplay(f"# Реролл успешно выполнен\nНовые победители:\n{winner_mentions}"),
                    disnake.ui.ActionRow(
                        disnake.ui.Button(
                            label="Назад в меню",
                            style=disnake.ButtonStyle.secondary,
                            custom_id=f"manage_back_menu:{gw_id}:{admin_id}",
                        )
                    ),
                )
                await inter.response.edit_message(content=None, embed=None, components=[container])

        elif cid.startswith("manage_page_prev:"):
            parts = cid.split(":")
            if len(parts) >= 4:
                gw_id, page, admin_id = int(parts[1]), int(parts[2]), int(parts[3])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await render_admin_people_paginator(inter, self.manager, gw_id, admin_id, page - 1)

        elif cid.startswith("manage_page_next:"):
            parts = cid.split(":")
            if len(parts) >= 4:
                gw_id, page, admin_id = int(parts[1]), int(parts[2]), int(parts[3])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await render_admin_people_paginator(inter, self.manager, gw_id, admin_id, page + 1)

        elif cid.startswith("manage_back_menu:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await render_admin_management_container(inter, self.manager, gw_id, admin_id)

        elif cid.startswith("manage_settings:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await render_admin_settings_container(inter, self.manager, gw_id, admin_id)

        elif cid.startswith("manage_edit_title:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                rec = await self.manager.get_giveaway_by_id(gw_id)
                if not rec:
                    await inter.response.send_message("Розыгрыш не найден.", ephemeral=True)
                    return
                await inter.response.send_modal(ActiveGiveawayTitleModal(self.manager, gw_id, admin_id, rec.title))

        elif cid.startswith("manage_edit_image:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                rec = await self.manager.get_giveaway_by_id(gw_id)
                if not rec:
                    await inter.response.send_message("Розыгрыш не найден.", ephemeral=True)
                    return
                await inter.response.send_modal(ActiveGiveawayImageModal(self.manager, gw_id, admin_id, rec.image_url))

        elif cid.startswith("manage_edit_conditions:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await render_admin_conditions_container(inter, self.manager, gw_id, admin_id)

        elif cid.startswith("manage_toggle_stage:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                rec = await self.manager.get_giveaway_by_id(gw_id)
                if not rec:
                    return
                new_stage = not rec.require_stage
                new_voice = False if new_stage else rec.require_voice
                await self.manager.update_giveaway(gw_id, require_stage=new_stage, require_voice=new_voice)
                await render_admin_conditions_container(inter, self.manager, gw_id, admin_id)

        elif cid.startswith("manage_toggle_voice:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                rec = await self.manager.get_giveaway_by_id(gw_id)
                if not rec:
                    return
                new_voice = not rec.require_voice
                new_stage = False if new_voice else rec.require_stage
                await self.manager.update_giveaway(gw_id, require_voice=new_voice, require_stage=new_stage)
                await render_admin_conditions_container(inter, self.manager, gw_id, admin_id)

        elif cid.startswith("manage_toggle_points:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                rec = await self.manager.get_giveaway_by_id(gw_id)
                if not rec:
                    return
                new_points = not rec.enabled_points
                await self.manager.update_giveaway(gw_id, enabled_points=new_points)
                await render_admin_conditions_container(inter, self.manager, gw_id, admin_id)

        elif cid.startswith("manage_toggle_server:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                rec = await self.manager.get_giveaway_by_id(gw_id)
                if not rec:
                    return
                if rec.require_server:
                    await self.manager.update_giveaway(
                        gw_id,
                        require_server=False,
                        required_guild_id=None,
                        server_invite_url=None,
                    )
                    await render_admin_conditions_container(inter, self.manager, gw_id, admin_id)
                else:
                    await inter.response.send_modal(
                        RequireServerModal(
                            manager=self.manager,
                            context="giveaway",
                            target_id=str(gw_id),
                            author_id=admin_id,
                        )
                    )

        elif cid.startswith("tpl_create:"):
            parts = cid.split(":")
            admin_id = int(parts[1]) if len(parts) >= 2 else inter.user.id
            if inter.user.id != admin_id:
                await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                return

            async def on_tpl_create_submitted(modal_inter: disnake.ModalInteraction, name: str) -> None:
                clean_name = name.strip() if name else "Новый шаблон"
                tpl = await self.manager.create_template(
                    guild_id=modal_inter.guild_id,
                    creator_id=admin_id,
                    name=clean_name,
                )
                await render_template_container(modal_inter, self.manager, tpl.id, admin_id)

            await inter.response.send_modal(TemplateNameModal(on_tpl_create_submitted))

        elif cid.startswith("tpl_use:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                tpl = await self.manager.get_template(tpl_id)
                if not tpl:
                    await inter.response.send_message("Шаблон не найден.", ephemeral=True)
                    return

                draft = GiveawayDraft(
                    draft_id=disnake.utils.utcnow().strftime("%f")[:8],
                    guild_id=inter.guild_id,
                    creator_id=inter.user.id,
                )
                draft.title = tpl.title
                draft.description = tpl.description
                draft.prizes = [PrizeItem(p.place, p.description) for p in tpl.prizes]
                draft.duration_str = tpl.duration_str
                if tpl.duration_str:
                    try:
                        draft.duration_delta = parse_duration(tpl.duration_str)
                    except Exception:
                        pass
                draft.image_url = tpl.image_url
                draft.require_stage = tpl.require_stage
                draft.require_voice = tpl.require_voice
                draft.enabled_points = tpl.enabled_points
                draft.winners_count = tpl.winners_count
                draft.template_id = tpl.id

                self.manager.drafts[draft.draft_id] = draft
                await render_builder_container(inter, draft, self.manager, admin_id)

        elif cid.startswith("tpl_edit:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await render_template_container(inter, self.manager, tpl_id, admin_id)

        elif cid.startswith("tpl_back_main:"):
            parts = cid.split(":")
            admin_id = int(parts[1]) if len(parts) >= 2 else inter.user.id
            if inter.user.id != admin_id:
                await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                return
            await render_main_panel_container(inter, self.manager, admin_id)

        elif cid.startswith("panel_create:"):
            parts = cid.split(":")
            author_id = int(parts[1]) if len(parts) >= 2 else inter.user.id
            if inter.user.id != author_id:
                await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                return
            draft = GiveawayDraft(
                draft_id=disnake.utils.utcnow().strftime("%f")[:8],
                creator_id=author_id,
                guild_id=inter.guild_id,
            )
            self.manager.drafts[draft.draft_id] = draft
            await render_builder_container(inter, draft, self.manager, author_id)

        elif cid.startswith("panel_templates:"):
            parts = cid.split(":")
            author_id = int(parts[1]) if len(parts) >= 2 else inter.user.id
            if inter.user.id != author_id:
                await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                return
            await render_templates_list_container(inter, self.manager, author_id)

        elif cid.startswith("tpledit_winners:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                tpl = await self.manager.get_template(tpl_id)
                if not tpl:
                    await inter.response.send_message("Шаблон не найден.", ephemeral=True)
                    return
                await inter.response.send_modal(TemplateWinnersModal(self.manager, tpl_id, admin_id, tpl.winners_count))

        elif cid.startswith("tpledit_name:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                tpl = await self.manager.get_template(tpl_id)
                if not tpl:
                    await inter.response.send_message("Шаблон не найден.", ephemeral=True)
                    return
                await inter.response.send_modal(TemplateRenameModal(self.manager, tpl_id, admin_id, tpl.name))

        elif cid.startswith("tpledit_title:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                tpl = await self.manager.get_template(tpl_id)
                if not tpl:
                    await inter.response.send_message("Шаблон не найден.", ephemeral=True)
                    return
                await inter.response.send_modal(TemplateTitleModal(self.manager, tpl_id, admin_id, tpl.title))

        elif cid.startswith("tpledit_desc:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                tpl = await self.manager.get_template(tpl_id)
                if not tpl:
                    await inter.response.send_message("Шаблон не найден.", ephemeral=True)
                    return
                await inter.response.send_modal(TemplateDescModal(self.manager, tpl_id, admin_id, tpl.description))

        elif cid.startswith("tpledit_prizes:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                tpl = await self.manager.get_template(tpl_id)
                if not tpl:
                    await inter.response.send_message("Шаблон не найден.", ephemeral=True)
                    return
                await inter.response.send_modal(TemplatePrizesModal(self.manager, tpl_id, admin_id, tpl.prizes))

        elif cid.startswith("tpledit_time:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                tpl = await self.manager.get_template(tpl_id)
                if not tpl:
                    await inter.response.send_message("Шаблон не найден.", ephemeral=True)
                    return
                await inter.response.send_modal(TemplateDurationModal(self.manager, tpl_id, admin_id, tpl.duration_str))

        elif cid.startswith("tpledit_img:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                tpl = await self.manager.get_template(tpl_id)
                if not tpl:
                    await inter.response.send_message("Шаблон не найден.", ephemeral=True)
                    return
                await inter.response.send_modal(TemplateImageModal(self.manager, tpl_id, admin_id, tpl.image_url))

        elif cid.startswith("tpledit_attrs:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await render_template_attributes_container(inter, self.manager, tpl_id, admin_id)

        elif cid.startswith("tpltog_stage:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                tpl = await self.manager.get_template(tpl_id)
                if tpl:
                    if tpl.require_stage:
                        await self.manager.update_template(tpl_id, require_stage=False)
                    else:
                        await self.manager.update_template(tpl_id, require_stage=True, require_voice=False)
                    await render_template_attributes_container(inter, self.manager, tpl_id, admin_id)

        elif cid.startswith("tpltog_voice:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                tpl = await self.manager.get_template(tpl_id)
                if tpl:
                    if tpl.require_voice:
                        await self.manager.update_template(tpl_id, require_voice=False)
                    else:
                        await self.manager.update_template(tpl_id, require_voice=True, require_stage=False)
                    await render_template_attributes_container(inter, self.manager, tpl_id, admin_id)

        elif cid.startswith("tpltog_pts:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                tpl = await self.manager.get_template(tpl_id)
                if tpl:
                    await self.manager.update_template(tpl_id, enabled_points=not tpl.enabled_points)
                    await render_template_attributes_container(inter, self.manager, tpl_id, admin_id)

        elif cid.startswith("tpltog_server:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                tpl = await self.manager.get_template(tpl_id)
                if tpl:
                    if tpl.require_server:
                        await self.manager.update_template(
                            tpl_id,
                            require_server=False,
                            required_guild_id=None,
                            server_invite_url=None,
                        )
                        await render_template_attributes_container(inter, self.manager, tpl_id, admin_id)
                    else:
                        await inter.response.send_modal(
                            RequireServerModal(
                                manager=self.manager,
                                context="template",
                                target_id=str(tpl_id),
                                author_id=admin_id,
                            )
                        )

        elif cid.startswith("tpltog_done:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await render_template_container(inter, self.manager, tpl_id, admin_id)

        elif cid.startswith("tpledit_use:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                tpl = await self.manager.get_template(tpl_id)
                if not tpl:
                    await inter.response.send_message("Шаблон не найден.", ephemeral=True)
                    return

                draft = GiveawayDraft(
                    draft_id=disnake.utils.utcnow().strftime("%f")[:8],
                    guild_id=inter.guild_id,
                    creator_id=inter.user.id,
                )
                draft.title = tpl.title
                draft.description = tpl.description
                draft.prizes = [PrizeItem(p.place, p.description) for p in tpl.prizes]
                draft.duration_str = tpl.duration_str
                if tpl.duration_str:
                    try:
                        draft.duration_delta = parse_duration(tpl.duration_str)
                    except Exception:
                        pass
                draft.image_url = tpl.image_url
                draft.require_stage = tpl.require_stage
                draft.require_voice = tpl.require_voice
                draft.enabled_points = tpl.enabled_points
                draft.require_server = tpl.require_server
                draft.required_guild_id = tpl.required_guild_id
                draft.server_invite_url = tpl.server_invite_url
                draft.winners_count = tpl.winners_count
                draft.template_id = tpl.id

                self.manager.drafts[draft.draft_id] = draft
                await render_builder_container(inter, draft, self.manager, admin_id)

        elif cid.startswith("tpledit_del:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await render_template_delete_confirm_container(inter, self.manager, tpl_id, admin_id)

        elif cid.startswith("tpl_confirm_del:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await self.manager.delete_template(tpl_id)
                await render_templates_list_container(inter, self.manager, admin_id)

        elif cid.startswith("tpl_cancel_del:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                tpl_id, admin_id = int(parts[1]), int(parts[2])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await render_template_container(inter, self.manager, tpl_id, admin_id)

        elif cid.startswith("tpledit_back:"):
            parts = cid.split(":")
            if len(parts) >= 2:
                admin_id = int(parts[1])
                if inter.user.id != admin_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await render_templates_list_container(inter, self.manager, admin_id)

        elif cid.startswith("builder_title:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.get(draft_id)
                if not draft:
                    await inter.response.send_message("Черновик устарел или не найден.", ephemeral=True)
                    return
                await inter.response.send_modal(TitleModal(draft, author_id, self.manager))

        elif cid.startswith("builder_desc:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.get(draft_id)
                if not draft:
                    await inter.response.send_message("Черновик устарел или не найден.", ephemeral=True)
                    return
                await inter.response.send_modal(DescriptionModal(draft, author_id, self.manager))

        elif cid.startswith("builder_prizes:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.get(draft_id)
                if not draft:
                    await inter.response.send_message("Черновик устарел или не найден.", ephemeral=True)
                    return
                await inter.response.send_modal(PrizesModal(draft, author_id, self.manager))

        elif cid.startswith("builder_duration:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.get(draft_id)
                if not draft:
                    await inter.response.send_message("Черновик устарел или не найден.", ephemeral=True)
                    return
                await inter.response.send_modal(DurationModal(draft, author_id, self.manager))

        elif cid.startswith("builder_winners:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.get(draft_id)
                if not draft:
                    await inter.response.send_message("Черновик устарел или не найден.", ephemeral=True)
                    return
                await inter.response.send_modal(WinnersCountModal(draft, author_id, self.manager))

        elif cid.startswith("builder_image:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.get(draft_id)
                if not draft:
                    await inter.response.send_message("Черновик устарел или не найден.", ephemeral=True)
                    return
                await inter.response.send_modal(ImageModal(draft, author_id, self.manager))

        elif cid.startswith("builder_create:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.get(draft_id)
                if not draft:
                    await inter.response.send_message("Черновик устарел или не найден.", ephemeral=True)
                    return
                is_ready, err = draft.is_ready_to_publish()
                if not is_ready:
                    container = Container(TextDisplay(err))
                    await inter.response.send_message(components=[container], ephemeral=True)
                    return
                await render_builder_attributes_container(inter, draft, self.manager, author_id)

        elif cid.startswith("builder_attr_stage:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.get(draft_id)
                if not draft:
                    await inter.response.send_message("Черновик не найден.", ephemeral=True)
                    return
                draft.require_stage = not draft.require_stage
                if draft.require_stage:
                    draft.require_voice = False
                await render_builder_attributes_container(inter, draft, self.manager, author_id)

        elif cid.startswith("builder_attr_voice:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.get(draft_id)
                if not draft:
                    await inter.response.send_message("Черновик не найден.", ephemeral=True)
                    return
                draft.require_voice = not draft.require_voice
                if draft.require_voice:
                    draft.require_stage = False
                await render_builder_attributes_container(inter, draft, self.manager, author_id)

        elif cid.startswith("builder_attr_points:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.get(draft_id)
                if not draft:
                    await inter.response.send_message("Черновик не найден.", ephemeral=True)
                    return
                draft.enabled_points = not draft.enabled_points
                await render_builder_attributes_container(inter, draft, self.manager, author_id)

        elif cid.startswith("builder_attr_server:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.get(draft_id)
                if not draft:
                    await inter.response.send_message("Черновик не найден.", ephemeral=True)
                    return
                if draft.require_server:
                    draft.require_server = False
                    draft.required_guild_id = None
                    draft.server_invite_url = None
                    await render_builder_attributes_container(inter, draft, self.manager, author_id)
                else:
                    await inter.response.send_modal(
                        RequireServerModal(
                            manager=self.manager,
                            context="builder",
                            target_id=draft_id,
                            author_id=author_id,
                        )
                    )

        elif cid.startswith("builder_proceed_channel:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.get(draft_id)
                if not draft:
                    await inter.response.send_message("Черновик не найден.", ephemeral=True)
                    return
                await render_builder_channel_container(inter, draft, self.manager, author_id)

        elif cid.startswith("builder_back_builder:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.get(draft_id)
                if not draft:
                    await inter.response.send_message("Черновик не найден.", ephemeral=True)
                    return
                await render_builder_container(inter, draft, self.manager, author_id)

        elif cid.startswith("builder_back_attrs:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.get(draft_id)
                if not draft:
                    await inter.response.send_message("Черновик не найден.", ephemeral=True)
                    return
                await render_builder_attributes_container(inter, draft, self.manager, author_id)

        elif cid.startswith("builder_back:") or cid.startswith("builder_cancel:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.pop(draft_id, None)
                if draft:
                    from bot.utils.image_helper import delete_local_file
                    delete_local_file(draft.image_path)
                await render_main_panel_container(inter, self.manager, author_id)

        elif cid.startswith("giveaway_enter:"):
            parts = cid.split(":")
            if len(parts) >= 2:
                gw_id = int(parts[1])
                if await self.manager.is_participant(gw_id, inter.author.id):
                    await render_leave_giveaway_container(inter, self.manager, gw_id, inter.author.id)
                    return

                await inter.response.defer(ephemeral=True)
                added, new_count, err_msg = await self.manager.add_participant(
                    giveaway_id=gw_id,
                    member=inter.author,
                )
                if not added:
                    record = await self.manager.get_giveaway_by_id(gw_id)
                    if record and record.require_server and "Для участия необходимо быть участником сервера" in err_msg:
                        partner_guild = None
                        if record.required_guild_id:
                            partner_guild = self.bot.get_guild(record.required_guild_id)
                            if not partner_guild:
                                try:
                                    partner_guild = await self.bot.fetch_guild(record.required_guild_id)
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
                await self.manager.update_giveaway_message_count(gw_id)

        elif cid.startswith("giveaway_leave_confirm:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, uid = int(parts[1]), int(parts[2])
                if inter.author.id != uid:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                await self.manager.kick_participant(gw_id, uid)
                container = Container(TextDisplay("# Вы покинули розыгрыш."))
                await inter.response.edit_message(content=None, embed=None, components=[container])

        elif cid.startswith("giveaway_leave_cancel:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                gw_id, uid = int(parts[1]), int(parts[2])
                if inter.author.id != uid:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                container = Container(TextDisplay("# Действие отменено."))
                await inter.response.edit_message(content=None, embed=None, components=[container])

        elif cid.startswith("giveaway_participants:"):
            parts = cid.split(":")
            if len(parts) >= 2:
                gw_id = int(parts[1])
                await render_participants_paginator_container(
                    inter=inter,
                    manager=self.manager,
                    giveaway_id=gw_id,
                    page=0,
                    user_id=inter.user.id,
                )

        elif cid.startswith("user_page_prev:"):
            parts = cid.split(":")
            if len(parts) >= 4:
                gw_id, page, uid = int(parts[1]), int(parts[2]), int(parts[3])
                if inter.user.id != uid:
                    await inter.response.send_message("Доступ к пагинатору ограничен.", ephemeral=True)
                    return
                await render_participants_paginator_container(
                    inter=inter,
                    manager=self.manager,
                    giveaway_id=gw_id,
                    page=page - 1,
                    user_id=uid,
                    is_edit=True,
                )

        elif cid.startswith("user_page_next:"):
            parts = cid.split(":")
            if len(parts) >= 4:
                gw_id, page, uid = int(parts[1]), int(parts[2]), int(parts[3])
                if inter.user.id != uid:
                    await inter.response.send_message("Доступ к пагинатору ограничен.", ephemeral=True)
                    return
                await render_participants_paginator_container(
                    inter=inter,
                    manager=self.manager,
                    giveaway_id=gw_id,
                    page=page + 1,
                    user_id=uid,
                    is_edit=True,
                )

    @commands.Cog.listener("on_dropdown")
    async def on_dynamic_dropdown(self, inter: disnake.MessageInteraction) -> None:
        cid = inter.data.custom_id
        if not cid:
            return

        if cid.startswith("builder_channel:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                draft_id, author_id = parts[1], int(parts[2])
                if inter.user.id != author_id:
                    await inter.response.send_message("Доступ ограничен.", ephemeral=True)
                    return
                draft = self.manager.drafts.get(draft_id)
                if not draft:
                    await inter.response.send_message("Черновик устарел или не найден.", ephemeral=True)
                    return
                if not inter.values:
                    return
                channel_id = int(inter.values[0])
                channel = inter.guild.get_channel(channel_id)
                if channel is None:
                    try:
                        channel = await inter.guild.fetch_channel(channel_id)
                    except Exception:
                        pass
                if channel is None:
                    await inter.response.send_message("Не удалось найти выбранный канал.", ephemeral=True)
                    return

                success, err, msg = await self.manager.publish_giveaway(draft, channel)
                if not success:
                    await inter.response.send_message(f"Ошибка публикации: {err}", ephemeral=True)
                    return

                self.manager.drafts.pop(draft_id, None)
                container = disnake.ui.Container(
                    disnake.ui.TextDisplay(f"# Розыгрыш опубликован!\nРозыгрыш успешно создан и опубликован в канале <#{channel.id}>.")
                )
                await inter.response.edit_message(content=None, embed=None, components=[container])

    @commands.Cog.listener("on_voice_state_update")
    async def on_voice_update(
        self,
        member: disnake.Member,
        before: disnake.VoiceState,
        after: disnake.VoiceState,
    ) -> None:
        await self.manager.update_voice_state(member, before, after)

    @giveaway.error
    async def giveaway_error(
        self,
        inter: disnake.ApplicationCommandInteraction,
        error: Exception,
    ) -> None:
        if isinstance(error, commands.MissingPermissions):
            await inter.response.send_message(
                "У вас недостаточно прав для создания розыгрышей. Требуется право 'Управлять сервером'.",
                ephemeral=True,
            )
        else:
            await inter.response.send_message(
                f"Произошла ошибка при выполнении команды: {error}",
                ephemeral=True,
            )

    @manage_context_menu.error
    async def manage_context_menu_error(
        self,
        inter: disnake.MessageCommandInteraction,
        error: Exception,
    ) -> None:
        if isinstance(error, commands.MissingPermissions):
            await inter.response.send_message(
                "У вас нет прав для управления этим розыгрышем. Требуется право 'Управлять сервером'.",
                ephemeral=True,
            )
        else:
            await inter.response.send_message(
                f"Ошибка: {error}",
                ephemeral=True,
            )


def setup(bot: commands.Bot) -> None:
    manager: GiveawayManager = getattr(bot, "giveaway_manager")
    bot.add_cog(GiveawayCog(bot, manager))
