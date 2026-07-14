"""
Cron Scheduler (Single Responsibility Principle).
Responsible ONLY for scheduling and dispatching registered cron jobs.
Uses APScheduler with AsyncIOScheduler under the hood.
"""
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from cronjobs.registry import CRON_REGISTRY
from cronjobs.base import BaseCronJob

logger = logging.getLogger(__name__)


class CronScheduler:
    """
    Manages registration and lifecycle of all cron jobs.
    Add new jobs to registry.py — this class never changes.
    """

    def __init__(self):
        self._scheduler = AsyncIOScheduler()

    def _make_handler(self, job: BaseCronJob):
        """Wraps a job's run() in a safe async handler with logging."""
        async def handler():
            run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"[CRON] ▶  Starting  '{job.name}'  at {run_at}")
            try:
                await job.run()
                logger.info(f"[CRON] ✔  Finished  '{job.name}'  at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            except Exception as exc:
                logger.error(
                    f"[CRON] ✘  Job '{job.name}' failed: {exc}", exc_info=True
                )
        return handler

    def register_all(self) -> None:
        """Read CRON_REGISTRY and register every (expression, job) pair."""
        logger.info("[CRON] ══════════════ Registering cron jobs ══════════════")

        for cron_expr, job in CRON_REGISTRY:
            parts = cron_expr.split()
            if len(parts) != 5:
                logger.warning(
                    f"[CRON] ⚠  Invalid cron expression '{cron_expr}' "
                    f"for job '{job.name}'. Skipping."
                )
                continue

            minute, hour, day, month, day_of_week = parts
            trigger = CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
            )
            self._scheduler.add_job(
                self._make_handler(job),
                trigger=trigger,
                id=job.name,
                replace_existing=True,
            )

            # Calculate the next fire time immediately after registration
            scheduled_job = self._scheduler.get_job(job.name)
            next_run = (
                scheduled_job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
                if scheduled_job and scheduled_job.next_run_time
                else "unknown"
            )

            logger.info(
                f"[CRON] ✔  Registered  '{job.name}' | "
                f"cron='{cron_expr}' | "
                f"next_run='{next_run}'"
            )

        logger.info("[CRON] ═══════════════════════════════════════════════════")

    def start(self) -> None:
        """Start the scheduler (call once at app startup)."""
        self._scheduler.start()        # start FIRST so next_run_time is computed
        self.register_all()            # then register (so next_run is available)
        logger.info("[CRON] Scheduler is RUNNING. All jobs loaded. ✅")

    def stop(self) -> None:
        """Gracefully shut down the scheduler (call at app shutdown)."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("[CRON] Scheduler stopped. 🛑")
