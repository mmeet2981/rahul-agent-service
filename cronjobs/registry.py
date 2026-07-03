"""
Cron Job Registry (Open/Closed Principle).
To add a new job:
  1. Create it under cronjobs/jobs/<your_job>/
  2. Import and append it here — no other file needs to change.
"""
from cronjobs.jobs.daily_purchase_suggestion.job import DailyPurchaseSuggestionJob

# Registry: list of (cron_expression, job_instance) tuples.
# cron_expression format: "minute hour day month weekday"
CRON_REGISTRY = [
    # Runs every day at 08:30
    ("30 8 * * *", DailyPurchaseSuggestionJob()),
]
