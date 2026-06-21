"""App-level transactional email (SMTP).

Unlike the per-tenant IMAP draft-saving in ``email_draft`` (which only *saves*
drafts and runs after login), this module actually *sends* a message and is used
**before** login — e.g. the password-reset code. Its credentials are therefore
read from app-level environment variables, not from any tenant's settings:

    RRD_SMTP_HOST       e.g. smtp.gmail.com
    RRD_SMTP_PORT       default 587
    RRD_SMTP_USER       the SMTP login (usually the sender address)
    RRD_SMTP_PASSWORD   SMTP password / app password
    RRD_SMTP_FROM       From address (defaults to RRD_SMTP_USER)
    RRD_SMTP_STARTTLS   "true" (default) — STARTTLS on the default port
    RRD_SMTP_SSL        "false" (default) — set true for implicit SSL (port 465)
    RRD_APP_NAME        display name used in the From header (default below)

If SMTP isn't configured the app still runs; reset just reports that email
delivery is unavailable instead of crashing.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Tuple

APP_NAME = os.environ.get("RRD_APP_NAME", "Revenue Recovery Desk")


def _cfg() -> dict:
    host = os.environ.get("RRD_SMTP_HOST", "").strip()
    user = os.environ.get("RRD_SMTP_USER", "").strip()
    password = os.environ.get("RRD_SMTP_PASSWORD", "")
    try:
        port = int(os.environ.get("RRD_SMTP_PORT", "587"))
    except ValueError:
        port = 587
    from_addr = os.environ.get("RRD_SMTP_FROM", "").strip() or user
    use_ssl = os.environ.get("RRD_SMTP_SSL", "false").strip().lower() in {"1", "true", "yes", "on"}
    starttls = os.environ.get("RRD_SMTP_STARTTLS", "true").strip().lower() in {"1", "true", "yes", "on"}
    return {"host": host, "port": port, "user": user, "password": password,
            "from": from_addr, "ssl": use_ssl, "starttls": starttls}


def smtp_configured() -> bool:
    """True when the minimum SMTP settings are present to send mail."""
    c = _cfg()
    return bool(c["host"] and c["user"] and c["password"] and c["from"])


def send_email(to_addr: str, subject: str, body: str) -> Tuple[bool, str]:
    """Send a plain-text email. Returns ``(ok, reason)`` — never raises."""
    if not smtp_configured():
        return False, "Email sending is not configured on this server."
    to_addr = (to_addr or "").strip()
    if not to_addr:
        return False, "No recipient address."

    c = _cfg()
    msg = EmailMessage()
    msg["From"] = formataddr((APP_NAME, c["from"]))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        # ssl.create_default_context() picks up the OS trust store (truststore is
        # injected at startup in net_bootstrap), so this works behind AV/proxy TLS.
        context = ssl.create_default_context()
        if c["ssl"]:
            with smtplib.SMTP_SSL(c["host"], c["port"], context=context, timeout=20) as s:
                s.login(c["user"], c["password"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(c["host"], c["port"], timeout=20) as s:
                if c["starttls"]:
                    s.starttls(context=context)
                s.login(c["user"], c["password"])
                s.send_message(msg)
        return True, "sent"
    except Exception as exc:  # noqa: BLE001 — surface a friendly reason, never crash
        return False, f"Couldn't send email: {exc}"
