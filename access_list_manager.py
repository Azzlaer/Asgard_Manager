from __future__ import annotations
from pathlib import Path


FILES = {
    "banned": "bannedlist.txt",
    "permitted": "permittedlist.txt",
    "admin": "adminlist.txt",
}


def _path(server: dict, kind: str) -> Path:
    if kind not in FILES:
        raise ValueError("Lista no válida")
    raw_savedir = str(server.get("savedir", "")).strip()
    if not raw_savedir:
        raise RuntimeError("Configura savedir antes de administrar las listas")
    savedir = Path(raw_savedir)
    savedir.mkdir(parents=True, exist_ok=True)
    return savedir / FILES[kind]


def read_list(server: dict, kind: str) -> list[str]:
    path = _path(server, kind)
    if not path.exists():
        return []
    return [
        line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def add_to_list(server: dict, kind: str, platform_id: str) -> list[str]:
    value = platform_id.strip()
    if not value:
        raise ValueError("ID vacío")
    values = read_list(server, kind)
    if value not in values:
        values.append(value)
    _path(server, kind).write_text("\n".join(values) + "\n", encoding="utf-8")
    return values


def remove_from_list(server: dict, kind: str, platform_id: str) -> list[str]:
    value = platform_id.strip()
    values = [item for item in read_list(server, kind) if item != value]
    _path(server, kind).write_text(("\n".join(values) + "\n") if values else "", encoding="utf-8")
    return values
