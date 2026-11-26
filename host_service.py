from __future__ import annotations

import json
import os
import atexit
import logging
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from backup_manager import BackupManager
from common import SERVICE_HOST, SERVICE_LOG_DIR, SERVICE_PORT, SERVICE_PID_PATH, SERVICE_LOCK_PATH
from database import connect, initialize, row_to_dict
from log_reader import tail_file
from process_manager import ProcessManager
from discord_integration import DiscordIntegrationManager
from access_list_manager import read_list, add_to_list, remove_from_list
from automation_manager import AutomationManager
from rcon_client import execute_rcon
from rcon_autoconfig import configure_rcon_mod
from config_mod_manager import (
    list_configs, read_config, save_config, delete_config,
    list_mods, set_mod_enabled, install_mod,
)
from world_modifiers import parse_parameters, apply_modifiers
from metrics_collector import MetricsCollector
from library_manager import list_entries, create_folder, import_item, delete_item, apply_item
from remote_manager import RemoteManager
from resource_control import automatic_policy, host_capacity, normalize_policy
import asgard_suite_bridge
from native_integrations import (
    find_discord_connector_files, find_azu_anticheat_files,
    read_integration_file, save_integration_file, extract_webhook_like_entries,
)


SERVICE_LOG_DIR.mkdir(parents=True, exist_ok=True)


_SERVICE_LOCK_HANDLE = None


