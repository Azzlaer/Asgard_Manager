from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import psutil

from common import APP_DIR, SERVICE_PID_PATH, SERVICE_URL


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
SERVICE_EXE_NAME = "ASGARD_Service.exe"


def _read_pid() -> int | None:
    try:
        value = SERVICE_PID_PATH.read_text(encoding="utf-8").strip()
        return int(value)
    except (OSError, ValueError):
        return None


def _same_path(left: str | Path, right: str | Path) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except (OSError, RuntimeError):
        return False


def _pid_is_asgard_service(pid: int) -> bool:
    try:
        proc = psutil.Process(pid)
        if not proc.is_running():
            return False

        service_exe = APP_DIR / SERVICE_EXE_NAME
        if service_exe.is_file() and _same_path(proc.exe(), service_exe):
            return True

        command = " ".join(proc.cmdline()).lower()
        return (
            ("host_service.py" in command or "asgard_service.py" in command)
            and str(APP_DIR).lower() in command
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return False


def _health() -> bool:
    try:
        with urlopen(f"{SERVICE_URL}/health", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


def status() -> tuple[bool, str]:
    pid = _read_pid()
    if pid and _pid_is_asgard_service(pid) and _health():
        return True, f"Servicio ASGARD activo. PID {pid}"
    if pid and _pid_is_asgard_service(pid):
        return True, f"Proceso ASGARD activo con PID {pid}, pero la API no responde."
    return False, "Servicio ASGARD detenido."


def _source_service_command() -> tuple[list[str], Path]:
    pythonw = APP_DIR / "pythonw.exe"
    if pythonw.is_file():
        interpreter = pythonw
    else:
        candidate = Path(sys.executable)
        if candidate.name.lower() == "python.exe":
            pythonw_candidate = candidate.with_name("pythonw.exe")
            interpreter = pythonw_candidate if pythonw_candidate.is_file() else candidate
        else:
            interpreter = candidate
    entry = APP_DIR / "asgard_service.py"
    if not entry.is_file():
        entry = APP_DIR / "host_service.py"
    return [str(interpreter), str(entry)], APP_DIR


def _service_command() -> tuple[list[str], Path]:
    service_exe = APP_DIR / SERVICE_EXE_NAME
    if service_exe.is_file():
        return [str(service_exe)], APP_DIR
    return _source_service_command()


def start() -> tuple[bool, str]:
    running, message = status()
    if running:
        return True, message

    try:
        SERVICE_PID_PATH.unlink(missing_ok=True)
    except OSError:
        pass

    command, cwd = _service_command()
    if len(command) == 2 and not Path(command[1]).is_file():
        return False, "No se encontró ASGARD_Service.exe ni el servicio Python."

    try:
        popen_kwargs = {
            "cwd": str(cwd),
            "close_fds": True,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = CREATE_NO_WINDOW | DETACHED_PROCESS
        else:
            popen_kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **popen_kwargs)
    except OSError as exc:
        return False, f"No se pudo iniciar el servicio ASGARD: {exc}"

    deadline = time.time() + 18
    while time.time() < deadline:
        if _health():
            pid = _read_pid() or process.pid
            return True, f"Servicio ASGARD iniciado. PID {pid}"
        if process.poll() is not None:
            return False, (
                "El servicio terminó durante el arranque con código "
                f"{process.returncode}. Revisa Data\\service_logs\\host_service.log."
            )
        time.sleep(0.4)

    return False, "El proceso se inició, pero la API no respondió a tiempo."


def _request_shutdown() -> bool:
    try:
        request = Request(
            f"{SERVICE_URL}/shutdown",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def stop() -> tuple[bool, str]:
    pid = _read_pid()

    if not pid or not _pid_is_asgard_service(pid):
        SERVICE_PID_PATH.unlink(missing_ok=True)
        return True, "El servicio ASGARD ya estaba detenido."

    _request_shutdown()

    deadline = time.time() + 12
    while time.time() < deadline:
        if not psutil.pid_exists(pid):
            SERVICE_PID_PATH.unlink(missing_ok=True)
            return True, f"Servicio ASGARD PID {pid} detenido correctamente."
        time.sleep(0.4)

    try:
        proc = psutil.Process(pid)
        if not _pid_is_asgard_service(pid):
            return False, "El PID cambió de propietario; se canceló el cierre por seguridad."
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except psutil.NoSuchProcess:
        pass

    SERVICE_PID_PATH.unlink(missing_ok=True)
    return True, f"Servicio ASGARD PID {pid} terminado."


def restart() -> tuple[bool, str]:
    ok, message = stop()
    if not ok:
        return False, message
    time.sleep(1)
    return start()


def main() -> int:
    action = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    handlers = {
        "start": start,
        "stop": stop,
        "restart": restart,
        "status": status,
    }
    if action not in handlers:
        print("Uso: ASGARD_Service_Control.exe start|stop|restart|status")
        return 2

    ok, message = handlers[action]()
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
