import asyncio

from aiohttp import web

from teleport_bot.bot.app import create_bot, create_dispatcher
from teleport_bot.config.logging import configure_logging
from teleport_bot.config.settings import get_settings
from teleport_bot.db.session import create_engine, create_session_factory
from teleport_bot.web.health import create_health_app


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    bot = create_bot(settings)
    dp = create_dispatcher(settings, session_factory)

    runner = web.AppRunner(create_health_app(settings, session_factory))
    await runner.setup()
    site = web.TCPSite(runner, settings.health_host, settings.health_port)
    await site.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
