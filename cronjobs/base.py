"""
Base class for all cron jobs (Open/Closed Principle — extend without modifying).
Every new cron job must implement this interface.
"""
from abc import ABC, abstractmethod


class BaseCronJob(ABC):
    """
    Abstract base class for all scheduled cron jobs.
    Ensures every job has a name and a run() entry point.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique human-readable name for the cron job."""
        ...

    @abstractmethod
    async def run(self) -> None:
        """
        Main execution logic of the cron job.
        Implement your business logic here.
        """
        ...
