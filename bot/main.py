import asyncio
import logging
import sys
import disnake
from disnake.ext import commands

from bot.config import BOT_TOKEN, TEST_GUILD_ID
from bot.giveaway.manager import GiveawayManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-18s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("GiveawayBot")



sync_flags = commands.CommandSyncFlags.default()
sync_flags.sync_commands_debug = True

bot = commands.Bot(
    command_prefix=None,
    intents=disnake.Intents.all(),
    test_guilds=[TEST_GUILD_ID] if TEST_GUILD_ID else None,
    command_sync_flags=sync_flags,
    activity=disnake.Activity(
        type=disnake.ActivityType.watching,
        name="за честностью выборов",
    ),
)

manager = GiveawayManager(bot)
bot.giveaway_manager = manager


@bot.event
async def on_ready() -> None:
    logger.info("=" * 50)
    logger.info("Бот успешно авторизован в Discord!")
    logger.info("Имя бота: %s (ID: %s)", bot.user.name, bot.user.id)
    logger.info("Версия Disnake: %s", disnake.__version__)
    logger.info("Подключено серверов: %d", len(bot.guilds))
    if TEST_GUILD_ID:
        logger.info("Тестовая гильдия для быстрой синхронизации: %s", TEST_GUILD_ID)
    logger.info("=" * 50)

    await manager.initialize()


@bot.event
async def on_slash_command_error(
    inter: disnake.ApplicationCommandInteraction,
    error: Exception,
) -> None:
    logger.error("Ошибка при выполнении команды /%s: %s", inter.application_command.name, error)
    if not inter.response.is_done():
        await inter.response.send_message(
            f"Ошибка: {error}",
            ephemeral=True,
        )
    else:
        try:
            await inter.followup.send(
                f"Ошибка: {error}",
                ephemeral=True,
            )
        except Exception:
            pass


def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        logger.critical(
            "Токен бота не найден! Пожалуйста, укажите валидный BOT_TOKEN в файле .env"
        )
        sys.exit(1)

    try:
        bot.load_extension("bot.cogs.giveaway")
        logger.info("Ког bot.cogs.giveaway успешно загружен.")
    except Exception as exc:
        logger.critical("Не удалось загрузить ког розыгрышей: %s", exc, exc_info=True)
        sys.exit(1)

    logger.info("Запуск Discord-бота...")
    try:
        bot.run(BOT_TOKEN)
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем.")
    except Exception as exc:
        logger.critical("Критическая ошибка при работе бота: %s", exc, exc_info=True)


if __name__ == "__main__":
    main()
