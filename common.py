from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _runtime_directory() -> Path:
    """Return the folder containing the portable application.

    PyInstaller one-file programs extract their Python modules to a temporary
    directory.  Using ``sys.executable`` while frozen keeps Data and Library
    beside the real EXE instead of inside that temporary directory.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = _runtime_directory()
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", APP_DIR))

# Portable layout.  Everything needed to move the manager to another folder is
# kept beside the executable.  The Library is deliberately visible at root.
APP_DATA_DIR = APP_DIR / "Data"
LIBRARY_ROOT = APP_DIR / "Library"
MOD_LIBRARY_ROOT = LIBRARY_ROOT / "Mods"
CONFIG_LIBRARY_ROOT = LIBRARY_ROOT / "Configs"

DB_PATH = APP_DATA_DIR / "asgard_host.db"
BACKUP_ROOT = APP_DATA_DIR / "backups"
SERVICE_LOG_DIR = APP_DATA_DIR / "service_logs"
SERVICE_HOST = "127.0.0.1"
SERVICE_PORT = 8765
SERVICE_URL = f"http://{SERVICE_HOST}:{SERVICE_PORT}"
SERVICE_PID_PATH = APP_DATA_DIR / "host_service.pid"
SERVICE_LOCK_PATH = APP_DATA_DIR / "host_service.lock"
MIGRATION_LOG = APP_DATA_DIR / "portable_migration.log"
REMOTE_PACKAGES_DIR = APP_DIR / "RemoteAgentPackage"
REMOTE_SETUP_DIR = APP_DIR / "RemoteSetup"
REMOTE_DOWNLOADS_DIR = APP_DIR / "RemoteDownloads"


def _merge_missing(source: Path, destination: Path) -> int:
    """Copy only files that do not already exist in the portable destination."""
    if not source.is_dir():
        return 0
    copied = 0
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            copied += 1
    return copied


def _migrate_legacy_data() -> None:
    """Import v5.3 data once without deleting or overwriting the old copy."""
    notes: list[str] = []
    legacy_roots = [
        LOCAL_APPDATA / "AsgardHostManager",
        APP_DIR / "AsgardHostManager",  # Early portable test builds.
    ]

    # Preserve the configured servers, Discord settings and automation rules.
    if not DB_PATH.exists():
        legacy_db_candidates = [APP_DIR / "asgard_host.db"]
        legacy_db_candidates.extend(root / "asgard_host.db" for root in legacy_roots)
        for source in legacy_db_candidates:
            try:
                if source.is_file() and source.resolve() != DB_PATH.resolve():
                    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, DB_PATH)
                    notes.append(f"Base de datos importada desde: {source}")
                    break
            except OSError as exc:
                notes.append(f"No se pudo importar {source}: {exc}")

    # The library is now visible beside the EXE. Merge missing items only.
    for root in legacy_roots:
        source_library = root / "Library"
        try:
            if source_library.is_dir() and source_library.resolve() != LIBRARY_ROOT.resolve():
                copied = _merge_missing(source_library, LIBRARY_ROOT)
                if copied:
                    notes.append(
                        f"Biblioteca importada desde {source_library}: {copied} archivo(s)"
                    )
        except OSError as exc:
            notes.append(f"No se pudo importar la biblioteca {source_library}: {exc}")

    if notes:
        try:
            MIGRATION_LOG.parent.mkdir(parents=True, exist_ok=True)
            with MIGRATION_LOG.open("a", encoding="utf-8") as handle:
                for note in notes:
                    handle.write(note + "\n")
        except OSError:
            pass


for _folder in (
    APP_DATA_DIR,
    BACKUP_ROOT,
    SERVICE_LOG_DIR,
    LIBRARY_ROOT,
    MOD_LIBRARY_ROOT,
    CONFIG_LIBRARY_ROOT,
    REMOTE_PACKAGES_DIR,
    REMOTE_SETUP_DIR,
    REMOTE_DOWNLOADS_DIR,
):
    _folder.mkdir(parents=True, exist_ok=True)

_migrate_legacy_data()
