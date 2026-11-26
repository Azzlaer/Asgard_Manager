from __future__ import annotations

import argparse
import atexit
import json
import hmac
import logging
from logging.handlers import RotatingFileHandler
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psutil

from process_manager import ProcessManager
from backup_manager import BackupManager
from resource_control import automatic_policy, host_capacity, normalize_policy


VERSION = "6.1.0"


def runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = runtime_dir()
CONFIG_PATH = APP_DIR / "agent_config.json"


def load_config() -> dict:
    defaults = {
        "bind": "127.0.0.1",
        "port": 8766,
        "token": "",
        "data_directory": str(APP_DIR / "AgentData"),
    }
    if CONFIG_PATH.is_file():
        try:
            defaults.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    if not defaults["token"]:
        defaults["token"] = uuid.uuid4().hex + uuid.uuid4().hex
        CONFIG_PATH.write_text(json.dumps(defaults, indent=2), encoding="utf-8")
    return defaults


CONFIG = load_config()
DATA_DIR = Path(CONFIG["data_directory"])
DATA_DIR.mkdir(parents=True, exist_ok=True)
SERVERS_FILE = DATA_DIR / "servers.json"
RUNTIME_FILE = DATA_DIR / "runtime.json"
EVENTS_FILE = DATA_DIR / "agent_events.log"
BACKUP_ROOT = DATA_DIR / "backups"
BACKUP_ROOT.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    handlers=[RotatingFileHandler(DATA_DIR / "agent.log", maxBytes=5 * 1024 * 1024, backupCount=4, encoding="utf-8")],
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, value) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


lock = threading.RLock()
servers: list[dict] = read_json(SERVERS_FILE, [])
runtime_state: dict[str, dict] = read_json(RUNTIME_FILE, {})


def add_event(server_id: int | None, level: str, message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{level}] [{server_id or 'HOST'}] {message}"
    logging.info(line)
    try:
        with EVENTS_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


process_manager = ProcessManager(add_event)
backup_manager = BackupManager(add_event, backup_root=BACKUP_ROOT)


def persist_runtime() -> None:
    state = {}
    for server in servers:
        sid = int(server["id"])
        metrics = process_manager.metrics(sid)
        if metrics.get("alive"):
            state[str(sid)] = {"pid": metrics["pid"], "started_at": time.time() - metrics.get("uptime_seconds", 0)}
    write_json(RUNTIME_FILE, state)


def recover_runtime() -> None:
    for key, value in runtime_state.items():
        try:
            process_manager.attach_existing(int(key), int(value["pid"]), float(value.get("started_at") or time.time()))
        except Exception:
            pass


recover_runtime()
atexit.register(persist_runtime)


def get_server(server_id: int) -> dict:
    with lock:
        item = next((dict(s) for s in servers if int(s["id"]) == server_id), None)
    if item is None:
        raise KeyError("Servidor no encontrado")
    return item


def save_servers() -> None:
    with lock:
        write_json(SERVERS_FILE, servers)


def next_id() -> int:
    return max([int(x["id"]) for x in servers] or [0]) + 1


def register_server(data: dict) -> dict:
    required = ["name", "executable", "working_directory", "parameters"]
    missing = [x for x in required if not str(data.get(x, "")).strip()]
    if missing:
        raise ValueError("Faltan campos: " + ", ".join(missing))
    exe = Path(str(data["executable"]))
    if not exe.is_file():
        raise FileNotFoundError(f"No existe: {exe}")
    with lock:
        sid = next_id()
        item = {
            "id": sid,
            "name": str(data["name"]),
            "executable": str(exe),
            "parameters": str(data["parameters"]),
            "working_directory": str(data.get("working_directory") or exe.parent),
            "savedir": str(data.get("savedir", "")),
            "log_file": str(data.get("log_file", "")),
            "backup_directory": str(data.get("backup_directory", "")),
            "backup_retention": int(data.get("backup_retention", 10)),
            "auto_start": bool(data.get("auto_start", False)),
            "resource_policy": normalize_policy(data.get("resource_policy")),
        }
        servers.append(item)
        save_servers()
    add_event(sid, "INFO", f"Servidor registrado: {item['name']}")
    return item


