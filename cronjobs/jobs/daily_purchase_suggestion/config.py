"""
Config for the Daily Purchase Suggestion cron job.
All values come from .env — no hard-coded secrets or URLs.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class PurchaseSuggestionConfig:
    """
    Single source of truth for all config needed by this cron job.
    Dependency Inversion: higher-level classes depend on this abstraction,
    not on raw os.getenv() calls scattered everywhere.
    """

    # ── ERP API ────────────────────────────────────────────────────────────
    API_BASE_URL: str = os.getenv(
        "ERP_API_BASE_URL",
        "https://rahul-trading-erp-ctash7bkhbgmdnhz.centralindia-01.azurewebsites.net",
    )
    PURCHASE_SERVICE_PATH: str = os.getenv(
        "ERP_PURCHASE_SERVICE_PATH", "/V1/purchase-service"
    )

    # ── Auth & Company ─────────────────────────────────────────────────────
    ERP_AUTH_TOKEN: str = os.getenv("ERP_AUTH_TOKEN", "")
    ERP_COMPANY_ID: str = os.getenv("ERP_COMPANY_ID", "4782")
    ERP_USER_ID: str = os.getenv("ERP_USER_ID", "22")

    # ── Purchase Order Defaults ────────────────────────────────────────────
    PO_PURCHASE_TYPE_ID: int = int(os.getenv("PO_PURCHASE_TYPE_ID", "3"))
    PO_STATUS_ID: int = int(os.getenv("PO_STATUS_ID", "34"))          # "pending" status
    # PO_BILL_TO_ADDRESS_ID: int = int(os.getenv("PO_BILL_TO_ADDRESS_ID", "3597"))
    # PO_SHIP_TO_ADDRESS_ID: int = int(os.getenv("PO_SHIP_TO_ADDRESS_ID", "3597"))
    PO_TAX_TYPE_IDS: list = [
        int(x) for x in os.getenv("PO_TAX_TYPE_IDS", "19,20").split(",") if x
    ]
    PO_TRANSACTION_TYPE_ID: int = int(os.getenv("PO_TRANSACTION_TYPE_ID", "3"))

    # ── Database (re-uses existing TARGET_DB_* vars from .env) ────────────
    # Consumed via src.utils.database.get_db_config() — no duplication needed.

    @property
    def purchase_api_url(self) -> str:
        return f"{self.API_BASE_URL}{self.PURCHASE_SERVICE_PATH}"
