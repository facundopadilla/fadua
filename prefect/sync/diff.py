def find_new_products(products, existing_ids):
    """Return the products whose id is not already present in existing_ids.

    WooCommerce provides `id` as an int; the sheet (read back via gspread)
    yields existing IDs as strings. Both sides are normalized to str before
    comparing, so the int/str boundary never causes a product that's already
    in the sheet to be misdetected as new.
    """
    normalized_existing_ids = {str(existing_id) for existing_id in existing_ids}
    return [
        product
        for product in products
        if str(product["id"]) not in normalized_existing_ids
    ]