def update_server(server_id: int, data: dict) -> dict:
    if process_manager.is_alive(server_id):
        raise RuntimeError("Detén el servidor antes de editarlo")
    with lock:
        index = next((i for i, s in enumerate(servers) if int(s["id"]) == server_id), None)
        if index is None:
            raise KeyError("Servidor no encontrado")
        merged = dict(servers[index])
        for key in (
            "name", "executable", "parameters", "working_directory", "savedir",
            "log_file", "backup_directory", "backup_retention", "auto_start", "resource_policy",
        ):
            if key in data:
                merged[key] = data[key]
        merged["backup_retention"] = int(merged.get("backup_retention", 10))
        merged["auto_start"] = bool(merged.get("auto_start", False))
        merged["resource_policy"] = normalize_policy(merged.get("resource_policy"))
        servers[index] = merged
        save_servers()
        return dict(merged)


def list_servers() -> list[dict]:
    result = []
    with lock:
        snapshot = [dict(s) for s in servers]
    for item in snapshot:
        sid = int(item["id"])
        item["resource_policy"] = normalize_policy(item.get("resource_policy"))
        metrics = process_manager.metrics(sid)
        item.update(metrics)
        item["resource_runtime"] = process_manager.resource_status(sid)
        item["status"] = "EN EJECUCIÓN" if metrics.get("alive") else "DETENIDO"
        result.append(item)
    return result


def get_resource_payload(server_id: int) -> dict:
    server = get_server(server_id)
    runtime = process_manager.resource_status(server_id)
    runtime.update(process_manager.metrics(server_id))
    return {
        "policy": normalize_policy(server.get("resource_policy")),
        "host": host_capacity(),
        "runtime": runtime,
    }


def _store_resource_policy(server_id: int, policy: dict) -> None:
    with lock:
        index = next((i for i, item in enumerate(servers) if int(item["id"]) == server_id), None)
        if index is None:
            raise KeyError("Servidor no encontrado")
        servers[index]["resource_policy"] = normalize_policy(policy)
        save_servers()


def save_resource_policy(server_id: int, data: dict) -> dict:
    policy = normalize_policy(data)
    _store_resource_policy(server_id, policy)
    applied = process_manager.apply_resources(server_id, policy) if process_manager.is_alive(server_id) else None
    return {"policy": policy, "host": host_capacity(), "runtime": process_manager.resource_status(server_id), "applied": applied}


def autoconfigure_resource_policy(server_id: int, profile: str) -> dict:
    policy = automatic_policy(profile, server_id, [int(s["id"]) for s in servers])
    _store_resource_policy(server_id, policy)
    applied = process_manager.apply_resources(server_id, policy) if process_manager.is_alive(server_id) else None
    add_event(server_id, "INFO", f"Perfil de recursos autoconfigurado: {policy['profile']}")
    return {"policy": policy, "host": host_capacity(), "runtime": process_manager.resource_status(server_id), "applied": applied}


def start_server(server_id: int) -> dict:
    server = get_server(server_id)
    policy = normalize_policy(server.get("resource_policy"))
    if policy.get("enabled") and policy.get("auto_rebalance"):
        policy = automatic_policy(policy.get("profile", "balanced"), server_id, [int(s["id"]) for s in servers])
        update_server(server_id, {"resource_policy": policy})
        server["resource_policy"] = policy
    pid = process_manager.start(server)
    persist_runtime()
    return {"ok": True, "pid": pid, **process_manager.metrics(server_id)}


def stop_server(server_id: int, force: bool = True) -> dict:
    ok = process_manager.stop_safe(server_id, timeout=60)
    if not ok and force:
        process_manager.kill_tree(server_id)
        ok = True
    persist_runtime()
    return {"ok": ok}


def backup_server(server_id: int, reason: str = "manual") -> dict:
    server = get_server(server_id)
    server["backup_directory"] = server.get("backup_directory") or str(BACKUP_ROOT / str(server_id))
    server.setdefault("backup_retention", 10)
    return backup_manager.create_backup(server, reason)


def restart_server(server_id: int, backup: bool = True) -> dict:
    if process_manager.is_alive(server_id):
        try:
            process_manager.send_command(server_id, "save")
            time.sleep(2)
        except Exception:
            pass
        stop_server(server_id, force=True)
    result = backup_server(server_id, "antes_reinicio") if backup and get_server(server_id).get("savedir") else None
    time.sleep(2)
    started = start_server(server_id)
    return {"started": started, "backup": result}


