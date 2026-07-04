import smtplib
from email.message import EmailMessage

# Bound the SMTP connection so a hung mail server can't freeze a cron run
# indefinitely (which, under flock, would also stall every later run).
SMTP_TIMEOUT_SECONDS = 30


def send_new_products_notification(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_app_password: str,
    notify_to: str,
    new_products: list,
) -> None:
    """Send a summary email listing the products just synced to the sheet.

    Caller decides whether to invoke this at all (the "zero new products ->
    stay silent" rule lives in the orchestrator, not here).
    """
    message = EmailMessage()
    message["Subject"] = _build_subject(len(new_products))
    message["From"] = smtp_user
    message["To"] = notify_to
    message.set_content(_build_body(new_products))

    with smtplib.SMTP(smtp_host, smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as server:
        server.starttls()
        server.login(smtp_user, smtp_app_password)
        server.send_message(message)


def _count_phrase(count: int) -> str:
    """Return a naturally pluralized Spanish noun phrase, e.g. '1 producto nuevo'."""
    if count == 1:
        return "1 producto nuevo"
    return f"{count} productos nuevos"


def _build_subject(count: int) -> str:
    """Build the email subject, agreeing in number (the demo syncs one product)."""
    synced_word = "sincronizado" if count == 1 else "sincronizados"
    return f"[PYTHON] {_count_phrase(count)} {synced_word}"


def _build_body(new_products: list) -> str:
    count = len(new_products)
    verb_phrase = "quedó agregado" if count == 1 else "quedaron agregados"

    lines = [
        "Hola,",
        "",
        f"La sincronización con WooCommerce encontró {_count_phrase(count)} y {verb_phrase} a la planilla:",
        "",
    ]
    for product in new_products:
        price_suffix = f" (${product['price']})" if product["price"] else ""
        lines.append(f"- {product['name']}{price_suffix}")
    lines.append("")
    lines.append("Se puede revisar el detalle completo en la planilla de Google Sheets.")
    lines.append("")
    lines.append("Este correo se generó automáticamente durante la sincronización periódica.")
    return "\n".join(lines)
