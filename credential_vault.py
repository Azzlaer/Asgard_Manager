from __future__ import annotations

import os
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from common import APP_DATA_DIR


KEY_FILE = APP_DATA_DIR / "remote_credentials.key"
_KEY_LOCK = threading.Lock()


def _fernet() -> Fernet:
    with _KEY_LOCK:
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not KEY_FILE.exists():
            try:
                fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(Fernet.generate_key())
        return Fernet(KEY_FILE.read_bytes().strip())


def encrypt_text(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError):
        return ""
