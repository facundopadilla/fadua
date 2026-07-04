import smtplib
from email.message import EmailMessage

# Bound the SMTP connection so a hung mail server can't freeze a cron run
# indefinitely (which, under flock, would also stall every later run).
SMTP_TIMEOUT_SECONDS = 30


def send_sync_notification(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_app_password: str,
    notify_to: str,
    new_products: list,
    changed_products: list,
) -> None:
    """Send a summary email listing the products just added and updated in the sheet.

    Caller decides whether to invoke this at all (the "nothing to report ->
    stay silent" rule lives in the orchestrator, not here).
    """
    message = EmailMessage()
    message["Subject"] = _build_subject(len(new_products), len(changed_products))
    message["From"] = smtp_user
    message["To"] = notify_to
    message.set_content(_build_body(new_products, changed_products))

    with smtplib.SMTP(smtp_host, smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as server:
        server.starttls()
        server.login(smtp_user, smtp_app_password)
        server.send_message(message)


def _pluralize(count: int, singular: str, plural: str) -> str:
    """Return count-prefixed Spanish text, agreeing in number, e.g. '1 producto nuevo'."""
    return f"{count} {singular}" if count == 1 else f"{count} {plural}"


def _build_subject(new_count: int, changed_count: int) -> str:
    """Build the email subject. A side whose count is 0 is never mentioned.

    When both sides are present, the combined form drops the "producto(s)"
    noun and keeps only "nuevo(s)"/"actualizado(s)", e.g.
    "[PYTHON] 2 nuevos, 1 actualizado".
    """
    if new_count and changed_count:
        new_phrase = _pluralize(new_count, "nuevo", "nuevos")
        changed_phrase = _pluralize(changed_count, "actualizado", "actualizados")
        return f"[PYTHON] {new_phrase}, {changed_phrase}"
    if new_count:
        return f"[PYTHON] {_pluralize(new_count, 'producto nuevo', 'productos nuevos')}"
    return f"[PYTHON] {_pluralize(changed_count, 'producto actualizado', 'productos actualizados')}"


def _price_suffix(price: str) -> str:
    """Return ' ($price)', or '' when price is blank (never render empty parens)."""
    return f" (${price})" if price else ""


def _describe_change(entry: dict) -> str:
    """Describe one changed product's field diffs as a single readable line."""
    label = entry["product"]["name"]
    changes = entry["changes"]
    descriptors = []
    if "Producto" in changes:
        old_value, new_value = changes["Producto"]
        descriptors.append(f"Producto {old_value} → {new_value}")
    if "Precio" in changes:
        old_value, new_value = changes["Precio"]
        descriptors.append(f"Precio ${old_value} → ${new_value}")
    if "Imagen" in changes:
        descriptors.append("Imagen actualizada")
    return f"{label}: {', '.join(descriptors)}"


def _build_body(new_products: list, changed_products: list) -> str:
    """Build the email body: up to two sections, only rendered when non-empty."""
    sections = []

    if new_products:
        lines = ["Nuevos:"]
        for product in new_products:
            lines.append(f"- {product['name']}{_price_suffix(product['price'])}")
        sections.append("\n".join(lines))

    if changed_products:
        lines = ["Actualizados:"]
        for entry in changed_products:
            lines.append(f"- {_describe_change(entry)}")
        sections.append("\n".join(lines))

    return "\n\n".join(sections)
