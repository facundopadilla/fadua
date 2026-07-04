import time

import requests

RETRY_ATTEMPTS = 3
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 30


class WooCommerceError(RuntimeError):
    """Raised when the WooCommerce API cannot be reached after all retries."""


def fetch_published_products(base_url: str, consumer_key: str, consumer_secret: str) -> list[dict]:
    """Fetch every published product from the WooCommerce REST API.

    Pages through the `products` endpoint (status=publish, per_page=100)
    until an empty page is returned, and normalizes each product into a
    plain dict: id, name, price (string, verbatim), image, permalink.

    Raises WooCommerceError if a page still fails after RETRY_ATTEMPTS
    attempts with exponential backoff.
    """
    products = []
    page = 1

    while True:
        page_products = _fetch_page(base_url, consumer_key, consumer_secret, page)
        if not page_products:
            break
        products.extend(_normalize(product) for product in page_products)
        page += 1

    return products


def _fetch_page(base_url: str, consumer_key: str, consumer_secret: str, page: int) -> list[dict]:
    url = f"{base_url}/wp-json/wc/v3/products"
    params = {"status": "publish", "per_page": PAGE_SIZE, "page": page}

    last_error: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = requests.get(
                url,
                params=params,
                auth=(consumer_key, consumer_secret),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            last_error = error
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(2**attempt)

    raise WooCommerceError(
        f"WooCommerce API request failed after {RETRY_ATTEMPTS} attempts (page {page}): {last_error}"
    ) from last_error


def _normalize(product: dict) -> dict:
    images = product.get("images") or []
    return {
        "id": product["id"],
        "name": product.get("name", ""),
        "price": product.get("price", ""),
        "image": images[0]["src"] if images else "",
        "permalink": product.get("permalink", ""),
    }
