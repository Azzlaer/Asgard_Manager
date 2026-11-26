from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from common import DB_PATH


SCHEMA = r"""
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    executable TEXT NOT NULL,
    parameters TEXT NOT NULL,
    working_directory TEXT NOT NULL,
    savedir TEXT NOT NULL DEFAULT '',
    log_file TEXT NOT NULL DEFAULT '',
    backup_directory TEXT NOT NULL DEFAULT '',
    backup_retention INTEGER NOT NULL DEFAULT 10,
    auto_start INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS runtime (
    server_id INTEGER PRIMARY KEY,
    pid INTEGER,
    status TEXT NOT NULL DEFAULT 'DETENIDO',
    started_at REAL,
    last_error TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE SET NULL
);


CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS discord_settings (
    server_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    text_channel_id TEXT NOT NULL DEFAULT '',
    message_id TEXT NOT NULL DEFAULT '',
    voice_channel_id TEXT NOT NULL DEFAULT '',
    max_players INTEGER NOT NULL DEFAULT 100,
    message_template TEXT NOT NULL DEFAULT '╭─────────── ⚔️ **ASGARD STATUS** ⚔️ ───────────╮\n│ 🏰 **Servidor:** {server_name}\n│ 🟢 **Estado:** {status}\n│ 🔑 **Join Code:** `{join_code}`\n│ 👥 **Jugadores:** **{players}/{max_players}**  ·  {occupancy}%\n│ 🕒 **Actualizado:** <t:{unix_time}:R>\n╰────────────────────────────────────────╯',
    voice_template TEXT NOT NULL DEFAULT 'Jugadores: {players}/{max_players}',
    join_code_regex TEXT NOT NULL DEFAULT '(?i)(?:registered\s+with|with)\s+join\s+code\s+([0-9]{4,10})',
    player_count_regex TEXT NOT NULL DEFAULT '(?i)join\s+code\s+[0-9]{4,10}.*?(?:now|active\s+with)\s+(\d+)\s+player\(s\)',
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS discord_runtime (
    server_id INTEGER PRIMARY KEY,
    join_code TEXT NOT NULL DEFAULT 'Esperando...',
    players INTEGER NOT NULL DEFAULT 0,
    last_update REAL,
    last_error TEXT NOT NULL DEFAULT '',
    steam_ids_json TEXT NOT NULL DEFAULT '[]',
    player_names_json TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS player_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER NOT NULL,
    steam_id TEXT NOT NULL,
    last_name TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    seen_count INTEGER NOT NULL DEFAULT 1,
    UNIQUE(server_id, steam_id),
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS online_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER NOT NULL,
    steam_id TEXT NOT NULL DEFAULT '',
    player_name TEXT NOT NULL DEFAULT '',
    connected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS server_automation (
    server_id INTEGER PRIMARY KEY,
    watchdog_enabled INTEGER NOT NULL DEFAULT 0,
    watchdog_delay INTEGER NOT NULL DEFAULT 15,
    restart_enabled INTEGER NOT NULL DEFAULT 0,
    restart_time TEXT NOT NULL DEFAULT '04:00',
    restart_backup INTEGER NOT NULL DEFAULT 1,
    startup_grace INTEGER NOT NULL DEFAULT 90,
    restart_cooldown INTEGER NOT NULL DEFAULT 300,
    max_restart_attempts INTEGER NOT NULL DEFAULT 3,
    force_kill_on_restart INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS automation_runtime (
    server_id INTEGER PRIMARY KEY,
    last_scheduled_date TEXT NOT NULL DEFAULT '',
    last_action TEXT NOT NULL DEFAULT '',
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    cooldown_until REAL NOT NULL DEFAULT 0,
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);



CREATE TABLE IF NOT EXISTS resource_settings (
    server_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    profile TEXT NOT NULL DEFAULT 'balanced',
    cpu_affinity_json TEXT NOT NULL DEFAULT '[]',
    cpu_limit_percent INTEGER NOT NULL DEFAULT 0,
    priority TEXT NOT NULL DEFAULT 'normal',
    ram_warning_mb INTEGER NOT NULL DEFAULT 0,
    ram_hard_limit_mb INTEGER NOT NULL DEFAULT 0,
    ram_action TEXT NOT NULL DEFAULT 'warn',
    apply_on_start INTEGER NOT NULL DEFAULT 1,
    auto_rebalance INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rcon_settings (
    server_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    host TEXT NOT NULL DEFAULT '127.0.0.1',
    port INTEGER NOT NULL DEFAULT 25575,
    password TEXT NOT NULL DEFAULT '',
    timeout REAL NOT NULL DEFAULT 5.0,
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS remote_hosts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    address TEXT NOT NULL,
    ssh_port INTEGER NOT NULL DEFAULT 22,
    username TEXT NOT NULL,
    auth_type TEXT NOT NULL DEFAULT 'password',
    password_encrypted TEXT NOT NULL DEFAULT '',
    key_path TEXT NOT NULL DEFAULT '',
    agent_port INTEGER NOT NULL DEFAULT 8766,
    api_token_encrypted TEXT NOT NULL DEFAULT '',
    remote_base TEXT NOT NULL DEFAULT 'C:/ASGARDRemote',
    tailscale_ip TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS remote_servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id INTEGER NOT NULL,
    agent_server_id INTEGER,
    name TEXT NOT NULL,
    executable TEXT NOT NULL,
    parameters TEXT NOT NULL DEFAULT '',
    working_directory TEXT NOT NULL DEFAULT '',
    savedir TEXT NOT NULL DEFAULT '',
    log_file TEXT NOT NULL DEFAULT '',
    backup_directory TEXT NOT NULL DEFAULT '',
    backup_retention INTEGER NOT NULL DEFAULT 10,
    auto_start INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(host_id, executable),
    FOREIGN KEY(host_id) REFERENCES remote_hosts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS remote_deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    remote_server_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    library_path TEXT NOT NULL,
    backup_path TEXT NOT NULL DEFAULT '',
    uploaded_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'COMPLETADO',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(remote_server_id) REFERENCES remote_servers(id) ON DELETE CASCADE
);



CREATE TABLE IF NOT EXISTS mod_bridge_settings (
    server_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    api_token TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'observe',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    severity INTEGER NOT NULL DEFAULT 0,
    player_name TEXT NOT NULL DEFAULT '',
    platform_id TEXT NOT NULL DEFAULT '',
    prefab TEXT NOT NULL DEFAULT '',
    position_json TEXT NOT NULL DEFAULT '{}',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_unix REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS punishments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER NOT NULL,
    platform_id TEXT NOT NULL DEFAULT '',
    player_name TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    severity INTEGER NOT NULL DEFAULT 100,
    avatar_mode TEXT NOT NULL DEFAULT 'vanilla',
    status TEXT NOT NULL DEFAULT 'PENDING',
    requested_unix REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    reason TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def initialize() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        # Migraciones incrementales para bases creadas por ASGARD 3.x-5.2.
        _ensure_column(conn, "server_automation", "startup_grace", "INTEGER NOT NULL DEFAULT 90")
        _ensure_column(conn, "server_automation", "restart_cooldown", "INTEGER NOT NULL DEFAULT 300")
        _ensure_column(conn, "server_automation", "max_restart_attempts", "INTEGER NOT NULL DEFAULT 3")
        _ensure_column(conn, "server_automation", "force_kill_on_restart", "INTEGER NOT NULL DEFAULT 1")

        # Migra únicamente la plantilla básica de versiones anteriores.
        old_templates = (
            "🟢 **{server_name}**\n\n"
            "**Estado:** {status}\n"
            "**Join Code:** `{join_code}`\n"
            "**Jugadores:** {players}/{max_players}\n"
            "**Actualizado:** <t:{unix_time}:R>"
        )
        new_template = (
            "╭─────────── ⚔️ **ASGARD STATUS** ⚔️ ───────────╮\n"
            "│ 🏰 **Servidor:** {server_name}\n"
            "│ 🟢 **Estado:** {status}\n"
            "│ 🔑 **Join Code:** `{join_code}`\n"
            "│ 👥 **Jugadores:** **{players}/{max_players}**  ·  {occupancy}%\n"
            "│ 🕒 **Actualizado:** <t:{unix_time}:R>\n"
            "╰────────────────────────────────────────╯"
        )
        conn.execute(
            """
            UPDATE discord_settings
            SET message_template=?
            WHERE message_template=?
            """,
            (new_template, old_templates),
        )


def row_to_dict(row):
    return dict(row) if row is not None else None
