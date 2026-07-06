"""
TEST JOB — Remove this file and its folder when done testing.

Runs every 1 minute and logs "Hii! from cron — <current time>".
Used only to verify the scheduler is wired up correctly.
"""
import logging
from datetime import datetime
from cronjobs.base import BaseCronJob

logger = logging.getLogger(__name__)


class TestHelloJob(BaseCronJob):
    """Simple test job. Delete cronjobs/jobs/test_hello/ when no longer needed."""

    @property
    def name(self) -> str:
        return "test_hello"

    async def run(self) -> str:
        message = f"Hii! from cron — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        logger.info(f"[TestHelloJob] {message}")
        print(f"[TestHelloJob] {message}")   # also visible in console / stdout
        return message
