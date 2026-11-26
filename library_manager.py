from __future__ import annotations

import shutil
import time
import zipfile
from pathlib import Path

from common import MOD_LIBRARY_ROOT, CONFIG_LIBRARY_ROOT, APP_DATA_DIR


KINDS = {
    "mods": MOD_LIBRARY_ROOT,
    "configs": CONFIG_LIBRARY_ROOT,
}


def _root(kind: str) -> Path:
    if kind not in KINDS:
        raise ValueError("Biblioteca inválida")
    return KINDS[kind]


def _safe_relative(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if target != root.resolve() and root.resolve() not in target.parents:
        raise ValueError("Ruta fuera de la biblioteca")
    return target


def list_entries(kind: str, relative: str = "") -> dict:
    root = _root(kind)
    folder = _safe_relative(root, relative)
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for item in sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        entries.append({
            "name": item.name,
            "relative_path": str(item.relative_to(root)),
            "is_dir": item.is_dir(),
            "size": item.stat().st_size if item.is_file() else 0,
        })
    parent = ""
    if folder != root:
        parent = str(folder.parent.relative_to(root))
    return {"kind": kind, "path": relative, "parent": parent, "entries": entries}


def create_folder(kind: str, parent: str, name: str) -> dict:
    clean = name.strip()
    if not clean or clean in {".", ".."} or any(c in clean for c in '<>:"/\\|?*'):
        raise ValueError("Nombre de carpeta inválido")
    target = _safe_relative(_root(kind), str(Path(parent) / clean))
    target.mkdir(parents=True, exist_ok=False)
    return {"relative_path": str(target.relative_to(_root(kind)))}


def import_item(kind: str, folder: str, source_path: str) -> dict:
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(source)
    destination_folder = _safe_relative(_root(kind), folder)
    destination_folder.mkdir(parents=True, exist_ok=True)
    destination = destination_folder / source.name
    if destination.exists():
        stamp = time.strftime("%Y%m%d_%H%M%S")
        destination = destination_folder / f"{source.stem}_{stamp}{source.suffix}"
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
    return {"relative_path": str(destination.relative_to(_root(kind)))}


def delete_item(kind: str, relative: str) -> None:
    target = _safe_relative(_root(kind), relative)
    if target == _root(kind):
        raise ValueError("No se puede eliminar la raíz")
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()


def _backup_bep(server: dict) -> Path:
    server_root = Path(server["executable"]).resolve().parent
    bep = server_root / "BepInEx"
    backup_root = APP_DATA_DIR / "library_apply_backups" / str(server["id"])
    backup_root.mkdir(parents=True, exist_ok=True)
    archive = backup_root / f"BepInEx_{time.strftime('%Y%m%d_%H%M%S')}.zip"
    if bep.is_dir():
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in bep.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(server_root))
    return archive


def _copy_content(source: Path, destination: Path) -> list[str]:
    installed = []
    destination.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        target = destination / source.name
        shutil.copy2(source, target)
        installed.append(str(target))
        return installed
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
        installed.append(str(target))
    return installed


def apply_item(server: dict, kind: str, relative: str) -> dict:
    source = _safe_relative(_root(kind), relative)
    if not source.exists():
        raise FileNotFoundError(source)
    server_root = Path(server["executable"]).resolve().parent
    bep = server_root / "BepInEx"
    backup = _backup_bep(server)

    installed = []
    if kind == "mods":
        plugins = bep / "plugins"
        if source.is_file() and source.suffix.lower() == ".zip":
            staging = APP_DATA_DIR / ".library_staging"
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True)
            try:
                with zipfile.ZipFile(source, "r") as zf:
                    zf.extractall(staging)
                bep_inside = next((x for x in staging.rglob("BepInEx") if x.is_dir()), None)
                base = bep_inside or staging
                for sub in ("plugins", "config", "patchers"):
                    src = base / sub
                    if src.exists():
                        installed.extend(_copy_content(src, bep / sub))
                if not installed:
                    for dll in staging.rglob("*.dll"):
                        plugins.mkdir(parents=True, exist_ok=True)
                        target = plugins / dll.name
                        shutil.copy2(dll, target)
                        installed.append(str(target))
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        else:
            installed = _copy_content(source, plugins)
    else:
        config = bep / "config"
        if source.is_file() and source.suffix.lower() == ".zip":
            staging = APP_DATA_DIR / ".config_staging"
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True)
            try:
                with zipfile.ZipFile(source, "r") as zf:
                    zf.extractall(staging)
                config_inside = next((x for x in staging.rglob("config") if x.is_dir()), None)
                installed = _copy_content(config_inside or staging, config)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        else:
            installed = _copy_content(source, config)

    return {"backup": str(backup), "installed": installed}
