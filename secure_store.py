"""
Self-Whisper Secure Credential Store.

Keeps the Google AI Studio API key in Windows Credential Manager (via the
`keyring` package) instead of plain text in config.json.

Behavior:
- available() -> True when keyring is installed and has a working backend.
- get_api_key() -> keyring value, else "" (caller falls back to legacy config).
- set_api_key(value) -> stores in keyring; empty value deletes the entry.
  Returns True on success, False when keyring is unavailable/broken (caller
  should then fall back to config file storage and tell the user).
- migrate_from_config(value) -> one-time move of a plain-text key into the
  vault; returns True if the vault now holds it.
"""

SERVICE_NAME = "Self-Whisper"
ACCOUNT_NAME = "gemini-api-key"

try:
    import keyring as _keyring
    import keyring.errors as _keyring_errors
except Exception:  # keyring not installed -> file fallback
    _keyring = None
    _keyring_errors = None


def available() -> bool:
    if _keyring is None:
        return False
    try:
        backend = _keyring.get_keyring()
        # The fail backend means "no usable vault on this machine".
        name = type(backend).__name__.lower()
        if "fail" in name or "null" in name:
            return False
        return True
    except Exception:
        return False


def get_api_key() -> str:
    if not available():
        return ""
    try:
        value = _keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)
        return (value or "").strip()
    except Exception:
        return ""


def set_api_key(value: str) -> bool:
    """Stores (or deletes, if empty) the key. True = vault now authoritative."""
    if not available():
        return False
    try:
        value = (value or "").strip()
        if value:
            _keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, value)
        else:
            try:
                _keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
            except Exception:
                pass
        return True
    except Exception:
        return False


def migrate_from_config(value: str) -> bool:
    """Moves a legacy plain-text key into the vault. Returns success."""
    value = (value or "").strip()
    if not value or not available():
        return False
    if get_api_key():
        return True  # vault already has one; keep it
    return set_api_key(value)
