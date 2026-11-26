from __future__ import annotations

import base64
import hashlib
import json
import ntpath
import os
import secrets
import shutil
import socket
import stat
import tempfile
import time
import zipfile
from pathlib import Path, PureWindowsPath
from typing import Callable, Iterable

import paramiko
import requests

from common import APP_DIR, APP_DATA_DIR, MOD_LIBRARY_ROOT, CONFIG_LIBRARY_ROOT, REMOTE_DOWNLOADS_DIR
from credential_vault import decrypt_text, encrypt_text
from database import connect


class RemoteError(RuntimeError):
    pass


def _ps_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _ps_encoded(script: str) -> str:
    payload = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return f"powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {payload}"


def _remote_path(value: str) -> str:
    return str(value).replace("\\", "/")


def _parent_windows(value: str) -> str:
    return str(PureWindowsPath(value).parent)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


class RemoteManager:
    def __init__(self, event_callback: Callable[[int | None, str, str], None]):
        self.event = event_callback

    # ---------- Database ----------
    def list_hosts(self, include_secrets: bool = False) -> list[dict]:
        with connect() as conn:
            rows = conn.execute("SELECT * FROM remote_hosts ORDER BY name COLLATE NOCASE").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            password_blob = item.pop("password_encrypted", "")
            token_blob = item.pop("api_token_encrypted", "")
            item["password"] = decrypt_text(password_blob) if include_secrets else ""
            item["api_token"] = decrypt_text(token_blob) if include_secrets else ""
            item["has_password"] = bool(password_blob)
            item["has_api_token"] = bool(token_blob)
            result.append(item)
        return result

    def get_host(self, host_id: int, include_secrets: bool = True) -> dict:
        with connect() as conn:
            row = conn.execute("SELECT * FROM remote_hosts WHERE id=?", (host_id,)).fetchone()
        if row is None:
            raise KeyError("Host remoto no encontrado")
        item = dict(row)
        password_blob = item.pop("password_encrypted", "")
        token_blob = item.pop("api_token_encrypted", "")
        item["password"] = decrypt_text(password_blob) if include_secrets else ""
        item["api_token"] = decrypt_text(token_blob) if include_secrets else ""
        item["has_password"] = bool(password_blob)
        item["has_api_token"] = bool(token_blob)
        return item

    def save_host(self, data: dict, host_id: int | None = None) -> dict:
        name = str(data.get("name", "")).strip()
        address = str(data.get("address", "")).strip()
        username = str(data.get("username", "")).strip()
        if not name or not address or not username:
            raise ValueError("Nombre, dirección y usuario son obligatorios")
        current = self.get_host(host_id) if host_id else {}
        password = data.get("password")
        if password in (None, "") and current:
            password = current.get("password", "")
        api_token = data.get("api_token")
        if not api_token:
            api_token = current.get("api_token") or secrets.token_urlsafe(32)
        values = (
            name,
            address,
            int(data.get("ssh_port", 22)),
            username,
            str(data.get("auth_type", "password")),
            encrypt_text(str(password or "")),
            str(data.get("key_path", "")).strip(),
            int(data.get("agent_port", 8766)),
            encrypt_text(str(api_token)),
            str(data.get("remote_base", "C:/ASGARDRemote")).strip() or "C:/ASGARDRemote",
            str(data.get("tailscale_ip", "")).strip(),
            int(bool(data.get("enabled", True))),
        )
        with connect() as conn:
            if host_id:
                conn.execute(
                    """
                    UPDATE remote_hosts SET name=?,address=?,ssh_port=?,username=?,auth_type=?,
                        password_encrypted=?,key_path=?,agent_port=?,api_token_encrypted=?,
                        remote_base=?,tailscale_ip=?,enabled=?,updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    values + (host_id,),
                )
                target_id = host_id
            else:
                cur = conn.execute(
                    """
                    INSERT INTO remote_hosts(name,address,ssh_port,username,auth_type,
                        password_encrypted,key_path,agent_port,api_token_encrypted,
                        remote_base,tailscale_ip,enabled)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    values,
                )
                target_id = int(cur.lastrowid)
        self.event(None, "INFO", f"Host remoto guardado: {name}")
        return self.get_host(target_id, include_secrets=False)

    def delete_host(self, host_id: int) -> None:
        host = self.get_host(host_id, include_secrets=False)
        with connect() as conn:
            conn.execute("DELETE FROM remote_hosts WHERE id=?", (host_id,))
        self.event(None, "WARNING", f"Host remoto eliminado: {host['name']}")

    def list_remote_servers(self, host_id: int | None = None, refresh: bool = True) -> list[dict]:
        sql = """
            SELECT rs.*, rh.name AS host_name, rh.address, rh.tailscale_ip, rh.agent_port,
                   rh.api_token_encrypted
            FROM remote_servers rs JOIN remote_hosts rh ON rh.id=rs.host_id
        """
        params: tuple = ()
        if host_id:
            sql += " WHERE rs.host_id=?"
            params = (host_id,)
        sql += " ORDER BY rh.name COLLATE NOCASE, rs.name COLLATE NOCASE"
        with connect() as conn:
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        for row in rows:
            row.pop("api_token_encrypted", None)
        if not refresh:
            return rows
        grouped: dict[int, list[dict]] = {}
        for row in rows:
            grouped.setdefault(int(row["host_id"]), []).append(row)
        for hid, items in grouped.items():
            try:
                live = {int(x["id"]): x for x in self.agent_request(hid, "GET", "/servers")}
                for item in items:
                    runtime = live.get(int(item["agent_server_id"] or 0), {})
                    item.update({
                        "status": runtime.get("status", "NO REGISTRADO"),
                        "alive": runtime.get("alive", False),
                        "pid": runtime.get("pid"),
                        "cpu_percent": runtime.get("cpu_percent", 0.0),
                        "ram_mb": runtime.get("ram_mb", 0.0),
                        "uptime_seconds": runtime.get("uptime_seconds", 0),
                    })
            except Exception as exc:
                for item in items:
                    item.update({"status": "HOST DESCONECTADO", "alive": False, "last_error": str(exc)})
        return rows

    def register_remote_server(self, host_id: int, data: dict) -> dict:
        payload = {
            "name": str(data.get("name") or "Servidor remoto"),
            "executable": str(data.get("executable", "")),
            "parameters": str(data.get("parameters", "")),
            "working_directory": str(data.get("working_directory") or _parent_windows(data.get("executable", ""))),
            "savedir": str(data.get("savedir", "")),
            "log_file": str(data.get("log_file", "")),
            "backup_directory": str(data.get("backup_directory", "")),
            "backup_retention": int(data.get("backup_retention", 10)),
            "auto_start": bool(data.get("auto_start", False)),
        }
        if not payload["executable"]:
            raise ValueError("Falta el ejecutable remoto")
        response = self.agent_request(host_id, "POST", "/servers", payload)
        with connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO remote_servers(host_id,agent_server_id,name,executable,parameters,
                    working_directory,savedir,log_file,backup_directory,backup_retention,auto_start)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    host_id, int(response["id"]), payload["name"], payload["executable"],
                    payload["parameters"], payload["working_directory"], payload["savedir"],
                    payload["log_file"], payload["backup_directory"], payload["backup_retention"],
                    int(payload["auto_start"]),
                ),
            )
            local_id = int(cur.lastrowid)
        self.event(None, "INFO", f"Servidor remoto registrado: {payload['name']}")
        return {"id": local_id, "agent_server_id": response["id"]}

    def delete_remote_server(self, remote_server_id: int) -> None:
        server = self.get_remote_server(remote_server_id)
        if server.get("agent_server_id"):
            try:
                self.agent_request(server["host_id"], "DELETE", f"/servers/{server['agent_server_id']}")
            except Exception:
                pass
        with connect() as conn:
            conn.execute("DELETE FROM remote_servers WHERE id=?", (remote_server_id,))

    def get_remote_server(self, remote_server_id: int) -> dict:
        with connect() as conn:
            row = conn.execute("SELECT * FROM remote_servers WHERE id=?", (remote_server_id,)).fetchone()
        if row is None:
            raise KeyError("Servidor remoto no encontrado")
        return dict(row)

    # ---------- SSH / agent ----------
    def _connect(self, host: dict) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = {
            "hostname": host["address"],
            "port": int(host["ssh_port"]),
            "username": host["username"],
            "timeout": 12,
            "banner_timeout": 12,
            "auth_timeout": 12,
            "look_for_keys": False,
            "allow_agent": False,
        }
        if host.get("auth_type") == "key":
            key_path = host.get("key_path", "")
            if not key_path or not Path(key_path).is_file():
                raise FileNotFoundError("No existe la clave privada configurada")
            kwargs["key_filename"] = key_path
            if host.get("password"):
                kwargs["passphrase"] = host["password"]
        else:
            kwargs["password"] = host.get("password", "")
        client.connect(**kwargs)
        return client

    def install_ssh_key(self, host_id: int) -> dict:
        host = self.get_host(host_id)
        if not host.get("password"):
            raise RemoteError("Se necesita la contraseña actual una vez para instalar la clave SSH")
        key_dir = APP_DATA_DIR / "ssh_keys"
        key_dir.mkdir(parents=True, exist_ok=True)
        private_path = key_dir / f"host_{host_id}_asgard_rsa.pem"
        key = paramiko.RSAKey.generate(3072)
        key.write_private_key_file(str(private_path))
        try:
            os.chmod(private_path, 0o600)
        except OSError:
            pass
        public_line = f"{key.get_name()} {key.get_base64()} ASGARD-{host['name']}"
        client = self._connect(host)
        try:
            script = f"""
$ErrorActionPreference='Stop'
$key={_ps_literal(public_line)}
$isAdmin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if($isAdmin){{
  $auth='C:\\ProgramData\\ssh\\administrators_authorized_keys'
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $auth)|Out-Null
}} else {{
  $ssh=Join-Path $HOME '.ssh';New-Item -ItemType Directory -Force -Path $ssh|Out-Null
  $auth=Join-Path $ssh 'authorized_keys'
}}
if(-not (Test-Path -LiteralPath $auth)){{New-Item -ItemType File -Force -Path $auth|Out-Null}}
if(-not (Select-String -LiteralPath $auth -SimpleMatch $key -Quiet)){{Add-Content -LiteralPath $auth -Value $key -Encoding ascii}}
if($isAdmin){{icacls $auth /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F'|Out-Null}}
[ordered]@{{authorized_keys=$auth;admin=$isAdmin}}|ConvertTo-Json -Compress
"""
            _stdin, stdout, stderr = client.exec_command(_ps_encoded(script), timeout=60)
            output = stdout.read().decode("utf-8", errors="replace").strip()
            error = stderr.read().decode("utf-8", errors="replace").strip()
            status = stdout.channel.recv_exit_status()
            if status != 0:
                raise RemoteError(error or output or "No se pudo instalar la clave")
        finally:
            client.close()
        # Comprueba la clave antes de cambiar la configuración persistente.
        test_host = dict(host)
        test_host["auth_type"] = "key"
        test_host["key_path"] = str(private_path)
        test_host["password"] = ""
        test_client = self._connect(test_host)
        test_client.close()
        with connect() as conn:
            conn.execute(
                "UPDATE remote_hosts SET auth_type='key',key_path=?,password_encrypted='',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (str(private_path), host_id),
            )
        tested = self.test_ssh(host_id)
        self.event(None, "INFO", f"Clave SSH instalada para {host['name']}")
        return {"key_path": str(private_path), "remote": json.loads(output.splitlines()[-1]), "test": tested}

    def run_ps(self, host_id: int, script: str, timeout: int = 60) -> str:
        host = self.get_host(host_id)
        client = self._connect(host)
        try:
            _stdin, stdout, stderr = client.exec_command(_ps_encoded(script), timeout=timeout)
            output = stdout.read().decode("utf-8", errors="replace").strip()
            error = stderr.read().decode("utf-8", errors="replace").strip()
            status = stdout.channel.recv_exit_status()
            if status != 0:
                raise RemoteError(error or output or f"PowerShell terminó con código {status}")
            return output
        finally:
            client.close()

    def test_ssh(self, host_id: int) -> dict:
        started = time.monotonic()
        output = self.run_ps(
            host_id,
            "$o=[ordered]@{computer=$env:COMPUTERNAME;user=[Environment]::UserName;"
            "windows=[Environment]::OSVersion.VersionString;admin=([Security.Principal.WindowsPrincipal]"
            "[Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)};"
            "$o|ConvertTo-Json -Compress",
            timeout=20,
        )
        data = json.loads(output.splitlines()[-1])
        data["latency_ms"] = round((time.monotonic() - started) * 1000)
        return data

    def _agent_base_url(self, host: dict) -> str:
        address = host.get("tailscale_ip") or host["address"]
        if ":" in address and not address.startswith("["):
            address = f"[{address}]"
        return f"http://{address}:{int(host['agent_port'])}"

    def agent_request(self, host_id: int, method: str, path: str, payload=None, timeout: int = 30):
        host = self.get_host(host_id)
        token = host.get("api_token", "")
        if not token:
            raise RemoteError("El host no tiene token de agente")
        response = requests.request(
            method,
            self._agent_base_url(host) + path,
            headers={"X-ASGARD-Token": token},
            json=payload,
            timeout=timeout,
        )
        try:
            data = response.json()
        except ValueError:
            data = {"error": response.text[:500]}
        if response.status_code >= 400:
            raise RemoteError(data.get("error", f"HTTP {response.status_code}"))
        return data

    def test_agent(self, host_id: int) -> dict:
        return self.agent_request(host_id, "GET", "/health", timeout=8)

    def _ensure_sftp_dir(self, sftp: paramiko.SFTPClient, path: str) -> None:
        clean = _remote_path(path).rstrip("/")
        parts = clean.split("/")
        current = parts[0]
        for part in parts[1:]:
            current += "/" + part
            try:
                sftp.stat(current)
            except OSError:
                sftp.mkdir(current)

    def _upload_file(self, host: dict, local: Path, remote: str, client=None) -> bool:
        own = client is None
        client = client or self._connect(host)
        try:
            sftp = client.open_sftp()
            try:
                self._ensure_sftp_dir(sftp, ntpath.dirname(remote))
                local_hash = _sha256(local)
                remote_hash = ""
                try:
                    script = f"if(Test-Path -LiteralPath {_ps_literal(remote)}){{(Get-FileHash -Algorithm SHA256 -LiteralPath {_ps_literal(remote)}).Hash.ToLower()}}"
                    _stdin, stdout, _stderr = client.exec_command(_ps_encoded(script), timeout=60)
                    remote_hash = stdout.read().decode("utf-8", errors="replace").strip().splitlines()[-1].lower()
                except Exception:
                    remote_hash = ""
                if remote_hash == local_hash:
                    return False
                temporary = remote + ".asgard-upload"
                sftp.put(str(local), _remote_path(temporary))
                script = (
                    f"$src={_ps_literal(temporary)};$dst={_ps_literal(remote)};"
                    "$parent=Split-Path -Parent $dst;New-Item -ItemType Directory -Force -Path $parent|Out-Null;"
                    "Move-Item -Force -LiteralPath $src -Destination $dst"
                )
                _stdin, stdout, stderr = client.exec_command(_ps_encoded(script), timeout=60)
                stdout.channel.recv_exit_status()
                error = stderr.read().decode("utf-8", errors="replace").strip()
                if error:
                    raise RemoteError(error)
                return True
            finally:
                sftp.close()
        finally:
            if own:
                client.close()

    def autoconfigure_agent(self, host_id: int) -> dict:
        host = self.get_host(host_id)
        key_result = None
        if host.get("auth_type") == "password" and host.get("password"):
            try:
                key_result = self.install_ssh_key(host_id)
                host = self.get_host(host_id)
            except Exception as exc:
                self.event(None, "WARNING", f"No se pudo migrar a clave SSH; se continuará con contraseña: {exc}")
        package_candidates = [
            APP_DIR / "RemoteAgentPackage" / "ASGARD_Remote_Agent.exe",
            APP_DIR / "ASGARD_Remote_Agent.exe",
        ]
        executable = next((p for p in package_candidates if p.is_file()), None)
        if executable is None:
            raise FileNotFoundError(
                "No se encontró ASGARD_Remote_Agent.exe. Compila la edición portable completa primero."
            )
        base = host["remote_base"].replace("/", "\\")
        agent_dir = ntpath.join(base, "Agent")
        remote_exe = ntpath.join(agent_dir, "ASGARD_Remote_Agent.exe")
        remote_config = ntpath.join(agent_dir, "agent_config.json")
        config = {
            "bind": "0.0.0.0",
            "port": int(host["agent_port"]),
            "token": host["api_token"],
            "data_directory": ntpath.join(agent_dir, "AgentData"),
        }
        with tempfile.TemporaryDirectory(prefix="asgard-agent-") as tmp:
            cfg = Path(tmp) / "agent_config.json"
            cfg.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            client = self._connect(host)
            try:
                self._upload_file(host, executable, remote_exe, client=client)
                self._upload_file(host, cfg, remote_config, client=client)
            finally:
                client.close()

        task_command = remote_exe.replace('"', '""')
        script = f"""
$ErrorActionPreference='Stop'
$exe={_ps_literal(remote_exe)}
$dir={_ps_literal(agent_dir)}
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$rule=Get-NetFirewallRule -DisplayName 'ASGARD Remote Agent LAN' -ErrorAction SilentlyContinue
if(-not $rule){{New-NetFirewallRule -DisplayName 'ASGARD Remote Agent LAN' -Direction Inbound -Action Allow -Protocol TCP -LocalPort {int(host['agent_port'])} -Profile Private | Out-Null}}
$tsRule=Get-NetFirewallRule -DisplayName 'ASGARD Remote Agent Tailscale' -ErrorAction SilentlyContinue
if(-not $tsRule){{New-NetFirewallRule -DisplayName 'ASGARD Remote Agent Tailscale' -Direction Inbound -Action Allow -Protocol TCP -LocalPort {int(host['agent_port'])} -RemoteAddress '100.64.0.0/10','fd7a:115c:a1e0::/48' | Out-Null}}
$action=New-ScheduledTaskAction -Execute $exe -WorkingDirectory $dir
$trigger=New-ScheduledTaskTrigger -AtStartup
$principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
$tailscale=''
$ts=Get-Command tailscale.exe -ErrorAction SilentlyContinue
if($ts){{try{{& $ts.Source up --unattended=true | Out-Null;$tailscale=(& $ts.Source ip -4 | Select-Object -First 1)}}catch{{}}}}
Register-ScheduledTask -TaskName 'ASGARDRemoteAgent' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'ASGARDRemoteAgent'
[ordered]@{{exe=$exe;task='ASGARDRemoteAgent';port={int(host['agent_port'])};tailscale=$tailscale}}|ConvertTo-Json -Compress
"""
        output = self.run_ps(host_id, script, timeout=90)
        installation = json.loads(output.splitlines()[-1])
        detected_ts = str(installation.get("tailscale") or "").strip()
        if detected_ts and not host.get("tailscale_ip"):
            with connect() as conn:
                conn.execute("UPDATE remote_hosts SET tailscale_ip=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (detected_ts, host_id))
            host = self.get_host(host_id)
        time.sleep(2)
        health = self.test_agent(host_id)
        self.event(None, "INFO", f"Agente remoto configurado en {host['name']}")
        return {"installation": installation, "health": health, "ssh_key": key_result}

    def discover_servers(self, host_id: int, root: str = "") -> list[dict]:
        try:
            return self.agent_request(host_id, "POST", "/servers/discover", {"root": root}, timeout=120)
        except Exception:
            search_root = root or "C:/games"
            script = f"""
$root={_ps_literal(search_root)}
if(-not (Test-Path -LiteralPath $root)){{throw 'No existe la raíz de búsqueda'}}
Get-ChildItem -LiteralPath $root -Filter valheim_server.exe -File -Recurse -ErrorAction SilentlyContinue |
 Select-Object -First 50 | ForEach-Object {{
   $bat=Get-ChildItem -LiteralPath $_.Directory.FullName -Filter *.bat -File -ErrorAction SilentlyContinue | Select-Object -First 1
   [ordered]@{{name=$_.Directory.Name;executable=$_.FullName;working_directory=$_.Directory.FullName;parameters='-nographics -batchmode -name "Servidor remoto" -port 2456 -world "Dedicated" -password "CAMBIAR" -crossplay -public 1';start_bat=if($bat){{$bat.FullName}}else{{''}}}}
 }} | ConvertTo-Json -Compress
"""
            output = self.run_ps(host_id, script, timeout=120)
            if not output:
                return []
            parsed = json.loads(output.splitlines()[-1])
            return parsed if isinstance(parsed, list) else [parsed]

    def control_server(self, remote_server_id: int, action: str, payload=None):
        server = self.get_remote_server(remote_server_id)
        return self.agent_request(
            int(server["host_id"]), "POST",
            f"/servers/{int(server['agent_server_id'])}/{action}", payload or {}, timeout=120,
        )

    def get_remote_resources(self, remote_server_id: int) -> dict:
        server = self.get_remote_server(remote_server_id)
        return self.agent_request(
            int(server["host_id"]), "GET",
            f"/servers/{int(server['agent_server_id'])}/resources", timeout=30,
        )

    def save_remote_resources(self, remote_server_id: int, data: dict) -> dict:
        server = self.get_remote_server(remote_server_id)
        return self.agent_request(
            int(server["host_id"]), "PUT",
            f"/servers/{int(server['agent_server_id'])}/resources", data, timeout=45,
        )

    def apply_remote_resources(self, remote_server_id: int) -> dict:
        return self.control_server(remote_server_id, "resources-apply", {})

    def autoconfigure_remote_resources(self, remote_server_id: int, profile: str) -> dict:
        return self.control_server(
            remote_server_id, "resources-autoconfigure", {"profile": profile}
        )

    def remote_logs(self, remote_server_id: int, lines: int = 300) -> dict:
        server = self.get_remote_server(remote_server_id)
        return self.agent_request(
            int(server["host_id"]), "GET",
            f"/servers/{int(server['agent_server_id'])}/logs?lines={int(lines)}", timeout=30,
        )

    # ---------- SFTP explorer / downloads ----------
    def _scope_root(self, server: dict, host: dict, scope: str) -> str:
        if scope == "savedir":
            value = server.get("savedir", "")
            if not value:
                raise RemoteError("El servidor no tiene Savedir configurado")
            return value
        if scope == "backups":
            return server.get("backup_directory") or ntpath.join(
                host["remote_base"], "Agent", "AgentData", "backups",
                str(server.get("agent_server_id") or server["id"]),
            )
        return _parent_windows(server["executable"])

    def _safe_remote_target(self, root: str, relative: str = "") -> str:
        normalized_root = ntpath.normpath(root)
        target = ntpath.normpath(ntpath.join(normalized_root, relative.replace("/", "\\")))
        root_cmp = normalized_root.rstrip("\\/").lower()
        target_cmp = target.lower()
        if target_cmp != root_cmp and not target_cmp.startswith(root_cmp + "\\"):
            raise ValueError("Ruta remota fuera del alcance permitido")
        return target

    def list_remote_files(self, remote_server_id: int, scope: str = "server", relative: str = "") -> dict:
        server = self.get_remote_server(remote_server_id)
        host = self.get_host(int(server["host_id"]))
        root = self._scope_root(server, host, scope)
        target = self._safe_remote_target(root, relative)
        client = self._connect(host)
        try:
            sftp = client.open_sftp()
            try:
                entries = []
                for attr in sorted(sftp.listdir_attr(_remote_path(target)), key=lambda a: (not stat.S_ISDIR(a.st_mode), a.filename.lower())):
                    entries.append({
                        "name": attr.filename,
                        "is_dir": stat.S_ISDIR(attr.st_mode),
                        "size": int(attr.st_size),
                        "mtime": int(attr.st_mtime),
                        "relative_path": str(PureWindowsPath(relative) / attr.filename).replace("\\", "/"),
                    })
            finally:
                sftp.close()
        finally:
            client.close()
        parent = ""
        if relative:
            parent = str(PureWindowsPath(relative).parent).replace("\\", "/")
            if parent == ".":
                parent = ""
        return {"scope": scope, "path": relative, "parent": parent, "root": root, "entries": entries}

    def upload_external(self, remote_server_id: int, scope: str, relative_folder: str, local_path: str) -> dict:
        server = self.get_remote_server(remote_server_id)
        host = self.get_host(int(server["host_id"]))
        source = Path(local_path)
        if not source.exists():
            raise FileNotFoundError(source)
        root = self._scope_root(server, host, scope)
        folder = self._safe_remote_target(root, relative_folder)
        uploaded, skipped = [], []
        client = self._connect(host)
        try:
            if source.is_file():
                destination = ntpath.join(folder, source.name)
                changed = self._upload_file(host, source, destination, client=client)
                (uploaded if changed else skipped).append(destination)
            else:
                for file in source.rglob("*"):
                    if file.is_file():
                        destination = ntpath.join(folder, source.name, *file.relative_to(source).parts)
                        changed = self._upload_file(host, file, destination, client=client)
                        (uploaded if changed else skipped).append(destination)
        finally:
            client.close()
        return {"uploaded": uploaded, "skipped": skipped}

    def _download_tree(self, sftp: paramiko.SFTPClient, remote: str, local: Path) -> None:
        attrs = sftp.stat(_remote_path(remote))
        if stat.S_ISDIR(attrs.st_mode):
            local.mkdir(parents=True, exist_ok=True)
            for item in sftp.listdir_attr(_remote_path(remote)):
                self._download_tree(sftp, ntpath.join(remote, item.filename), local / item.filename)
        else:
            local.parent.mkdir(parents=True, exist_ok=True)
            sftp.get(_remote_path(remote), str(local))

    def download_remote(self, remote_server_id: int, scope: str, relative: str) -> dict:
        server = self.get_remote_server(remote_server_id)
        host = self.get_host(int(server["host_id"]))
        root = self._scope_root(server, host, scope)
        remote = self._safe_remote_target(root, relative)
        safe_host = "".join(c if c.isalnum() or c in "-_ " else "_" for c in host["name"]).strip()
        safe_server = "".join(c if c.isalnum() or c in "-_ " else "_" for c in server["name"]).strip()
        local = REMOTE_DOWNLOADS_DIR / safe_host / safe_server / Path(relative.replace("\\", "/")).name
        client = self._connect(host)
        try:
            sftp = client.open_sftp()
            try:
                self._download_tree(sftp, remote, local)
            finally:
                sftp.close()
        finally:
            client.close()
        return {"local_path": str(local), "remote_path": remote}

    def backup_and_download(self, remote_server_id: int) -> dict:
        server = self.get_remote_server(remote_server_id)
        host = self.get_host(int(server["host_id"]))
        backup = self.control_server(remote_server_id, "backup", {"reason": "manual_descargado"})
        remote = str(backup["path"])
        safe_host = "".join(c if c.isalnum() or c in "-_ " else "_" for c in host["name"]).strip()
        safe_server = "".join(c if c.isalnum() or c in "-_ " else "_" for c in server["name"]).strip()
        local = REMOTE_DOWNLOADS_DIR / safe_host / safe_server / Path(remote.replace("\\", "/")).name
        client = self._connect(host)
        try:
            sftp = client.open_sftp()
            try:
                local.parent.mkdir(parents=True, exist_ok=True)
                sftp.get(_remote_path(remote), str(local))
            finally:
                sftp.close()
        finally:
            client.close()
        return {"backup": backup, "local_path": str(local)}

    # ---------- Library deployment ----------
    def _library_source(self, kind: str, relative: str) -> Path:
        root = MOD_LIBRARY_ROOT if kind == "mods" else CONFIG_LIBRARY_ROOT
        source = (root / relative).resolve()
        if source != root.resolve() and root.resolve() not in source.parents:
            raise ValueError("Ruta fuera de la biblioteca")
        if not source.exists():
            raise FileNotFoundError(source)
        return source

    @staticmethod
    def _safe_extract_zip(archive: zipfile.ZipFile, destination: Path) -> None:
        root = destination.resolve()
        for member in archive.infolist():
            # ZIP files can contain ../ or absolute paths. Never allow a library
            # package to write outside the temporary staging directory.
            raw_name = member.filename.replace("\\", "/")
            if raw_name.startswith(("/", "\\")) or ":" in raw_name.split("/", 1)[0]:
                raise RemoteError(f"ZIP inseguro: ruta absoluta {member.filename}")
            target = (root / raw_name).resolve()
            if target != root and root not in target.parents:
                raise RemoteError(f"ZIP inseguro: {member.filename}")
        archive.extractall(root)

    @staticmethod
    def _package_folder_name(source: Path) -> str:
        raw = source.stem if source.is_file() else source.name
        safe = "".join(c if c.isalnum() or c in "-_. " else "_" for c in raw).strip(" .")
        return safe or "ASGARD_Package"

    def _iter_files(self, source: Path, kind: str, staging: Path) -> Iterable[tuple[Path, str]]:
        base = source
        package_name = self._package_folder_name(source)
        if source.is_file() and source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as archive:
                self._safe_extract_zip(archive, staging)
            bep = next((x for x in staging.rglob("BepInEx") if x.is_dir()), None)
            if bep:
                base = bep
            else:
                children = [x for x in staging.iterdir() if x.name != "__MACOSX"]
                base = children[0] if len(children) == 1 and children[0].is_dir() else staging
        if kind == "mods":
            found = False
            for sub in ("plugins", "config", "patchers"):
                folder = base / sub
                if folder.is_dir():
                    found = True
                    for file in folder.rglob("*"):
                        if file.is_file():
                            yield file, f"BepInEx/{sub}/{file.relative_to(folder).as_posix()}"
            if found:
                return
            if base.is_file():
                yield base, f"BepInEx/plugins/{base.name}"
            else:
                # Preserve the complete mod directory. Many Valheim mods depend
                # on JSON, bundles or native files stored beside the DLL.
                for file in base.rglob("*"):
                    if file.is_file():
                        relative = file.relative_to(base).as_posix()
                        yield file, f"BepInEx/plugins/{package_name}/{relative}"
        else:
            config = next((x for x in base.rglob("config") if x.is_dir()), None) if base.is_dir() else None
            base = config or base
            if base.is_file():
                yield base, f"BepInEx/config/{base.name}"
            else:
                for file in base.rglob("*"):
                    if file.is_file():
                        yield file, f"BepInEx/config/{file.relative_to(base).as_posix()}"

    def deploy_library(self, remote_server_id: int, kind: str, relative: str) -> dict:
        if kind not in {"mods", "configs"}:
            raise ValueError("Tipo de biblioteca inválido")
        server = self.get_remote_server(remote_server_id)
        host = self.get_host(int(server["host_id"]))
        try:
            runtime = self.agent_request(int(server["host_id"]), "GET", "/servers")
            current = next((x for x in runtime if int(x["id"]) == int(server["agent_server_id"])), None)
            if current and current.get("alive"):
                raise RemoteError("Detén el servidor remoto antes de instalar archivos")
        except RemoteError:
            raise
        except Exception:
            pass
        source = self._library_source(kind, relative)
        server_root = _parent_windows(server["executable"])
        backup_root = ntpath.join(host["remote_base"].replace("/", "\\"), "Backups", str(remote_server_id))
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup_zip = ntpath.join(backup_root, f"BepInEx_{stamp}.zip")
        backup_script = f"""
$src={_ps_literal(ntpath.join(server_root, 'BepInEx'))}
$dst={_ps_literal(backup_zip)}
if(Test-Path -LiteralPath $src){{New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst)|Out-Null;Compress-Archive -Path (Join-Path $src '*') -DestinationPath $dst -Force}}
"""
        self.run_ps(int(server["host_id"]), backup_script, timeout=300)
        uploaded: list[str] = []
        skipped: list[str] = []
        client = self._connect(host)
        try:
            with tempfile.TemporaryDirectory(prefix="asgard-deploy-") as tmp:
                for local, relative_remote in self._iter_files(source, kind, Path(tmp)):
                    destination = ntpath.join(server_root, *relative_remote.split("/"))
                    changed = self._upload_file(host, local, destination, client=client)
                    (uploaded if changed else skipped).append(destination)
        finally:
            client.close()
        self.event(None, "INFO", f"Despliegue remoto {kind}: {len(uploaded)} actualizado(s), {len(skipped)} sin cambios")
        return {"backup": backup_zip, "uploaded": uploaded, "skipped": skipped}
