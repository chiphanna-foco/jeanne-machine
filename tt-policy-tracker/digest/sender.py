"""Email sender using Postmark (with SMTP fallback for Phase 0 dev)."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from config import settings

logger = logging.getLogger(__name__)


async def send_via_postmark(to: str, subject: str, html_body: str) -> str | None:
    """Send an email via the Postmark API. Returns the MessageID on success."""
    if not settings.postmark_token:
        logger.warning("No POSTMARK_TOKEN configured — falling back to log-only mode")
        return _log_only(to, subject, html_body)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.postmarkapp.com/email",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": settings.postmark_token,
            },
            json={
                "From": settings.digest_from_email,
                "To": to,
                "Subject": subject,
                "HtmlBody": html_body,
                "MessageStream": "outbound",
            },
        )

        if resp.status_code == 200:
            data = resp.json()
            message_id = data.get("MessageID", "")
            logger.info(f"Email sent to {to} via Postmark (MessageID={message_id})")
            return message_id
        else:
            logger.error(f"Postmark send failed ({resp.status_code}): {resp.text}")
            return None


def send_via_smtp(
    to: str,
    subject: str,
    html_body: str,
    smtp_host: str = "localhost",
    smtp_port: int = 1025,
) -> None:
    """Send via local SMTP (for dev — e.g. Mailpit or MailHog)."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.digest_from_email
    msg["To"] = to
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.sendmail(settings.digest_from_email, [to], msg.as_string())
        logger.info(f"Email sent to {to} via SMTP ({smtp_host}:{smtp_port})")
    except Exception as e:
        logger.error(f"SMTP send failed: {e}")


def _log_only(to: str, subject: str, html_body: str) -> str:
    """Just log the email content when no email provider is configured."""
    logger.info(f"[LOG-ONLY EMAIL] To: {to} | Subject: {subject}")
    logger.info(f"[LOG-ONLY EMAIL] Body length: {len(html_body)} chars")
    # Write to a file so it can be inspected
    filename = f"digest_preview_{to.replace('@', '_at_')}.html"
    with open(filename, "w") as f:
        f.write(html_body)
    logger.info(f"[LOG-ONLY EMAIL] HTML saved to {filename}")
    return "log-only"
