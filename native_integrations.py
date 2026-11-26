from __future__ import annotations

import re
import shutil
import time
from pathlib import Path


def _config_root(server: dict) -> Path:
    return Path(server["executable"]).resolve().parent / "BepInEx" / "config"


def _find_files(server: dict, keywords: list[str]) -> list[Path]:
    root = _config_root(server)
    if not root.is_dir():
        return []
    found = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".cfg", ".ini", ".json", ".yml", ".yaml"}:
            lowered = str(path.relative_to(root)).lower()
            if any(keyword.lower() in lowered for keyword in keywords):
                found.append(path)
    return sorted(found)


def find_discord_connector_files(server: dict) -> list[dict]:
    return [
        {"name": p.name, "path": str(p), "relative_path": str(p.relative_to(_config_root(server)))}
        for p in _find_files(server, ["discordconnector", "discord_connector", "discord"])
    ]


def find_azu_anticheat_files(server: dict) -> list[dict]:
    return [
        {"name": p.name, "path": str(p), "relative_path": str(p.relative_to(_config_root(server)))}
        for p in _find_files(server, ["azuanticheat", "azu_anticheat", "anticheat", "webhook"])
    ]


def read_integration_file(path: str) -> str:
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(target)
    return target.read_text(encoding="utf-8", errors="replace")


def save_integration_file(path: str, content: str) -> dict:
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(target)
    backup_dir = target.parent / ".asgard_integrations_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{target.name}.{time.strftime('%Y%m%d_%H%M%S')}.bak"
    shutil.copy2(target, backup)
    target.write_text(content, encoding="utf-8")
    return {"path": str(target), "backup": str(backup)}


def extract_webhook_like_entries(content: str) -> list[dict]:
    entries = []
    section = ""
    for line_no, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            continue
        if "=" not in line or stripped.startswith("#"):
            continue
        key, value = line.split("=", 1)
        if any(term in key.lower() for term in ("webhook", "url", "event", "enabled", "token")):
            entries.append({
                "line": line_no,
                "section": section,
                "key": key.strip(),
                "value": value.strip(),
            })
    return entries
