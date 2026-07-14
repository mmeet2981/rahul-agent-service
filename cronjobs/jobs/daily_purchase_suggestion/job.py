"""
Daily Purchase Suggestion Cron Job (Orchestrator).
Implements BaseCronJob — only orchestrates the layers, owns no business logic.

Flow:
  1. Repository  → fetch product stock/sales data from DB
  2. Service     → apply condition: (current_stock + pending_inwards) < (min_stock_qty + open_sale_qty)
  3. ApiClient   → for each product that needs a PO, call ERP API with status = pending
"""
import logging
from cronjobs.base import BaseCronJob
from cronjobs.jobs.daily_purchase_suggestion.config import PurchaseSuggestionConfig
from cronjobs.jobs.daily_purchase_suggestion.repository import PurchaseSuggestionRepository
from cronjobs.jobs.daily_purchase_suggestion.service import PurchaseSuggestionService
from cronjobs.jobs.daily_purchase_suggestion.api_client import PurchaseApiClient

logger = logging.getLogger(__name__)


class DailyPurchaseSuggestionJob(BaseCronJob):
    """
    Runs every day at 08:30.
    Checks stock levels and raises Purchase Orders (status=pending)
    automatically for any product that falls below the threshold.
    """

    def __init__(self):
        self._config = PurchaseSuggestionConfig()
        self._repository = PurchaseSuggestionRepository()
        self._service = PurchaseSuggestionService()
        self._api_client = PurchaseApiClient(self._config)

    @property
    def name(self) -> str:
        return "daily_purchase_suggestion"

    async def run(self) -> None:
        logger.info("[DailyPurchaseSuggestionJob] ═══ Job started ═══")

        # Step 1 – Fetch data
        try:
            products = self._repository.get_stock_evaluation_data()
        except Exception as exc:
            logger.error(
                f"[DailyPurchaseSuggestionJob] Failed to fetch DB data: {exc}",
                exc_info=True,
            )
            return

        if not products:
            logger.warning("[DailyPurchaseSuggestionJob] No products found. Exiting.")
            return

        # Step 2 – Apply business condition
        suggestions = self._service.evaluate(products)

        if not suggestions:
            logger.info(
                "[DailyPurchaseSuggestionJob] All products have sufficient stock. No PO needed."
            )
            return

        # Step 3 – Create POs via ERP API
        success_count = 0
        failure_count = 0

        for product, suggested_qty in suggestions:
            try:
                await self._api_client.create_purchase_order(product, suggested_qty)
                success_count += 1
            except Exception as exc:
                failure_count += 1
                logger.error(
                    f"[DailyPurchaseSuggestionJob] Failed to create PO for "
                    f"product_id={product.get('product_id')}: {exc}",
                    exc_info=True,
                )

        logger.info(
            f"[DailyPurchaseSuggestionJob] ═══ Job completed ═══ | "
            f"POs created: {success_count} | Failures: {failure_count}"
        )
