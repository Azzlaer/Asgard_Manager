from __future__ import annotations

import json
import re
import threading
from collections import deque
import time
from pathlib import Path
from typing import Callable, Optional

import requests

from database import connect


DISCORD_API = "https://discord.com/api/v10"
FILE_POLL_SECONDS = 0.5
STATE_RECOVERY_BYTES = 2 * 1024 * 1024
UPDATE_DEBOUNCE_SECONDS = 0.8
STATE_HEARTBEAT_SECONDS = 2.0

SESSION_STATE_PATTERN = re.compile(
    r'(?i)join\s+code\s+([0-9]{4,10}).*?(?:now|active\s+with)\s+(\d+)\s+player\(s\)'
)
STEAM_ID_PATTERN = re.compile(
    r'(?i)received\s+local\s+Platform\s+ID\s+((?:Steam|PlayFab|Xbox|Microsoft|PSN|Crossplay)[_:\-A-Za-z0-9]+)'
)
CHARACTER_NAME_PATTERN = re.compile(
    r'(?i)Got\s+character\s+ZDOID\s+from\s+(.+?)\s*:\s*\d+:\d+'
)


class DiscordRestClient:
    def __init__(self, token_getter: Callable[[], str], event_callback):
        self._token_getter = token_getter
        self._event_callback = event_callback
        self._session = requests.Session()
        self._lock = threading.Lock()

    def _headers(self):
        token = self._token_getter().strip()
        if not token:
            raise RuntimeError("No se configuró el token del bot.")
        return {
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "AsgardHostManager/6.0",
        }

    def request(self, method, endpoint, payload=None, retries=4):
        url = f"{DISCORD_API}{endpoint}"
        with self._lock:
            for attempt in range(retries):
                response = self._session.request(
                    method, url, headers=self._headers(), json=payload, timeout=20
                )
                if response.status_code == 429:
                    try:
                        delay = float(response.json().get("retry_after", 1.5))
                    except Exception:
                        delay = 1.5
                    time.sleep(max(0.5, delay))
                    continue
                if 200 <= response.status_code < 300:
                    if not response.content:
                        return {}
                    try:
                        return response.json()
                    except ValueError:
                        return {}
                if response.status_code >= 500 and attempt < retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(
                    f"Discord HTTP {response.status_code}: {response.text[:500]}"
                )
        raise RuntimeError("No fue posible completar la petición a Discord.")

    def get_bot(self):
        return self.request("GET", "/users/@me")

    def create_message(self, channel_id, content):
        if not channel_id:
            raise RuntimeError("Falta Channel ID de texto.")
        return self.request(
            "POST", f"/channels/{channel_id}/messages",
            {"content": content, "allowed_mentions": {"parse": []}},
        )

    def edit_message(self, channel_id, message_id, content):
        if not channel_id or not message_id:
            raise RuntimeError("Falta Channel ID o Message ID.")
        return self.request(
            "PATCH", f"/channels/{channel_id}/messages/{message_id}",
            {"content": content, "allowed_mentions": {"parse": []}},
        )

    def rename_channel(self, channel_id, name):
        if not channel_id:
            raise RuntimeError("Falta Channel ID de voz.")
        return self.request(
            "PATCH", f"/channels/{channel_id}", {"name": name.strip()[:100]}
        )