def tail_file(path_value: str, lines: int = 300) -> list[str]:
    path = Path(path_value)
    if not path.is_file():
        return []
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        block = 8192
        data = b""
        pos = size
        while pos > 0 and data.count(b"\n") <= lines:
            take = min(block, pos)
            pos -= take
            handle.seek(pos)
            data = handle.read(take) + data
    return data.decode("utf-8", errors="replace").splitlines()[-lines:]


def discover(root: str) -> list[dict]:
    roots: list[Path]
    if root:
        roots = [Path(root)]
    else:
        roots = [Path("C:/games"), Path("C:/servers"), Path("D:/games"), Path("D:/servers")]
    found = []
    seen = set()
    for base in roots:
        if not base.is_dir():
            continue
        try:
            candidates = base.rglob("valheim_server.exe")
            for exe in candidates:
                key = str(exe.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)
                bat = next(exe.parent.glob("*.bat"), None)
                parameters = '-nographics -batchmode -name "Servidor remoto" -port 2456 -world "Dedicated" -password "CAMBIAR" -crossplay -public 1'
                if bat:
                    try:
                        text = bat.read_text(encoding="utf-8", errors="ignore")
                        for line in text.splitlines():
                            if "valheim_server" in line.lower():
                                lower = line.lower()
                                marker = lower.find("valheim_server.exe")
                                parameters = line[marker + len("valheim_server.exe"):].strip().lstrip('"').strip() or parameters
                                break
                    except OSError:
                        pass
                found.append({
                    "name": exe.parent.name,
                    "executable": str(exe),
                    "working_directory": str(exe.parent),
                    "parameters": parameters,
                    "start_bat": str(bat) if bat else "",
                })
                if len(found) >= 50:
                    return found
        except (OSError, PermissionError):
            continue
    return found


def system_metrics() -> dict:
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(Path.home().anchor or "/")
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "cpu_percent": psutil.cpu_percent(interval=0.15),
        "ram_percent": vm.percent,
        "ram_used_mb": round((vm.total - vm.available) / 1024 ** 2, 1),
        "ram_total_mb": round(vm.total / 1024 ** 2, 1),
        "disk_percent": disk.percent,
        "boot_time": psutil.boot_time(),
        "version": VERSION,
        **host_capacity(),
    }


resource_guard_state: dict[int, dict] = {}


def resource_guard_loop() -> None:
    while True:
        try:
            now = time.time()
            for server in list(servers):
                sid = int(server["id"])
                policy = normalize_policy(server.get("resource_policy"))
                if not policy.get("enabled") or not policy.get("ram_warning_mb") or not process_manager.is_alive(sid):
                    resource_guard_state.pop(sid, None)
                    continue
                metrics = process_manager.metrics(sid)
                state = resource_guard_state.setdefault(sid, {"samples": 0, "last_notice": 0.0, "actioning": False, "cooldown_until": 0.0})
                if float(metrics.get("ram_mb", 0)) < int(policy["ram_warning_mb"]):
                    state["samples"] = 0
                    state["actioning"] = False
                    continue
                state["samples"] += 1
                if now - state["last_notice"] > 600:
                    add_event(sid, "WARNING", f"RAM {metrics.get('ram_mb', 0):.1f} MB supera el umbral {policy['ram_warning_mb']} MB")
                    state["last_notice"] = now
                if policy.get("ram_action") == "backup_restart" and state["samples"] >= 3 and not state["actioning"] and now >= state.get("cooldown_until", 0):
                    state["actioning"] = True
                    def perform(target=sid, guard=state):
                        try:
                            add_event(target, "WARNING", "Protección de RAM: backup y reinicio controlado")
                            restart_server(target, backup=True)
                        except Exception as exc:
                            add_event(target, "ERROR", f"Protección de RAM no pudo reiniciar: {exc}")
                        finally:
                            guard["samples"] = 0
                            guard["actioning"] = False
                            guard["cooldown_until"] = time.time() + 900
                    threading.Thread(target=perform, daemon=True).start()
                elif policy.get("ram_action") == "restart_when_empty" and now - state["last_notice"] > 60:
                    add_event(sid, "INFO", "Reinicio al quedar vacío requiere contador de jugadores del panel; el agente mantendrá solo la advertencia")
        except Exception as exc:
            logging.exception("Resource guard: %s", exc)
        time.sleep(10)


