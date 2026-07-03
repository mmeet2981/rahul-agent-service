"""
Monthly Best Seller Marketing Cron Job.
Implements BaseCronJob to automate emailing top selling products to customers.
"""
import logging
import os
import httpx
from cronjobs.base import BaseCronJob
from src.utils.database import get_db_cursor, get_db_config

logger = logging.getLogger(__name__)


class MonthlyBestSellerMarketingJob(BaseCronJob):
    """
    Runs automatically based on cron settings (e.g. monthly).
    Finds the top 5 best selling items and emails them to active customer contacts.
    """

    @property
    def name(self) -> str:
        return "monthly_best_seller_marketing"

    async def run(self, test_email: str = None) -> None:
        logger.info("[MonthlyBestSellerMarketingJob] ═══ Job started ═══")

        # Step 1: Fetch top 5 selling products of the latest active month
        top_products = []
        products_query = """
            SELECT 
                COALESCE(il.details->>'product_name', il.details->>'item_name') as product_name,
                SUM((il.details->>'quantity')::numeric) as total_quantity,
                SUM((il.details->>'amount')::numeric) as total_amount
            FROM sales_details sd
            CROSS JOIN UNNEST(sd.item_line_ids) as line_id
            JOIN item_lines il ON il.id = line_id
            WHERE sd.date >= DATE_TRUNC('month', (SELECT MAX(date) FROM sales_details))
              AND sd.date <= (SELECT MAX(date) FROM sales_details)
              AND sd.is_deleted = FALSE 
              AND il.is_deleted = FALSE
              AND COALESCE(il.details->>'product_name', il.details->>'item_name') IS NOT NULL
            GROUP BY product_name
            ORDER BY total_quantity DESC
            LIMIT 5;
        """

        try:
            with get_db_cursor(commit=False, db_config=get_db_config()) as cursor:
                cursor.execute(products_query)
                rows = cursor.fetchall()
                for row in rows:
                    top_products.append(row["product_name"])
        except Exception as exc:
            logger.error(f"[MonthlyBestSellerMarketingJob] Failed to fetch top products: {exc}", exc_info=True)
            return

        if not top_products:
            logger.warning("[MonthlyBestSellerMarketingJob] No best-selling products found. Exiting.")
            return

        logger.info(f"[MonthlyBestSellerMarketingJob] Top 5 products found: {top_products}")

        # Step 2: Fetch target customer email contacts
        customers = []
        if test_email:
            logger.info(f"[MonthlyBestSellerMarketingJob] Running in TEST mode. Only sending to: {test_email}")
            customers.append({
                "company_name": "Test Company",
                "email": test_email,
                "contact_name": "Test User"
            })
        else:
            customers_query = """
                SELECT 
                    em.id as customer_id,
                    em.name as company_name,
                    poc.email as email,
                    COALESCE(poc.name, em.name) as contact_name
                FROM entity_master em
                JOIN poc_details poc ON poc.entity_id = em.id
                WHERE em.is_deleted = FALSE
                  AND poc.email IS NOT NULL 
                  AND poc.email <> '';
            """

            try:
                with get_db_cursor(commit=False, db_config=get_db_config()) as cursor:
                    cursor.execute(customers_query)
                    rows = cursor.fetchall()
                    for row in rows:
                        customers.append({
                            "company_name": row["company_name"],
                            "email": row["email"],
                            "contact_name": row["contact_name"]
                        })
            except Exception as exc:
                logger.error(f"[MonthlyBestSellerMarketingJob] Failed to fetch customer emails: {exc}", exc_info=True)
                return

        if not customers:
            logger.warning("[MonthlyBestSellerMarketingJob] No target customers with emails found. Exiting.")
            return

        logger.info(f"[MonthlyBestSellerMarketingJob] Found {len(customers)} target customers.")

        # Step 3: Format and send emails via Node.js email service
        email_host = os.getenv("EMAIL_HOST", f"http://127.0.0.1:{os.getenv('EMAIL_SERVICE_PORT', '3005')}")
        node_api_url = f"{email_host}/send"

        # Build list of items in HTML and Text
        items_html = "<ol>" + "".join([f"<li><b>{prod}</b></li>" for prod in top_products]) + "</ol>"
        items_text = "\n".join([f"{i}. {prod}" for i, prod in enumerate(top_products, 1)])

        success_count = 0
        failure_count = 0

        async with httpx.AsyncClient() as client:
            for cust in customers:
                email_body = f"""Dear {cust['contact_name']},

We are pleased to share our top 5 best-selling products of this month with you! These items are highly popular among our clients right now:

{items_text}

If you would like to place an order or get a quote, please feel free to reply to this email or contact us.

Best regards,
Sales & Marketing Team
"""
                email_html = f"""<p>Dear {cust['contact_name']},</p>
<p>We are pleased to share our top 5 best-selling products of this month with you! These items are highly popular among our clients right now:</p>
{items_html}
<p>If you would like to place an order or get a quote, please feel free to reply to this email or contact us.</p>
<p>Best regards,<br>
<b>Sales & Marketing Team</b></p>
"""
                payload = {
                    "to": cust["email"],
                    "subject": "Our Top 5 Best-Selling Products of the Month!",
                    "text": email_body,
                    "html": email_html
                }

                try:
                    logger.info(f"[MonthlyBestSellerMarketingJob] Sending email to {cust['email']} ({cust['company_name']})")
                    resp = await client.post(node_api_url, json=payload)
                    resp.raise_for_status()
                    success_count += 1
                except Exception as exc:
                    logger.error(f"[MonthlyBestSellerMarketingJob] Failed to send email to {cust['email']}: {exc}")
                    failure_count += 1

        logger.info(
            f"[MonthlyBestSellerMarketingJob] ═══ Job completed ═══ | "
            f"Sent successfully: {success_count} | Failures: {failure_count}"
        )
