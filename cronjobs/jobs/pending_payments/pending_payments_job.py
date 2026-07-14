import logging
import os
import httpx
from cronjobs.base import BaseCronJob
from src.utils.database import get_db_cursor, get_db_config

logger = logging.getLogger(__name__)


class PendingPaymentsJob(BaseCronJob):
    """
    Runs automatically based on cron settings.
    Finds outstanding payments and emails the invoice details to active customer contacts.
    """

    @property
    def name(self) -> str:
        return "pending_payments"

    async def run(self, test_email: str = None) -> None:
        logger.info("[PendingPaymentsJob] ═══ Job started ═══")

        # Step 1: Fetch pending payments from target database
        payments_query = """
            SELECT 
                i.invoice_no,
                i.date AS invoice_date,
                v.voucher_number,
                br.original_amount,
                br.outstanding_amount,
                em.name AS customer_name,
                poc.name AS contact_name,
                poc.email AS email
            FROM invoices i
            JOIN accounts.vouchers v ON v.reference_number = i.invoice_no
            JOIN accounts.bill_references br ON br.originating_voucher_id = v.id and br.outstanding_amount > 0
            JOIN accounts.entity_ledger_map elm ON elm.ledger_id = br.ledger_id
            JOIN entity_master em ON em.id = elm.entity_id
            JOIN poc_details poc ON poc.entity_id = em.id
            WHERE i.is_deleted = FALSE
              AND em.is_deleted = FALSE
              AND poc.is_deleted = FALSE;
        """

        groups = {}
        try:
            with get_db_cursor(commit=False, db_config=get_db_config()) as cursor:
                cursor.execute(payments_query)
                rows = cursor.fetchall()
                for row in rows:
                    email = row["email"]
                    if not email:
                        continue
                    if email not in groups:
                        groups[email] = {
                            "contact_name": row["contact_name"],
                            "customer_name": row["customer_name"],
                            "payments": []
                        }
                    groups[email]["payments"].append(row)
        except Exception as exc:
            logger.error(f"[PendingPaymentsJob] Failed to fetch pending payments: {exc}", exc_info=True)
            return

        if not groups:
            logger.warning("[PendingPaymentsJob] No pending payments with customer emails found. Exiting.")
            return

        logger.info(f"[PendingPaymentsJob] Found pending payments for {len(groups)} customer contacts.")

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
                payments = data["payments"]
                
                # Format payments list in Plain Text
                payments_text = ""
                # Format payments in HTML table
                payments_html = """
                <table style="border-collapse: collapse; width: 100%; border: 1px solid #ddd; font-family: Arial, sans-serif;">
                    <thead>
                        <tr style="background-color: #f2f2f2; text-align: left;">
                            <th style="padding: 12px; border-bottom: 1px solid #ddd;">Invoice No</th>
                            <th style="padding: 12px; border-bottom: 1px solid #ddd;">Invoice Date</th>
                            <th style="padding: 12px; border-bottom: 1px solid #ddd;">Original Amount</th>
                            <th style="padding: 12px; border-bottom: 1px solid #ddd;">Paid Amount</th>
                            <th style="padding: 12px; border-bottom: 1px solid #ddd;">Outstanding Amount</th>
                        </tr>
                    </thead>
                    <tbody>
                """
                
                for idx, pay in enumerate(payments, 1):
                    inv_no = pay["invoice_no"]
                    inv_date = pay["invoice_date"]
                    orig_amt = pay["original_amount"]
                    out_amt = pay["outstanding_amount"]
                    paid_amt = orig_amt - out_amt
                    
                    payments_text += f"{idx}. Invoice: {inv_no} | Date: {inv_date} | Original: {orig_amt} | Paid: {paid_amt} | Outstanding: {out_amt}\n"
                    payments_html += f"""
                        <tr>
                            <td style="padding: 12px; border-bottom: 1px solid #ddd;"><b>{inv_no}</b></td>
                            <td style="padding: 12px; border-bottom: 1px solid #ddd;">{inv_date}</td>
                            <td style="padding: 12px; border-bottom: 1px solid #ddd;">₹{orig_amt:,.2f}</td>
                            <td style="padding: 12px; border-bottom: 1px solid #ddd; color: #2e7d32;">₹{paid_amt:,.2f}</td>
                            <td style="padding: 12px; border-bottom: 1px solid #ddd; color: #d93025; font-weight: bold;">₹{out_amt:,.2f}</td>
                        </tr>
                    """
                
                payments_html += """
                    </tbody>
                </table>
                """
                
                email_body = f"""Dear {contact_name},

This is a reminder regarding outstanding payments on invoices with {customer_name}. Below is the summary of outstanding amounts:

{payments_text}
Please arrange for the payment at the earliest. If you have already made the payment, please reply to this email with the transaction details.

Best regards,
Accounts Department
"""

                email_html_body = f"""
                <div style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                    <h2 style="color: #d93025; margin-top: 0;">Outstanding Payment Reminder</h2>
                    <p>Dear <strong>{contact_name}</strong>,</p>
                    <p>This is a reminder regarding outstanding payments on invoices with <strong>{customer_name}</strong>. Below is the summary of your outstanding amounts:</p>
                    <div style="margin: 20px 0;">
                        {payments_html}
                    </div>
                    <p>Please arrange for the payment at the earliest. If you have already processed the payment, please reply directly to this email with the transaction details so we can update our records.</p>
                    <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
                    <p style="font-size: 12px; color: #777;">Best regards,<br><strong>Accounts Department</strong></p>
                </div>
                """

                payload = {
                    "to": recipient,
                    "subject": f"Outstanding Payment Reminder - {customer_name}",
                    "text": email_body,
                    "html": email_html_body
                }

                try:
                    logger.info(f"[PendingPaymentsJob] Sending email to {recipient} (Original: {email}) for {customer_name}")
                    resp = await client.post(node_api_url, json=payload)
                    resp.raise_for_status()
                    success_count += 1
                except Exception as exc:
                    logger.error(f"[PendingPaymentsJob] Failed to send email to {recipient}: {exc}")
                    failure_count += 1

        logger.info(
            f"[PendingPaymentsJob] ═══ Job completed ═══ | "
            f"Sent successfully: {success_count} | Failures: {failure_count}"
        )
