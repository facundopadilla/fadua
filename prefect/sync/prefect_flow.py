"""Prefect-orchestrated entrypoint for the WooCommerce -> Sheets sync.

This is the version that actually runs on the VPS. `sync_flow.serve(...)`
registers a deployment with a 5-minute cron schedule and starts a runner, so
every run shows up in the Prefect UI (state, logs, retries, duration) and the
schedule can be paused from there.

It reuses the same modules as the plain cron entrypoint (`python -m sync`),
which stays in the repo as a dependency-free reference.

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
from sync.diff import find_new_products
from sync.notifier import send_new_products_notification
from sync.sheets import append_rows, read_existing_ids
from sync.woocommerce import fetch_published_products

LOCAL_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


@task
def fetch_products() -> list[dict]:
    # The WooCommerce client already retries with exponential backoff, so no
    # extra Prefect retry is layered on top here.
    config = load_config()
    return fetch_published_products(
        config.wc_base_url, config.wc_consumer_key, config.wc_consumer_secret
    )


@task(retries=2, retry_delay_seconds=5)
def read_ids() -> set:
    config = load_config()
    return read_existing_ids(
        config.google_sa_json, config.google_sheet_id, config.google_sheet_tab
    )


@task(retries=2, retry_delay_seconds=5)
def append_products(new_products: list) -> None:
    config = load_config()
    timestamp = datetime.now(LOCAL_TZ).isoformat(timespec="seconds")
    rows = [
        [str(p["id"]), p["name"], p["price"], p["image"], timestamp]
        for p in new_products
    ]
    append_rows(
        config.google_sa_json, config.google_sheet_id, config.google_sheet_tab, rows
    )


@task
def notify(new_products: list) -> None:
    config = load_config()
    send_new_products_notification(
        config.smtp_host,
        config.smtp_port,
        config.smtp_user,
        config.smtp_app_password,
        config.notify_to,
        new_products,
    )


@flow(name="fadua-woo-sheets-sync")
def sync_flow() -> None:
    logger = get_run_logger()

    products = fetch_products()
    existing_ids = read_ids()
    new_products = find_new_products(products, existing_ids)

    if not new_products:
        logger.info("No new products found; nothing to sync this run.")
        return

    append_products(new_products)
    logger.info("Appended %d new product(s) to the sheet.", len(new_products))

    # The rows are already safe in the sheet; a notification failure must not
    # fail the run (same contract as the cron entrypoint).
    try:
        notify(new_products)
        logger.info("Notification sent for %d new product(s).", len(new_products))
    except Exception as error:
        logger.error("Notification failed (data already safe in the sheet): %s", error)


if __name__ == "__main__":
    # Registers the deployment and starts the runner. Keep GOOGLE_SHEET_TAB set
    # to "python" so this writes to the same tab as the cron reference version.
    sync_flow.serve(name="fadua-sync", cron="*/5 * * * *")
