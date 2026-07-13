import logging
import os
import httpx
from cronjobs.base import BaseCronJob
from src.utils.database import get_db_cursor, get_db_config

logger = logging.getLogger(__name__)


class PendingSalesInquiriesJob(BaseCronJob):
    """
    Runs automatically based on cron settings.
    Finds pending sales inquiries and emails them to active customer contacts.
    """

    @property
    def name(self) -> str:
        return "pending_sales_inquiries"

    async def run(self, test_email: str = None) -> None:
        logger.info("[PendingSalesInquiriesJob] ═══ Job started ═══")

        # Step 1: Fetch pending inquiries from target database
        inquiries_query = """
            SELECT 
                i.id AS inquiry_id,
                i.inquiry_code,
                i.status AS inquiry_status,
                i.product_requested,
                i.quantity,
                i.uom,
                i.created_at,
                em.id AS customer_id,
                em.name AS customer_name,
                poc.name AS contact_name,
                poc.email AS email
            FROM inquiries i
            JOIN entity_master em ON i.customer_id = em.id
            JOIN poc_details poc ON poc.entity_id = em.id
            WHERE i.status NOT IN ('CONVERTED', 'REJECTED')
              AND i.is_deleted = FALSE
              AND em.is_deleted = FALSE
              AND poc.is_deleted = FALSE;
        """

        groups = {}
        try:
            with get_db_cursor(commit=False, db_config=get_db_config()) as cursor:
                cursor.execute(inquiries_query)
                rows = cursor.fetchall()
                for row in rows:
                    email = row["email"]
                    if not email:
                        continue
                    if email not in groups:
                        groups[email] = {
                            "contact_name": row["contact_name"],
                            "customer_name": row["customer_name"],
                            "inquiries": []
                        }
                    groups[email]["inquiries"].append(row)
        except Exception as exc:
            logger.error(f"[PendingSalesInquiriesJob] Failed to fetch pending inquiries: {exc}", exc_info=True)
            return

        if not groups:
            logger.warning("[PendingSalesInquiriesJob] No pending inquiries with customer emails found. Exiting.")
            return

        logger.info(f"[PendingSalesInquiriesJob] Found pending inquiries for {len(groups)} customer contacts.")

        # Step 2: Format and send emails via Node.js email service
        email_host = os.getenv("EMAIL_HOST", f"http://127.0.0.1:{os.getenv('EMAIL_SERVICE_PORT', '3005')}")
        node_api_url = f"{email_host}/send"

        success_count = 0
        failure_count = 0

        async with httpx.AsyncClient() as client:
            for email, data in groups.items():
                recipient = test_email or os.getenv("TEST_EMAIL") or email
                contact_name = data["contact_name"]
                customer_name = data["customer_name"]
                inquiries = data["inquiries"]
                
                # Format inquiries list in Plain Text
                inquiries_text = ""
                # Format inquiries in HTML table
                inquiries_html = """
                <table style="border-collapse: collapse; width: 100%; border: 1px solid #ddd; font-family: Arial, sans-serif;">
                    <thead>
                        <tr style="background-color: #f2f2f2; text-align: left;">
                            <th style="padding: 12px; border-bottom: 1px solid #ddd;">Inquiry Code</th>
                            <th style="padding: 12px; border-bottom: 1px solid #ddd;">Product</th>
                            <th style="padding: 12px; border-bottom: 1px solid #ddd;">Quantity</th>
                            <th style="padding: 12px; border-bottom: 1px solid #ddd;">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                """
                
                for idx, inq in enumerate(inquiries, 1):
                    prod = inq["product_requested"] or "N/A"
                    qty = inq["quantity"]
                    uom = inq["uom"] or ""
                    qty_str = f"{qty} {uom}".strip() if qty is not None else "N/A"
                    code = inq["inquiry_code"]
                    status = inq["inquiry_status"]
                    
                    inquiries_text += f"{idx}. {code}: {prod} | Quantity: {qty_str} | Status: {status}\n"
                    inquiries_html += f"""
                        <tr>
                            <td style="padding: 12px; border-bottom: 1px solid #ddd;"><b>{code}</b></td>
                            <td style="padding: 12px; border-bottom: 1px solid #ddd;">{prod}</td>
                            <td style="padding: 12px; border-bottom: 1px solid #ddd;">{qty_str}</td>
                            <td style="padding: 12px; border-bottom: 1px solid #ddd;"><span style="background-color: #e6f7ff; color: #1890ff; padding: 4px 8px; border-radius: 4px; font-size: 12px;">{status}</span></td>
                        </tr>
                    """
                
                inquiries_html += """
                    </tbody>
                </table>
                """
                
                email_body = f"""Dear {contact_name},

We would like to share an update on your pending sales inquiries with {customer_name}. Below is the status of inquiries currently being processed:

{inquiries_text}
If you have any questions or would like to proceed with any of these inquiries, please reply to this email.

Best regards,
Sales Operations Team
"""

                email_html_body = f"""
                <div style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                    <h2 style="color: #1a73e8; margin-top: 0;">Pending Sales Inquiries Update</h2>
                    <p>Dear <strong>{contact_name}</strong>,</p>
                    <p>We would like to share an update on your pending sales inquiries with <strong>{customer_name}</strong>. Below is the status of inquiries currently being processed:</p>
                    <div style="margin: 20px 0;">
                        {inquiries_html}
                    </div>
                    <p>If you have any questions or would like to proceed with any of these inquiries, please feel free to reply directly to this email.</p>
                    <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
                    <p style="font-size: 12px; color: #777;">Best regards,<br><strong>Sales Operations Team</strong></p>
                </div>
                """

                payload = {
                    "to": recipient,
                    "subject": f"Update on Your Pending Sales Inquiries - {customer_name}",
                    "text": email_body,
                    "html": email_html_body
                }

                try:
                    logger.info(f"[PendingSalesInquiriesJob] Sending email to {recipient} (Original: {email}) for {customer_name}")
                    resp = await client.post(node_api_url, json=payload)
                    resp.raise_for_status()
                    success_count += 1
                except Exception as exc:
                    logger.error(f"[PendingSalesInquiriesJob] Failed to send email to {recipient}: {exc}")
                    failure_count += 1

        logger.info(
            f"[PendingSalesInquiriesJob] ═══ Job completed ═══ | "
            f"Sent successfully: {success_count} | Failures: {failure_count}"
        )