threading.Thread(target=resource_guard_loop, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server_version = "ASGARDRemoteAgent/6.1"

    def _auth(self) -> bool:
        return hmac.compare_digest(self.headers.get("X-ASGARD-Token", "").encode("utf-8"), str(CONFIG["token"]).encode("utf-8"))

    def _json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 <= length <= 8 * 1024 * 1024:
            raise ValueError("Tamaño de solicitud inválido")
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def log_message(self, fmt, *args):
        logging.info(fmt, *args)

    def _guard(self) -> bool:
        if not self._auth():
            self._json(401, {"error": "Token inválido"})
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if path == "/health":
                return self._json(200, {"ok": True, **system_metrics()})
            if path == "/system":
                return self._json(200, system_metrics())
            if path == "/servers":
                return self._json(200, list_servers())
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "servers" and parts[2] == "logs":
                sid = int(parts[1])
                count = max(1, min(5000, int(query.get("lines", ["300"])[0])))
                return self._json(200, {"lines": tail_file(get_server(sid).get("log_file", ""), count)})
            if len(parts) == 3 and parts[0] == "servers" and parts[2] == "resources":
                return self._json(200, get_resource_payload(int(parts[1])))
            if len(parts) == 3 and parts[0] == "servers" and parts[2] == "metrics":
                sid = int(parts[1])
                return self._json(200, process_manager.metrics(sid))
            return self._json(404, {"error": "Ruta no encontrada"})
        except Exception as exc:
            return self._json(500, {"error": str(exc)})

    def do_POST(self):
        if not self._guard():
            return
        try:
            path = urlparse(self.path).path
            data = self._read_json()
            if path == "/servers/discover":
                return self._json(200, discover(str(data.get("root", ""))))
            if path == "/servers":
                return self._json(201, register_server(data))
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "servers":
                sid = int(parts[1]); action = parts[2]
                if action == "start": return self._json(200, start_server(sid))
                if action == "stop": return self._json(200, stop_server(sid, bool(data.get("force", True))))
                if action == "restart": return self._json(200, restart_server(sid, bool(data.get("backup", True))))
                if action == "kill": return self._json(200, {"ok": process_manager.kill_tree(sid)})
                if action == "backup": return self._json(200, backup_server(sid, str(data.get("reason", "manual"))))
                if action == "resources-apply":
                    return self._json(200, process_manager.apply_resources(sid, get_server(sid).get("resource_policy", {})))
                if action == "resources-autoconfigure":
                    return self._json(200, autoconfigure_resource_policy(sid, str(data.get("profile", "balanced"))))
                if action == "command":
                    process_manager.send_command(sid, str(data.get("command", "")))
                    return self._json(200, {"ok": True})
            return self._json(404, {"error": "Ruta no encontrada"})
        except Exception as exc:
            return self._json(500, {"error": str(exc)})

    def do_PUT(self):
        if not self._guard():
            return
        try:
            path = urlparse(self.path).path
            data = self._read_json()
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "servers" and parts[2] == "resources":
                return self._json(200, save_resource_policy(int(parts[1]), data))
            if len(parts) == 2 and parts[0] == "servers":
                return self._json(200, update_server(int(parts[1]), data))
            return self._json(404, {"error": "Ruta no encontrada"})
        except Exception as exc:
            return self._json(500, {"error": str(exc)})

    def do_DELETE(self):
        if not self._guard():
            return
        try:
            parts = urlparse(self.path).path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "servers":
                sid = int(parts[1])
                if process_manager.is_alive(sid):
                    raise RuntimeError("No puedes eliminar un servidor activo")
                with lock:
                    servers[:] = [s for s in servers if int(s["id"]) != sid]
                    save_servers()
                return self._json(200, {"ok": True})
            return self._json(404, {"error": "Ruta no encontrada"})
        except Exception as exc:
            return self._json(500, {"error": str(exc)})


def auto_start() -> None:
    for server in list(servers):
        if server.get("auto_start") and not process_manager.is_alive(int(server["id"])):
            try:
                start_server(int(server["id"]))
            except Exception as exc:
                add_event(int(server["id"]), "ERROR", f"Auto inicio falló: {exc}")


def run() -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", int(CONFIG["port"])), Handler)
    add_event(None, "INFO", f"ASGARD Remote Agent {VERSION} en {CONFIG['bind']}:{CONFIG['port']}")
    httpd.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-token", action="store_true")
    args = parser.parse_args()
    if args.print_token:
        print(CONFIG["token"])
    else:
        run()
