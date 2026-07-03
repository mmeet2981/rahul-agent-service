from fastapi import FastAPI
from cronjobs.scheduler import CronScheduler

_scheduler = CronScheduler()


async def startup(app: FastAPI) -> None:
    """Called once at application boot. Starts the cron scheduler."""
    _scheduler.start()