def _acquire_single_instance_lock() -> bool:
    """Impide que dos servicios ASGARD ejecuten auto_start al mismo tiempo."""
    global _SERVICE_LOCK_HANDLE
    SERVICE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = open(SERVICE_LOCK_PATH, "a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError):
        handle.close()
        return False
    _SERVICE_LOCK_HANDLE = handle
    return True


def _release_single_instance_lock() -> None:
    global _SERVICE_LOCK_HANDLE
    handle = _SERVICE_LOCK_HANDLE
    _SERVICE_LOCK_HANDLE = None
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except (OSError, IOError):
        pass
    try:
        handle.close()
    except OSError:
        pass


def _write_service_pid() -> None:
    SERVICE_PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    SERVICE_PID_PATH.write_text(str(os.getpid()), encoding="utf-8")


def _remove_service_pid() -> None:
    try:
        if SERVICE_PID_PATH.exists():
            current = SERVICE_PID_PATH.read_text(encoding="utf-8").strip()
            if current == str(os.getpid()):
                SERVICE_PID_PATH.unlink()
    except OSError:
        pass


if not _acquire_single_instance_lock():
    raise SystemExit("Otra instancia del servicio ASGARD ya está activa")
_write_service_pid()
atexit.register(_remove_service_pid)
atexit.register(_release_single_instance_lock)
logging.basicConfig(
    filename=SERVICE_LOG_DIR / "host_service.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def add_event(server_id: int | None, level: str, message: str) -> None:
    logging.info("[%s] %s", server_id, message)
    with connect() as conn:
        conn.execute(
            "INSERT INTO events(server_id, level, message) VALUES (?, ?, ?)",
            (server_id, level, message),
        )


initialize()
process_manager = ProcessManager(add_event)
backup_manager = BackupManager(add_event)
discord_manager = DiscordIntegrationManager(add_event)
remote_manager = RemoteManager(add_event)
automation_manager = None
operation_lock = threading.RLock()




def get_resource_settings(server_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM resource_settings WHERE server_id=?", (server_id,)).fetchone()
    if row is None:
        policy = normalize_policy(None)
        policy["server_id"] = server_id
        return policy
    item = dict(row)
    try:
        item["cpu_affinity"] = json.loads(item.pop("cpu_affinity_json", "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        item["cpu_affinity"] = []
    for key in ("enabled", "apply_on_start", "auto_rebalance"):
        item[key] = bool(item.get(key))
    return normalize_policy(item) | {"server_id": server_id}


def save_resource_settings(server_id: int, data: dict) -> dict:
    policy = normalize_policy(data)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO resource_settings(
                server_id,enabled,profile,cpu_affinity_json,cpu_limit_percent,
                priority,ram_warning_mb,ram_hard_limit_mb,ram_action,
                apply_on_start,auto_rebalance,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(server_id) DO UPDATE SET
                enabled=excluded.enabled,profile=excluded.profile,
                cpu_affinity_json=excluded.cpu_affinity_json,
                cpu_limit_percent=excluded.cpu_limit_percent,
                priority=excluded.priority,ram_warning_mb=excluded.ram_warning_mb,
                ram_hard_limit_mb=excluded.ram_hard_limit_mb,
                ram_action=excluded.ram_action,apply_on_start=excluded.apply_on_start,
                auto_rebalance=excluded.auto_rebalance,updated_at=CURRENT_TIMESTAMP
            """,
            (
                server_id, int(policy["enabled"]), policy["profile"],
                json.dumps(policy["cpu_affinity"]), policy["cpu_limit_percent"],
                policy["priority"], policy["ram_warning_mb"],
                policy["ram_hard_limit_mb"], policy["ram_action"],
                int(policy["apply_on_start"]), int(policy["auto_rebalance"]),
            ),
        )
    return policy | {"server_id": server_id}


def resource_payload(server_id: int) -> dict:
    policy = get_resource_settings(server_id)
    status = process_manager.resource_status(server_id)
    status.update(process_manager.metrics(server_id))
    return {"policy": policy, "host": host_capacity(), "runtime": status}


def autoconfigure_resources(server_id: int, profile: str) -> dict:
    with connect() as conn:
        ids = [int(row["id"]) for row in conn.execute("SELECT id FROM servers ORDER BY id").fetchall()]
    policy = automatic_policy(profile, server_id, ids)
    save_resource_settings(server_id, policy)
    applied = None
    if process_manager.is_alive(server_id):
        applied = process_manager.apply_resources(server_id, policy)
    add_event(server_id, "INFO", f"Perfil de recursos autoconfigurado: {policy['profile']}")
    return {"policy": policy, "host": host_capacity(), "runtime": process_manager.resource_status(server_id), "applied": applied}

def get_rcon_settings(server_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM rcon_settings WHERE server_id=?", (server_id,)).fetchone()
    if row:
        return dict(row)
    return {
        "server_id": server_id, "enabled": 0, "host": "127.0.0.1",
        "port": 25575, "password": "", "timeout": 5.0,
    }

def save_rcon_settings(server_id: int, data: dict) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO rcon_settings(server_id,enabled,host,port,password,timeout)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(server_id) DO UPDATE SET
                enabled=excluded.enabled,host=excluded.host,port=excluded.port,
                password=excluded.password,timeout=excluded.timeout
            """,
            (
                server_id, int(bool(data.get("enabled"))),
                data.get("host","127.0.0.1"), int(data.get("port",25575)),
                data.get("password",""), float(data.get("timeout",5.0)),
            ),
        )

def send_server_command(server_id: int, command: str) -> dict:
    settings = get_rcon_settings(server_id)
    if settings["enabled"]:
        response = execute_rcon(settings, command)
        add_event(server_id, "INFO", f"RCON: {command}")
        return {"transport": "rcon", "response": response}
    process_manager.send_command(server_id, command)
    return {"transport": "console", "response": ""}

def get_server(server_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM servers WHERE id=?", (server_id,)).fetchone()
    if row is None:
        raise KeyError("Servidor no encontrado")
    item = dict(row)
    item["resource_policy"] = get_resource_settings(server_id)
    return item


def update_runtime(server_id: int, status: str, pid=None, started_at=None, last_error="") -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO runtime(server_id, pid, status, started_at, last_error)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                pid=excluded.pid,
                status=excluded.status,
                started_at=excluded.started_at,
                last_error=excluded.last_error
            """,
            (server_id, pid, status, started_at, last_error),
        )


def _runtime_snapshot(server_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM runtime WHERE server_id=?", (server_id,)).fetchone()
    return dict(row) if row else {
        "server_id": server_id,
        "pid": None,
        "status": "DETENIDO",
        "started_at": None,
        "last_error": "",
    }


def _persist_reconciliation(server: dict, state: dict, emit_event: bool = False) -> dict:
    """Persist only state proven by the real process table."""
    sid = int(server["id"])
    previous = _runtime_snapshot(sid)
    duplicates = list(state.get("duplicate_pids") or [])
    if duplicates:
        all_pids = list(state.get("matching_pids") or [])
        message = "Procesos duplicados detectados: " + ", ".join(map(str, all_pids))
        changed = (
            previous.get("status") != "DUPLICADO"
            or int(previous.get("pid") or 0) != int(state.get("pid") or 0)
            or previous.get("last_error") != message
        )
        if changed:
            update_runtime(sid, "DUPLICADO", state.get("pid"), state.get("started_at"), message)
        if emit_event and changed:
            add_event(sid, "ERROR", message)
    elif state.get("alive"):
        changed = (
            previous.get("status") != "EN EJECUCIÓN"
            or int(previous.get("pid") or 0) != int(state.get("pid") or 0)
        )
        if changed:
            update_runtime(sid, "EN EJECUCIÓN", state.get("pid"), state.get("started_at"), "")
        if emit_event and int(previous.get("pid") or 0) != int(state.get("pid") or 0):
            add_event(sid, "INFO", f"Proceso real recuperado automáticamente: PID {state.get('pid')}")
    else:
        was_live = previous.get("status") not in (None, "DETENIDO") or previous.get("pid") is not None
        with connect() as conn:
            discord_row = conn.execute(
                "SELECT join_code,players FROM discord_runtime WHERE server_id=?", (sid,)
            ).fetchone()
        stale_telemetry = bool(
            discord_row
            and (
                int(discord_row["players"] or 0) != 0
                or str(discord_row["join_code"] or "") not in ("", "—", "Esperando...")
            )
        )
        if was_live:
            update_runtime(sid, "DETENIDO", None, None, "")
        if was_live or stale_telemetry:
            discord_manager.mark_offline(sid, sync_discord=False)
        if emit_event and was_live:
            add_event(sid, "WARNING", "El proceso configurado ya no existe; runtime y telemetría limpiados")
    return state


def reconcile_server_process(
    server: dict,
    emit_event: bool = False,
    snapshots: list[dict] | None = None,
    force_refresh: bool = False,
) -> dict:
    sid = int(server["id"])
    previous = _runtime_snapshot(sid)
    server = dict(server)
    server["resource_policy"] = server.get("resource_policy") or get_resource_settings(sid)
    state = process_manager.reconcile(
        server,
        preferred_pid=previous.get("pid"),
        snapshots=snapshots,
        force_refresh=force_refresh,
    )
    return _persist_reconciliation(server, state, emit_event=emit_event)


def recover_runtime() -> None:
    with connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM servers ORDER BY id").fetchall()]
    snapshots = process_manager.all_valheim_processes(force_refresh=True)
    active_ids = []
    for server in rows:
        state = reconcile_server_process(server, emit_event=True, snapshots=snapshots)
        if state.get("alive"):
            active_ids.append(int(server["id"]))
    discord_manager.start_enabled(active_ids)


recover_runtime()


def process_reconciliation_loop() -> None:
    """Repair lost PIDs using one shared process snapshot every six seconds."""
    while True:
        try:
            if operation_lock.acquire(timeout=0.2):
                try:
                    with connect() as conn:
                        rows = [dict(row) for row in conn.execute("SELECT * FROM servers ORDER BY id").fetchall()]
                    snapshots = process_manager.all_valheim_processes(force_refresh=True)
                    for server in rows:
                        state = reconcile_server_process(
                            server,
                            emit_event=True,
                            snapshots=snapshots,
                        )
                        sid = int(server["id"])
                        if state.get("alive") and not state.get("duplicate_pids"):
                            try:
                                discord_manager.start_monitor(sid)
                            except Exception as exc:
                                add_event(sid, "ERROR", f"Monitor Discord: {exc}")
                finally:
                    operation_lock.release()
        except Exception as exc:
            logging.exception("Process reconciliation: %s", exc)
        time.sleep(6)


threading.Thread(target=process_reconciliation_loop, daemon=True).start()


def start_server(server_id: int) -> dict:
    with operation_lock:
        server = get_server(server_id)
        policy = normalize_policy(server.get("resource_policy"))
        if policy.get("enabled") and policy.get("auto_rebalance"):
            with connect() as conn:
                ids = [int(row["id"]) for row in conn.execute("SELECT id FROM servers ORDER BY id").fetchall()]
            policy = automatic_policy(policy.get("profile", "balanced"), server_id, ids)
            save_resource_settings(server_id, policy)
            server["resource_policy"] = policy

        state = reconcile_server_process(server, emit_event=True, force_refresh=True)
        if state.get("duplicate_pids"):
            raise RuntimeError(
                "El servidor tiene procesos duplicados: "
                + ", ".join(map(str, state.get("matching_pids") or []))
                + ". Pulsa Detener para cerrarlos todos y después Iniciar."
            )

        pid = process_manager.start(server)
        state = reconcile_server_process(server, emit_event=True, force_refresh=True)
        metrics = process_manager.metrics(server_id)
        update_runtime(server_id, "EN EJECUCIÓN", pid, state.get("started_at") or time.time(), "")
        try:
            discord_manager.start_monitor(server_id)
        except Exception as exc:
            add_event(server_id, "ERROR", f"Monitor Discord: {exc}")
        return metrics


def stop_server(server_id: int) -> dict:
    with operation_lock:
        server = get_server(server_id)
        state = reconcile_server_process(server, emit_event=True, force_refresh=True)
        update_runtime(server_id, "DETENIENDO", state.get("pid"))

        if state.get("duplicate_pids"):
            stopped = process_manager.kill_matching(server)
            ok = not process_manager.scan_server(server)
            add_event(server_id, "WARNING", "Detener cerró todas las instancias duplicadas")
        else:
            ok = process_manager.stop_safe(server_id)
            stopped = [state.get("pid")] if state.get("pid") else []

        if ok:
            update_runtime(server_id, "DETENIDO", None, None, "")
            discord_manager.mark_offline(server_id, sync_discord=True)
        else:
            update_runtime(
                server_id,
                "NO RESPONDE",
                process_manager.metrics(server_id).get("pid"),
                last_error="No fue posible detener completamente el proceso",
            )
        return {"ok": ok, "stopped_pids": [pid for pid in stopped if pid]}


def kill_server(server_id: int) -> dict:
    with operation_lock:
        server = get_server(server_id)
        stopped = process_manager.kill_matching(server)
        ok = not process_manager.scan_server(server)
        update_runtime(server_id, "DETENIDO" if ok else "NO RESPONDE", None if ok else None)
        if ok:
            discord_manager.mark_offline(server_id, sync_discord=True)
        return {"ok": ok, "stopped_pids": stopped}


def restart_server(server_id: int, backup: bool = True, force_kill: bool = True) -> dict:
    """Reinicio externo real: guardar, cierre seguro, fallback forzado y arranque."""
    with operation_lock:
        server = get_server(server_id)
        state = reconcile_server_process(server, emit_event=True, force_refresh=True)
        update_runtime(
            server_id,
            "REINICIANDO",
            state.get("pid"),
        )

        if state.get("duplicate_pids"):
            add_event(server_id, "WARNING", "Reinicio detectó duplicados; cerrando todas las instancias antes de continuar")
            process_manager.kill_matching(server)
            update_runtime(server_id, "DETENIDO", None, None, "")
            discord_manager.mark_offline(server_id, sync_discord=False)
        elif process_manager.is_alive(server_id):
            try:
                # Valheim acepta save desde su consola; RCON también puede manejarlo.
                send_server_command(server_id, "save")
                time.sleep(2)
            except Exception as exc:
                add_event(server_id, "WARNING", f"No se pudo ordenar save antes de reiniciar: {exc}")

            if not process_manager.stop_safe(server_id, timeout=60):
                if not force_kill:
                    update_runtime(
                        server_id,
                        "NO RESPONDE",
                        process_manager.metrics(server_id).get("pid"),
                        last_error="El cierre seguro agotó el tiempo y el fallback forzado está desactivado",
                    )
                    raise RuntimeError(
                        "El servidor no cerró de forma segura y el cierre forzado está desactivado"
                    )
                add_event(
                    server_id,
                    "WARNING",
                    "Cierre seguro agotado; terminando únicamente el árbol de este servidor",
                )
                process_manager.kill_tree(server_id)
            update_runtime(server_id, "DETENIDO")

        if backup and server.get("savedir"):
            result = backup_manager.create_backup(server, "antes_reinicio")
            with connect() as conn:
                conn.execute(
                    "INSERT INTO backups(server_id,path,reason,size_bytes) VALUES(?,?,?,?)",
                    (server_id, result["path"], result["reason"], result["size_bytes"]),
                )

        time.sleep(2)
        result = start_server(server_id)
        add_event(server_id, "INFO", "Reinicio completado y proceso verificado")
        return result


automation_manager = AutomationManager(
    process_manager, start_server, restart_server, add_event
)
threading.Thread(target=automation_manager.run, daemon=True).start()

def _server_ids():
    with connect() as conn:
        return [int(row["id"]) for row in conn.execute("SELECT id FROM servers").fetchall()]

metrics_collector = MetricsCollector(process_manager, _server_ids)
threading.Thread(target=metrics_collector.run, daemon=True).start()

def _server_health(server: dict, metrics: dict, runtime: dict, discord_settings: dict) -> dict:
    """Diagnóstico vivo calculado desde un solo snapshot del servicio."""
    alive = bool(metrics.get("alive"))
    uptime = int(metrics.get("uptime_seconds", 0) or 0)
    now = time.time()
    last_update = runtime.get("last_update")
    try:
        telemetry_age = max(0.0, now - float(last_update)) if last_update else None
    except (TypeError, ValueError):
        telemetry_age = None

    discord_enabled = bool(discord_settings.get("enabled"))
    discord_error = str(runtime.get("last_error", "") or "").strip()

    duplicate_pids = list(server.get("duplicate_pids") or [])
    if duplicate_pids:
        pids = [server.get("pid")] + duplicate_pids
        state, detail, score = "DUPLICADO", "Procesos activos: " + ", ".join(str(pid) for pid in pids if pid), 15
    elif not alive:
        state, detail, score = "DETENIDO", "El proceso no está activo", 0
    elif uptime < 25:
        state, detail, score = "INICIANDO", "Proceso activo dentro de la gracia de arranque", 65
    elif discord_enabled and discord_error:
        state, detail, score = "ALERTA DISCORD", discord_error[:160], 70
    elif discord_enabled and (telemetry_age is None or telemetry_age > 8):
        age_text = "sin heartbeat" if telemetry_age is None else f"heartbeat hace {telemetry_age:.1f}s"
        state, detail, score = "TELEMETRÍA ATRASADA", age_text, 75
    else:
        state, detail, score = "SALUDABLE", "Proceso y telemetría sincronizados", 100

    return {
        "health_state": state,
        "health_detail": detail,
        "health_score": score,
        "health_checked_at": now,
        "telemetry_age_seconds": round(telemetry_age, 1) if telemetry_age is not None else None,
    }


def list_servers() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT s.*, r.pid, r.status, r.started_at, r.last_error
            FROM servers s
            LEFT JOIN runtime r ON r.server_id=s.id
            ORDER BY s.name COLLATE NOCASE
            """
        ).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        sid = int(item["id"])
        item["resource_policy"] = get_resource_settings(sid)

        # The background reconciliation worker owns process discovery. The API
        # only reads its cached result, so opening/refresing the GUI never scans
        # the complete Windows process table.
        state = process_manager.cached_state(sid)
        if not state:
            state = {
                "alive": str(item.get("status") or "") in ("EN EJECUCIÓN", "DUPLICADO", "INICIANDO", "REINICIANDO"),
                "pid": item.get("pid"),
                "started_at": item.get("started_at"),
                "matching_pids": [item.get("pid")] if item.get("pid") else [],
                "duplicate_pids": [],
                "status": item.get("status") or "DETENIDO",
            }
        metrics = metrics_collector.latest_server(sid)
        runtime = discord_manager.get_runtime(sid)
        discord_settings = discord_manager.get_settings(sid)

        item.update(metrics)
        actual_alive = bool(state.get("alive") and metrics.get("alive"))
        item["alive"] = actual_alive
        item["pid"] = state.get("pid") if actual_alive else None
        item["status"] = state.get("status", "DETENIDO") if actual_alive else "DETENIDO"
        item["duplicate_pids"] = list(state.get("duplicate_pids") or [])
        item["matching_pids"] = list(state.get("matching_pids") or [])
        item["resource_runtime"] = process_manager.resource_status(sid)

        if actual_alive:
            item["join_code"] = runtime.get("join_code", "Esperando...")
            item["players"] = int(runtime.get("players", 0) or 0)
            item["discord_error"] = runtime.get("last_error", "")
        else:
            # Never display telemetry from a dead process.
            item["join_code"] = "—"
            item["players"] = 0
            item["discord_error"] = ""

        item.update(_server_health(item, metrics, runtime, discord_settings))
        result.append(item)
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "AsgardHost/7.0"

    def _json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def log_message(self, format, *args):
        logging.info(format, *args)

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/health":
                return self._json(200, {"ok": True})
            if path.startswith("/asgard-suite/"):
                parts = path.strip("/").split("/")
                if len(parts) >= 3:
                    sid = int(parts[1])
                    action = parts[2]
                    if action == "settings":
                        return self._json(200, asgard_suite_bridge.get_settings(sid))
                    if action == "audit":
                        limit = int(query.get("limit", ["300"])[0])
                        return self._json(200, asgard_suite_bridge.list_audit(sid, limit))
                    if action == "punishments":
                        limit = int(query.get("limit", ["200"])[0])
                        return self._json(200, asgard_suite_bridge.list_punishments(sid, limit))
            if path == "/metrics/host":
                limit = int(query.get("limit", ["120"])[0])
                return self._json(200, metrics_collector.host(limit))
            if path.startswith("/servers/") and path.endswith("/resources"):
                sid = int(path.split("/")[2])
                return self._json(200, resource_payload(sid))
            if path.startswith("/servers/") and path.endswith("/metrics"):
                sid = int(path.split("/")[2])
                limit = int(query.get("limit", ["120"])[0])
                return self._json(200, metrics_collector.server(sid, limit))
            if path.startswith("/library/"):
                parts = path.strip("/").split("/")
                kind = parts[1]
                rel = query.get("path", [""])[0]
                return self._json(200, list_entries(kind, rel))
            if path == "/remote/hosts":
                return self._json(200, remote_manager.list_hosts(include_secrets=False))
            if path == "/remote/servers":
                host_id = int(query.get("host_id", ["0"])[0] or 0)
                return self._json(200, remote_manager.list_remote_servers(host_id or None, refresh=True))
            if path.startswith("/remote/servers/") and path.endswith("/resources"):
                rid = int(path.split("/")[3])
                return self._json(200, remote_manager.get_remote_resources(rid))
            if path.startswith("/remote/servers/") and path.endswith("/files"):
                rid = int(path.split("/")[3])
                scope = query.get("scope", ["server"])[0]
                relative = query.get("path", [""])[0]
                return self._json(200, remote_manager.list_remote_files(rid, scope, relative))
            if path.startswith("/remote/servers/") and path.endswith("/logs"):
                rid = int(path.split("/")[3])
                lines = int(query.get("lines", ["300"])[0])
                return self._json(200, remote_manager.remote_logs(rid, lines))
            if path.startswith("/remote/hosts/") and path.endswith("/agent-health"):
                hid = int(path.split("/")[3])
                return self._json(200, remote_manager.test_agent(hid))
            if path == "/shutdown":
                self._json(200, {"ok": True, "message": "Apagando servicio ASGARD"})
                threading.Thread(
                    target=self.server.shutdown,
                    name="AsgardServiceShutdown",
                    daemon=True,
                ).start()
                return
            if path == "/settings/discord":
                token = discord_manager.get_token()
                return self._json(200, {"configured": bool(token), "token": token})
            if path.startswith("/servers/") and path.endswith("/health"):
                sid = int(path.split("/")[2])
                server = next((item for item in list_servers() if int(item["id"]) == sid), None)
                if server is None:
                    return self._json(404, {"error": "Servidor no encontrado"})
                return self._json(200, {
                    "server_id": sid,
                    "state": server.get("health_state"),
                    "detail": server.get("health_detail"),
                    "score": server.get("health_score"),
                    "checked_at": server.get("health_checked_at"),
                    "telemetry_age_seconds": server.get("telemetry_age_seconds"),
                    "alive": server.get("alive"),
                    "pid": server.get("pid"),
                    "players": server.get("players"),
                    "join_code": server.get("join_code"),
                })
            if path == "/servers":
                return self._json(200, list_servers())
            if path.startswith("/servers/") and path.endswith("/integrations/discordconnector"):
                sid = int(path.split("/")[2])
                return self._json(200, find_discord_connector_files(get_server(sid)))
            if path.startswith("/servers/") and path.endswith("/integrations/azuanticheat"):
                sid = int(path.split("/")[2])
                return self._json(200, find_azu_anticheat_files(get_server(sid)))
            if path.startswith("/integrations/file"):
                target = query.get("path", [""])[0]
                content = read_integration_file(target)
                return self._json(200, {
                    "content": content,
                    "entries": extract_webhook_like_entries(content),
                })
            if path.startswith("/servers/") and path.endswith("/rcon"):
                sid = int(path.split("/")[2])
                return self._json(200, get_rcon_settings(sid))
            if path.startswith("/servers/") and path.endswith("/configs"):
                sid = int(path.split("/")[2])
                return self._json(200, list_configs(get_server(sid)))
            if path.startswith("/servers/") and "/configs/content" in path:
                sid = int(path.split("/")[2])
                rel = query.get("path", [""])[0]
                return self._json(200, {"content": read_config(get_server(sid), rel)})
            if path.startswith("/servers/") and path.endswith("/mods"):
                sid = int(path.split("/")[2])
                return self._json(200, list_mods(get_server(sid)))
            if path.startswith("/servers/") and path.endswith("/world-modifiers"):
                sid = int(path.split("/")[2])
                server = get_server(sid)
                return self._json(200, parse_parameters(server["parameters"]))
            if path.startswith("/servers/") and path.endswith("/players/online"):
                sid = int(path.split("/")[2])
                with connect() as conn:
                    rows = conn.execute(
                        "SELECT * FROM online_players WHERE server_id=? ORDER BY id", (sid,)
                    ).fetchall()
                return self._json(200, [dict(r) for r in rows])
            if path.startswith("/servers/") and path.endswith("/players/registry"):
                sid = int(path.split("/")[2])
                with connect() as conn:
                    rows = conn.execute(
                        "SELECT * FROM player_registry WHERE server_id=? ORDER BY last_seen DESC", (sid,)
                    ).fetchall()
                return self._json(200, [dict(r) for r in rows])
            if path.startswith("/servers/") and "/access/" in path:
                parts = path.strip("/").split("/")
                sid = int(parts[1]); kind = parts[3]
                return self._json(200, {"items": read_list(get_server(sid), kind)})
            if path.startswith("/servers/") and path.endswith("/automation"):
                sid = int(path.split("/")[2])
                return self._json(200, automation_manager.get_settings(sid))
            if path.startswith("/servers/") and path.endswith("/discord"):
                sid = int(path.split("/")[2])
                return self._json(200, {
                    "settings": discord_manager.get_settings(sid),
                    "runtime": discord_manager.get_runtime(sid),
                })
            if path.startswith("/servers/") and path.endswith("/logs"):
                sid = int(path.split("/")[2])
                server = get_server(sid)
                lines = int(query.get("lines", ["300"])[0])
                return self._json(200, {"lines": tail_file(server["log_file"], lines)})
            if path.startswith("/servers/") and path.endswith("/backups"):
                sid = int(path.split("/")[2])
                with connect() as conn:
                    rows = conn.execute(
                        "SELECT * FROM backups WHERE server_id=? ORDER BY id DESC",
                        (sid,),
                    ).fetchall()
                return self._json(200, [dict(r) for r in rows])
            if path == "/events":
                limit = int(query.get("limit", ["200"])[0])
                with connect() as conn:
                    rows = conn.execute(
                        """
                        SELECT e.*, s.name AS server_name
                        FROM events e LEFT JOIN servers s ON s.id=e.server_id
                        ORDER BY e.id DESC LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
                return self._json(200, [dict(r) for r in rows])
            return self._json(404, {"error": "Ruta no encontrada"})
        except Exception as exc:
            return self._json(500, {"error": str(exc)})

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            data = self._read_json()
            if path.startswith("/asgard-suite/"):
                parts = path.strip("/").split("/")
                if len(parts) >= 3:
                    sid = int(parts[1]); action = parts[2]
                    token = self.headers.get("X-Asgard-Token", "")
                    if not asgard_suite_bridge.authorized(sid, token):
                        return self._json(403, {"error": "Token ASGARD inválido"})
                    if action == "audit":
                        return self._json(200, asgard_suite_bridge.ingest_audit(sid, data))
                    if action == "punishments":
                        result = asgard_suite_bridge.queue_punishment(sid, data)
                        platform_id = str(data.get("platform_id", "")).strip()
                        if bool(data.get("ban")) and platform_id:
                            add_to_list(get_server(sid), "banned", platform_id)
                            result["banned"] = True
                        return self._json(200, result)

            if path == "/shutdown":
                self._json(200, {"ok": True, "message": "Apagando servicio ASGARD"})
                threading.Thread(
                    target=self.server.shutdown,
                    name="AsgardServiceShutdown",
                    daemon=True,
                ).start()
                return
            if path == "/settings/discord":
                discord_manager.set_token(data.get("token", ""))
                return self._json(200, {"ok": True})
            if path == "/discord/test":
                return self._json(200, discord_manager.test_bot())

            if path == "/remote/hosts":
                return self._json(201, remote_manager.save_host(data))
            if path == "/remote/servers":
                return self._json(201, remote_manager.register_remote_server(int(data["host_id"]), data))
            remote_parts = path.strip("/").split("/")
            if len(remote_parts) == 4 and remote_parts[:2] == ["remote", "hosts"]:
                hid = int(remote_parts[2]); action = remote_parts[3]
                if action == "test-ssh":
                    return self._json(200, remote_manager.test_ssh(hid))
                if action == "test-agent":
                    return self._json(200, remote_manager.test_agent(hid))
                if action == "autoconfigure":
                    return self._json(200, remote_manager.autoconfigure_agent(hid))
                if action == "discover":
                    return self._json(200, remote_manager.discover_servers(hid, str(data.get("root", ""))))
            if len(remote_parts) == 4 and remote_parts[:2] == ["remote", "servers"]:
                rid = int(remote_parts[2]); action = remote_parts[3]
                if action in {"start", "stop", "restart", "kill", "backup", "command"}:
                    return self._json(200, remote_manager.control_server(rid, action, data))
                if action == "resources-apply":
                    return self._json(200, remote_manager.apply_remote_resources(rid))
                if action == "resources-autoconfigure":
                    return self._json(200, remote_manager.autoconfigure_remote_resources(rid, str(data.get("profile", "balanced"))))
                if action == "backup-download":
                    return self._json(200, remote_manager.backup_and_download(rid))
                if action == "files-upload":
                    return self._json(200, remote_manager.upload_external(rid, str(data.get("scope", "server")), str(data.get("path", "")), str(data["local_path"])))
                if action == "files-download":
                    return self._json(200, remote_manager.download_remote(rid, str(data.get("scope", "server")), str(data["path"])))
                if action == "deploy":
                    result = remote_manager.deploy_library(rid, str(data["kind"]), str(data["relative_path"]))
                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO remote_deployments(remote_server_id,kind,library_path,backup_path,uploaded_count,skipped_count) VALUES(?,?,?,?,?,?)",
                            (rid, data["kind"], data["relative_path"], result.get("backup", ""), len(result.get("uploaded", [])), len(result.get("skipped", []))),
                        )
                    return self._json(200, result)

            if path.startswith("/library/") and path.endswith("/folder"):
                kind = path.strip("/").split("/")[1]
                return self._json(200, create_folder(kind, data.get("parent", ""), data["name"]))
            if path.startswith("/library/") and path.endswith("/import"):
                kind = path.strip("/").split("/")[1]
                return self._json(200, import_item(kind, data.get("folder", ""), data["source_path"]))
            if path.startswith("/servers/") and "/library-apply/" in path:
                parts = path.strip("/").split("/")
                sid = int(parts[1]); kind = parts[3]
                if process_manager.is_alive(sid):
                    raise RuntimeError("Detén el servidor antes de aplicar biblioteca")
                return self._json(200, apply_item(get_server(sid), kind, data["relative_path"]))

            if path == "/servers":
                required = ["name", "executable", "parameters", "working_directory"]
                missing = [key for key in required if not str(data.get(key, "")).strip()]
                if missing:
                    raise ValueError("Faltan campos: " + ", ".join(missing))
                with connect() as conn:
                    cur = conn.execute(
                        """
                        INSERT INTO servers(
                            name, executable, parameters, working_directory,
                            savedir, log_file, backup_directory,
                            backup_retention, auto_start
                        ) VALUES(?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            data["name"], data["executable"], data["parameters"],
                            data["working_directory"], data.get("savedir", ""),
                            data.get("log_file", ""), data.get("backup_directory", ""),
                            int(data.get("backup_retention", 10)),
                            int(bool(data.get("auto_start", False))),
                        ),
                    )
                    sid = cur.lastrowid
                    conn.execute("INSERT INTO runtime(server_id,status) VALUES(?,?)", (sid, "DETENIDO"))
                return self._json(201, {"id": sid})

            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "servers" and parts[2] == "rcon-test":
                sid = int(parts[1])
                settings = get_rcon_settings(sid)
                return self._json(200, {"response": execute_rcon(settings, data.get("command","help"))})
            if len(parts) == 3 and parts[0] == "servers" and parts[2] == "rcon-auto-config":
                sid = int(parts[1])
                if process_manager.is_alive(sid):
                    raise RuntimeError("Detén el servidor antes de configurar automáticamente RCON")
                current = get_rcon_settings(sid)
                current.update({key: value for key, value in data.items() if value not in (None, "")})
                # El modo automático siempre deriva el puerto desde -port, salvo que
                # la petición incluya explícitamente un puerto personalizado.
                if "port" not in data:
                    current["port"] = 0
                result = configure_rcon_mod(get_server(sid), current)
                save_rcon_settings(sid, result["settings"])
                add_event(
                    sid,
                    "INFO",
                    f'RCON configurado automáticamente: {result["implementation"]} '
                    f'en puerto {result["settings"]["port"]}',
                )
                return self._json(200, result)
            if len(parts) == 3 and parts[0] == "servers" and parts[2] == "mods-install":
                sid = int(parts[1])
                if process_manager.is_alive(sid):
                    raise RuntimeError("Detén el servidor antes de instalar mods")
                return self._json(200, install_mod(get_server(sid), data["path"]))
            if len(parts) == 3 and parts[0] == "servers" and parts[2] == "mods-toggle":
                sid = int(parts[1])
                if process_manager.is_alive(sid):
                    raise RuntimeError("Detén el servidor antes de activar/desactivar mods")
                return self._json(200, set_mod_enabled(get_server(sid), data["name"], bool(data["enabled"])))
            if len(parts) == 4 and parts[0] == "servers" and parts[2] == "access":
                sid = int(parts[1]); kind = parts[3]
                return self._json(200, {"items": add_to_list(get_server(sid), kind, data.get("id", ""))})
            if len(parts) >= 3 and parts[0] == "servers":
                sid = int(parts[1])
                action = parts[2]
                if action == "resources-apply":
                    policy = get_resource_settings(sid)
                    return self._json(200, process_manager.apply_resources(sid, policy))
                if action == "resources-autoconfigure":
                    return self._json(200, autoconfigure_resources(sid, str(data.get("profile", "balanced"))))
                if action == "start":
                    return self._json(200, start_server(sid))
                if action == "stop":
                    return self._json(200, stop_server(sid))
                if action == "kill":
                    return self._json(200, kill_server(sid))
                if action == "restart":
                    return self._json(200, restart_server(
                        sid,
                        bool(data.get("backup", True)),
                        bool(data.get("force_kill", True)),
                    ))
                if action == "backup":
                    server = get_server(sid)
                    result = backup_manager.create_backup(server, data.get("reason", "manual"))
                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO backups(server_id,path,reason,size_bytes) VALUES(?,?,?,?)",
                            (sid, result["path"], result["reason"], result["size_bytes"]),
                        )
                    return self._json(200, result)
                if action == "command":
                    return self._json(200, send_server_command(sid, data.get("command", "")))
                if action == "say":
                    message = data.get("message", "").strip()
                    if not message:
                        raise ValueError("Mensaje vacío")
                    return self._json(200, send_server_command(sid, "say " + message))
                if action == "discord-create-message":
                    return self._json(200, discord_manager.create_message(sid))
                if action == "discord-sync":
                    return self._json(200, discord_manager.sync(sid))
                if action == "players-rebuild":
                    return self._json(200, discord_manager.rebuild_player_registry(sid))
                if action == "restore":
                    with operation_lock:
                        server = get_server(sid)
                        if process_manager.scan_server(server, force_refresh=True) or process_manager.is_alive(sid):
                            raise RuntimeError("Detén todas las instancias antes de restaurar")
                        backup_manager.restore_backup(server, data["path"])
                    return self._json(200, {"ok": True})

            return self._json(404, {"error": "Ruta no encontrada"})
        except Exception as exc:
            return self._json(500, {"error": str(exc)})

    def do_PUT(self):
        try:
            path = urlparse(self.path).path
            data = self._read_json()
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "asgard-suite" and parts[2] == "settings":
                return self._json(200, asgard_suite_bridge.save_settings(int(parts[1]), data))
            if len(parts) == 3 and parts[:2] == ["remote", "hosts"]:
                return self._json(200, remote_manager.save_host(data, int(parts[2])))
            if path == "/integrations/file":
                return self._json(200, save_integration_file(data["path"], data["content"]))
            if len(parts) == 4 and parts[:2] == ["remote", "servers"] and parts[3] == "resources":
                return self._json(200, remote_manager.save_remote_resources(int(parts[2]), data))
            if len(parts) == 3 and parts[0] == "servers" and parts[2] == "resources":
                sid = int(parts[1])
                policy = save_resource_settings(sid, data)
                applied = process_manager.apply_resources(sid, policy) if process_manager.is_alive(sid) else None
                return self._json(200, {"policy": policy, "runtime": process_manager.resource_status(sid), "applied": applied})
            if len(parts) == 3 and parts[0] == "servers" and parts[2] == "rcon":
                sid = int(parts[1])
                save_rcon_settings(sid, data)
                return self._json(200, {"ok": True})
            if len(parts) == 3 and parts[0] == "servers" and parts[2] == "configs":
                sid = int(parts[1])
                if process_manager.is_alive(sid):
                    raise RuntimeError("Detén el servidor antes de editar configuraciones")
                return self._json(200, save_config(get_server(sid), data["path"], data["content"]))
            if len(parts) == 3 and parts[0] == "servers" and parts[2] == "world-modifiers":
                sid = int(parts[1])
                if process_manager.is_alive(sid):
                    raise RuntimeError("Detén el servidor antes de cambiar modificadores")
                server = get_server(sid)
                params = apply_modifiers(server["parameters"], data)
                with connect() as conn:
                    conn.execute("UPDATE servers SET parameters=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (params,sid))
                return self._json(200, {"parameters": params})
            if len(parts) == 3 and parts[0] == "servers" and parts[2] == "automation":
                sid = int(parts[1])
                automation_manager.save_settings(sid, data)
                return self._json(200, {"ok": True})
            if len(parts) == 3 and parts[0] == "servers" and parts[2] == "discord":
                sid = int(parts[1])
                discord_manager.save_settings(sid, data)
                return self._json(200, {"ok": True})
            if len(parts) == 2 and parts[0] == "servers":
                sid = int(parts[1])
                if process_manager.is_alive(sid):
                    raise RuntimeError("Detén el servidor antes de editarlo")
                with connect() as conn:
                    conn.execute(
                        """
                        UPDATE servers SET
                            name=?, executable=?, parameters=?, working_directory=?,
                            savedir=?, log_file=?, backup_directory=?,
                            backup_retention=?, auto_start=?,
                            updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                        """,
                        (
                            data["name"], data["executable"], data["parameters"],
                            data["working_directory"], data.get("savedir", ""),
                            data.get("log_file", ""), data.get("backup_directory", ""),
                            int(data.get("backup_retention", 10)),
                            int(bool(data.get("auto_start", False))), sid,
                        ),
                    )
                return self._json(200, {"ok": True})
            return self._json(404, {"error": "Ruta no encontrada"})
        except Exception as exc:
            return self._json(500, {"error": str(exc)})

    def do_DELETE(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            data = self._read_json()
            parts = path.strip("/").split("/")

            if len(parts) == 3 and parts[:2] == ["remote", "hosts"]:
                remote_manager.delete_host(int(parts[2]))
                return self._json(200, {"ok": True})
            if len(parts) == 3 and parts[:2] == ["remote", "servers"]:
                remote_manager.delete_remote_server(int(parts[2]))
                return self._json(200, {"ok": True})

            if path.startswith("/library/"):
                kind = parts[1]
                target = query.get("path", [data.get("path", "")])[0]
                delete_item(kind, target)
                return self._json(200, {"ok": True})

            if len(parts) == 4 and parts[0] == "servers" and parts[2] == "access":
                sid = int(parts[1])
                kind = parts[3]
                values = data.get("ids") or [data.get("id", "")]
                result = read_list(get_server(sid), kind)
                for value in values:
                    if str(value).strip():
                        result = remove_from_list(get_server(sid), kind, str(value))
                add_event(sid, "INFO", f"Lista {kind}: {len(values)} elemento(s) eliminados")
                return self._json(200, {"items": result})

            if len(parts) == 3 and parts[0] == "servers" and parts[2] == "configs":
                sid = int(parts[1])
                if process_manager.is_alive(sid):
                    raise RuntimeError("Detén el servidor antes de eliminar configuraciones")
                rel = data.get("path") or query.get("path", [""])[0]
                result = delete_config(get_server(sid), rel)
                add_event(sid, "WARNING", f"Configuración eliminada con backup: {rel}")
                return self._json(200, result)

            if path == "/integrations/file":
                target = data.get("path") or query.get("path", [""])[0]
                target_path = Path(target).resolve()
                if not target_path.is_file():
                    raise FileNotFoundError(target_path)
                backup = target_path.with_name(
                    target_path.name + time.strftime(".asgard_%Y%m%d_%H%M%S.deleted.bak")
                )
                import shutil
                shutil.copy2(target_path, backup)
                target_path.unlink()
                return self._json(200, {"ok": True, "backup": str(backup)})

            if len(parts) == 2 and parts[0] == "servers":
                sid = int(parts[1])
                if process_manager.is_alive(sid):
                    raise RuntimeError("No puedes eliminar un servidor activo")
                with connect() as conn:
                    conn.execute("DELETE FROM servers WHERE id=?", (sid,))
                return self._json(200, {"ok": True})

            return self._json(404, {"error": "Ruta no encontrada"})
        except Exception as exc:
            return self._json(500, {"error": str(exc)})


_resource_guard_state: dict[int, dict] = {}


def resource_guard_loop() -> None:
    while True:
        try:
            with connect() as conn:
                rows = conn.execute("SELECT server_id FROM resource_settings WHERE enabled=1 AND ram_warning_mb>0").fetchall()
            now = time.time()
            for row in rows:
                sid = int(row["server_id"])
                if not process_manager.is_alive(sid):
                    _resource_guard_state.pop(sid, None)
                    continue
                policy = get_resource_settings(sid)
                metrics = process_manager.metrics(sid)
                state = _resource_guard_state.setdefault(sid, {"samples": 0, "last_notice": 0.0, "actioning": False, "cooldown_until": 0.0})
                if float(metrics.get("ram_mb", 0)) < int(policy["ram_warning_mb"]):
                    state["samples"] = 0
                    state["actioning"] = False
                    continue
                state["samples"] += 1
                if now - state["last_notice"] > 600:
                    add_event(sid, "WARNING", f"RAM del servidor {metrics.get('ram_mb', 0):.1f} MB supera el umbral {policy['ram_warning_mb']} MB")
                    state["last_notice"] = now
                if state["actioning"] or state["samples"] < 3 or now < state.get("cooldown_until", 0):
                    continue
                action = policy.get("ram_action", "warn")
                should_restart = action == "backup_restart"
                if action == "restart_when_empty":
                    with connect() as conn:
                        drow = conn.execute("SELECT enabled FROM discord_settings WHERE server_id=?", (sid,)).fetchone()
                    if drow and bool(drow["enabled"]):
                        should_restart = int(discord_manager.get_runtime(sid).get("players", 0) or 0) == 0
                    else:
                        should_restart = False
                        if now - state["last_notice"] > 60:
                            add_event(sid, "INFO", "Reinicio al quedar vacío requiere el monitor Discord/jugadores habilitado; se mantiene solo la advertencia")
                if should_restart:
                    state["actioning"] = True
                    state["last_notice"] = now
                    def perform(target=sid, guard=state):
                        try:
                            add_event(target, "WARNING", "Protección de RAM: iniciando backup y reinicio controlado")
                            restart_server(target, backup=True, force_kill=True)
                        except Exception as exc:
                            add_event(target, "ERROR", f"Protección de RAM no pudo reiniciar: {exc}")
                        finally:
                            guard["samples"] = 0
                            guard["actioning"] = False
                            guard["cooldown_until"] = time.time() + 900
                    threading.Thread(target=perform, daemon=True).start()
        except Exception as exc:
            logging.exception("Resource guard: %s", exc)
        time.sleep(10)


threading.Thread(target=resource_guard_loop, daemon=True).start()


def auto_start() -> None:
    with connect() as conn:
        rows = conn.execute("SELECT id FROM servers WHERE auto_start=1").fetchall()
    for row in rows:
        try:
            start_server(int(row["id"]))
        except Exception as exc:
            add_event(int(row["id"]), "ERROR", f"Auto inicio falló: {exc}")


def run_service() -> None:
    # Reserva primero el puerto; una segunda instancia no alcanza a ejecutar auto_start.
    server = ThreadingHTTPServer((SERVICE_HOST, SERVICE_PORT), Handler)
    threading.Thread(target=auto_start, daemon=True).start()
    logging.info(
        "Servicio iniciado en %s:%s con PID %s",
        SERVICE_HOST,
        SERVICE_PORT,
        os.getpid(),
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        _remove_service_pid()
        logging.info("Servicio ASGARD detenido")


if __name__ == "__main__":
    run_service()
