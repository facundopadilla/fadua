def classify_products(products, existing_by_id):
    """Split fetched WooCommerce products into new and changed, against the sheet's current state.

    `existing_by_id` (as returned by `sheets.read_existing_rows`) maps
    str(ID) -> {"row": int, "Producto": str, "Precio": str, "Imagen": str}.
    WooCommerce provides `id` as an int while sheet-derived keys/values are
    always str, so every comparison normalizes to str before comparing (the
    int/str boundary must never cause a false "new" or a false "unchanged").

    Returns (new, changed):
    - `new`: products whose id is not a key in existing_by_id, unmodified.
    - `changed`: one dict per product whose id IS a key but whose Producto,
      Precio, and/or Imagen differ from the sheet's current values:
      {"product": product, "row": int, "changes": {field: (old, new)}}.
      A product with no differences is omitted entirely (not included with
      an empty "changes" dict), and a product can have more than one changed
      field at once (e.g. both Precio and Imagen).

    Pure function: no I/O, no side effects.
    """
    new = []
    changed = []
    for product in products:
        product_id = str(product["id"])
        existing = existing_by_id.get(product_id)
        if existing is None:
            new.append(product)
            continue

        changes = {}
        if str(product["name"]) != existing["Producto"]:
            changes["Producto"] = (existing["Producto"], str(product["name"]))
        if str(product["price"]) != existing["Precio"]:
            changes["Precio"] = (existing["Precio"], str(product["price"]))
        if str(product["image"]) != existing["Imagen"]:
            changes["Imagen"] = (existing["Imagen"], str(product["image"]))

        if changes:
            changed.append({"product": product, "row": existing["row"], "changes": changes})

    return new, changed
