from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import datetime

from database import connect


class AutomationManager:
    """Supervisor de procesos, recuperación de caídas y reinicios programados."""

    def __init__(self, process_manager, start_callback, restart_callback, event_callback):
        self.process_manager = process_manager
        self.start_callback = start_callback
        self.restart_callback = restart_callback
        self.event_callback = event_callback
        self.stop_event = threading.Event()
        self.dead_since: dict[int, float] = {}
        self.restart_attempts: dict[int, deque[float]] = defaultdict(deque)
        self.invalid_time_reported: set[int] = set()
        self.cooldown_reported: set[int] = set()
        self.watchdog_in_progress: set[int] = set()
        self.scheduled_in_progress: set[int] = set()
        self.state_lock = threading.RLock()

    def get_settings(self, server_id):
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM server_automation WHERE server_id=?", (server_id,)
            ).fetchone()
        if row:
            return dict(row)
        return {
            "server_id": server_id,
            "watchdog_enabled": 0,
            "watchdog_delay": 15,
            "restart_enabled": 0,
            "restart_time": "04:00",
            "restart_backup": 1,
            "startup_grace": 90,
            "restart_cooldown": 300,
            "max_restart_attempts": 3,
            "force_kill_on_restart": 1,
        }

    @staticmethod
    def _valid_time(value: str) -> bool:
        try:
            datetime.strptime(value, "%H:%M")
            return True
        except ValueError:
            return False

    def save_settings(self, server_id, data):
        restart_time = str(data.get("restart_time", "04:00")).strip()
        if not self._valid_time(restart_time):
            raise ValueError("La hora de reinicio debe usar formato HH:MM, por ejemplo 04:00")
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO server_automation(
                    server_id,watchdog_enabled,watchdog_delay,restart_enabled,
                    restart_time,restart_backup,startup_grace,restart_cooldown,
                    max_restart_attempts,force_kill_on_restart
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(server_id) DO UPDATE SET
                    watchdog_enabled=excluded.watchdog_enabled,
                    watchdog_delay=excluded.watchdog_delay,
                    restart_enabled=excluded.restart_enabled,
                    restart_time=excluded.restart_time,
                    restart_backup=excluded.restart_backup,
                    startup_grace=excluded.startup_grace,
                    restart_cooldown=excluded.restart_cooldown,
                    max_restart_attempts=excluded.max_restart_attempts,
                    force_kill_on_restart=excluded.force_kill_on_restart
                """,
                (
                    server_id,
                    int(bool(data.get("watchdog_enabled"))),
                    max(5, int(data.get("watchdog_delay", 15))),
                    int(bool(data.get("restart_enabled"))),
                    restart_time,
                    int(bool(data.get("restart_backup", True))),
                    max(15, int(data.get("startup_grace", 90))),
                    max(60, int(data.get("restart_cooldown", 300))),
                    max(1, int(data.get("max_restart_attempts", 3))),
                    int(bool(data.get("force_kill_on_restart", True))),
                ),
            )
        self.invalid_time_reported.discard(int(server_id))

    def _runtime_row(self, server_id: int) -> dict:
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM automation_runtime WHERE server_id=?", (server_id,)
            ).fetchone()
        return dict(row) if row else {
            "server_id": server_id,
            "last_scheduled_date": "",
            "last_action": "",
            "consecutive_failures": 0,
            "cooldown_until": 0.0,
        }

    def _save_runtime(self, server_id: int, **values) -> None:
        current = self._runtime_row(server_id)
        current.update(values)
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO automation_runtime(
                    server_id,last_scheduled_date,last_action,
                    consecutive_failures,cooldown_until
                ) VALUES(?,?,?,?,?)
                ON CONFLICT(server_id) DO UPDATE SET
                    last_scheduled_date=excluded.last_scheduled_date,
                    last_action=excluded.last_action,
                    consecutive_failures=excluded.consecutive_failures,
                    cooldown_until=excluded.cooldown_until
                """,
                (
                    server_id,
                    current.get("last_scheduled_date", ""),
                    current.get("last_action", ""),
                    int(current.get("consecutive_failures", 0)),
                    float(current.get("cooldown_until", 0.0)),
                ),
            )

    def _mark_database_running(self, sid: int) -> None:
        metrics = self.process_manager.metrics(sid)
        if not metrics.get("alive"):
            return
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime(server_id,pid,status,started_at,last_error)
                VALUES(?,?,?,?, '')
                ON CONFLICT(server_id) DO UPDATE SET
                    pid=excluded.pid,status='EN EJECUCIÓN',
                    started_at=COALESCE(runtime.started_at,excluded.started_at),
                    last_error=''
                """,
                (sid, metrics.get("pid"), "EN EJECUCIÓN", time.time()),
            )

    def _restart_allowed(self, sid: int, item: dict) -> bool:
        now = time.time()
        cooldown = max(60, int(item.get("restart_cooldown", 300)))
        max_attempts = max(1, int(item.get("max_restart_attempts", 3)))
        attempts = self.restart_attempts[sid]
        while attempts and now - attempts[0] > cooldown:
            attempts.popleft()
        runtime = self._runtime_row(sid)
        until = float(runtime.get("cooldown_until", 0) or 0)
        if now < until:
            if sid not in self.cooldown_reported:
                remaining = max(1, int(until - now))
                self.event_callback(
                    sid, "WARNING",
                    f"Supervisor en enfriamiento por {remaining}s para evitar un bucle de reinicios",
                )
                self.cooldown_reported.add(sid)
            return False
        self.cooldown_reported.discard(sid)
        if len(attempts) >= max_attempts:
            until = now + cooldown
            self._save_runtime(
                sid,
                last_action="cooldown",
                consecutive_failures=len(attempts),
                cooldown_until=until,
            )
            self.event_callback(
                sid,
                "ERROR",
                f"Supervisor pausado: {len(attempts)} reinicios dentro de {cooldown}s",
            )
            return False
        return True

    def _recover_crashed(self, sid: int, item: dict) -> None:
        try:
            if not self._restart_allowed(sid, item):
                return
            self.restart_attempts[sid].append(time.time())
            self.event_callback(sid, "WARNING", "Supervisor: levantando servidor caído")
            try:
                self.start_callback(sid)
                self._save_runtime(
                    sid,
                    last_action="watchdog_start_ok",
                    consecutive_failures=0,
                    cooldown_until=0,
                )
                self.event_callback(sid, "INFO", "Supervisor: servidor recuperado")
            except Exception as exc:
                runtime = self._runtime_row(sid)
                failures = int(runtime.get("consecutive_failures", 0)) + 1
                self._save_runtime(
                    sid,
                    last_action=f"watchdog_error: {exc}",
                    consecutive_failures=failures,
                )
                self.event_callback(sid, "ERROR", f"Supervisor no pudo iniciar el servidor: {exc}")
        finally:
            with self.state_lock:
                self.watchdog_in_progress.discard(sid)

    def _scheduled_restart(self, sid: int, item: dict, today: str) -> None:
        self.event_callback(sid, "INFO", "Reinicio programado iniciado")
        # Marca la fecha antes de trabajar para impedir hilos duplicados si el cierre tarda.
        self._save_runtime(sid, last_scheduled_date=today, last_action="scheduled_restart_started")
        try:
            if self.process_manager.is_alive(sid):
                self.restart_callback(
                    sid,
                    bool(item.get("restart_backup", 1)),
                    bool(item.get("force_kill_on_restart", 1)),
                )
                action = "scheduled_restart_ok"
                message = "Reinicio programado completado"
            else:
                # No enciende un servidor detenido manualmente. Solo deja constancia.
                action = "scheduled_restart_skipped_stopped"
                message = "Reinicio programado omitido: el servidor estaba detenido"
            self._save_runtime(
                sid,
                last_scheduled_date=today,
                last_action=action,
                consecutive_failures=0,
            )
            self.event_callback(sid, "INFO", message)
        except Exception as exc:
            self._save_runtime(
                sid,
                last_scheduled_date=today,
                last_action=f"scheduled_restart_error: {exc}",
                consecutive_failures=self._runtime_row(sid).get("consecutive_failures", 0) + 1,
            )
            self.event_callback(sid, "ERROR", f"Reinicio programado falló: {exc}")
        finally:
            with self.state_lock:
                self.scheduled_in_progress.discard(sid)

    def run(self):
        while not self.stop_event.is_set():
            try:
                with connect() as conn:
                    rows = conn.execute(
                        """
                        SELECT s.id,s.name,s.auto_start,r.status,r.started_at,a.*
                        FROM servers s
                        JOIN server_automation a ON a.server_id=s.id
                        LEFT JOIN runtime r ON r.server_id=s.id
                        """
                    ).fetchall()
                now = datetime.now()
                today = now.date().isoformat()
                current_hm = now.strftime("%H:%M")

                for row in rows:
                    item = dict(row)
                    sid = int(item["id"])
                    alive = self.process_manager.is_alive(sid)
                    status = item.get("status") or "DETENIDO"

                    # Reconciliación: la base puede quedar atrasada tras reiniciar el panel.
                    if alive and status != "EN EJECUCIÓN":
                        self._mark_database_running(sid)
                        status = "EN EJECUCIÓN"

                    if item.get("watchdog_enabled") and status in ("EN EJECUCIÓN", "INICIANDO"):
                        if alive:
                            self.dead_since.pop(sid, None)
                        else:
                            started_at = float(item.get("started_at") or 0)
                            startup_grace = max(15, int(item.get("startup_grace", 90)))
                            if started_at and time.time() - started_at < startup_grace:
                                continue
                            first = self.dead_since.setdefault(sid, time.time())
                            delay = max(5, int(item.get("watchdog_delay", 15)))
                            if time.time() - first >= delay:
                                with self.state_lock:
                                    if sid in self.watchdog_in_progress:
                                        continue
                                    self.watchdog_in_progress.add(sid)
                                self.dead_since.pop(sid, None)
                                threading.Thread(
                                    target=self._recover_crashed,
                                    args=(sid, item),
                                    name=f"AsgardWatchdog-{sid}",
                                    daemon=True,
                                ).start()

                    if item.get("restart_enabled"):
                        restart_time = str(item.get("restart_time", "04:00"))
                        if not self._valid_time(restart_time):
                            if sid not in self.invalid_time_reported:
                                self.event_callback(
                                    sid, "ERROR", f"Hora de reinicio inválida: {restart_time}"
                                )
                                self.invalid_time_reported.add(sid)
                            continue
                        runtime = self._runtime_row(sid)
                        # >= hace que el reinicio ocurra aunque el servicio se haya iniciado
                        # unos minutos después de la hora exacta.
                        if current_hm >= restart_time and runtime.get("last_scheduled_date") != today:
                            with self.state_lock:
                                if sid in self.scheduled_in_progress:
                                    continue
                                self.scheduled_in_progress.add(sid)
                            threading.Thread(
                                target=self._scheduled_restart,
                                args=(sid, item, today),
                                name=f"AsgardScheduledRestart-{sid}",
                                daemon=True,
                            ).start()
            except Exception as exc:
                self.event_callback(None, "ERROR", f"Supervisor ASGARD: {exc}")
            self.stop_event.wait(5)
