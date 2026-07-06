import logging
import os
import httpx
import asyncio
from cronjobs.base import BaseCronJob
from src.utils.database import get_db_cursor, get_db_config
from src.agentic.llms.primary import get_primary_llm

logger = logging.getLogger(__name__)


class MonthlyBestSellerMarketingJob(BaseCronJob):
    
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
                        "customer_id": row["customer_id"],
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

        items_text = "\n".join([f"{i}. {prod}" for i, prod in enumerate(top_products, 1)])

        # Generate styled HTML list items
        items_html_rows = ""
        for i, prod in enumerate(top_products, 1):
            bg_color = "#f8fafc" if i % 2 == 1 else "#ffffff"
            items_html_rows += f"""
            <tr>
                <td style="padding: 12px 15px; background-color: {bg_color}; border-radius: 6px; border: 1px solid #e2e8f0; margin-bottom: 8px;">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%">
                        <tr>
                            <td width="30" valign="middle" style="font-size: 16px; font-weight: bold; color: #3b82f6;">#{i}</td>
                            <td valign="middle" style="font-size: 15px; font-weight: bold; color: #1e293b; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;">{prod}</td>
                        </tr>
                    </table>
                </td>
            </tr>
            <tr><td height="8"></td></tr>
            """

        success_count = 0
        failure_count = 0

        # Initialize primary LLM for personalized generation
        llm = get_primary_llm()

        async with httpx.AsyncClient() as client:
            for cust in customers:
                recipient = test_email or os.getenv("TEST_EMAIL") or cust["email"]

                # Fetch customer purchase history
                history_query = """
                    SELECT DISTINCT COALESCE(il.details->>'product_name', il.details->>'item_name') as product_name
                    FROM sales_details sd
                    CROSS JOIN UNNEST(sd.item_line_ids) as line_id
                    JOIN item_lines il ON il.id = line_id
                    WHERE sd.buyer_id = %s
                      AND sd.is_deleted = FALSE
                      AND il.is_deleted = FALSE;
                """
                purchased_products = set()
                try:
                    with get_db_cursor(commit=False, db_config=get_db_config()) as cursor:
                        cursor.execute(history_query, (cust["customer_id"],))
                        h_rows = cursor.fetchall()
                        for hr in h_rows:
                            if hr["product_name"]:
                                purchased_products.add(hr["product_name"])
                except Exception as exc:
                    logger.error(f"[MonthlyBestSellerMarketingJob] Failed to fetch purchase history for customer {cust['customer_id']}: {exc}")

                matched_products = [prod for prod in top_products if prod in purchased_products]

                # Generate a customized greeting/intro paragraph using LLM based on their name, company, and purchase history
                history_list_str = ", ".join(list(purchased_products)) if purchased_products else ""
                top_products_str = ", ".join(top_products)

                prompt = f"""You are a professional email marketing assistant. Write a highly personalized, warm, and engaging email greeting/introduction paragraph for a customer.
                
                Customer Details:
                - Contact Name: {cust['contact_name']}
                - Company Name: {cust['company_name']}
                - Prior Purchase History (products they bought from us in the past): {history_list_str if history_list_str else 'No prior purchases'}
                - Top 5 Best-Selling Products of this month: {top_products_str}
                
                Guidelines:
                1. Make the message feel premium, professional, and personalized.
                2. If they have a purchase history, reference specific products they bought in the past and relate them to this month's top sellers or express appreciation for their trust.
                3. If they don't have a purchase history, write a welcoming message mentioning that we want to share our top-selling items to help their business.
                4. Do NOT write a subject line or signature/sign-off. Just output the body paragraph(s) (1-2 sentences max).
                5. Keep the tone conversational, helpful, and natural. Do NOT use placeholder tags. Do NOT use markdown.
                """

                try:
                    personalized_text = await llm.generate(prompt=prompt)
                    # Strip any surrounding quotes or spacing
                    personalized_text = str(personalized_text).strip().strip('"').strip("'").strip()
                except Exception as llm_exc:
                    logger.error(f"[MonthlyBestSellerMarketingJob] LLM generation failed: {llm_exc}")
                    # Fallback to standard message
                    if matched_products:
                        matched_str = ", ".join(matched_products)
                        personalized_text = f"We noticed that you have previously purchased these top-selling products from us: {matched_str}. It's great to see they are performing exceptionally well this month!"
                    else:
                        personalized_text = "These items are highly popular among our clients right now and might be a great fit for your current inventory."

                if matched_products:
                    bg_color_card = "#ecfdf5"
                    border_color_card = "#10b981"
                    text_color_card = "#065f46"
                else:
                    bg_color_card = "#f0f9ff"
                    border_color_card = "#0284c7"
                    text_color_card = "#0369a1"

                personalization_html = f"""
                <p style="color: #475569; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 15px; line-height: 1.6; margin-bottom: 20px; text-align: left;">
                    {personalized_text}
                </p>
                """
                personalization_text = personalized_text

                email_body = f"""Hi {cust['contact_name']},

We are pleased to share our top 5 best-selling products of this month with you!

{personalization_text}

Here is the list of our best sellers:
{items_text}

If you would like to place an order or get a quote, please feel free to reply to this email or contact us.

Best regards,
Sales & Marketing Team
"""

                email_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Monthly Best Sellers</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased;">
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f8fafc; padding: 20px 0;">
        <tr>
            <td align="center">
                <table border="0" cellpadding="0" cellspacing="0" width="600" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06); border: 1px solid #e2e8f0;">
                    <!-- Header with Gradient -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%); padding: 35px 20px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 26px; font-weight: bold; letter-spacing: 0.5px; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;">Monthly Best Sellers</h1>
                            <p style="color: #bfdbfe; margin: 8px 0 0 0; font-size: 14px; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;">Our Top Performing Products of the Month</p>
                        </td>
                    </tr>
                    <!-- Content -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #1e293b; font-size: 16px; font-weight: bold; margin-top: 0; margin-bottom: 12px; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; text-align: left;">Hi {cust['contact_name']},</p>
                            
                            {personalization_html}
                            
                            <!-- Products List -->
                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 25px; margin-bottom: 25px;">
                                {items_html_rows}
                            </table>
                            
                            <p style="color: #475569; font-size: 15px; line-height: 1.6; margin-top: 20px; margin-bottom: 30px; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; text-align: left;">
                                If you would like to place an order, request samples, or get a customized quote, please feel free to reply directly to this email or click the button below.
                            </p>
                            
                            <!-- Call to Action -->
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td align="center">
                                        <a href="mailto:sales@company.com" style="background-color: #2563eb; color: #ffffff; padding: 12px 30px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 15px; display: inline-block; box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.2); font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;">
                                            Contact Us / Get a Quote
                                        </a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <!-- Footer -->
                    <tr>
                        <td style="padding: 20px 30px 30px 30px; border-top: 1px solid #f1f5f9; text-align: center;">
                            <p style="color: #1e3a8a; font-weight: bold; font-size: 14px; margin: 0 0 5px 0; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;">Sales & Marketing Team</p>
                            <p style="color: #94a3b8; font-size: 12px; margin: 0; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;">© 2026 ERP Corporate Services. All rights reserved.</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

                payload = {
                    "to": recipient,
                    "subject": "Our Top 5 Best-Selling Products of the Month!",
                    "text": email_body,
                    "html": email_html
                }

                try:
                    logger.info(f"[MonthlyBestSellerMarketingJob] Sending email to {recipient} (Original: {cust['email']}) for {cust['company_name']}")
                    resp = await client.post(node_api_url, json=payload)
                    resp.raise_for_status()
                    success_count += 1
                except Exception as exc:
                    logger.error(f"[MonthlyBestSellerMarketingJob] Failed to send email to {recipient}: {exc}")
                    failure_count += 1

                # Wait 2.5 seconds to prevent rate-limiting SMTP connection on the server
                await asyncio.sleep(2.5)

        logger.info(
            f"[MonthlyBestSellerMarketingJob] ═══ Job completed ═══ | "
            f"Sent successfully: {success_count} | Failures: {failure_count}"
        )
