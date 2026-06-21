"""Application configuration.

Settings come from three layers, in increasing priority:

1. Hard-coded defaults below.
2. Environment variables (loaded from a ``.env`` file when present).
3. Values saved by the user in the Settings page (stored in SQLite).

``config`` never imports ``database`` so it stays dependency-free and easy to
test. The Settings page reads/writes the persisted layer through ``memory``.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXPORTS_DIR = PROJECT_ROOT / "exports"
SAMPLE_DIR = PROJECT_ROOT / "sample_data"
DB_PATH = DATA_DIR / "recovery_desk.db"

for _d in (DATA_DIR, EXPORTS_DIR, SAMPLE_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _load_dotenv() -> None:
    """Minimal .env loader so we do not require python-dotenv at runtime."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Do not clobber variables already present in the real environment.
            os.environ.setdefault(key, value)
    except OSError:
        # A missing or unreadable .env file is never fatal.
        pass


_load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    """Runtime configuration for the whole application."""

    company_name: str = "Your Company"
    message_signature: str = "Best regards,\nThe Accounts Team"
    default_currency: str = "USD"
    currency_symbol: str = "$"

    # Money above this needs human approval before any firm action.
    high_value_threshold: float = field(
        default_factory=lambda: _env_float("HIGH_VALUE_THRESHOLD", 5000.0)
    )

    # Daily scheduled analysis time, 24h "HH:MM".
    daily_analysis_time: str = field(
        default_factory=lambda: os.environ.get("DAILY_ANALYSIS_TIME", "08:00")
    )

    # Default follow-up cadence in days, per record type / stage.
    invoice_follow_up_days: int = 5
    quote_follow_up_days: int = 4
    lead_follow_up_days: int = 3

    # AI is optional. The app must work fully with this disabled.
    # Provider: "gemini" (free tier, default) or "anthropic" (paid).
    ai_enabled: bool = field(default_factory=lambda: _env_bool("AI_ENABLED", False))
    ai_provider: str = field(
        default_factory=lambda: os.environ.get("AI_PROVIDER", "gemini").strip().lower()
    )
    ai_model: str = field(
        default_factory=lambda: os.environ.get("AI_MODEL", "")
    )

    # Email drafting is optional. When enabled, approving an item saves a
    # draft (never sends) into the account's Drafts folder over IMAP.
    email_draft_enabled: bool = field(
        default_factory=lambda: _env_bool("EMAIL_DRAFT_ENABLED", False)
    )

    # Per-tenant email credentials, set at runtime from the tenant's own
    # encrypted database row (memory.load_email_credentials) — NOT from env.
    # In single-user/local mode these stay empty and the env vars below are
    # used instead, preserving the original local-dev workflow.
    email_address_override: str = ""
    email_app_password_override: str = ""

    def follow_up_intervals(self) -> Dict[str, int]:
        return {
            "invoice": self.invoice_follow_up_days,
            "quote": self.quote_follow_up_days,
            "lead": self.lead_follow_up_days,
        }

    @property
    def ai_api_key(self) -> Optional[str]:
        """Read the API key from the environment only — never persisted.

        Provider-specific env vars take priority; AI_API_KEY works for either.
        """
        if self.ai_provider == "gemini":
            return os.environ.get("GEMINI_API_KEY") or os.environ.get("AI_API_KEY")
        return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("AI_API_KEY")

    @property
    def ai_model_resolved(self) -> str:
        """The model id to use, falling back to a sensible per-provider default.

        Guards against a model id left over from the *other* provider (e.g. a
        persisted "claude-..." while the provider is now "gemini"): a mismatched
        id is ignored in favour of the provider default, so switching providers
        never silently sends an incompatible model name to the API.
        """
        default = "gemini-2.5-flash-lite" if self.ai_provider == "gemini" else "claude-opus-4-8"
        model = (self.ai_model or "").strip()
        if not model:
            return default
        is_gemini_model = model.lower().startswith("gemini")
        if self.ai_provider == "gemini" and not is_gemini_model:
            return default
        if self.ai_provider != "gemini" and is_gemini_model:
            return default
        return model

    @property
    def ai_active(self) -> bool:
        """AI is usable only when enabled *and* a key is present."""
        return bool(self.ai_enabled and self.ai_api_key)

    # Email credentials: ALWAYS per-tenant, never fall back to env vars. The
    # env-var fallback was a legacy single-user convenience, but in multi-tenant
    # SaaS mode it leaks the operator's personal Gmail into every signup's
    # Settings UI, which is both confusing ("why is this someone else's email?")
    # and a privacy footgun. Local dev: sign up a tenant once, save creds in UI.
    @property
    def email_address(self) -> Optional[str]:
        return self.email_address_override or None

    @property
    def email_app_password(self) -> Optional[str]:
        return self.email_app_password_override or None

    @property
    def email_imap_host(self) -> str:
        return os.environ.get("EMAIL_IMAP_HOST", "imap.gmail.com")

    @property
    def email_imap_port(self) -> int:
        try:
            return int(os.environ.get("EMAIL_IMAP_PORT", "993"))
        except ValueError:
            return 993

    @property
    def email_drafts_folder(self) -> str:
        return os.environ.get("EMAIL_DRAFTS_FOLDER", "[Gmail]/Drafts")

    @property
    def email_draft_active(self) -> bool:
        """Email drafting is usable only when enabled *and* credentials are present."""
        return bool(
            self.email_draft_enabled and self.email_address and self.email_app_password
        )

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Settings":
        """Build settings from a stored dict, ignoring unknown keys."""
        valid = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in (data or {}).items() if k in valid}
        return cls(**clean)  # type: ignore[arg-type]


# A module-level default used when no persisted settings exist yet.
DEFAULT_SETTINGS = Settings()