class DiscordServerMonitor:
    def __init__(self, server: dict, settings: dict, client: DiscordRestClient, event_callback):
        self.server = server
        self.settings = settings
        self.client = client
        self.event_callback = event_callback
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.position = 0
        self.join_code = "Esperando..."
        self.players = 0
        self.steam_ids: list[str] = []
        self.player_names: list[str] = []
        self.current_sessions: list[dict] = []
        self.pending_steam_ids = deque()
        self.batch_mode = False
        self.last_message = ""
        self.last_voice = ""
        self.update_due = 0.0
        self.update_dirty = False
        self.last_error = ""
        self.last_heartbeat = 0.0
        self.join_pattern = re.compile(settings["join_code_regex"])
        self.count_pattern = re.compile(settings["player_count_regex"])

    @property
    def server_id(self):
        return int(self.server["id"])

    def log(self, level, message):
        self.event_callback(self.server_id, level, message)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._run, name=f"DiscordMonitor-{self.server_id}", daemon=True
        )
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _persist_player(self, steam_id: str, player_name: str = "", increment: bool = False):
        if not steam_id:
            return
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO player_registry(server_id,steam_id,last_name)
                VALUES(?,?,?)
                ON CONFLICT(server_id,steam_id) DO UPDATE SET
                    last_name=CASE WHEN excluded.last_name<>'' THEN excluded.last_name ELSE player_registry.last_name END,
                    last_seen=CURRENT_TIMESTAMP,
                    seen_count=player_registry.seen_count + ?
                """,
                (self.server_id, steam_id, player_name, 1 if increment else 0),
            )

    def _sync_online_table(self):
        """Reconciliar la tabla sin reiniciar connected_at en cada refresco.

        Las sesiones con Steam/Platform ID se emparejan por ID; las todavía
        incompletas se emparejan por nombre o por el primer hueco disponible.
        De esta forma la ventana de jugadores puede refrescarse en vivo sin
        parpadear ni mostrar horas de conexión falsas.
        """
        if self.batch_mode:
            return
        desired = list(self.current_sessions[:max(0, self.players)])
        with connect() as conn:
            existing = [dict(row) for row in conn.execute(
                "SELECT * FROM online_players WHERE server_id=? ORDER BY id",
                (self.server_id,),
            ).fetchall()]
            used: set[int] = set()
            keep_ids: list[int] = []

            for session in desired:
                steam_id = str(session.get("steam_id", "") or "")
                player_name = str(session.get("player_name", "") or "")
                match = None
                if steam_id:
                    match = next((row for row in existing if row["id"] not in used and row.get("steam_id") == steam_id), None)
                if match is None and player_name:
                    match = next((row for row in existing if row["id"] not in used and row.get("player_name") == player_name), None)
                if match is None:
                    match = next((row for row in existing if row["id"] not in used and not row.get("steam_id") and not row.get("player_name")), None)

                if match is not None:
                    row_id = int(match["id"])
                    used.add(row_id)
                    keep_ids.append(row_id)
                    conn.execute(
                        "UPDATE online_players SET steam_id=?, player_name=? WHERE id=?",
                        (steam_id, player_name, row_id),
                    )
                else:
                    cursor = conn.execute(
                        "INSERT INTO online_players(server_id,steam_id,player_name) VALUES(?,?,?)",
                        (self.server_id, steam_id, player_name),
                    )
                    keep_ids.append(int(cursor.lastrowid))

            if keep_ids:
                marks = ",".join("?" for _ in keep_ids)
                conn.execute(
                    f"DELETE FROM online_players WHERE server_id=? AND id NOT IN ({marks})",
                    (self.server_id, *keep_ids),
                )
            else:
                conn.execute("DELETE FROM online_players WHERE server_id=?", (self.server_id,))

    def _save_runtime(self, error=None):
        if error is not None:
            self.last_error = str(error)
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO discord_runtime(
                    server_id,join_code,players,last_update,last_error,
                    steam_ids_json,player_names_json
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(server_id) DO UPDATE SET
                    join_code=excluded.join_code,
                    players=excluded.players,
                    last_update=excluded.last_update,
                    last_error=excluded.last_error,
                    steam_ids_json=excluded.steam_ids_json,
                    player_names_json=excluded.player_names_json
                """,
                (
                    self.server_id, self.join_code, self.players, time.time(), self.last_error,
                    json.dumps(self.steam_ids[-100:]),
                    json.dumps(self.player_names[-100:]),
                ),
            )

    def _recover(self, path: Path):
        """Reconstruye estado sin contar la lectura histórica como una nueva visita."""
        size = path.stat().st_size
        start = max(0, size - STATE_RECOVERY_BYTES)
        with path.open("rb") as fh:
            fh.seek(start)
            data = fh.read().decode("utf-8", errors="replace")
        if start > 0 and "\n" in data:
            data = data.split("\n", 1)[1]
        self.batch_mode = True
        try:
            for line in data.splitlines():
                self._process_line(line, schedule=False, recovery=True)
        finally:
            self.batch_mode = False
        self._sync_online_table()
        self._save_runtime()

    @staticmethod
    def _group(match):
        return match.group(1).strip() if match.lastindex else match.group(0).strip()

    def _find_session(self, steam_id: str) -> dict | None:
        return next(
            (session for session in reversed(self.current_sessions)
             if session.get("steam_id") == steam_id),
            None,
        )

    def _trim_sessions(self, count: int) -> None:
        """Ajusta el número de sesiones sin mover nombres entre Steam IDs."""
        count = max(0, count)
        while len(self.current_sessions) > count:
            empty_index = next(
                (i for i, session in enumerate(self.current_sessions)
                 if not session.get("steam_id") and not session.get("player_name")),
                None,
            )
            if empty_index is not None:
                self.current_sessions.pop(empty_index)
            else:
                # Valheim no incluye el ID en todas las líneas de desconexión.
                # Quitar la sesión más antigua es solo para la lista online; el
                # registro persistente Steam ID -> nombre ya no se reescribe.
                self.current_sessions.pop(0)
        while len(self.current_sessions) < count:
            self.current_sessions.append({"steam_id": "", "player_name": ""})

    def _process_line(self, line, schedule=True, recovery=False):
        changed = False
        state = SESSION_STATE_PATTERN.search(line)
        if state:
            code = state.group(1)
            count = max(0, min(int(state.group(2)), int(self.settings["max_players"])))
            if code != self.join_code:
                self.join_code = code
                changed = True
            if count != self.players:
                self.players = count
                self._trim_sessions(count)
                self._sync_online_table()
                changed = True
        else:
            code_match = self.join_pattern.search(line)
            if code_match:
                code = self._group(code_match)
                if code and code != self.join_code:
                    self.join_code = code
                    changed = True
            count_match = self.count_pattern.search(line)
            if count_match:
                count = max(
                    0, min(int(self._group(count_match)), int(self.settings["max_players"]))
                )
                if count != self.players:
                    self.players = count
                    self._trim_sessions(count)
                    self._sync_online_table()
                    changed = True

        steam = STEAM_ID_PATTERN.search(line)
        if steam:
            value = steam.group(1)
            if value not in self.steam_ids:
                self.steam_ids.append(value)

            target = self._find_session(value)
            if target is None:
                # Usa primero un hueco completamente vacío creado por el contador.
                target = next(
                    (session for session in self.current_sessions
                     if not session.get("steam_id") and not session.get("player_name")),
                    None,
                )
                if target is None:
                    target = {"steam_id": "", "player_name": ""}
                    self.current_sessions.append(target)
                target["steam_id"] = value

            if not target.get("player_name") and value not in self.pending_steam_ids:
                self.pending_steam_ids.append(value)
            self._persist_player(value, increment=not recovery)
            self._sync_online_table()
            changed = True

        name = CHARACTER_NAME_PATTERN.search(line)
        if name:
            value = name.group(1).strip()
            if value and value not in self.player_names:
                self.player_names.append(value)

            target = None
            # La línea Got character ZDOID suele aparecer después del Platform ID.
            # Se vincula al ID pendiente exacto, no al primer hueco genérico.
            while self.pending_steam_ids and target is None:
                steam_id = self.pending_steam_ids.popleft()
                candidate = self._find_session(steam_id)
                if candidate is not None and not candidate.get("player_name"):
                    target = candidate

            if target is None:
                target = next(
                    (session for session in reversed(self.current_sessions)
                     if session.get("steam_id") and not session.get("player_name")),
                    None,
                )
            if target is None:
                target = next(
                    (session for session in self.current_sessions
                     if not session.get("steam_id") and not session.get("player_name")),
                    None,
                )
            if target is None:
                target = {"steam_id": "", "player_name": ""}
                self.current_sessions.append(target)

            # Nunca copia el mismo nombre a otros Steam IDs por rellenar huecos.
            target["player_name"] = value
            steam_id = target.get("steam_id", "")
            if steam_id:
                self._persist_player(steam_id, value, increment=False)
            self._sync_online_table()
            changed = True

        if changed:
            if not self.batch_mode:
                self._save_runtime()
            if schedule and not self.batch_mode:
                self.update_dirty = True
                self.update_due = time.monotonic() + UPDATE_DEBOUNCE_SECONDS

    def _values(self):
        status = "En línea" if self.join_code != "Esperando..." else "Iniciando"
        maximum = max(1, int(self.settings["max_players"]))
        online_labels = []
        for index, session in enumerate(self.current_sessions[:max(0, self.players)], start=1):
            label = (session.get("player_name") or session.get("steam_id") or f"Jugador {index} (identificando...)").strip()
            online_labels.append(label)
        return {
            "server_name": self.server["name"],
            "status": status,
            "join_code": self.join_code,
            "players": self.players,
            "max_players": maximum,
            "occupancy": round((self.players / maximum) * 100),
            "player_list": ", ".join(online_labels) if online_labels else "Nadie conectado",
            "unix_time": int(time.time()),
        }

    def sync_discord(self, force=False):
        try:
            values = self._values()
            if self.settings["text_channel_id"] and self.settings["message_id"]:
                content = self.settings["message_template"].format(**values)
                if force or content != self.last_message:
                    self.client.edit_message(
                        self.settings["text_channel_id"],
                        self.settings["message_id"],
                        content,
                    )
                    self.last_message = content
            if self.settings["voice_channel_id"]:
                name = self.settings["voice_template"].format(**values)
                if force or name != self.last_voice:
                    self.client.rename_channel(self.settings["voice_channel_id"], name)
                    self.last_voice = name
            self._save_runtime("")
        except Exception as exc:
            self._save_runtime(str(exc))
            self.log("ERROR", f"Discord: {exc}")

    def _run(self):
        path = Path(self.server.get("log_file", ""))
        while not self.stop_event.is_set() and not path.is_file():
            time.sleep(2)
            path = Path(self.server.get("log_file", ""))
        if self.stop_event.is_set():
            return
        try:
            self._recover(path)
            self.position = path.stat().st_size
            self.sync_discord(force=True)
            self.log("INFO", "Monitor Discord iniciado")
            while not self.stop_event.is_set():
                try:
                    size = path.stat().st_size
                    if size < self.position:
                        self.position = 0
                        self.players = 0
                        self.steam_ids.clear()
                        self.player_names.clear()
                        self.current_sessions.clear()
                        self.pending_steam_ids.clear()
                        self._sync_online_table()
                    if size > self.position:
                        with path.open("r", encoding="utf-8", errors="replace") as fh:
                            fh.seek(self.position)
                            for line in fh:
                                self._process_line(line.rstrip("\r\n"))
                            self.position = fh.tell()
                    now = time.monotonic()
                    if self.update_dirty and now >= self.update_due:
                        self.update_dirty = False
                        self.sync_discord()
                    if now - self.last_heartbeat >= STATE_HEARTBEAT_SECONDS:
                        self._trim_sessions(self.players)
                        self._sync_online_table()
                        self._save_runtime()
                        self.last_heartbeat = now
                    time.sleep(FILE_POLL_SECONDS)
                except FileNotFoundError:
                    time.sleep(2)
                except Exception as exc:
                    self.log("ERROR", f"Lector Discord: {exc}")
                    time.sleep(2)
        finally:
            self.log("INFO", "Monitor Discord detenido")


