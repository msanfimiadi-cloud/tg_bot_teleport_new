from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from teleport_bot.services.subscriptions import SubscriptionLifecycleService


async def run_subscription_lifecycle(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await SubscriptionLifecycleService(session, bot).process_daily()


def create_scheduler(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_subscription_lifecycle,
        "cron",
        hour=9,
        minute=0,
        args=[session_factory, bot],
        id="subscription_lifecycle_daily",
        replace_existing=True,
    )
    return scheduler
