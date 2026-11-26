from __future__ import annotations

import shutil
import time
import zipfile
from pathlib import Path


CONFIG_EXTENSIONS = {".cfg", ".ini", ".json", ".yml", ".yaml", ".toml"}


def server_root(server: dict) -> Path:
    return Path(server["executable"]).resolve().parent


def bep_root(server: dict) -> Path:
    return server_root(server) / "BepInEx"


def _safe_config_path(server: dict, relative_path: str) -> tuple[Path, Path]:
    root = (bep_root(server) / "config").resolve()
    path = (root / relative_path).resolve()
    if root not in path.parents:
        raise ValueError("Ruta fuera de BepInEx/config")
    return root, path


def list_configs(server: dict) -> list[dict]:
    root = bep_root(server) / "config"
    if not root.is_dir():
        return []
    result = []
    for path in sorted(root.rglob("*")):
        if ".asgard_backups" in path.parts:
            continue
        if path.is_file() and path.suffix.lower() in CONFIG_EXTENSIONS:
            result.append({
                "name": path.name,
                "relative_path": str(path.relative_to(root)),
                "size": path.stat().st_size,
                "modified": path.stat().st_mtime,
            })
    return result


def read_config(server: dict, relative_path: str) -> str:
    _, path = _safe_config_path(server, relative_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8", errors="replace")


def _backup_config(root: Path, path: Path, action: str) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = root / ".asgard_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    safe_rel = "__".join(path.relative_to(root).parts)
    backup = backup_dir / f"{safe_rel}.{stamp}.{action}.bak"
    shutil.copy2(path, backup)
    return backup


def save_config(server: dict, relative_path: str, content: str) -> dict:
    root, path = _safe_config_path(server, relative_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    backup = _backup_config(root, path, "save")
    path.write_text(content, encoding="utf-8")
    return {"backup": str(backup), "path": str(path)}


def delete_config(server: dict, relative_path: str) -> dict:
    """Elimina una configuración seleccionada conservando un backup recuperable."""
    root, path = _safe_config_path(server, relative_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() not in CONFIG_EXTENSIONS:
        raise ValueError("El archivo no es una configuración compatible")
    backup = _backup_config(root, path, "delete")
    path.unlink()
    # Limpia únicamente carpetas vacías dentro de config.
    parent = path.parent
    while parent != root:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent
    return {"ok": True, "deleted": str(path), "backup": str(backup)}


def _mod_entries(folder: Path, enabled: bool) -> list[dict]:
    if not folder.is_dir():
        return []
    result = []
    for path in sorted(folder.iterdir()):
        if path.name.startswith("."):
            continue
        dll_count = 1 if path.is_file() and path.suffix.lower() == ".dll" else 0
        if path.is_dir():
            dll_count = len(list(path.rglob("*.dll")))
        if dll_count:
            result.append({
                "name": path.name,
                "path": str(path),
                "enabled": enabled,
                "dll_count": dll_count,
                "type": "folder" if path.is_dir() else "dll",
            })
    return result


def list_mods(server: dict) -> list[dict]:
    bep = bep_root(server)
    return _mod_entries(bep / "plugins", True) + _mod_entries(bep / "disabled_plugins", False)


def set_mod_enabled(server: dict, item_name: str, enabled: bool) -> dict:
    bep = bep_root(server)
    plugins = bep / "plugins"
    disabled = bep / "disabled_plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    disabled.mkdir(parents=True, exist_ok=True)
    source_dir = disabled if enabled else plugins
    dest_dir = plugins if enabled else disabled
    source = source_dir / item_name
    if not source.exists():
        raise FileNotFoundError(source)
    destination = dest_dir / item_name
    if destination.exists():
        raise FileExistsError(destination)
    shutil.move(str(source), str(destination))
    return {"path": str(destination), "enabled": enabled}


def install_mod(server: dict, source_path: str) -> dict:
    source = Path(source_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    bep = bep_root(server)
    plugins = bep / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)

    if source.suffix.lower() == ".dll":
        destination = plugins / source.name
        shutil.copy2(source, destination)
        return {"installed": [str(destination)]}

    if source.suffix.lower() != ".zip":
        raise ValueError("Solo se permiten DLL o ZIP")

    staging = bep / ".asgard_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    installed = []
    try:
        with zipfile.ZipFile(source, "r") as zf:
            zf.extractall(staging)
        bep_inside = next((p for p in staging.rglob("BepInEx") if p.is_dir()), None)
        base = bep_inside if bep_inside else staging
        for sub in ("plugins", "config", "patchers"):
            src = base / sub
            if src.is_dir():
                dst = bep / sub
                dst.mkdir(parents=True, exist_ok=True)
                for item in src.iterdir():
                    target = dst / item.name
                    if item.is_dir():
                        shutil.copytree(item, target, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, target)
                    installed.append(str(target))
        if not installed:
            for dll in staging.rglob("*.dll"):
                target = plugins / dll.name
                shutil.copy2(dll, target)
                installed.append(str(target))
        return {"installed": installed}
    finally:
        shutil.rmtree(staging, ignore_errors=True)
