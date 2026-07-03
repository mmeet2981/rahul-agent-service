import asyncio
import logging
from cronjobs.jobs.monthly_best_seller_marketing.marketing_job import MonthlyBestSellerMarketingJob

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

async def test_run():
    print("\n=== STARTING STANDALONE TEST RUN ===")
    job = MonthlyBestSellerMarketingJob()
    
    # TODO: Replace with your actual email to test email delivery
    test_email = "gopikotadiya2002@gmail.com" 
    
    await job.run(test_email=test_email)
    print("=== STANDALONE TEST RUN FINISHED ===\n")

if __name__ == "__main__":
    asyncio.run(test_run())
