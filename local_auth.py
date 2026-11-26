"""Local control-plane authentication; the game bridge uses separate tokens."""
from __future__ import annotations

import hmac
import os
import secrets
import tempfile
from pathlib import Path

from common import APP_DATA_DIR

TOKEN_FILE = APP_DATA_DIR / "local_api.token"


def load_token() -> str:
    """Publish a complete token atomically without overwriting another process."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TOKEN_FILE.exists():
        fd, name = tempfile.mkstemp(prefix=".api-token-", dir=TOKEN_FILE.parent)
        try:
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                handle.write(secrets.token_urlsafe(48))
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(name, TOKEN_FILE)
            except FileExistsError:
                pass
        finally:
            Path(name).unlink(missing_ok=True)
    token = TOKEN_FILE.read_text(encoding="ascii").strip()
    if len(token) < 43:
        raise RuntimeError("Token local inválido; detén ASGARD y revisa Data/local_api.token")
    return token


def local_headers() -> dict[str, str]:
    return {"X-ASGARD-Local-Token": load_token()}


def authorized(token: str) -> bool:
    return hmac.compare_digest(token.encode("utf-8"), load_token().encode("ascii"))


def is_bridge_ingest(method: str, path: str) -> bool:
    parts = path.split("/")
    return (method == "POST" and len(parts) == 4 and parts[:2] == ["", "asgard-suite"]
            and parts[2].isascii() and parts[2].isdigit()
            and parts[3] in {"audit", "punishments"})
