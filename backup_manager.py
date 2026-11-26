from __future__ import annotations

import shutil
import time
import zipfile
from pathlib import Path
from typing import Callable

from common import BACKUP_ROOT


class BackupManager:
    def __init__(self, event_callback: Callable[[int, str, str], None]):
        self._event_callback = event_callback
        BACKUP_ROOT.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_name(value: str) -> str:
        return "".join(c if c.isalnum() or c in "-_ " else "_" for c in value).strip()

    def create_backup(self, server: dict, reason: str) -> dict:
        server_id = int(server["id"])
        source = Path(server["savedir"])
        if not source.is_dir():
            raise FileNotFoundError(f"No existe savedir: {source}")

        destination = Path(server["backup_directory"]) if server["backup_directory"] else BACKUP_ROOT / self._safe_name(server["name"])
        destination.mkdir(parents=True, exist_ok=True)

        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{self._safe_name(server['name'])}_{stamp}_{self._safe_name(reason)}.zip"
        archive = destination / filename

        self._event_callback(server_id, "INFO", f"Creando backup: {archive.name}")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in source.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(source))

        self.apply_retention(server)
        return {
            "path": str(archive),
            "size_bytes": archive.stat().st_size,
            "reason": reason,
        }

    def apply_retention(self, server: dict) -> None:
        retention = max(1, int(server["backup_retention"]))
        destination = Path(server["backup_directory"]) if server["backup_directory"] else BACKUP_ROOT / self._safe_name(server["name"])
        if not destination.is_dir():
            return
        backups = sorted(destination.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[retention:]:
            try:
                old.unlink()
            except OSError:
                pass

    def restore_backup(self, server: dict, backup_path: str) -> None:
        server_id = int(server["id"])
        source = Path(backup_path)
        target = Path(server["savedir"])
        if not source.is_file():
            raise FileNotFoundError(f"No existe el backup: {source}")

        target.mkdir(parents=True, exist_ok=True)
        safety = self.create_backup(server, "antes_restaurar")
        self._event_callback(server_id, "INFO", f"Backup preventivo: {safety['path']}")

        for child in target.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

        with zipfile.ZipFile(source, "r") as zf:
            zf.extractall(target)

        self._event_callback(server_id, "INFO", f"Backup restaurado: {source.name}")
