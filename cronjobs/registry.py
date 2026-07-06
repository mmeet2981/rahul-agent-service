"""
Cron Job Registry (Open/Closed Principle).
To add a new job:
  1. Create it under cronjobs/jobs/<your_job>/
  2. Import and append it here — no other file needs to change.
"""
from cronjobs.jobs.daily_purchase_suggestion.job import DailyPurchaseSuggestionJob
from cronjobs.jobs.monthly_best_seller_marketing.marketing_job import MonthlyBestSellerMarketingJob
from cronjobs.jobs.pending_sales_inquiries.pending_inquiries_job import PendingSalesInquiriesJob
from cronjobs.jobs.pending_payments.pending_payments_job import PendingPaymentsJob

# Registry: list of (cron_expression, job_instance) tuples.
# cron_expression format: "minute hour day month weekday"
CRON_REGISTRY = [
    # Runs every day at 08:30
    ("30 8 * * *", DailyPurchaseSuggestionJob()),
    # Runs at 09:00 on the 1st day of every month
    ("* * * * *", MonthlyBestSellerMarketingJob()),
    # Runs at 10:00 every day
    ("0 10 * * *", PendingSalesInquiriesJob()),
    # Runs at 11:00 every day
    ("0 11 * * *", PendingPaymentsJob()),
]


