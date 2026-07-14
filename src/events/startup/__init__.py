from fastapi import FastAPI
from cronjobs.scheduler import CronScheduler

_scheduler = CronScheduler()


async def startup(app: FastAPI) -> None:
    """Called once at application boot. Starts the cron scheduler."""
    _scheduler.start()


async def shutdown(app: FastAPI) -> None:
    """Called once when the app shuts down. Stops the cron scheduler."""
    _scheduler.stop()