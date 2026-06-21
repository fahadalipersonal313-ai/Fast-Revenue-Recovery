"""Make Python's TLS use the operating-system trust store.

Why this exists: security software that performs HTTPS/SSL scanning (e.g. Avast
"Web/Mail Shield", Kaspersky, corporate proxies) transparently re-signs TLS
traffic with its own root certificate. That root is installed in the *Windows*
certificate store, but Python's bundled ``certifi`` list does not contain it, so
otherwise-valid HTTPS calls (Gemini, the email IMAP server) fail with
``CERTIFICATE_VERIFY_FAILED``.

``truststore`` redirects Python's certificate verification to the OS trust
store, where the scanner's root already lives — fixing the calls without
disabling antivirus or weakening verification (we never skip verification).

This is best-effort: if ``truststore`` is not installed or injection fails, we
silently leave the default behaviour in place so the app still starts.
"""

from __future__ import annotations

_INJECTED = False


def enable_os_trust_store() -> bool:
    """Route TLS verification through the OS trust store. Safe to call repeatedly."""
    global _INJECTED
    if _INJECTED:
        return True
    try:
        import truststore

        truststore.inject_into_ssl()
        _INJECTED = True
        return True
    except Exception:
        return False
