from __future__ import annotations

import re
import secrets
import shlex
import shutil
import time
from pathlib import Path


def _server_root(server: dict) -> Path:
    return Path(server["executable"]).resolve().parent


def _game_port(parameters: str) -> int:
    try:
        tokens = shlex.split(parameters or "", posix=False)
    except ValueError:
        tokens = (parameters or "").split()
    for index, token in enumerate(tokens[:-1]):
        if token.lower() == "-port":
            try:
                return int(tokens[index + 1].strip('"'))
            except ValueError:
                break
    return 2456


def suggested_settings(server: dict, current: dict | None = None) -> dict:
    current = current or {}
    configured_port = int(current.get("port") or 0)
    defaultish = configured_port in (0, 25575)
    port = _game_port(server.get("parameters", "")) + 2 if defaultish else configured_port
    if not 1 <= port <= 65535:
        raise ValueError(f"Puerto RCON fuera de rango: {port}")
    password = str(current.get("password") or "").strip()
    if not password:
        password = secrets.token_urlsafe(18)
    return {
        "enabled": True,
        "host": "127.0.0.1",
        "port": port,
        "password": password,
        "timeout": float(current.get("timeout", 5.0) or 5.0),
    }


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(path.name + f".asgard_{stamp}.bak")
    shutil.copy2(path, backup)
    return backup


def _set_bepinex_values(path: Path, section: str, values: dict[str, str]) -> None:
    """Actualiza un CFG de BepInEx sin destruir comentarios ni otras secciones."""
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    lines = text.splitlines()
    section_lower = section.strip().lower()
    key_map = {key.lower(): (key, value) for key, value in values.items()}
    found_section = False
    active = False
    replaced: set[str] = set()
    output: list[str] = []

    for line in lines:
        match_section = re.match(r"^\s*\[(.+?)\]\s*$", line)
        if match_section:
            if active:
                for lower, (key, value) in key_map.items():
                    if lower not in replaced:
                        output.append(f"{key} = {value}")
                        replaced.add(lower)
            active = match_section.group(1).strip().lower() == section_lower
            found_section = found_section or active
            output.append(line)
            continue

        if active:
            match_key = re.match(r"^(\s*)([^#;=]+?)(\s*=\s*)(.*)$", line)
            if match_key:
                original_key = match_key.group(2).strip()
                lower = original_key.lower()
                if lower in key_map:
                    _, value = key_map[lower]
                    output.append(f"{match_key.group(1)}{original_key}{match_key.group(3)}{value}")
                    replaced.add(lower)
                    continue
        output.append(line)

    if active:
        for lower, (key, value) in key_map.items():
            if lower not in replaced:
                output.append(f"{key} = {value}")
                replaced.add(lower)

    if not found_section:
        if output and output[-1].strip():
            output.append("")
        output.append(f"[{section}]")
        for key, value in values.items():
            output.append(f"{key} = {value}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _find_plugin(root: Path, patterns: tuple[str, ...]) -> bool:
    plugins = root / "BepInEx" / "plugins"
    if not plugins.is_dir():
        return False
    names = [p.name.lower() for p in plugins.rglob("*.dll")]
    return any(any(pattern in name for pattern in patterns) for name in names)


def configure_rcon_mod(server: dict, current: dict | None = None) -> dict:
    settings = suggested_settings(server, current)
    root = _server_root(server)
    config_root = root / "BepInEx" / "config"
    tristan = config_root / "org.tristan.rcon.cfg"
    avii = config_root / "nl.avii.plugins.rcon.cfg"

    target: Path | None = None
    implementation = ""
    created = False

    if tristan.exists() or _find_plugin(root, ("valheimrcon", "tristan")):
        target = tristan
        implementation = "Tristan ValheimRcon"
        created = not target.exists()
        backup = _backup(target)
        _set_bepinex_values(
            target,
            "1. Rcon",
            {
                "Port": str(settings["port"]),
                "Password": settings["password"],
            },
        )
    elif avii.exists() or _find_plugin(root, ("rcon.dll", "avii")):
        target = avii
        implementation = "AviiNL rcon"
        created = not target.exists()
        backup = _backup(target)
        _set_bepinex_values(
            target,
            "rcon",
            {
                "enabled": "true",
                "port": str(settings["port"]),
                "password": settings["password"],
            },
        )
    else:
        raise RuntimeError(
            "No se encontró org.tristan.rcon.cfg, nl.avii.plugins.rcon.cfg "
            "ni una DLL RCON compatible dentro de BepInEx/plugins. "
            "Instala/inicia el mod RCON una vez y vuelve a usar la configuración automática."
        )

    return {
        "settings": settings,
        "implementation": implementation,
        "config_path": str(target),
        "backup": str(backup) if backup else "",
        "created": created,
        "game_port": _game_port(server.get("parameters", "")),
    }
