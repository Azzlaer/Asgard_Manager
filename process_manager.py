from __future__ import annotations

import ntpath
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import psutil

from console_controller import send_console_command
from resource_control import ResourceController, normalize_policy


@dataclass
class ManagedProcess:
    server_id: int
    pid: int
    process: Optional[subprocess.Popen]
    started_at: float


class ProcessManager:
    """Single source of truth for configured Valheim processes.

    R10 does not trust a PID stored in SQLite by itself. PIDs are reusable on
    Windows, and a service restart can lose an otherwise healthy server. Every
    decision is reconciled against the real process executable and command-line
    signature (port, savedir, world and name).
    """

    def __init__(self, event_callback: Callable[[int, str, str], None]):
        self._event_callback = event_callback
        self._managed: dict[int, ManagedProcess] = {}
        self._lock = threading.RLock()
        self._cpu_samples: dict[int, tuple[float, float]] = {}
        self._last_states: dict[int, dict] = {}
        self._scan_cache: list[dict] = []
        self._scan_cache_at = 0.0
        self._scan_cache_ttl = 4.0
        self._scan_lock = threading.RLock()
        self.resources = ResourceController(self._event_callback)

    def _event(self, server_id: int, level: str, message: str) -> None:
        self._event_callback(server_id, level, message)

    @staticmethod
    def _normalize_fs_value(value: str) -> str:
        """Normalize Windows paths without requiring that they exist."""
        value = (value or "").strip().strip('"').strip("'")
        if not value:
            return ""
        value = os.path.expandvars(value).replace("/", "\\")
        return ntpath.normcase(ntpath.normpath(value))

    @staticmethod
    def _normalize_text(value: str) -> str:
        return (value or "").strip().strip('"').strip("'").casefold()

    @staticmethod
    def _parameter_value(parameters: str, name: str) -> str:
        match = re.search(
            rf'(?:^|\s)-{re.escape(name)}\s+(?:"([^"]*)"|\'([^\']*)\'|([^\s]+))',
            parameters or "",
            re.IGNORECASE,
        )
        if not match:
            return ""
        return next((value for value in match.groups() if value is not None), "").strip()

    def _server_signature(self, server: dict) -> dict[str, str]:
        parameters = str(server.get("parameters") or "")
        savedir = self._parameter_value(parameters, "savedir") or str(server.get("savedir") or "")
        return {
            "port": self._normalize_text(self._parameter_value(parameters, "port")),
            "world": self._normalize_text(self._parameter_value(parameters, "world")),
            "savedir": self._normalize_fs_value(savedir),
            "name": self._normalize_text(self._parameter_value(parameters, "name")),
        }

    def _process_snapshot(self, proc: psutil.Process) -> dict | None:
        try:
            info = proc.as_dict(attrs=["pid", "name", "exe", "cmdline", "create_time"])
            cmdline_parts = info.get("cmdline") or []
            cmdline = subprocess.list2cmdline(cmdline_parts) if cmdline_parts else ""
            return {
                "pid": int(info["pid"]),
                "name": str(info.get("name") or ""),
                "exe": str(info.get("exe") or ""),
                "cmdline": cmdline,
                "create_time": float(info.get("create_time") or 0.0),
                "port": self._normalize_text(self._parameter_value(cmdline, "port")),
                "world": self._normalize_text(self._parameter_value(cmdline, "world")),
                "savedir": self._normalize_fs_value(self._parameter_value(cmdline, "savedir")),
                "server_name": self._normalize_text(self._parameter_value(cmdline, "name")),
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError, RuntimeError):
            return None

    def invalidate_scan_cache(self) -> None:
        with self._scan_lock:
            self._scan_cache_at = 0.0
            self._scan_cache = []

    def all_valheim_processes(self, force_refresh: bool = False) -> list[dict]:
        """Return a cached snapshot of valheim_server.exe processes.

        R9 enumerated the complete Windows process table once per configured
        server and again for every GUI refresh. R10 scans at most once per
        cache window and shares the snapshot across all servers.
        """
        now = time.monotonic()
        with self._scan_lock:
            if not force_refresh and self._scan_cache and now - self._scan_cache_at < self._scan_cache_ttl:
                return [dict(row) for row in self._scan_cache]

        rows: list[dict] = []
        attrs = ["pid", "name", "exe", "cmdline", "create_time"]
        for proc in psutil.process_iter(attrs=attrs, ad_value=None):
            try:
                info = proc.info
                if str(info.get("name") or "").casefold() != "valheim_server.exe":
                    continue
                cmdline_parts = info.get("cmdline") or []
                cmdline = subprocess.list2cmdline(cmdline_parts) if cmdline_parts else ""
                rows.append({
                    "pid": int(info["pid"]),
                    "name": str(info.get("name") or ""),
                    "exe": str(info.get("exe") or ""),
                    "cmdline": cmdline,
                    "create_time": float(info.get("create_time") or 0.0),
                    "port": self._normalize_text(self._parameter_value(cmdline, "port")),
                    "world": self._normalize_text(self._parameter_value(cmdline, "world")),
                    "savedir": self._normalize_fs_value(self._parameter_value(cmdline, "savedir")),
                    "server_name": self._normalize_text(self._parameter_value(cmdline, "name")),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError, RuntimeError, KeyError, TypeError):
                continue

        rows.sort(key=lambda row: (row.get("create_time", 0.0), row["pid"]))
        with self._scan_lock:
            self._scan_cache = [dict(row) for row in rows]
            self._scan_cache_at = time.monotonic()
        return rows

    def _matches_server(self, server: dict, snapshot: dict) -> bool:
        expected_exe_text = str(server.get("executable") or "")
        expected_name = ntpath.basename(expected_exe_text.replace("/", "\\"))
        if not expected_name:
            return False

        if str(snapshot.get("name") or "").casefold() != expected_name.casefold():
            return False

        proc_exe = str(snapshot.get("exe") or "")
        if proc_exe and self._normalize_fs_value(proc_exe) != self._normalize_fs_value(expected_exe_text):
            return False

        expected = self._server_signature(server)

        # Port is the strongest discriminator and must never be guessed.
        if expected["port"]:
            if snapshot.get("port") != expected["port"]:
                return False

        # Savedir is the second strongest discriminator. With a configured
        # savedir, do not attach a process that points at another world's data.
        if expected["savedir"]:
            actual_savedir = str(snapshot.get("savedir") or "")
            if actual_savedir and actual_savedir != expected["savedir"]:
                return False
            if not actual_savedir and not expected["port"]:
                return False

        # World/name refine an already strong match. They are mandatory only
        # when neither port nor savedir is available.
        strong_key = bool(expected["port"] or expected["savedir"])
        for key, actual_key in (("world", "world"), ("name", "server_name")):
            wanted = expected[key]
            actual = str(snapshot.get(actual_key) or "")
            if wanted and actual and wanted != actual:
                return False
            if wanted and not actual and not strong_key:
                return False

        # Refuse weak executable-only matches when multiple servers share one
        # Valheim installation.
        return strong_key or bool(expected["world"] and expected["name"])

    def scan_server(
        self,
        server: dict,
        snapshots: list[dict] | None = None,
        force_refresh: bool = False,
    ) -> list[dict]:
        rows = snapshots if snapshots is not None else self.all_valheim_processes(force_refresh=force_refresh)
        return [row for row in rows if self._matches_server(server, row)]

    def _find_matching_processes(self, server: dict) -> list[int]:
        return [int(row["pid"]) for row in self.scan_server(server)]

    def _pid_alive(self, pid: int) -> bool:
        try:
            proc = psutil.Process(pid)
            return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    def is_alive(self, server_id: int) -> bool:
        with self._lock:
            item = self._managed.get(server_id)
            if not item:
                return False
            alive = self._pid_alive(item.pid)
            if not alive:
                self._managed.pop(server_id, None)
                self._cpu_samples.pop(server_id, None)
                self.resources.release(server_id)
            return alive

    def detach(self, server_id: int) -> None:
        with self._lock:
            self._managed.pop(server_id, None)
            self._cpu_samples.pop(server_id, None)
        self.resources.release(server_id)

    def attach_existing(
        self,
        server_id: int,
        pid: int,
        started_at: float | None = None,
        resource_policy: dict | None = None,
        server: dict | None = None,
    ) -> bool:
        try:
            proc = psutil.Process(pid)
            if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                return False
            if server is not None:
                snapshot = self._process_snapshot(proc)
                if not snapshot or not self._matches_server(server, snapshot):
                    return False
            with self._lock:
                self._managed[server_id] = ManagedProcess(
                    server_id=server_id,
                    pid=pid,
                    process=None,
                    started_at=started_at or proc.create_time(),
                )
            policy = normalize_policy(resource_policy)
            if policy.get("enabled") and policy.get("apply_on_start", True):
                try:
                    self.resources.apply(server_id, pid, policy)
                except Exception as exc:
                    self._event(server_id, "WARNING", f"No se pudieron recuperar límites de recursos: {exc}")
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    def reconcile(
        self,
        server: dict,
        preferred_pid: int | None = None,
        snapshots: list[dict] | None = None,
        force_refresh: bool = False,
    ) -> dict:
        """Rebuild managed state from one shared/cached process snapshot."""
        server_id = int(server["id"])
        with self._lock:
            matches = self.scan_server(server, snapshots=snapshots, force_refresh=force_refresh)
            pids = [int(row["pid"]) for row in matches]
            current = self._managed.get(server_id)

            chosen: dict | None = None
            if preferred_pid:
                chosen = next((row for row in matches if int(row["pid"]) == int(preferred_pid)), None)
            if chosen is None and current:
                chosen = next((row for row in matches if int(row["pid"]) == current.pid), None)
            if chosen is None and matches:
                # Oldest process is normally the real long-running instance;
                # the duplicate is usually the newer restart attempt.
                chosen = min(matches, key=lambda row: (row.get("create_time", 0.0), row["pid"]))

            if chosen is None:
                self.detach(server_id)
                state = {
                    "alive": False,
                    "pid": None,
                    "started_at": None,
                    "matching_pids": [],
                    "duplicate_pids": [],
                    "status": "DETENIDO",
                }
                self._last_states[server_id] = dict(state)
                return state

            chosen_pid = int(chosen["pid"])
            if not current or current.pid != chosen_pid or not self._pid_alive(chosen_pid):
                if not self.attach_existing(
                    server_id,
                    chosen_pid,
                    float(chosen.get("create_time") or time.time()),
                    server.get("resource_policy"),
                    server=server,
                ):
                    self.detach(server_id)
                    state = {
                        "alive": False,
                        "pid": None,
                        "started_at": None,
                        "matching_pids": pids,
                        "duplicate_pids": pids if len(pids) > 1 else [],
                        "status": "ERROR",
                    }
                    self._last_states[server_id] = dict(state)
                    return state

            duplicates = [pid for pid in pids if pid != chosen_pid]
            state = {
                "alive": True,
                "pid": chosen_pid,
                "started_at": float(chosen.get("create_time") or time.time()),
                "matching_pids": pids,
                "duplicate_pids": duplicates,
                "status": "DUPLICADO" if duplicates else "EN EJECUCIÓN",
            }
            self._last_states[server_id] = dict(state)
            return state

    def cached_state(self, server_id: int) -> dict:
        with self._lock:
            state = self._last_states.get(int(server_id))
            return dict(state) if state else {}

    def start(self, server: dict) -> int:
        server_id = int(server["id"])
        with self._lock:
            reconciled = self.reconcile(server)
            if reconciled["duplicate_pids"]:
                all_pids = reconciled["matching_pids"]
                raise RuntimeError(
                    "Se detectaron instancias duplicadas de este servidor: "
                    + ", ".join(str(pid) for pid in all_pids)
                    + ". ASGARD bloqueó otro arranque."
                )
            if reconciled["alive"]:
                pid = int(reconciled["pid"])
                self._event(
                    server_id,
                    "WARNING",
                    f"Instancia existente detectada; ASGARD recuperó el PID {pid} en vez de duplicarla",
                )
                return pid

            exe = Path(server["executable"])
            workdir = Path(server["working_directory"] or exe.parent)
            if not exe.is_file():
                raise FileNotFoundError(f"No existe el ejecutable: {exe}")
            if not workdir.is_dir():
                raise FileNotFoundError(f"No existe la carpeta de trabajo: {workdir}")

            steam_appid_file = exe.parent / "steam_appid.txt"
            expected_appid = "892970"
            try:
                current_appid = (
                    steam_appid_file.read_text(encoding="utf-8", errors="ignore").strip()
                    if steam_appid_file.exists()
                    else ""
                )
                if current_appid != expected_appid:
                    if steam_appid_file.exists():
                        backup_file = exe.parent / "steam_appid.txt.asgard_backup"
                        if not backup_file.exists():
                            backup_file.write_text(current_appid, encoding="utf-8")
                    steam_appid_file.write_text(expected_appid + "\n", encoding="utf-8")
                    self._event(
                        server_id,
                        "WARNING",
                        f"steam_appid.txt corregido de '{current_appid or 'vacío'}' a '{expected_appid}'",
                    )
            except OSError as exc:
                raise RuntimeError(f"No se pudo validar steam_appid.txt en {exe.parent}: {exc}") from exc

            # Keep Windows quoting exactly as configured while avoiding shell=True.
            command_line = f'"{exe}" {server["parameters"]}'
            creationflags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            child_env = os.environ.copy()
            child_env["SteamAppId"] = expected_appid
            child_env["SteamGameId"] = expected_appid

            self.invalidate_scan_cache()
            process = subprocess.Popen(
                command_line,
                cwd=str(workdir),
                shell=False,
                creationflags=creationflags,
                startupinfo=startupinfo,
                env=child_env,
            )
            self._managed[server_id] = ManagedProcess(
                server_id=server_id,
                pid=process.pid,
                process=process,
                started_at=time.time(),
            )

            time.sleep(1.2)
            exit_code = process.poll()
            if exit_code is not None:
                self.detach(server_id)
                raise RuntimeError(
                    f"valheim_server.exe terminó durante el arranque con código {exit_code}. "
                    "Revisa parámetros, carpeta de trabajo y el archivo -logFile."
                )

            # Final race check: never leave the newly spawned process alive when
            # another instance appeared between scan and Popen.
            self.invalidate_scan_cache()
            matches = self.scan_server(server, force_refresh=True)
            pids = [int(row["pid"]) for row in matches]
            if len(pids) > 1:
                try:
                    psutil.Process(process.pid).terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                self.detach(server_id)
                raise RuntimeError(
                    "Otro proceso del mismo servidor apareció durante el arranque. "
                    f"Nuevo PID {process.pid} cancelado; detectados: {', '.join(map(str, pids))}."
                )

            policy = normalize_policy(server.get("resource_policy"))
            if policy.get("enabled") and policy.get("apply_on_start", True):
                try:
                    self.resources.apply(server_id, process.pid, policy)
                except Exception as exc:
                    self._event(server_id, "WARNING", f"No se pudieron aplicar límites de recursos: {exc}")

            self._event(server_id, "INFO", f"Servidor iniciado con PID {process.pid}; steam_appid.txt={expected_appid}")
            return process.pid

    def stop_safe(self, server_id: int, timeout: int = 45) -> bool:
        with self._lock:
            item = self._managed.get(server_id)
            if not item or not self.is_alive(server_id):
                self.detach(server_id)
                return True
            pid = item.pid

        self._event(server_id, "INFO", f"Enviando CTRL+BREAK al grupo PID {pid}")
        try:
            os.kill(pid, signal.CTRL_BREAK_EVENT)
        except (OSError, ProcessLookupError) as exc:
            self._event(server_id, "WARNING", f"No se pudo enviar cierre seguro al PID {pid}: {exc}")
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_alive(server_id):
                self.detach(server_id)
                self._event(server_id, "INFO", "Servidor cerrado correctamente")
                return True
            time.sleep(0.5)

        self._event(server_id, "WARNING", "El servidor no respondió al cierre seguro")
        return False

    def kill_tree(self, server_id: int) -> bool:
        with self._lock:
            item = self._managed.get(server_id)
            if not item:
                self.resources.release(server_id)
                return True
            pid = item.pid

        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in reversed(children):
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            _, alive = psutil.wait_procs(children, timeout=5)
            for child in alive:
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            try:
                parent.terminate()
                parent.wait(timeout=5)
            except psutil.TimeoutExpired:
                parent.kill()
                parent.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
            self._event(server_id, "WARNING", f"Árbol PID {pid} terminado forzadamente")
            return True
        finally:
            self.detach(server_id)

    def kill_matching(self, server: dict) -> list[int]:
        """Force-stop every real process belonging to one configured server."""
        self.invalidate_scan_cache()
        pids = [int(row["pid"]) for row in self.scan_server(server, force_refresh=True)]
        stopped: list[int] = []
        for pid in pids:
            try:
                parent = psutil.Process(pid)
                children = parent.children(recursive=True)
                for child in reversed(children):
                    try:
                        child.terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                _, alive = psutil.wait_procs(children, timeout=4)
                for child in alive:
                    try:
                        child.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                try:
                    parent.terminate()
                    parent.wait(timeout=5)
                except psutil.TimeoutExpired:
                    parent.kill()
                    parent.wait(timeout=5)
                except psutil.NoSuchProcess:
                    pass
                stopped.append(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        self.detach(int(server["id"]))
        if stopped:
            self._event(int(server["id"]), "WARNING", "Procesos detenidos: " + ", ".join(map(str, stopped)))
        return stopped

    def apply_resources(self, server_id: int, policy: dict) -> dict:
        with self._lock:
            item = self._managed.get(server_id)
            if not item or not self.is_alive(server_id):
                raise RuntimeError("El servidor no está activo")
            pid = item.pid
        return self.resources.apply(server_id, pid, policy)

    def resource_status(self, server_id: int) -> dict:
        with self._lock:
            item = self._managed.get(server_id)
            pid = item.pid if item and self.is_alive(server_id) else None
        return self.resources.status(server_id, pid)

    def send_command(self, server_id: int, command: str) -> None:
        with self._lock:
            item = self._managed.get(server_id)
            if not item or not self.is_alive(server_id):
                raise RuntimeError("El servidor no está activo")
            pid = item.pid
        send_console_command(pid, command)
        self._event(server_id, "INFO", f"Comando enviado: {command}")

    def metrics(self, server_id: int) -> dict:
        with self._lock:
            item = self._managed.get(server_id)
            if not item or not self.is_alive(server_id):
                return {
                    "alive": False,
                    "pid": None,
                    "cpu_percent": 0.0,
                    "ram_mb": 0.0,
                    "uptime_seconds": 0,
                }
            pid = item.pid
            started_at = item.started_at

        try:
            root = psutil.Process(pid)
            processes = [root] + root.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self.detach(server_id)
            return {
                "alive": False,
                "pid": None,
                "cpu_percent": 0.0,
                "ram_mb": 0.0,
                "uptime_seconds": 0,
            }

        total_cpu_seconds = 0.0
        ram = 0
        for proc in processes:
            try:
                times = proc.cpu_times()
                total_cpu_seconds += times.user + times.system
                ram += proc.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        now = time.monotonic()
        previous = self._cpu_samples.get(server_id)
        cpu_percent = 0.0
        if previous:
            prev_time, prev_cpu = previous
            elapsed = now - prev_time
            if elapsed > 0:
                logical_cpus = max(1, psutil.cpu_count(logical=True) or 1)
                raw_percent = (total_cpu_seconds - prev_cpu) / elapsed * 100.0
                cpu_percent = max(0.0, min(100.0, raw_percent / logical_cpus))
        self._cpu_samples[server_id] = (now, total_cpu_seconds)

        return {
            "alive": True,
            "pid": pid,
            "cpu_percent": round(cpu_percent, 1),
            "ram_mb": round(ram / (1024 ** 2), 1),
            "uptime_seconds": max(0, int(time.time() - started_at)),
        }
