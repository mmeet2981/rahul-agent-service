import unittest
from datetime import date, timedelta
from src.agentic.tools.inquiry.template_handler import (
    is_template_request,
    is_template_format,
    parse_inquiry_template,
    _normalize_date,
    get_template_text,
)


class TestInquiryTemplate(unittest.TestCase):

    def test_is_template_request(self):
        self.assertTrue(is_template_request("/template"))
        self.assertTrue(is_template_request("template"))
        self.assertTrue(is_template_request("inquiry template"))
        self.assertTrue(is_template_request("inquiry format"))
        self.assertTrue(is_template_request("/format"))
        self.assertTrue(is_template_request("format"))

        # Non-template requests should return False (fallback)
        self.assertFalse(is_template_request("hi"))
        self.assertFalse(is_template_request("I need 500 reams of paper"))
        self.assertFalse(is_template_request("what is my status?"))

    def test_is_template_format(self):
        sample_with_header = """
        *INQUIRY*
        Customer: ABC Corp
        Product: Copier Paper
        Qty: 500
        UOM: Ream
        """
        self.assertTrue(is_template_format(sample_with_header))

        sample_without_header_but_with_core_keys = """
        Customer: XYZ Industries
        Product: Maplitho Paper
        Quantity: 1000
        UOM: Kg
        Delivery Date: 2026-03-30
        """
        self.assertTrue(is_template_format(sample_without_header_but_with_core_keys))

        # Conversational inputs MUST return False for LLM fallback!
        self.assertFalse(is_template_format("Hi, I want to create an inquiry"))
        self.assertFalse(is_template_format("Can you help me place an order?"))
        self.assertFalse(is_template_format("JK Copier Paper"))
        self.assertFalse(is_template_format("Yes, please submit it"))
        self.assertFalse(is_template_format("500 reams"))

    def test_parse_single_product_template(self):
        sample = """
        *INQUIRY*
        Customer: Adinath Print Pack Solutions
        Contact: Rahul Sharma
        Delivery Date: 2026-04-15
        Notes: Urgent delivery please

        Product: JK-ULTIMA-220GSM-80.0CMS
        Quantity: 500
        UOM: Ream
        Size: 80.0CMS
        GSM: 220
        Price: 150
        """
        parsed = parse_inquiry_template(sample)
        self.assertEqual(parsed["customer"], "Adinath Print Pack Solutions")
        self.assertEqual(parsed["contact"], "Rahul Sharma")
        self.assertEqual(parsed["delivery_date"], "2026-04-15")
        self.assertEqual(parsed["notes"], "Urgent delivery please")
        self.assertEqual(len(parsed["items"]), 1)

        item = parsed["items"][0]
        self.assertEqual(item["product_name"], "JK-ULTIMA-220GSM-80.0CMS")
        self.assertEqual(item["quantity"], "500")
        self.assertEqual(item["uom"], "Ream")
        self.assertEqual(item["size"], "80.0CMS")
        self.assertEqual(item["gsm"], "220")
        self.assertEqual(item["price"], "150")

    def test_parse_multi_product_template(self):
        sample = """
        *NEW INQUIRY*
        Customer: VIJAY TRADERS - SURAT
        Delivery Date: 30-04-2026

        1. Product: JK-ULTIMA-220GSM-80.0CMS
           Qty: 250
           UOM: Ream
           GSM: 220

        2. Product: Maplitho Paper
           Qty: 1000
           UOM: Kg
           Size: 63.5X91.5
           Price: 85
        """
        parsed = parse_inquiry_template(sample)
        self.assertEqual(parsed["customer"], "VIJAY TRADERS - SURAT")
        self.assertEqual(parsed["delivery_date"], "30-04-2026")
        self.assertEqual(len(parsed["items"]), 2)

        item1 = parsed["items"][0]
        self.assertEqual(item1["product_name"], "JK-ULTIMA-220GSM-80.0CMS")
        self.assertEqual(item1["quantity"], "250")
        self.assertEqual(item1["uom"], "Ream")

        item2 = parsed["items"][1]
        self.assertEqual(item2["product_name"], "Maplitho Paper")
        self.assertEqual(item2["quantity"], "1000")
        self.assertEqual(item2["uom"], "Kg")
        self.assertEqual(item2["size"], "63.5X91.5")
        self.assertEqual(item2["price"], "85")

    def test_normalize_date(self):
        self.assertEqual(_normalize_date("2026-05-20"), "2026-05-20")
        self.assertEqual(_normalize_date("20/05/2026"), "2026-05-20")
        self.assertEqual(_normalize_date("20-05-2026"), "2026-05-20")

        tomorrow_str = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.assertEqual(_normalize_date("tomorrow"), tomorrow_str)

    def test_get_template_text(self):
        text = get_template_text()
        self.assertIn("*INQUIRY*", text)
        self.assertIn("Customer:", text)
        self.assertIn("Product:", text)
        self.assertIn("Quantity:", text)
        self.assertIn("UOM:", text)
        self.assertNotIn("Price:", text)

    def test_parse_template_ignores_placeholders_and_price(self):
        sample = """
        📋 *Inquiry Template*
        Copy, fill, and send the format below to submit your inquiry directly:

        *INQUIRY*
        Customer: 3I LABELS INDIA PVT. LTD.
        Contact: CHINTAN PREMSHANKER SHUKLA
        Delivery Date: 2026-09-29

        Product: B-W&P PAPER
        Quantity: 200
        UOM: Box
        Size: 720 X 120
        GSM: 300
        Price: <Target Price> (Optional)
        Notes: <Special instructions> (Optional)

        Product: Art paper B
        Quantity: 200
        UOM: Box
        Size: 720 X 120
        GSM: 300
        """
        parsed = parse_inquiry_template(sample)
        self.assertEqual(parsed["customer"], "3I LABELS INDIA PVT. LTD.")
        self.assertEqual(parsed["contact"], "CHINTAN PREMSHANKER SHUKLA")
        self.assertEqual(parsed["delivery_date"], "2026-09-29")
        # Notes and price must be ignored when unfilled or placeholder
        self.assertEqual(parsed["notes"], "")
        self.assertEqual(len(parsed["items"]), 2)

        item1 = parsed["items"][0]
        self.assertEqual(item1["product_name"], "B-W&P PAPER")
        self.assertEqual(item1["price"], "")
        self.assertNotIn("specifications", item1)

        item2 = parsed["items"][1]
        self.assertEqual(item2["product_name"], "Art paper B")

    def test_resolve_customer_api(self):
        import asyncio
        from unittest.mock import patch, AsyncMock, MagicMock
        from src.agentic.tools.inquiry.template_handler import _resolve_customer

        async def run():
            # Test 1: Successful API response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "success": True,
                "data": {
                    "entities": [
                        {"id": 8517, "name": "Adinath Print Pack Solutions", "entity_code": "B3726"}
                    ]
                }
            }

            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_response
                cust, err = await _resolve_customer("Adinath")
                self.assertIsNone(err)
                self.assertEqual(cust["id"], 8517)
                self.assertEqual(cust["name"], "Adinath Print Pack Solutions")

            # Test 2: API returns empty list
            mock_empty = MagicMock()
            mock_empty.status_code = 200
            mock_empty.json.return_value = {"success": True, "data": {"entities": []}}

            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_empty
                with patch("src.agentic.tools.inquiry.template_handler.get_db_cursor") as mock_db:
                    mock_cur = mock_db.return_value.__enter__.return_value
                    mock_cur.fetchall.return_value = []
                    cust, err = await _resolve_customer("NoSuchCustomerXYZ")
                    self.assertIsNone(cust)
                    self.assertIn("No customer found matching", err)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

