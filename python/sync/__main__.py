import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sync.config import MissingConfigError, load_config
from sync.diff import classify_products
from sync.notifier import send_sync_notification
from sync.sheets import append_rows, read_existing_rows, update_rows
from sync.woocommerce import fetch_published_products

# Anchored to this file's location (not cwd) so the log path is stable
# whether the script is invoked by cron, `uv run python -m sync`, or a
# shell in some other directory.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = PACKAGE_ROOT / "logs" / "sync.log"

# FADUA operates in Argentina; stamp the "Sincronizado" column in local time
# so it matches the wall clock when a product is loaded (and the n8n version,
# whose container runs in the same zone).
LOCAL_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def _configure_logging() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE)],
    )


def main() -> None:
    _configure_logging()
    logger = logging.getLogger("sync")

    try:
        config = load_config()
    except MissingConfigError as error:
        logger.error("Configuration error, sheet left untouched: %s", error)
        sys.exit(1)

    try:
        products = fetch_published_products(
            config.wc_base_url, config.wc_consumer_key, config.wc_consumer_secret
        )
    except Exception as error:
        # Covers exhausted retries and any other fetch-stage failure.
        # Fail clean: log and exit without touching the sheet. The sheet
        # is the source of truth, so the next run (<=5 min later) recovers
        # on its own with no data loss.
        logger.error("WooCommerce fetch failed, sheet left untouched: %s", error)
        sys.exit(1)

    try:
        existing_by_id = read_existing_rows(
            config.google_sa_json, config.google_sheet_id, config.google_sheet_tab
        )
        new_products, changed_products = classify_products(products, existing_by_id)

        if not new_products and not changed_products:
            logger.info("No new or changed products found; nothing to sync this run.")
            return

        timestamp = datetime.now(LOCAL_TZ).isoformat(timespec="seconds")

        if new_products:
            new_rows = [
                [
                    str(product["id"]),
                    product["name"],
                    product["price"],
                    product["image"],
                    timestamp,
                ]
                for product in new_products
            ]
            append_rows(
                config.google_sa_json, config.google_sheet_id, config.google_sheet_tab, new_rows
            )
            logger.info("Appended %d new product(s) to the sheet.", len(new_products))

        if changed_products:
            updates = [
                (
                    entry["row"],
                    [
                        str(entry["product"]["id"]),
                        entry["product"]["name"],
                        entry["product"]["price"],
                        entry["product"]["image"],
                        timestamp,
                    ],
                )
                for entry in changed_products
            ]
            update_rows(
                config.google_sa_json, config.google_sheet_id, config.google_sheet_tab, updates
            )
            logger.info("Updated %d changed product(s) in the sheet.", len(changed_products))
    except Exception as error:
        logger.error("Sheet sync failed: %s", error)
        sys.exit(1)

    # Both writes already succeeded and the data is safe. A notification
    # failure from here on is logged but must not fail the run.
    try:
        send_sync_notification(
            config.smtp_host,
            config.smtp_port,
            config.smtp_user,
            config.smtp_app_password,
            config.notify_to,
            new_products,
            changed_products,
        )
        logger.info(
            "Notification email sent for %d new and %d changed product(s).",
            len(new_products),
            len(changed_products),
        )
    except Exception as error:
        logger.error("Notification email failed (data already safe in the sheet): %s", error)


if __name__ == "__main__":
    main()
