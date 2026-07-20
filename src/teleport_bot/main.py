import asyncio

from aiohttp import web

from teleport_bot.bot.app import create_bot, create_dispatcher
from teleport_bot.config.logging import configure_logging
from teleport_bot.config.settings import get_settings
from teleport_bot.db.session import create_engine, create_session_factory
from teleport_bot.scheduler import create_scheduler
from teleport_bot.web.health import create_health_app


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    bot = create_bot(settings)
    dp = create_dispatcher(settings, session_factory)

    health_app = create_health_app(settings, session_factory, bot)
    runner = web.AppRunner(health_app)
    await runner.setup()
    site = web.TCPSite(runner, settings.health_host, settings.health_port)
    await site.start()
    scheduler = create_scheduler(session_factory, bot)
    scheduler.start()
    health_app["ready"] = True
    try:
        await dp.start_polling(bot)
    finally:
        health_app["ready"] = False
        scheduler.shutdown(wait=False)
        await runner.cleanup()
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
