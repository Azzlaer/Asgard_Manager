from __future__ import annotations

import os
import shutil
import stat
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path, PureWindowsPath
from typing import Callable

from common import BACKUP_ROOT


def extract_verified(archive: Path, target: Path) -> None:
    """Extract only regular files into a fresh staging directory."""
    with zipfile.ZipFile(archive) as zf:
        entries = zf.infolist()
        if not entries or not any(not e.is_dir() for e in entries):
            raise ValueError("Backup vacío")
        seen = set()
        total = 0
        for entry in entries:
            name = entry.filename.replace(chr(92), "/")
            parts = name.rstrip("/").split("/")
            if any(not p or p in (".", "..") or ":" in p or p.endswith((".", " ")) or PureWindowsPath(p).is_reserved() for p in parts):
                raise ValueError("Ruta insegura en backup")
            key = "/".join(parts).casefold()
            if key in seen or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("Entrada duplicada o enlace en backup")
            seen.add(key)
            total += entry.file_size
        if total > shutil.disk_usage(target).free:
            raise OSError("Espacio insuficiente para restaurar")
        for entry in entries:
            dest = target.joinpath(*entry.filename.replace(chr(92), "/").rstrip("/").split("/"))
            if entry.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(entry) as src, dest.open("xb") as dst:
                    shutil.copyfileobj(src, dst)


class BackupManager:
    def __init__(self, event_callback: Callable[[int, str, str], None], backup_root: Path = BACKUP_ROOT):
        self._event_callback = event_callback
        self._lock = threading.RLock()
        self.backup_root = Path(backup_root)
        self.backup_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_name(value: str) -> str:
        return "".join(c if c.isalnum() or c in "-_ " else "_" for c in value).strip() or "server"

    def _destination(self, server: dict) -> Path:
        return Path(server.get("backup_directory") or self.backup_root / self._safe_name(server["name"])).resolve()

    def create_backup(self, server: dict, reason: str, *, retain: bool = True) -> dict:
        with self._lock:
            if not server.get("savedir"):
                raise ValueError("savedir obligatorio")
            source = Path(server["savedir"]).resolve()
            if not source.is_dir() or source == source.parent:
                raise ValueError("savedir inválido")
            destination = self._destination(server)
            if destination == source or source in destination.parents:
                raise ValueError("Los backups deben estar fuera del mundo")
            destination.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            prefix = f"{int(server['id'])}_{self._safe_name(server['name'])}_"
            archive = destination / f"{prefix}{stamp}_{uuid.uuid4().hex[:12]}_{self._safe_name(reason)}.zip"
            partial = archive.with_suffix(".partial")
            try:
                with zipfile.ZipFile(partial, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                    for path in source.rglob("*"):
                        if path.is_symlink() or (getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
                            raise ValueError("Enlace no permitido en savedir")
                        if path.is_file():
                            zf.write(path, path.relative_to(source))
                with zipfile.ZipFile(partial) as zf:
                    if not zf.namelist() or zf.testzip() is not None:
                        raise ValueError("Backup corrupto")
                os.replace(partial, archive)
            finally:
                partial.unlink(missing_ok=True)
            if retain:
                self.apply_retention(server)
            self._event_callback(int(server["id"]), "INFO", f"Backup verificado: {archive.name}")
            return {"path": str(archive), "size_bytes": archive.stat().st_size, "reason": reason}

    def apply_retention(self, server: dict) -> None:
        with self._lock:
            retention = max(1, int(server["backup_retention"]))
            prefix = f"{int(server['id'])}_{self._safe_name(server['name'])}_"
            backups = sorted(self._destination(server).glob(prefix + "*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in backups[retention:]:
                try:
                    old.unlink()
                except OSError:
                    pass

    def restore_backup(self, server: dict, backup_path: str) -> None:
        with self._lock:
            if not server.get("savedir"):
                raise ValueError("savedir obligatorio")
            source = Path(backup_path).resolve(strict=True)
            target = Path(server["savedir"]).resolve(strict=True)
            if not target.is_dir() or target == target.parent or target in source.parents:
                raise ValueError("Ruta de restauración inválida")
            stage = Path(tempfile.mkdtemp(prefix=".asgard-restore-", dir=target.parent))
            previous = target.parent / (".asgard-previous-" + uuid.uuid4().hex)
            try:
                extract_verified(source, stage)
                safety = self.create_backup(server, "antes_restaurar", retain=False)
                self._event_callback(int(server["id"]), "INFO", f"Backup preventivo: {safety['path']}")
                target.rename(previous)
                try:
                    stage.rename(target)
                except BaseException:
                    previous.rename(target)
                    raise
                # Retain original directory for manual recovery until explicitly removed.
                self._event_callback(int(server["id"]), "INFO", f"Restaurado: {source.name}; mundo anterior: {previous}")
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
