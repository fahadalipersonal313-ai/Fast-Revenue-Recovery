"""Optional email drafting — strictly non-essential and fail-safe.

Design rules enforced here, mirroring ``ai_helper.py``:

* The whole app must work with email drafting disabled or unavailable.
* This module only ever **saves a draft**. It never sends, never uses SMTP,
  and never auto-transmits anything — the human still opens their email
  client and decides what to do with the draft.
* Any failure (no credentials, network error, IMAP rejection) is caught and
  reported back as ``(False, reason)`` so callers can log it and move on —
  it must never crash the approval flow.
"""

from __future__ import annotations

import imaplib
import time
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Optional, Tuple

from .config import Settings


def email_draft_available(settings: Settings) -> bool:
    """True only if email drafting is enabled and credentials are present."""
    return settings.email_draft_active


def _build_message(
    from_addr: str, to_addr: str, subject: str, body: str
) -> EmailMessage:
    msg = EmailMessage()
    msg["Message-ID"] = make_msgid()
    msg["From"] = from_addr
    if to_addr:
        msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


def save_draft(
    settings: Settings, to_addr: str, subject: str, body: str
) -> Tuple[bool, str]:
    """Save a draft message to the user's Drafts folder over IMAP (no sending).

    Returns ``(True, "")`` on success or ``(False, reason)`` on any failure —
    callers must treat the latter as non-fatal.
    """
    if not settings.email_draft_active:
        return False, "Email drafting is disabled or credentials are missing."

    from_addr = settings.email_address or ""
    msg = _build_message(from_addr, to_addr, subject, body)

    try:
        with imaplib.IMAP4_SSL(
            settings.email_imap_host, settings.email_imap_port
        ) as imap:
            imap.login(from_addr, settings.email_app_password)
            # \Draft flag marks it as a draft in clients that honour IMAP flags.
            status, _ = imap.append(
                settings.email_drafts_folder,
                "\\Draft",
                imaplib.Time2Internaldate(time.time()),
                msg.as_bytes(),
            )
            if status != "OK":
                return False, f"IMAP append returned status {status!r}."
            return True, ""
    except Exception as exc:  # noqa: BLE001 - any failure here must stay non-fatal
        return False, str(exc)


def _build_message_with_attachment(
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    attachment_bytes: bytes,
    attachment_filename: str,
    attachment_mime: str,
) -> EmailMessage:
    msg = _build_message(from_addr, to_addr, subject, body)
    maintype, _, subtype = attachment_mime.partition("/")
    if not subtype:
        maintype, subtype = "application", "octet-stream"
    msg.add_attachment(
        attachment_bytes,
        maintype=maintype,
        subtype=subtype,
        filename=attachment_filename,
    )
    return msg


def save_draft_with_attachment(
    settings: Settings,
    to_addr: str,
    subject: str,
    body: str,
    attachment_bytes: bytes,
    attachment_filename: str,
    attachment_mime: str = "application/pdf",
) -> Tuple[bool, str]:
    """Save a draft with a single binary attachment over IMAP.

    Mirrors ``save_draft`` — never sends, returns ``(False, reason)`` on any
    failure. Used by the Invoice Generator page to drop a PDF straight into
    the user's Drafts folder.
    """
    if not settings.email_draft_active:
        return False, "Email drafting is disabled or credentials are missing."
    if not attachment_bytes:
        return False, "Attachment is empty."

    from_addr = settings.email_address or ""
    msg = _build_message_with_attachment(
        from_addr, to_addr, subject, body,
        attachment_bytes, attachment_filename, attachment_mime,
    )

    try:
        with imaplib.IMAP4_SSL(
            settings.email_imap_host, settings.email_imap_port
        ) as imap:
            imap.login(from_addr, settings.email_app_password)
            status, _ = imap.append(
                settings.email_drafts_folder,
                "\\Draft",
                imaplib.Time2Internaldate(time.time()),
                msg.as_bytes(),
            )
            if status != "OK":
                return False, f"IMAP append returned status {status!r}."
            return True, ""
    except Exception as exc:  # noqa: BLE001 - any failure here must stay non-fatal
        return False, str(exc)
