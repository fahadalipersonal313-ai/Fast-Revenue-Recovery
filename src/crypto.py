"""Encryption at rest for per-tenant secrets (email app passwords).

In the single-user/local mode, email credentials lived in `.env`. In SaaS
mode, every client supplies their *own* email credentials, which must be
stored in the database — but never in plain text. This module encrypts them
with a key only the app operator controls (``APP_SECRET_KEY``), never the
client.

If ``APP_SECRET_KEY`` is not set, we fall back to a fixed development key so
the app still runs locally — but `auth.py` warns loudly, because that means
anything encrypted is not actually protected. Production deployments MUST set
``APP_SECRET_KEY`` to a long random value and keep it secret.
"""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache
from typing import Optional

_DEV_FALLBACK_KEY = "insecure-development-key-do-not-use-in-production"


def using_dev_fallback_key() -> bool:
    return not bool(os.environ.get("APP_SECRET_KEY"))


@lru_cache(maxsize=1)
def _fernet():
    from cryptography.fernet import Fernet

    secret = os.environ.get("APP_SECRET_KEY") or _DEV_FALLBACK_KEY
    # Derive a valid 32-byte urlsafe-base64 Fernet key from any secret string.
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> Optional[str]:
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except Exception:
        # Wrong/rotated key, corrupted data, etc. — never crash the app over it.
        return None