class DiscordIntegrationManager:
    def __init__(self, event_callback):
        self.event_callback = event_callback
        self.client = DiscordRestClient(self.get_token, event_callback)
        self.monitors: dict[int, DiscordServerMonitor] = {}
        self.lock = threading.RLock()

    def get_token(self):
        with connect() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key='discord_bot_token'"
            ).fetchone()
        return row["value"] if row else ""

    def set_token(self, token):
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO app_settings(key,value) VALUES('discord_bot_token',?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """, (token.strip(),)
            )

    def get_settings(self, server_id):
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM discord_settings WHERE server_id=?", (server_id,)
            ).fetchone()
        if row:
            return dict(row)
        return {
            "server_id": server_id, "enabled": 0, "text_channel_id": "",
            "message_id": "", "voice_channel_id": "", "max_players": 100,
            "message_template": (
                "╭─────────── ⚔️ **ASGARD STATUS** ⚔️ ───────────╮\n"
                "│ 🏰 **Servidor:** {server_name}\n"
                "│ 🟢 **Estado:** {status}\n"
                "│ 🔑 **Join Code:** `{join_code}`\n"
                "│ 👥 **Jugadores:** **{players}/{max_players}**  ·  {occupancy}%\n"
                "│ 🎮 **En línea:** {player_list}\n"
                "│ 🕒 **Actualizado:** <t:{unix_time}:R>\n"
                "╰────────────────────────────────────────╯"
            ),
            "voice_template": "Jugadores: {players}/{max_players}",
            "join_code_regex": r"(?i)(?:registered\s+with|with)\s+join\s+code\s+([0-9]{4,10})",
            "player_count_regex": r"(?i)join\s+code\s+[0-9]{4,10}.*?(?:now|active\s+with)\s+(\d+)\s+player\(s\)",
        }

    def save_settings(self, server_id, data):
        re.compile(data["join_code_regex"])
        re.compile(data["player_count_regex"])
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO discord_settings(
                    server_id,enabled,text_channel_id,message_id,voice_channel_id,
                    max_players,message_template,voice_template,
                    join_code_regex,player_count_regex
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(server_id) DO UPDATE SET
                    enabled=excluded.enabled,
                    text_channel_id=excluded.text_channel_id,
                    message_id=excluded.message_id,
                    voice_channel_id=excluded.voice_channel_id,
                    max_players=excluded.max_players,
                    message_template=excluded.message_template,
                    voice_template=excluded.voice_template,
                    join_code_regex=excluded.join_code_regex,
                    player_count_regex=excluded.player_count_regex
                """,
                (
                    server_id, int(bool(data.get("enabled"))),
                    data.get("text_channel_id", ""), data.get("message_id", ""),
                    data.get("voice_channel_id", ""), int(data.get("max_players", 100)),
                    data["message_template"], data["voice_template"],
                    data["join_code_regex"], data["player_count_regex"],
                ),
            )
        self.restart_monitor(server_id)

    def get_server(self, server_id):
        with connect() as conn:
            row = conn.execute("SELECT * FROM servers WHERE id=?", (server_id,)).fetchone()
        if not row:
            raise KeyError("Servidor no encontrado")
        return dict(row)

    def start_monitor(self, server_id):
        settings = self.get_settings(server_id)
        if not settings["enabled"]:
            return
        server = self.get_server(server_id)
        if not server.get("log_file"):
            raise RuntimeError("Configura el archivo log del servidor.")
        with self.lock:
            old = self.monitors.get(server_id)
            if old and old.thread and old.thread.is_alive():
                return
            monitor = DiscordServerMonitor(server, settings, self.client, self.event_callback)
            self.monitors[server_id] = monitor
            monitor.start()

    def stop_monitor(self, server_id):
        with self.lock:
            monitor = self.monitors.pop(server_id, None)
        if monitor:
            monitor.stop()

    def restart_monitor(self, server_id):
        self.stop_monitor(server_id)
        settings = self.get_settings(server_id)
        if settings["enabled"]:
            self.start_monitor(server_id)

    def start_enabled(self, active_server_ids=None):
        active = None if active_server_ids is None else {int(value) for value in active_server_ids}
        with connect() as conn:
            rows = conn.execute("SELECT server_id FROM discord_settings WHERE enabled=1").fetchall()
        for row in rows:
            server_id = int(row["server_id"])
            if active is not None and server_id not in active:
                self.mark_offline(server_id, sync_discord=False)
                continue
            try:
                self.start_monitor(server_id)
            except Exception as exc:
                self.event_callback(server_id, "ERROR", f"Discord inicio: {exc}")

    def mark_offline(self, server_id, sync_discord=True):
        """Stop live telemetry and remove stale players/join code.

        This is intentionally called whenever process reconciliation proves the
        server is down. It prevents impossible panel rows such as DETENIDO with
        three online players and an old join code.
        """
        server_id = int(server_id)
        self.stop_monitor(server_id)
        now = time.time()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO discord_runtime(
                    server_id,join_code,players,last_update,last_error,
                    steam_ids_json,player_names_json
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(server_id) DO UPDATE SET
                    join_code=excluded.join_code,
                    players=excluded.players,
                    last_update=excluded.last_update,
                    last_error=excluded.last_error,
                    steam_ids_json=excluded.steam_ids_json,
                    player_names_json=excluded.player_names_json
                """,
                (server_id, "—", 0, now, "", "[]", "[]"),
            )
            conn.execute("DELETE FROM online_players WHERE server_id=?", (server_id,))

        if not sync_discord:
            return
        try:
            settings = self.get_settings(server_id)
            if not settings.get("enabled"):
                return
            server = self.get_server(server_id)
            maximum = max(1, int(settings.get("max_players", 100)))
            values = {
                "server_name": server["name"],
                "status": "Fuera de línea",
                "join_code": "—",
                "players": 0,
                "max_players": maximum,
                "occupancy": 0,
                "player_list": "Nadie conectado",
                "unix_time": int(now),
            }
            if settings.get("text_channel_id") and settings.get("message_id"):
                self.client.edit_message(
                    settings["text_channel_id"],
                    settings["message_id"],
                    settings["message_template"].format(**values),
                )
            if settings.get("voice_channel_id"):
                self.client.rename_channel(
                    settings["voice_channel_id"],
                    settings["voice_template"].format(**values),
                )
        except Exception as exc:
            self.event_callback(server_id, "ERROR", f"Discord estado offline: {exc}")

    def rebuild_player_registry(self, server_id):
        """Reconstruye Steam ID -> último nombre usando el log completo del servidor."""
        settings = self.get_settings(server_id)
        server = self.get_server(server_id)
        path = Path(server.get("log_file", ""))
        if not path.is_file():
            raise FileNotFoundError(
                "No se encontró el log configurado. Edita el servidor y selecciona su archivo de log."
            )

        with self.lock:
            old = self.monitors.pop(server_id, None)
        if old:
            old.stop()
            if old.thread and old.thread.is_alive():
                old.thread.join(timeout=3)

        try:
            with connect() as conn:
                conn.execute("DELETE FROM online_players WHERE server_id=?", (server_id,))
                conn.execute("DELETE FROM player_registry WHERE server_id=?", (server_id,))

            monitor = DiscordServerMonitor(server, settings, self.client, self.event_callback)
            monitor.batch_mode = True
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        monitor._process_line(
                            line.rstrip("\r\n"), schedule=False, recovery=True
                        )
            finally:
                monitor.batch_mode = False
            monitor._sync_online_table()
            monitor._save_runtime()

            with connect() as conn:
                count = int(conn.execute(
                    "SELECT COUNT(*) FROM player_registry WHERE server_id=?",
                    (server_id,),
                ).fetchone()[0])
            self.event_callback(
                server_id,
                "INFO",
                f"Registro persistente reconstruido desde el log: {count} jugador(es)",
            )
            return {"ok": True, "players": count, "log_file": str(path)}
        finally:
            if settings.get("enabled"):
                try:
                    self.start_monitor(server_id)
                except Exception as exc:
                    self.event_callback(
                        server_id, "ERROR", f"No se pudo reanudar monitor Discord: {exc}"
                    )

    def create_message(self, server_id):
        settings = self.get_settings(server_id)
        if not settings["text_channel_id"]:
            raise RuntimeError("Configura Channel ID de texto.")

        server = self.get_server(server_id)
        runtime = self.get_runtime(server_id)

        players = max(0, int(runtime.get("players", 0) or 0))
        max_players = max(1, int(settings.get("max_players", 100) or 100))
        join_code = runtime.get("join_code") or "Esperando..."
        status = "En línea" if join_code != "Esperando..." else "Iniciando"

        # Debe contener exactamente las mismas variables disponibles durante
        # la edición en tiempo real. La plantilla v5 usa {occupancy}.
        values = {
            "server_name": server["name"],
            "status": status,
            "join_code": join_code,
            "players": players,
            "max_players": max_players,
            "occupancy": round((players / max_players) * 100),
            "player_list": ", ".join(runtime.get("player_names", [])[-players:]) if players and runtime.get("player_names") else ("Nadie conectado" if players == 0 else "Identificando jugadores..."),
            "unix_time": int(time.time()),
        }

        try:
            content = settings["message_template"].format(**values)
        except KeyError as exc:
            raise RuntimeError(
                f"La plantilla de Discord contiene una variable no válida: {exc}. "
                "Variables disponibles: server_name, status, join_code, players, "
                "max_players, occupancy, player_list y unix_time."
            ) from exc

        result = self.client.create_message(
            settings["text_channel_id"],
            content,
        )

        message_id = result.get("id")
        if not message_id:
            raise RuntimeError(
                "Discord aceptó la petición, pero no devolvió el ID del mensaje."
            )

        settings["message_id"] = str(message_id)
        self.save_settings(server_id, settings)
        self.event_callback(
            server_id,
            "INFO",
            f"Mensaje Discord creado y guardado con ID {message_id}",
        )
        return {
            "message_id": settings["message_id"],
            "channel_id": settings["text_channel_id"],
        }

    def test_bot(self):
        return self.client.get_bot()

    def sync(self, server_id):
        self.start_monitor(server_id)
        monitor = self.monitors.get(server_id)
        if not monitor:
            raise RuntimeError("El monitor Discord no está habilitado.")
        monitor.sync_discord(force=True)
        return {"ok": True}

    def get_runtime(self, server_id):
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM discord_runtime WHERE server_id=?", (server_id,)
            ).fetchone()
        if not row:
            return {
                "server_id": server_id, "join_code": "Esperando...", "players": 0,
                "last_update": None, "last_error": "", "steam_ids": [], "player_names": []
            }
        data = dict(row)
        try:
            data["steam_ids"] = json.loads(data.pop("steam_ids_json"))
        except Exception:
            data["steam_ids"] = []
        try:
            data["player_names"] = json.loads(data.pop("player_names_json"))
        except Exception:
            data["player_names"] = []
        return data
