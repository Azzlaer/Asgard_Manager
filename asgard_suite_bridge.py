from __future__ import annotations
import json, secrets, time
from database import connect


def get_settings(server_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM mod_bridge_settings WHERE server_id=?", (server_id,)).fetchone()
        if not row:
            token = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO mod_bridge_settings(server_id,enabled,api_token,mode) VALUES(?,1,?,'observe')", (server_id, token))
            row = conn.execute("SELECT * FROM mod_bridge_settings WHERE server_id=?", (server_id,)).fetchone()
    return dict(row)


def save_settings(server_id: int, data: dict) -> dict:
    current = get_settings(server_id)
    token = str(data.get("api_token") or current["api_token"]).strip()
    mode = str(data.get("mode") or current["mode"]).strip().lower()
    if mode not in {"observe", "manual", "automatic"}:
        raise ValueError("Modo inválido")
    with connect() as conn:
        conn.execute("""
            INSERT INTO mod_bridge_settings(server_id,enabled,api_token,mode,updated_at)
            VALUES(?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(server_id) DO UPDATE SET enabled=excluded.enabled,api_token=excluded.api_token,mode=excluded.mode,updated_at=CURRENT_TIMESTAMP
        """, (server_id, int(bool(data.get("enabled", current["enabled"]))), token, mode))
    return get_settings(server_id)


def authorized(server_id: int, token: str) -> bool:
    if not token:
        return False
    with connect() as conn:
        settings = conn.execute("SELECT enabled, api_token FROM mod_bridge_settings WHERE server_id=?", (server_id,)).fetchone()
    return bool(settings and settings["enabled"] and settings["api_token"]) and secrets.compare_digest(str(settings["api_token"]).encode("utf-8"), str(token).encode("utf-8"))


def ingest_audit(server_id: int, data: dict) -> dict:
    with connect() as conn:
        cur = conn.execute("""
            INSERT INTO audit_events(server_id,event_type,severity,player_name,platform_id,prefab,position_json,evidence_json,created_unix)
            VALUES(?,?,?,?,?,?,?,?,?)
        """, (
            server_id,
            str(data.get("event_type", "unknown"))[:80],
            int(data.get("severity", 0)),
            str(data.get("player_name", ""))[:120],
            str(data.get("platform_id", ""))[:160],
            str(data.get("prefab", ""))[:160],
            json.dumps(data.get("position") or {}, ensure_ascii=False),
            json.dumps(data.get("evidence") or {}, ensure_ascii=False),
            float(data.get("created_unix") or time.time()),
        ))
        event_id = int(cur.lastrowid)
    return {"ok": True, "event_id": event_id}


def list_audit(server_id: int, limit: int = 300) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM audit_events WHERE server_id=? ORDER BY id DESC LIMIT ?", (server_id, max(1,min(limit,2000)))).fetchall()
    return [dict(r) for r in rows]


def queue_punishment(server_id: int, data: dict) -> dict:
    with connect() as conn:
        cur = conn.execute("""
            INSERT INTO punishments(server_id,platform_id,player_name,reason,severity,avatar_mode,status,requested_unix)
            VALUES(?,?,?,?,?,?,?,?)
        """, (
            server_id,
            str(data.get("platform_id", ""))[:160],
            str(data.get("player_name", ""))[:120],
            str(data.get("reason", "Regla crítica"))[:500],
            int(data.get("severity", 100)),
            str(data.get("avatar_mode", "vanilla"))[:32],
            "PENDING",
            time.time(),
        ))
        punishment_id = int(cur.lastrowid)
    return {"ok": True, "punishment_id": punishment_id}


def list_punishments(server_id: int, limit: int = 200) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM punishments WHERE server_id=? ORDER BY id DESC LIMIT ?", (server_id, max(1,min(limit,1000)))).fetchall()
    return [dict(r) for r in rows]
