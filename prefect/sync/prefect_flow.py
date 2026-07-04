"""Prefect-orchestrated entrypoint for the WooCommerce -> Sheets sync.

This is the version that actually runs on the VPS. `sync_flow.serve(...)`
registers a deployment with a 5-minute cron schedule and starts a runner, so
every run shows up in the Prefect UI (state, logs, retries, duration) and the
schedule can be paused from there.

It reuses the same modules as the plain cron entrypoint (`python -m sync`),
which stays in the repo as a dependency-free reference. It detects both new
products (appended) and changes to existing ones (price/name/image, updated in
place), and emails a summary of both.

Security note: each task loads its own config from environment variables
instead of receiving it as an argument. Task arguments are tracked by Prefect,
so passing the config (which holds the consumer secret and the Gmail app
password) could expose those secrets in the UI. Only product data — which is
public — flows between tasks.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from prefect import flow, task
from prefect.logging import get_run_logger

from sync.config import load_config
from sync.diff import classify_products
from sync.notifier import send_sync_notification
from sync.sheets import append_rows, read_existing_rows, update_rows
from sync.woocommerce import fetch_published_products

LOCAL_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


@task
def fetch_products() -> list[dict]:
    # The WooCommerce client already retries with exponential backoff.
    config = load_config()
    return fetch_published_products(
        config.wc_base_url, config.wc_consumer_key, config.wc_consumer_secret
    )


@task(retries=2, retry_delay_seconds=5)
def read_rows() -> dict:
    config = load_config()
    return read_existing_rows(
        config.google_sa_json, config.google_sheet_id, config.google_sheet_tab
    )


@task(retries=2, retry_delay_seconds=5)
def append_new(new_products: list, timestamp: str) -> None:
    config = load_config()
    rows = [
        [str(p["id"]), p["name"], p["price"], p["image"], timestamp]
        for p in new_products
    ]
    append_rows(
        config.google_sa_json, config.google_sheet_id, config.google_sheet_tab, rows
    )


@task(retries=2, retry_delay_seconds=5)
def update_changed(changed_products: list, timestamp: str) -> None:
    config = load_config()
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


@task
def notify(new_products: list, changed_products: list) -> None:
    config = load_config()
    send_sync_notification(
        config.smtp_host,
        config.smtp_port,
        config.smtp_user,
        config.smtp_app_password,
        config.notify_to,
        new_products,
        changed_products,
    )


@flow(name="fadua-woo-sheets-sync")
def sync_flow() -> None:
    logger = get_run_logger()

    products = fetch_products()
    existing_by_id = read_rows()
    new_products, changed_products = classify_products(products, existing_by_id)

    if not new_products and not changed_products:
        logger.info("No new or changed products found; nothing to sync this run.")
        return

    timestamp = datetime.now(LOCAL_TZ).isoformat(timespec="seconds")

    if new_products:
        append_new(new_products, timestamp)
        logger.info("Appended %d new product(s) to the sheet.", len(new_products))

    if changed_products:
        update_changed(changed_products, timestamp)
        logger.info(
            "Updated %d changed product(s) in the sheet.", len(changed_products)
        )

    # The rows are already safe in the sheet; a notification failure must not
    # fail the run (same contract as the cron entrypoint).
    try:
        notify(new_products, changed_products)
        logger.info(
            "Notification sent for %d new and %d changed product(s).",
            len(new_products),
            len(changed_products),
        )
    except Exception as error:
        logger.error("Notification failed (data already safe in the sheet): %s", error)


if __name__ == "__main__":
    # Registers the deployment and starts the runner. Keep GOOGLE_SHEET_TAB set
    # to the Prefect tab so this writes to its own tab.
    sync_flow.serve(name="fadua-sync", cron="*/5 * * * *")
