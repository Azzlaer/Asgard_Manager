from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import requests
from local_auth import local_headers

from common import (
    SERVICE_URL, APP_DIR, APP_DATA_DIR, LIBRARY_ROOT,
    MOD_LIBRARY_ROOT, CONFIG_LIBRARY_ROOT,
)
from service_control import start as start_asgard_service, stop as stop_asgard_service, restart as restart_asgard_service, status as status_asgard_service
from remote_gui import RemoteCenterWindow
from resource_gui import ResourcePolicyWindow
from asgard_theme import apply_void_theme, PALETTE, VoidSigil, load_window_logo
from asgard_suite_gui import AsgardSuiteWindow


class Api:
    def request(self, method: str, path: str, payload=None, timeout=60):
        response = requests.request(
            method,
            SERVICE_URL + path,
            headers=local_headers(),
            allow_redirects=False,
            json=payload,
            timeout=timeout,
        )
        data = response.json()
        if response.status_code >= 400:
            raise RuntimeError(data.get("error", f"HTTP {response.status_code}"))
        return data

    def health(self):
        return self.request("GET", "/health", timeout=3)


api = Api()


class ServerEditor(tk.Toplevel):
    def __init__(self, parent, server, on_save):
        super().__init__(parent)
        self.title("Editar servidor" if server else "Agregar servidor")
        self.geometry("980x720")
        self.minsize(820, 650)
        self.transient(parent)
        self.grab_set()
        self.server = server or {}
        self.on_save = on_save

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(4, weight=1)

        self.vars = {
            "name": tk.StringVar(value=self.server.get("name", "Servidor Valheim")),
            "executable": tk.StringVar(value=self.server.get("executable", "")),
            "working_directory": tk.StringVar(value=self.server.get("working_directory", "")),
            "savedir": tk.StringVar(value=self.server.get("savedir", "")),
            "log_file": tk.StringVar(value=self.server.get("log_file", "")),
            "backup_directory": tk.StringVar(value=self.server.get("backup_directory", "")),
            "backup_retention": tk.StringVar(value=str(self.server.get("backup_retention", 10))),
        }
        self.auto_var = tk.BooleanVar(value=bool(self.server.get("auto_start", False)))

        fields = [
            ("Nombre", "name", None),
            ("valheim_server.exe", "executable", self._browse_exe),
            ("Carpeta de trabajo", "working_directory", self._browse_work),
            ("Savedir", "savedir", self._browse_savedir),
        ]
        for row, (label, key, command) in enumerate(fields):
            ttk.Label(root, text=label).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 8))
            ttk.Entry(root, textvariable=self.vars[key]).grid(row=row, column=1, sticky="ew", pady=5)
            if command:
                ttk.Button(root, text="Examinar", command=command).grid(row=row, column=2, padx=(8, 0))

        ttk.Label(root, text="Parámetros").grid(row=4, column=0, sticky="nw", pady=5)
        self.params = tk.Text(root, wrap="word", height=12)
        self.params.insert("1.0", self.server.get(
            "parameters",
            '-nographics -batchmode -name "Mi servidor" -port 2456 '
            '-world "MiMundo" -password "CAMBIAR" -crossplay -public 1 -saveinterval 1800'
        ))
        self.params.grid(row=4, column=1, columnspan=2, sticky="nsew", pady=5)

        extra = [
            ("Archivo log", "log_file", self._browse_log),
            ("Carpeta backups", "backup_directory", self._browse_backup),
            ("Backups a conservar", "backup_retention", None),
        ]
        for idx, (label, key, command) in enumerate(extra, start=5):
            ttk.Label(root, text=label).grid(row=idx, column=0, sticky="w", pady=5, padx=(0, 8))
            ttk.Entry(root, textvariable=self.vars[key]).grid(row=idx, column=1, sticky="ew", pady=5)
            if command:
                ttk.Button(root, text="Examinar", command=command).grid(row=idx, column=2, padx=(8, 0))

        ttk.Checkbutton(root, text="Auto iniciar con el servicio", variable=self.auto_var).grid(
            row=8, column=1, sticky="w", pady=8
        )

        buttons = ttk.Frame(root)
        buttons.grid(row=9, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Guardar", command=self._save).pack(side="right")

    def _browse_exe(self):
        value = filedialog.askopenfilename(filetypes=[("Valheim", "valheim_server.exe"), ("EXE", "*.exe")])
        if value:
            self.vars["executable"].set(value)
            if not self.vars["working_directory"].get():
                self.vars["working_directory"].set(str(Path(value).parent))

    def _browse_work(self):
        value = filedialog.askdirectory()
        if value: self.vars["working_directory"].set(value)

    def _browse_savedir(self):
        value = filedialog.askdirectory()
        if value: self.vars["savedir"].set(value)

    def _browse_log(self):
        value = filedialog.askopenfilename(filetypes=[("Logs", "*.txt *.log"), ("Todos", "*.*")])
        if value: self.vars["log_file"].set(value)

    def _browse_backup(self):
        value = filedialog.askdirectory()
        if value: self.vars["backup_directory"].set(value)

    def _save(self):
        try:
            payload = {key: var.get().strip() for key, var in self.vars.items()}
            payload["parameters"] = self.params.get("1.0", "end-1c").strip()
            payload["backup_retention"] = int(payload["backup_retention"])
            payload["auto_start"] = self.auto_var.get()
            for key in ("name", "executable", "working_directory", "parameters"):
                if not payload[key]:
                    raise ValueError(f"Falta {key}")
            self.on_save(payload)
            self.destroy()
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)


class DiscordEditor(tk.Toplevel):
    def __init__(self, parent, server_id, data, on_save):
        super().__init__(parent)
        self.title("Discord del servidor")
        self.geometry("900x720")
        self.minsize(760, 620)
        self.transient(parent)
        self.grab_set()
        self.server_id = server_id
        self.settings = data["settings"]
        self.runtime = data["runtime"]
        self.on_save = on_save

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(7, weight=1)

        self.enabled = tk.BooleanVar(value=bool(self.settings.get("enabled")))
        self.vars = {
            "text_channel_id": tk.StringVar(value=self.settings.get("text_channel_id", "")),
            "message_id": tk.StringVar(value=self.settings.get("message_id", "")),
            "voice_channel_id": tk.StringVar(value=self.settings.get("voice_channel_id", "")),
            "max_players": tk.StringVar(value=str(self.settings.get("max_players", 100))),
            "voice_template": tk.StringVar(value=self.settings.get("voice_template", "Jugadores: {players}/{max_players}")),
            "join_code_regex": tk.StringVar(value=self.settings.get("join_code_regex", "")),
            "player_count_regex": tk.StringVar(value=self.settings.get("player_count_regex", "")),
        }

        ttk.Checkbutton(root, text="Habilitar monitor Discord", variable=self.enabled).grid(
            row=0, column=1, sticky="w", pady=5
        )
        fields = [
            ("Channel ID texto", "text_channel_id"),
            ("Message ID", "message_id"),
            ("Channel ID voz", "voice_channel_id"),
            ("Máximo jugadores", "max_players"),
            ("Plantilla canal voz", "voice_template"),
            ("Regex Join Code", "join_code_regex"),
            ("Regex jugadores", "player_count_regex"),
        ]
        for row, (label, key) in enumerate(fields, start=1):
            ttk.Label(root, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=5)
            ttk.Entry(root, textvariable=self.vars[key]).grid(row=row, column=1, sticky="ew", pady=5)

        ttk.Label(root, text="Plantilla del mensaje").grid(row=8, column=0, sticky="nw", pady=5)
        ttk.Label(root, text="Incluye {player_list} para mostrar nombres en vivo.", style="Muted.TLabel").grid(row=7, column=1, sticky="w", pady=(0, 3))
        self.message = tk.Text(root, height=10, wrap="word")
        self.message.insert("1.0", self.settings.get("message_template", ""))
        self.message.grid(row=8, column=1, sticky="nsew", pady=5)
        root.rowconfigure(8, weight=1)

        status = (
            f'Join Code: {self.runtime.get("join_code", "—")}   '
            f'Jugadores: {self.runtime.get("players", 0)}   '
            f'Steam IDs: {len(self.runtime.get("steam_ids", []))}'
        )
        ttk.Label(root, text=status).grid(row=9, column=0, columnspan=2, sticky="w", pady=8)

        buttons = ttk.Frame(root)
        buttons.grid(row=10, column=0, columnspan=2, sticky="ew")
        ttk.Button(buttons, text="Insertar lista de jugadores", command=self._insert_player_list).pack(side="left")
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Guardar", command=self._save, style="Accent.TButton").pack(side="right")

    def _insert_player_list(self):
        content = self.message.get("1.0", "end-1c")
        if "{player_list}" in content:
            messagebox.showinfo("ASGARD", "La plantilla ya contiene {player_list}.", parent=self)
            return
        suffix = "\n🎮 **En línea:** {player_list}"
        self.message.insert("end", suffix)

    def _save(self):
        try:
            payload = {key: var.get().strip() for key, var in self.vars.items()}
            payload["enabled"] = self.enabled.get()
            payload["max_players"] = int(payload["max_players"])
            payload["message_template"] = self.message.get("1.0", "end-1c")
            self.on_save(payload)
            self.destroy()
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)


class SimpleListWindow(tk.Toplevel):
    def __init__(self, parent, title, columns, rows):
        super().__init__(parent)
        self.title(title)
        self.geometry("850x500")
        tree = ttk.Treeview(self, columns=[c[0] for c in columns], show="headings")
        for key, label, width in columns:
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="w")
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        for row in rows:
            tree.insert("", "end", values=[row.get(c[0], "") for c in columns])


class LiveListWindow(tk.Toplevel):
    """Tabla que vuelve a consultar el servicio sin bloquear la GUI."""

    def __init__(self, parent, title, columns, loader, interval_ms=1500):
        super().__init__(parent)
        self.title(title)
        self.geometry("900x540")
        self.minsize(720, 420)
        self.columns = columns
        self.loader = loader
        self.interval_ms = max(750, int(interval_ms))
        self.running = True
        self.busy = False
        self.protocol("WM_DELETE_WINDOW", self._close)

        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)
        top = ttk.Frame(root)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text=title, font=("Segoe UI Semibold", 14)).pack(side="left")
        self.status = tk.StringVar(value="Sincronizando...")
        ttk.Label(top, textvariable=self.status, style="Muted.TLabel").pack(side="right")

        self.tree = ttk.Treeview(root, columns=[c[0] for c in columns], show="headings")
        for key, label, width in columns:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w")
        scroll = ttk.Scrollbar(root, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.after(50, self.refresh)

    def _close(self):
        self.running = False
        self.destroy()

    def refresh(self):
        if not self.running:
            return
        if self.busy:
            self.after(self.interval_ms, self.refresh)
            return
        self.busy = True

        def worker():
            try:
                rows = self.loader()
                self.after(0, lambda: self._render(rows))
            except Exception as exc:
                self.after(0, lambda e=exc: self._error(e))

        threading.Thread(target=worker, daemon=True).start()

    def _render(self, rows):
        if not self.running or not self.winfo_exists():
            return
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(rows):
            values = []
            for key, _label, _width in self.columns:
                value = row.get(key, "")
                if key == "player_name" and not value:
                    value = "Identificando..."
                elif key == "steam_id" and not value:
                    value = "Pendiente del log"
                values.append(value)
            self.tree.insert("", "end", iid=str(index), values=values)
        for iid in selected:
            if self.tree.exists(iid):
                self.tree.selection_add(iid)
        self.status.set(f"{len(rows)} conectado(s) · actualización automática")
        self.busy = False
        self.after(self.interval_ms, self.refresh)

    def _error(self, exc):
        if not self.running:
            return
        self.status.set(f"Error de sincronización: {exc}")
        self.busy = False
        self.after(self.interval_ms, self.refresh)


class AutomationEditor(tk.Toplevel):
    def __init__(self, parent, data, on_save):
        super().__init__(parent)
        self.title("Supervisor, watchdog y reinicios")
        self.geometry("650x520")
        self.minsize(590, 460)
        self.transient(parent)
        self.grab_set()

        root = ttk.Frame(self, padding=15)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)

        self.watchdog = tk.BooleanVar(value=bool(data.get("watchdog_enabled")))
        self.delay = tk.StringVar(value=str(data.get("watchdog_delay", 15)))
        self.startup_grace = tk.StringVar(value=str(data.get("startup_grace", 45)))
        self.cooldown = tk.StringVar(value=str(data.get("restart_cooldown", 300)))
        self.max_attempts = tk.StringVar(value=str(data.get("max_restart_attempts", 3)))
        self.force_kill = tk.BooleanVar(value=bool(data.get("force_kill_on_restart", True)))
        self.restart = tk.BooleanVar(value=bool(data.get("restart_enabled")))
        self.time = tk.StringVar(value=data.get("restart_time", "04:00"))
        self.backup = tk.BooleanVar(value=bool(data.get("restart_backup", True)))

        watchdog_box = ttk.LabelFrame(root, text="Supervisor permanente", padding=12)
        watchdog_box.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        watchdog_box.columnconfigure(1, weight=1)
        ttk.Checkbutton(
            watchdog_box,
            text="Levantar el servidor si el proceso se cae inesperadamente",
            variable=self.watchdog,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        fields = [
            ("Espera tras detectar caída (segundos)", self.delay),
            ("Gracia de arranque (segundos)", self.startup_grace),
            ("Enfriamiento tras varios fallos (segundos)", self.cooldown),
            ("Intentos antes de entrar en enfriamiento", self.max_attempts),
        ]
        for row, (label, var) in enumerate(fields, start=1):
            ttk.Label(watchdog_box, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
            ttk.Entry(watchdog_box, textvariable=var, width=14).grid(row=row, column=1, sticky="w", pady=4)

        restart_box = ttk.LabelFrame(root, text="Reinicio automático diario", padding=12)
        restart_box.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        restart_box.columnconfigure(1, weight=1)
        ttk.Checkbutton(restart_box, text="Habilitar reinicio diario", variable=self.restart).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        ttk.Label(restart_box, text="Hora local (HH:MM)").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(restart_box, textvariable=self.time, width=14).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Checkbutton(
            restart_box, text="Crear backup antes del reinicio", variable=self.backup
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(
            restart_box,
            text="Si el cierre seguro falla, terminar solo ese proceso y volverlo a iniciar",
            variable=self.force_kill,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=4)

        ttk.Label(
            root,
            text=(
                "El supervisor distingue una caída de una detención manual, evita bucles de reinicio "
                "y conserva el estado aunque se reinicie el panel."
            ),
            wraplength=590,
            foreground="#FF8A9B",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 12))

        buttons = ttk.Frame(root)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Guardar", command=lambda: self._save(on_save)).pack(side="right")

    def _save(self, on_save):
        try:
            payload = {
                "watchdog_enabled": self.watchdog.get(),
                "watchdog_delay": max(1, int(self.delay.get())),
                "startup_grace": max(5, int(self.startup_grace.get())),
                "restart_cooldown": max(30, int(self.cooldown.get())),
                "max_restart_attempts": max(1, int(self.max_attempts.get())),
                "force_kill_on_restart": self.force_kill.get(),
                "restart_enabled": self.restart.get(),
                "restart_time": self.time.get().strip(),
                "restart_backup": self.backup.get(),
            }
            on_save(payload)
            self.destroy()
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)

class AccessManagerWindow(tk.Toplevel):
    LABELS = {"banned": "Baneados", "permitted": "Whitelist", "admin": "Admins"}

    def __init__(self, parent, sid):
        super().__init__(parent)
        self.title("Baneados / Whitelist / Administradores")
        self.geometry("880x560")
        self.minsize(700, 450)
        self.sid = sid
        self.kind = tk.StringVar(value="banned")

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Lista:", font=("Segoe UI Semibold", 10)).pack(side="left", padx=(0, 6))
        for value, label in self.LABELS.items():
            ttk.Radiobutton(
                top, text=label, value=value, variable=self.kind, command=self.refresh
            ).pack(side="left", padx=5)
        ttk.Label(
            top,
            text="Puedes seleccionar varios registros con Ctrl o Shift.",
            foreground="#FF8A9B",
        ).pack(side="right")

        tree_frame = ttk.Frame(self, padding=(10, 0, 10, 0))
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            tree_frame, columns=("id",), show="headings", selectmode="extended"
        )
        self.tree.heading("id", text="Steam / Platform ID")
        self.tree.column("id", width=720, anchor="w")
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Delete>", lambda _event: self.remove())

        bottom = ttk.Frame(self, padding=10)
        bottom.pack(fill="x")
        self.value = tk.StringVar()
        ttk.Entry(bottom, textvariable=self.value).pack(side="left", fill="x", expand=True)
        ttk.Button(bottom, text="Agregar", command=self.add).pack(side="left", padx=6)
        ttk.Button(
            bottom,
            text="Eliminar seleccionado",
            command=self.remove,
            style="Danger.TButton",
        ).pack(side="left")
        ttk.Button(bottom, text="Actualizar", command=self.refresh).pack(side="left", padx=(6, 0))
        self.refresh()

    def refresh(self):
        try:
            data = api.request("GET", f"/servers/{self.sid}/access/{self.kind.get()}")
            self.tree.delete(*self.tree.get_children())
            for item in data["items"]:
                self.tree.insert("", "end", values=(item,))
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)

    def add(self):
        value = self.value.get().strip()
        if not value:
            messagebox.showinfo("ASGARD", "Escribe un Steam ID o Platform ID.", parent=self)
            return
        try:
            api.request("POST", f"/servers/{self.sid}/access/{self.kind.get()}", {"id": value})
            self.value.set("")
            self.refresh()
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)

    def remove(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("ASGARD", "Selecciona uno o varios registros.", parent=self)
            return
        values = [str(self.tree.item(item, "values")[0]) for item in selected]
        label = self.LABELS.get(self.kind.get(), self.kind.get())
        if not messagebox.askyesno(
            "ASGARD",
            f"¿Eliminar {len(values)} registro(s) de {label}?",
            parent=self,
        ):
            return
        try:
            api.request(
                "DELETE",
                f"/servers/{self.sid}/access/{self.kind.get()}",
                {"ids": values},
            )
            self.refresh()
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)

class RconEditor(tk.Toplevel):
    def __init__(self, parent, data, on_save, on_test, on_auto):
        super().__init__(parent)
        self.title("RCON del servidor")
        self.geometry("640x390")
        self.transient(parent)
        self.grab_set()
        self.on_auto = on_auto

        root = ttk.Frame(self, padding=15)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        self.enabled = tk.BooleanVar(value=bool(data.get("enabled")))
        self.host = tk.StringVar(value=data.get("host", "127.0.0.1"))
        self.port = tk.StringVar(value=str(data.get("port", 25575)))
        self.password = tk.StringVar(value=data.get("password", ""))
        self.timeout = tk.StringVar(value=str(data.get("timeout", 5.0)))

        ttk.Checkbutton(root, text="Usar Source RCON", variable=self.enabled).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        for row, (label, var) in enumerate(
            [("Host", self.host), ("Puerto", self.port), ("Contraseña", self.password), ("Timeout", self.timeout)],
            1,
        ):
            ttk.Label(root, text=label).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 10))
            ttk.Entry(root, textvariable=var, show="•" if label == "Contraseña" else "").grid(
                row=row, column=1, sticky="ew", pady=5
            )

        ttk.Label(
            root,
            text=(
                "Configuración automática: detecta ValheimRcon o Avii RCON, calcula el puerto "
                "desde el puerto del servidor, genera contraseña y sincroniza el panel."
            ),
            wraplength=590,
            foreground="#FF8A9B",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 10))

        buttons = ttk.Frame(root)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=5)
        ttk.Button(buttons, text="Configurar mod automáticamente", command=self._auto).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Probar", command=lambda: on_test(self.payload())).pack(side="left", padx=5)
        ttk.Button(buttons, text="Guardar", command=lambda: (on_save(self.payload()), self.destroy())).pack(side="left")

    def payload(self):
        return {
            "enabled": self.enabled.get(),
            "host": self.host.get().strip(),
            "port": int(self.port.get()),
            "password": self.password.get(),
            "timeout": float(self.timeout.get()),
        }

    def _auto(self):
        self.on_auto(self.apply_auto_result)

    def apply_auto_result(self, result):
        settings = result.get("settings", result)
        self.enabled.set(bool(settings.get("enabled", True)))
        self.host.set(settings.get("host", "127.0.0.1"))
        self.port.set(str(settings.get("port", self.port.get())))
        self.password.set(settings.get("password", self.password.get()))
        self.timeout.set(str(settings.get("timeout", self.timeout.get())))
        messagebox.showinfo(
            "RCON configurado",
            "Configuración automática completada.\n\n"
            f'Mod detectado: {result.get("implementation", "RCON compatible")}\n'
            f'Archivo: {result.get("config_path", "—")}\n'
            f'Puerto: {settings.get("port", "—")}\n\n'
            "Guarda esta ventana y arranca el servidor para probar la conexión.",
            parent=self,
        )

class ConfigManagerWindow(tk.Toplevel):
    def __init__(self, parent, sid):
        super().__init__(parent)
        self.sid = sid
        self.title("Config Manager")
        self.geometry("1100x700")

        left = ttk.Frame(self, padding=8)
        left.pack(side="left", fill="y")
        right = ttk.Frame(self, padding=8)
        right.pack(side="right", fill="both", expand=True)

        ttk.Label(left, text="Configuraciones detectadas", font=("Segoe UI Semibold", 11)).pack(anchor="w")
        self.list = tk.Listbox(
            left, width=45, exportselection=False,
            bg="#130507", fg="#F7E7EA", selectbackground="#9F0D27"
        )
        self.list.pack(fill="y", expand=True, pady=(8, 8))
        ttk.Button(left, text="Actualizar lista", command=self.load_list).pack(fill="x")
        ttk.Button(
            left,
            text="Eliminar seleccionado",
            command=self.delete_selected,
            style="Danger.TButton",
        ).pack(fill="x", pady=(6, 0))

        self.editor = tk.Text(
            right, wrap="none", bg="#070203", fg="#F7E7EA",
            insertbackground="#FFFFFF", font=("Consolas", 10)
        )
        self.editor.pack(fill="both", expand=True)
        bar = ttk.Frame(right)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Label(bar, text="Cada guardado y borrado crea respaldo automático.", foreground="#FF8A9B").pack(side="left")
        ttk.Button(bar, text="Recargar archivo", command=self.open_selected).pack(side="right", padx=(6, 0))
        ttk.Button(bar, text="Guardar", command=self.save).pack(side="right")

        self.list.bind("<<ListboxSelect>>", lambda _event: self.open_selected())
        self.list.bind("<Delete>", lambda _event: self.delete_selected())
        self.items = []
        self.load_list()

    def load_list(self):
        try:
            self.items = api.request("GET", f"/servers/{self.sid}/configs")
            self.list.delete(0, "end")
            for item in self.items:
                self.list.insert("end", item["relative_path"])
            self.editor.delete("1.0", "end")
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)

    def selected_relative_path(self):
        selection = self.list.curselection()
        if not selection:
            return None
        return self.items[selection[0]]["relative_path"]

    def open_selected(self):
        rel = self.selected_relative_path()
        if not rel:
            return
        try:
            data = api.request(
                "GET", f"/servers/{self.sid}/configs/content?path={requests.utils.quote(rel)}"
            )
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", data["content"])
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)

    def save(self):
        rel = self.selected_relative_path()
        if not rel:
            messagebox.showinfo("ASGARD", "Selecciona una configuración.", parent=self)
            return
        try:
            result = api.request(
                "PUT",
                f"/servers/{self.sid}/configs",
                {"path": rel, "content": self.editor.get("1.0", "end-1c")},
            )
            messagebox.showinfo(
                "ASGARD", f'Guardado con backup automático.\n\n{result.get("backup", "")}', parent=self
            )
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)

    def delete_selected(self):
        rel = self.selected_relative_path()
        if not rel:
            messagebox.showinfo("ASGARD", "Selecciona una configuración.", parent=self)
            return
        if not messagebox.askyesno(
            "ASGARD",
            f"¿Eliminar esta configuración?\n\n{rel}\n\nSe creará un respaldo antes de borrarla.",
            parent=self,
        ):
            return
        try:
            result = api.request(
                "DELETE", f"/servers/{self.sid}/configs", {"path": rel}
            )
            self.load_list()
            messagebox.showinfo(
                "ASGARD",
                f'Configuración eliminada.\n\nBackup: {result.get("backup", "—")}',
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)

class ModManagerWindow(tk.Toplevel):
    def __init__(self,parent,sid):
        super().__init__(parent);self.sid=sid
        self.title("Mod Manager");self.geometry("900x600")
        self.tree=ttk.Treeview(self,columns=("name","state","dlls","path"),show="headings")
        for c,t,w in [("name","Mod/Carpeta",250),("state","Estado",100),("dlls","DLL",60),("path","Ruta",450)]:
            self.tree.heading(c,text=t);self.tree.column(c,width=w)
        self.tree.pack(fill="both",expand=True,padx=10,pady=10)
        bar=ttk.Frame(self,padding=10);bar.pack(fill="x")
        ttk.Button(bar,text="Instalar DLL/ZIP",command=self.install).pack(side="left")
        ttk.Button(bar,text="Activar",command=lambda:self.toggle(True)).pack(side="left",padx=5)
        ttk.Button(bar,text="Desactivar",command=lambda:self.toggle(False)).pack(side="left")
        ttk.Button(bar,text="Actualizar",command=self.refresh).pack(side="right")
        self.refresh()
    def refresh(self):
        rows=api.request("GET",f"/servers/{self.sid}/mods")
        self.tree.delete(*self.tree.get_children())
        for r in rows:self.tree.insert("", "end", values=(r["name"],"Activo" if r["enabled"] else "Desactivado",r["dll_count"],r["path"]))
    def install(self):
        path=filedialog.askopenfilename(filetypes=[("Mods","*.dll *.zip")])
        if path:
            api.request("POST",f"/servers/{self.sid}/mods-install",{"path":path});self.refresh()
    def toggle(self,enabled):
        sel=self.tree.selection()
        if not sel:return
        name=self.tree.item(sel[0],"values")[0]
        api.request("POST",f"/servers/{self.sid}/mods-toggle",{"name":name,"enabled":enabled});self.refresh()


class WorldModifiersWindow(tk.Toplevel):
    OPTIONS = {
        "preset": ["", "normal", "casual", "easy", "hard", "hardcore", "immersive", "hammer"],
        "combat": ["", "veryeasy", "easy", "hard", "veryhard"],
        "resources": ["", "muchless", "less", "more", "muchmore", "most"],
        "portals": ["", "casual", "hard", "veryhard"],
        "raids": ["", "none", "muchless", "less", "more", "muchmore"],
        "deathpenalty": ["", "casual", "veryeasy", "easy", "hard", "hardcore"],
    }
    KEY_OPTIONS = [
        ("nobuildcost", "Construcción sin costo"),
        ("playerevents", "Asaltos según jugador"),
        ("passivemobs", "Criaturas pasivas"),
        ("nomap", "Sin mapa"),
        ("fire", "Peligro de incendios"),
        ("noportals", "Sin portales"),
        ("nobossportals", "Jefes no atraviesan portales"),
        ("noworkbench", "Construcción sin banco de trabajo"),
        ("nocraftcost", "Fabricación sin costo"),
    ]

    def __init__(self, parent, data, on_save):
        super().__init__(parent)
        self.title("Modificadores del mundo")
        self.geometry("780x720")
        self.minsize(690, 620)
        self.transient(parent)
        self.grab_set()

        root = ttk.Frame(self, padding=15)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        self.vars = {}
        for row, (key, options) in enumerate(self.OPTIONS.items()):
            ttk.Label(root, text=key.capitalize()).grid(row=row, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=data.get(key, ""))
            self.vars[key] = var
            ttk.Combobox(root, textvariable=var, values=options, state="readonly").grid(
                row=row, column=1, sticky="ew", pady=4
            )

        current_keys = [str(value).strip() for value in data.get("setkeys", []) if str(value).strip()]
        lowered = {value.lower(): value for value in current_keys}
        key_box = ttk.LabelFrame(root, text="Claves preestablecidas", padding=10)
        key_box.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 8))
        key_box.columnconfigure(0, weight=1)
        key_box.columnconfigure(1, weight=1)
        self.key_vars = {}
        known_names = {key for key, _label in self.KEY_OPTIONS}
        for index, (key, label) in enumerate(self.KEY_OPTIONS):
            var = tk.BooleanVar(value=key in lowered)
            self.key_vars[key] = var
            ttk.Checkbutton(key_box, text=label, variable=var).grid(
                row=index // 2, column=index % 2, sticky="w", padx=5, pady=3
            )

        event_rate_value = ""
        extras = []
        for value in current_keys:
            parts = value.split(None, 1)
            key = parts[0].lower()
            if key == "eventrate":
                event_rate_value = parts[1] if len(parts) > 1 else ""
            elif key not in known_names:
                extras.append(value)

        ttk.Label(root, text="EventRate (porcentaje, vacío = predeterminado)").grid(
            row=7, column=0, sticky="w", pady=4
        )
        self.event_rate = tk.StringVar(value=event_rate_value)
        ttk.Entry(root, textvariable=self.event_rate).grid(row=7, column=1, sticky="ew", pady=4)

        ttk.Label(root, text="Setkeys adicionales (separadas por coma)").grid(
            row=8, column=0, sticky="w", pady=4
        )
        self.extra_setkeys = tk.StringVar(value=", ".join(extras))
        ttk.Entry(root, textvariable=self.extra_setkeys).grid(row=8, column=1, sticky="ew", pady=4)

        ttk.Label(
            root,
            text=(
                "Los cambios editan los parámetros de inicio del servidor. Detén el servidor antes de guardar. "
                "Algunas claves avanzadas dependen de la versión de Valheim instalada."
            ),
            wraplength=720,
            foreground="#FF8A9B",
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 10))

        buttons = ttk.Frame(root)
        buttons.grid(row=10, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Guardar", command=lambda: self._save(on_save)).pack(side="right")

    def _save(self, on_save):
        try:
            on_save(self.payload())
            self.destroy()
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)

    def payload(self):
        data = {key: var.get() for key, var in self.vars.items()}
        setkeys = [key for key, var in self.key_vars.items() if var.get()]
        event_rate = self.event_rate.get().strip()
        if event_rate:
            try:
                numeric = float(event_rate)
                if numeric < 0:
                    raise ValueError
            except ValueError as exc:
                raise ValueError("EventRate debe ser un número mayor o igual a cero.") from exc
            setkeys.append(f"EventRate {event_rate}")
        setkeys.extend(
            value.strip() for value in self.extra_setkeys.get().split(",") if value.strip()
        )
        data["setkeys"] = setkeys
        return data

class NativeIntegrationWindow(tk.Toplevel):
    def __init__(self, parent, sid, integration_type, title):
        super().__init__(parent)
        self.sid = sid
        self.integration_type = integration_type
        self.title(title)
        self.geometry("1100x720")

        left = ttk.Frame(self, padding=10)
        left.pack(side="left", fill="y")
        right = ttk.Frame(self, padding=10)
        right.pack(side="right", fill="both", expand=True)

        ttk.Label(left, text="Archivos detectados", font=("Segoe UI Semibold", 12)).pack(anchor="w")
        self.files = tk.Listbox(left, width=42, bg="#130507", fg="#F7E7EA", selectbackground="#9F0D27")
        self.files.pack(fill="y", expand=True, pady=(8, 8))
        ttk.Button(left, text="Volver a detectar", command=self.load_files).pack(fill="x")

        self.editor = tk.Text(
            right, wrap="none", bg="#070203", fg="#F7E7EA",
            insertbackground="#FFFFFF", font=("Consolas", 10)
        )
        self.editor.pack(fill="both", expand=True)

        lower = ttk.Frame(right)
        lower.pack(fill="x", pady=(8, 0))
        self.info_var = tk.StringVar(value="Selecciona un archivo.")
        ttk.Label(lower, textvariable=self.info_var).pack(side="left")
        ttk.Button(lower, text="Guardar con backup", command=self.save).pack(side="right")

        self.items = []
        self.current_path = ""
        self.files.bind("<<ListboxSelect>>", lambda _e: self.open_selected())
        self.load_files()

    def load_files(self):
        try:
            self.items = api.request(
                "GET",
                f"/servers/{self.sid}/integrations/{self.integration_type}",
            )
            self.files.delete(0, "end")
            for item in self.items:
                self.files.insert("end", item["relative_path"])
            self.info_var.set(f"{len(self.items)} archivo(s) detectado(s).")
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)

    def open_selected(self):
        selection = self.files.curselection()
        if not selection:
            return
        item = self.items[selection[0]]
        self.current_path = item["path"]
        try:
            data = api.request(
                "GET",
                "/integrations/file?path=" + requests.utils.quote(self.current_path),
            )
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", data["content"])
            entries = data.get("entries", [])
            self.info_var.set(
                f'{item["name"]} · {len(entries)} campos webhook/evento detectados'
            )
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)

    def save(self):
        if not self.current_path:
            return
        try:
            result = api.request(
                "PUT",
                "/integrations/file",
                {
                    "path": self.current_path,
                    "content": self.editor.get("1.0", "end-1c"),
                },
            )
            messagebox.showinfo(
                "ASGARD",
                "Configuración guardada.\n\nBackup:\n" + result["backup"],
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)


class MiniGraph(tk.Canvas):
    def __init__(self, parent, title, suffix="", **kwargs):
        super().__init__(parent, bg="#070203", highlightthickness=1, highlightbackground="#4B1118", **kwargs)
        self.title = title
        self.suffix = suffix
        self.values = []
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_values(self, values):
        self.values = list(values)
        self.redraw()

    def redraw(self):
        self.delete("all")
        w = max(20, self.winfo_width())
        h = max(20, self.winfo_height())
        self.create_text(10, 8, anchor="nw", text=self.title, fill="#FF8A9B", font=("Segoe UI Semibold", 10))
        if not self.values:
            self.create_text(w/2, h/2, text="Sin datos", fill="#8A666D")
            return
        values = self.values[-120:]
        maximum = max(max(values), 1)
        minimum = min(values)
        span = max(maximum - minimum, 1)
        pts = []
        chart_top, chart_bottom = 32, h - 18
        for i, value in enumerate(values):
            x = 8 + (w - 16) * i / max(1, len(values)-1)
            y = chart_bottom - (chart_bottom-chart_top) * (value-minimum)/span
            pts.extend((x, y))
        if len(pts) >= 4:
            self.create_line(*pts, fill="#FF294D", width=2, smooth=True)
        latest = values[-1]
        self.create_text(w-10, 8, anchor="ne", text=f"{latest:.1f}{self.suffix}", fill="#FFF4F4", font=("Segoe UI Semibold", 11))


class MonitoringWindow(tk.Toplevel):
    def __init__(self, parent, server_id=None):
        super().__init__(parent)
        self.server_id = server_id
        self.title("Monitoreo local ASGARD")
        self.geometry("1050x720")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.running = True

        header = ttk.Frame(self, padding=10)
        header.pack(fill="x")
        title = "Servidor seleccionado" if server_id else "Host completo"
        ttk.Label(header, text=title, font=("Segoe UI Semibold", 16)).pack(side="left")
        ttk.Label(header, text="Actualización cada segundo · historial en memoria").pack(side="right")

        grid = ttk.Frame(self, padding=10)
        grid.pack(fill="both", expand=True)
        for i in range(2):
            grid.columnconfigure(i, weight=1)
            grid.rowconfigure(i, weight=1)

        self.cpu = MiniGraph(grid, "CPU", "%")
        self.ram = MiniGraph(grid, "RAM", " MB" if server_id else "%")
        self.net_down = MiniGraph(grid, "Red descarga", " KB/s")
        self.net_up = MiniGraph(grid, "Red subida", " KB/s")
        self.cpu.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.ram.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        self.net_down.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.net_up.grid(row=1, column=1, sticky="nsew", padx=5, pady=5)
        self.after(100, self.refresh)

    def _close(self):
        self.running = False
        self.destroy()

    def refresh(self):
        if not self.running:
            return
        try:
            host = api.request("GET", "/metrics/host?limit=120", timeout=4)
            if self.server_id:
                server = api.request("GET", f"/servers/{self.server_id}/metrics?limit=120", timeout=4)
                self.cpu.set_values([x.get("cpu_percent", 0) for x in server])
                self.ram.set_values([x.get("ram_mb", 0) for x in server])
            else:
                self.cpu.set_values([x.get("cpu_percent", 0) for x in host])
                self.ram.set_values([x.get("ram_percent", 0) for x in host])
            self.net_down.set_values([x.get("network_down_bps", 0)/1024 for x in host])
            self.net_up.set_values([x.get("network_up_bps", 0)/1024 for x in host])
        except Exception:
            pass
        self.after(1000, self.refresh)


class LibraryWindow(tk.Toplevel):
    def __init__(self, parent, kind, selected_server_getter):
        super().__init__(parent)
        self.kind = kind
        self.selected_server_getter = selected_server_getter
        self.current = ""
        self.items = []
        self.title("Biblioteca de Mods" if kind == "mods" else "Biblioteca de Configuraciones")
        self.geometry("900x600")

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        self.path_var = tk.StringVar(value="/")
        ttk.Label(top, textvariable=self.path_var, font=("Segoe UI Semibold", 11)).pack(side="left")
        ttk.Button(top, text="Subir", command=self.up).pack(side="right")
        ttk.Button(top, text="Abrir carpeta", command=self.open_local_folder).pack(
            side="right", padx=(0, 6)
        )

        self.tree = ttk.Treeview(self, columns=("name","type","size"), show="headings")
        for col, text, width in [("name","Nombre",520),("type","Tipo",130),("size","Tamaño",120)]:
            self.tree.heading(col, text=text); self.tree.column(col, width=width)
        self.tree.pack(fill="both", expand=True, padx=10)
        self.tree.bind("<Double-1>", lambda _e: self.open_item())

        bar = ttk.Frame(self, padding=10)
        bar.pack(fill="x")
        ttk.Button(bar, text="Nueva carpeta", command=self.new_folder).pack(side="left")
        ttk.Button(bar, text="Importar archivo/carpeta", command=self.import_source).pack(side="left", padx=5)
        ttk.Button(bar, text="Eliminar", command=self.delete_selected).pack(side="left")
        ttk.Button(bar, text="Aplicar al servidor seleccionado", command=self.apply_selected).pack(side="right")
        ttk.Button(bar, text="Actualizar", command=self.refresh).pack(side="right", padx=5)
        self.refresh()

    def open_local_folder(self):
        root = MOD_LIBRARY_ROOT if self.kind == "mods" else CONFIG_LIBRARY_ROOT
        target = root / self.current if self.current else root
        target.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(target))
        except AttributeError:
            subprocess.Popen(["xdg-open", str(target)])

    def refresh(self):
        data = api.request("GET", f"/library/{self.kind}?path={requests.utils.quote(self.current)}")
        self.items = data["entries"]
        self.path_var.set("/" + self.current.replace("\\","/"))
        self.tree.delete(*self.tree.get_children())
        for item in self.items:
            size = "" if item["is_dir"] else f'{item["size"]/1024:.1f} KB'
            self.tree.insert("", "end", values=(item["name"], "Carpeta" if item["is_dir"] else "Archivo", size))

    def selected_item(self):
        sel = self.tree.selection()
        if not sel: return None
        name = self.tree.item(sel[0], "values")[0]
        return next((x for x in self.items if x["name"] == name), None)

    def open_item(self):
        item = self.selected_item()
        if item and item["is_dir"]:
            self.current = item["relative_path"]; self.refresh()

    def up(self):
        if not self.current: return
        self.current = str(Path(self.current).parent)
        if self.current == ".": self.current = ""
        self.refresh()

    def new_folder(self):
        d=tk.Toplevel(self); d.title("Nueva carpeta"); d.transient(self); d.grab_set()
        v=tk.StringVar(); ttk.Entry(d,textvariable=v,width=45).pack(padx=15,pady=15)
        def save():
            api.request("POST",f"/library/{self.kind}/folder",{"parent":self.current,"name":v.get()})
            d.destroy(); self.refresh()
        ttk.Button(d,text="Crear",command=save).pack(pady=(0,15))

    def import_source(self):
        path = filedialog.askopenfilename(title="Seleccionar archivo")
        if not path:
            path = filedialog.askdirectory(title="Seleccionar carpeta")
        if path:
            api.request("POST",f"/library/{self.kind}/import",{"folder":self.current,"source_path":path})
            self.refresh()

    def delete_selected(self):
        item=self.selected_item()
        if item and messagebox.askyesno("ASGARD",f'¿Eliminar {item["name"]} de la biblioteca?'):
            api.request("DELETE",f'/library/{self.kind}?path={requests.utils.quote(item["relative_path"])}')
            self.refresh()

    def apply_selected(self):
        item=self.selected_item()
        sid=self.selected_server_getter()
        if not item or sid is None: return
        if item["is_dir"] or not item["is_dir"]:
            result=api.request("POST",f"/servers/{sid}/library-apply/{self.kind}",{"relative_path":item["relative_path"]},timeout=120)
            messagebox.showinfo("ASGARD",f'Aplicado correctamente.\nArchivos: {len(result.get("installed",[]))}\nBackup: {result.get("backup","")}')


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ASGARD Host Manager v7.0.10.1 — Crimson Void · Logo integrado")
        self._window_logo = load_window_logo()
        if self._window_logo is not None:
            try:
                self.iconphoto(True, self._window_logo)
            except tk.TclError:
                pass
        self.geometry("1500x850")
        self.minsize(1100, 700)
        self.servers = []
        self._last_log_server_id = None
        self._summary_vars = {}
        self._last_log_content = ""
        self._last_events_content = ""
        self._refresh_inflight = False
        self._details_inflight = False
        self._last_server_refresh = 0.0
        self._last_details_refresh = 0.0
        self._last_backups_refresh = 0.0
        self._details_server_id = None
        self._closing = False
        self._build()
        self.bind("<Control-n>", lambda _e: self.add_server())
        self.bind("<Control-e>", lambda _e: self.edit_server())
        self.bind("<F5>", lambda _e: (self.refresh(force=True), self.refresh_details(force=True)))
        self.bind("<Control-r>", lambda _e: self.restart_selected())
        self.bind("<Control-b>", lambda _e: self.backup_selected())
        self.protocol("WM_DELETE_WINDOW", self._close_app)
        self.after(150, self._start_portable_service)
        self.after(700, self._refresh_loop)

    def _build(self):
        self._configure_style()
        self._build_menubar()
        self._build_header()

        quick = ttk.Frame(self, padding=(8, 8, 8, 4))
        quick.pack(fill="x")
        for text, command in [
            ("Iniciar", self.start_selected),
            ("Detener", self.stop_selected),
            ("Reiniciar", self.restart_selected),
            ("Backup", self.backup_selected),
            ("Recursos", self.configure_resources),
            ("Actualizar", self.refresh),
        ]:
            ttk.Button(quick, text=text, command=command, style="Accent.TButton" if text in {"Iniciar", "Recursos"} else "TButton").pack(side="left", padx=(0, 6))
        ttk.Label(quick, text="Selecciona uno o varios servidores en la lista.").pack(side="right")

        paned = ttk.Panedwindow(self, orient="vertical")
        paned.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        list_frame = ttk.LabelFrame(paned, text="Servidores", padding=6)
        columns = ("name", "status", "health", "pid", "players", "join_code", "cpu", "ram", "uptime", "exe")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="extended")
        heads = {
            "name": "Servidor", "status": "Estado", "health": "Salud", "pid": "PID", "players": "Jugadores",
            "join_code": "Join Code", "cpu": "CPU", "ram": "RAM",
            "uptime": "Tiempo activo", "exe": "Ejecutable",
        }
        widths = {
            "name": 180, "status": 110, "health": 150, "pid": 75, "players": 85, "join_code": 95,
            "cpu": 70, "ram": 90, "uptime": 105, "exe": 380,
        }
        for col in columns:
            self.tree.heading(col, text=heads[col])
            self.tree.column(col, width=widths[col], anchor="w")
        ys = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(list_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.tag_configure("healthy", foreground=PALETTE["success"])
        self.tree.tag_configure("starting", foreground=PALETTE["warning"])
        self.tree.tag_configure("warning", foreground=PALETTE["accent_soft"])
        self.tree.tag_configure("offline", foreground=PALETTE["dim"])
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        paned.add(list_frame, weight=3)

        lower_split = ttk.Panedwindow(paned, orient="horizontal")
        lower = ttk.Notebook(lower_split)
        self.log_text = tk.Text(
            lower, wrap="none", bg=PALETTE["void"], fg=PALETTE["text"],
            insertbackground="#FFFFFF", font=("Consolas", 9)
        )
        self.events_text = tk.Text(
            lower, wrap="word", bg=PALETTE["void"], fg=PALETTE["text"],
            insertbackground="#FFFFFF", font=("Consolas", 9)
        )
        self.backups_tree = ttk.Treeview(
            lower, columns=("date", "reason", "size", "path"), show="headings"
        )
        for col, title, width in [
            ("date", "Fecha", 150), ("reason", "Motivo", 130),
            ("size", "Tamaño", 100), ("path", "Archivo", 700),
        ]:
            self.backups_tree.heading(col, text=title)
            self.backups_tree.column(col, width=width)
        lower.add(self.log_text, text="Log Valheim")
        lower.add(self.events_text, text="Eventos Host")
        lower.add(self.backups_tree, text="Backups")
        lower_split.add(lower, weight=1)

        dashboard = ttk.LabelFrame(
            lower_split, text="Dashboard del servidor seleccionado", padding=10
        )
        dashboard.columnconfigure(0, weight=1)
        dashboard.columnconfigure(1, weight=1)
        dashboard.rowconfigure(2, weight=1)
        dashboard.rowconfigure(3, weight=1)
        self._server_dash_vars = {}
        cards = ttk.Frame(dashboard)
        cards.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        for column in range(4):
            cards.columnconfigure(column, weight=1)
        for index, (key, title) in enumerate([
            ("name", "SERVIDOR"), ("status", "ESTADO"), ("health", "SALUD"), ("pid", "PID"),
            ("players", "JUGADORES"), ("join_code", "JOIN CODE"), ("cpu", "CPU"), ("ram", "RAM"),
        ]):
            card = ttk.Frame(cards, style="Card.TFrame", padding=8)
            card.grid(row=index // 4, column=index % 4, sticky="ew", padx=3, pady=3)
            value = tk.StringVar(value="—")
            self._server_dash_vars[key] = value
            ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(card, textvariable=value, style="CardValueSmall.TLabel").pack(anchor="w")

        self.server_cpu_graph = MiniGraph(dashboard, "CPU del proceso", "%", height=130)
        self.server_ram_graph = MiniGraph(dashboard, "RAM del proceso", " MB", height=130)
        self.server_cpu_graph.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=4)
        self.server_ram_graph.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=4)
        self._server_dashboard_note = tk.StringVar(value="Selecciona un servidor para ver sus recursos.")
        ttk.Label(
            dashboard, textvariable=self._server_dashboard_note,
            foreground="#FF8A9B", wraplength=500
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        lower_split.add(dashboard, weight=1)
        paned.add(lower_split, weight=2)

        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.refresh_details(force=True))
        self.status_var = tk.StringVar(value="Conectando con el servicio...")
        ttk.Label(self, textvariable=self.status_var, style="Status.TLabel", relief="sunken", anchor="w").pack(
            fill="x", side="bottom"
        )

    def _configure_style(self):
        self._style = apply_void_theme(self)

    def _build_header(self):
        header = ttk.Frame(self, style="Void.TFrame", padding=(18, 12))
        header.pack(fill="x")
        VoidSigil(header, size=68).pack(side="left", padx=(0, 12))
        title_box = ttk.Frame(header, style="Void.TFrame")
        title_box.pack(side="left")
        ttk.Label(title_box, text="ASGARD // CRIMSON VOID", style="Hero.TLabel").pack(anchor="w")
        ttk.Label(title_box, text="Host Manager · Estado vivo · Discord · Valheim Master Suite", style="HeroSub.TLabel").pack(anchor="w")

        cards = ttk.Frame(header, style="Void.TFrame")
        cards.pack(side="right")
        for key, title in [("total", "SERVIDORES"),("online", "ONLINE"),("players", "JUGADORES"),("ram", "RAM TOTAL")]:
            card = ttk.Frame(cards, style="Card.TFrame", padding=(14, 8))
            card.pack(side="left", padx=4)
            ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
            var = tk.StringVar(value="0")
            self._summary_vars[key] = var
            ttk.Label(card, textvariable=var, style="CardValue.TLabel").pack(anchor="w")

    def _build_menubar(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        menu_servers = tk.Menu(menubar, tearoff=False)
        menu_servers.add_command(label="Agregar servidor", command=self.add_server)
        menu_servers.add_command(label="Editar servidor", command=self.edit_server)
        menu_servers.add_command(label="Eliminar servidor", command=self.delete_server)
        menu_servers.add_separator()
        menu_servers.add_command(label="Seleccionar todos", command=self.select_all)
        menu_servers.add_command(
            label="Quitar selección",
            command=lambda: self.tree.selection_remove(self.tree.selection()),
        )
        menu_servers.add_separator()
        menu_servers.add_command(label="Abrir carpeta", command=self.open_folder)
        menu_servers.add_separator()
        menu_servers.add_command(label="Salir", command=self.destroy)
        menubar.add_cascade(label="Servidores", menu=menu_servers)

        menu_actions = tk.Menu(menubar, tearoff=False)
        menu_actions.add_command(label="Iniciar seleccionados", command=self.start_selected)
        menu_actions.add_command(label="Detener seguro", command=self.stop_selected)
        menu_actions.add_command(label="Reiniciar seleccionados", command=self.restart_selected)
        menu_actions.add_separator()
        menu_actions.add_command(label="Terminar proceso", command=self.kill_selected)
        menu_actions.add_separator()
        menu_actions.add_command(label="Crear backup", command=self.backup_selected)
        menu_actions.add_command(label="Restaurar backup", command=self.restore_selected)
        menubar.add_cascade(label="Acciones", menu=menu_actions)

        menu_discord = tk.Menu(menubar, tearoff=False)
        menu_discord.add_command(label="Configurar bot token", command=self.configure_bot_token)
        menu_discord.add_separator()
        menu_discord.add_command(label="Configurar servidor", command=self.configure_discord)
        menu_discord.add_command(label="Crear mensaje", command=self.create_discord_message)
        menu_discord.add_command(label="Sincronizar ahora", command=self.sync_discord)
        menubar.add_cascade(label="Discord", menu=menu_discord)

        menu_players = tk.Menu(menubar, tearoff=False)
        menu_players.add_command(label="Jugadores conectados", command=self.show_online_players)
        menu_players.add_command(label="Registro persistente", command=self.show_player_registry)
        menu_players.add_command(
            label="Reconstruir nombres desde el log",
            command=self.rebuild_player_registry,
        )
        menu_players.add_separator()
        menu_players.add_command(label="Bans / Whitelist / Admin", command=self.manage_access)
        menubar.add_cascade(label="Jugadores", menu=menu_players)

        menu_config = tk.Menu(menubar, tearoff=False)
        menu_config.add_command(label="Parámetros del servidor", command=self.edit_server)
        menu_config.add_command(label="Modificadores del mundo", command=self.configure_world_modifiers)
        menu_config.add_command(label="CPU y memoria", command=self.configure_resources)
        menu_config.add_separator()
        menu_config.add_command(label="Config Manager", command=self.open_config_manager)
        menu_config.add_command(label="Mod Manager", command=self.open_mod_manager)
        menubar.add_cascade(label="Configuración", menu=menu_config)

        menu_rcon = tk.Menu(menubar, tearoff=False)
        menu_rcon.add_command(label="Configurar RCON", command=self.configure_rcon)
        menu_rcon.add_command(label="Comandos preestablecidos", command=self.command_palette)
        menu_rcon.add_command(label="Comando personalizado", command=self.custom_command)
        menubar.add_cascade(label="RCON", menu=menu_rcon)

        menu_integrations = tk.Menu(menubar, tearoff=False)
        menu_integrations.add_command(
            label="DiscordConnector",
            command=self.open_discord_connector_manager,
        )
        menu_integrations.add_command(
            label="AzuAntiCheat",
            command=self.open_azu_anticheat_manager,
        )
        menu_integrations.add_separator()
        menu_integrations.add_command(
            label="Discord nativo ASGARD",
            command=self.configure_discord,
        )
        menubar.add_cascade(label="Integraciones", menu=menu_integrations)

        menu_remote = tk.Menu(menubar, tearoff=False)
        menu_remote.add_command(label="Centro de control remoto", command=self.open_remote_center)
        menu_remote.add_separator()
        menu_remote.add_command(label="Guía de preparación del host", command=self.open_remote_setup_guide)
        menubar.add_cascade(label="Remoto", menu=menu_remote)

        menu_library = tk.Menu(menubar, tearoff=False)
        menu_library.add_command(label="Biblioteca de Mods", command=lambda: self.open_library("mods"))
        menu_library.add_command(label="Biblioteca de Configuraciones", command=lambda: self.open_library("configs"))
        menu_library.add_separator()
        menu_library.add_command(label="Abrir carpeta Library", command=self.open_library_folder)
        menu_library.add_command(label="Abrir carpeta Data", command=self.open_data_folder)
        menubar.add_cascade(label="Biblioteca", menu=menu_library)

        menu_monitor = tk.Menu(menubar, tearoff=False)
        menu_monitor.add_command(label="Dashboard del host", command=self.open_host_monitor)
        menu_monitor.add_command(label="Métricas del servidor seleccionado", command=self.open_server_monitor)
        menubar.add_cascade(label="Monitoreo", menu=menu_monitor)

        menu_automation = tk.Menu(menubar, tearoff=False)
        menu_automation.add_command(
            label="Configurar reinicios y watchdog",
            command=self.configure_automation,
        )
        menubar.add_cascade(label="Automatización", menu=menu_automation)

        menu_suite = tk.Menu(menubar, tearoff=False)
        menu_suite.add_command(label="Centro ASGARD Suite", command=self.open_asgard_suite)
        menu_suite.add_command(label="Auditoría y castigos", command=self.open_asgard_suite)
        menubar.add_cascade(label="ASGARD Suite", menu=menu_suite)

        menu_tools = tk.Menu(menubar, tearoff=False)
        menu_tools.add_command(label="Actualizar lista", command=self.refresh)
        menu_tools.add_command(label="Actualizar detalles", command=self.refresh_details)
        menu_tools.add_separator()
        menu_tools.add_command(
            label="Probar conexión con servicio",
            command=self._ensure_service,
        )
        menu_tools.add_separator()
        menu_tools.add_command(
            label="Estado del servicio ASGARD",
            command=lambda: self._run_service_control("status"),
        )
        menu_tools.add_command(
            label="Reiniciar servicio ASGARD",
            command=lambda: self._run_service_control("restart"),
        )
        menu_tools.add_command(
            label="Detener servicio ASGARD",
            command=lambda: self._run_service_control("stop"),
        )
        menubar.add_cascade(label="Herramientas", menu=menu_tools)

    def open_asgard_suite(self):
        sid = self.selected_one()
        if sid is None:
            return
        AsgardSuiteWindow(self, api, sid)

    def _start_portable_service(self):
        def worker():
            ok, message = start_asgard_service()
            self.after(0, lambda: self.status_var.set(message))
            self.after(700, self._ensure_service)
        threading.Thread(target=worker, daemon=True).start()

    def _run_service_control(self, action: str):
        if action == "stop":
            if not messagebox.askyesno(
                "ASGARD",
                "¿Detener el servicio ASGARD?\n\n"
                "Los servidores Valheim ya iniciados continuarán ejecutándose, "
                "pero el panel perderá el control hasta volver a iniciar el servicio.",
            ):
                return
        elif action == "restart":
            if not messagebox.askyesno(
                "ASGARD",
                "¿Reiniciar el servicio ASGARD?\n\n"
                "Los procesos Valheim no serán terminados.",
            ):
                return

        handlers = {
            "start": start_asgard_service,
            "stop": stop_asgard_service,
            "restart": restart_asgard_service,
            "status": status_asgard_service,
        }

        def worker():
            try:
                ok, message = handlers[action]()
                self.after(0, lambda: messagebox.showinfo(
                    "Servicio ASGARD" if ok else "Error", message
                ))
                self.after(900, self._ensure_service)
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("ASGARD", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _ensure_service(self):
        try:
            api.health()
            self.status_var.set(
                f"Servicio ASGARD conectado · Datos: {APP_DATA_DIR} · Biblioteca: {LIBRARY_ROOT}"
            )
        except Exception:
            self.status_var.set(
                "Servicio no disponible. Usa Herramientas > Reiniciar servicio ASGARD."
            )

    def selected_ids(self, require=True):
        ids = [int(iid) for iid in self.tree.selection()]
        if require and not ids:
            messagebox.showinfo("ASGARD", "Selecciona uno o varios servidores.")
        return ids

    def selected_one(self):
        ids = self.selected_ids()
        if len(ids) != 1:
            if ids:
                messagebox.showinfo("ASGARD", "Selecciona solamente un servidor.")
            return None
        return ids[0]

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())

    def call_async(self, fn, success=None):
        def worker():
            try:
                result = fn()
                if success:
                    self.after(0, lambda: success(result))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("ASGARD", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def add_server(self):
        ServerEditor(self, None, lambda payload: self.call_async(
            lambda: api.request("POST", "/servers", payload),
            lambda _: self.refresh()
        ))

    def edit_server(self):
        sid = self.selected_one()
        if sid is None: return
        server = next((s for s in self.servers if s["id"] == sid), None)
        ServerEditor(self, server, lambda payload: self.call_async(
            lambda: api.request("PUT", f"/servers/{sid}", payload),
            lambda _: self.refresh()
        ))

    def delete_server(self):
        sid = self.selected_one()
        if sid is None: return
        if messagebox.askyesno("ASGARD", "¿Eliminar el servidor del panel?"):
            self.call_async(lambda: api.request("DELETE", f"/servers/{sid}"), lambda _: self.refresh())

    def _multi_action(self, action, payload=None):
        ids = self.selected_ids()
        for sid in ids:
            self.call_async(lambda sid=sid: api.request("POST", f"/servers/{sid}/{action}", payload or {}))

    def start_selected(self): self._multi_action("start")
    def stop_selected(self): self._multi_action("stop")
    def restart_selected(self): self._multi_action("restart", {"backup": True})
    def backup_selected(self): self._multi_action("backup", {"reason": "manual"})

    def kill_selected(self):
        if messagebox.askyesno("ASGARD", "¿Terminar forzadamente los procesos seleccionados?"):
            self._multi_action("kill")

    def restore_selected(self):
        sid = self.selected_one()
        if sid is None: return
        path = filedialog.askopenfilename(filetypes=[("Backups ZIP", "*.zip")])
        if path and messagebox.askyesno("ASGARD", "Se creará un backup preventivo. ¿Restaurar?"):
            self.call_async(lambda: api.request("POST", f"/servers/{sid}/restore", {"path": path}))

    @staticmethod
    def _open_windows_folder(path: Path):
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(path))
        except AttributeError:
            subprocess.Popen(["xdg-open", str(path)])

    def open_library_folder(self):
        self._open_windows_folder(LIBRARY_ROOT)

    def open_data_folder(self):
        self._open_windows_folder(APP_DATA_DIR)

    def configure_bot_token(self):
        try:
            current = api.request("GET", "/settings/discord", timeout=5)
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc))
            return
        dialog = tk.Toplevel(self)
        dialog.title("Token del bot Discord")
        dialog.transient(self)
        dialog.grab_set()
        value = tk.StringVar(value=current.get("token", ""))
        ttk.Label(dialog, text="Bot Token").pack(padx=15, pady=(15, 5))
        entry = ttk.Entry(dialog, textvariable=value, show="•", width=70)
        entry.pack(padx=15)
        def save():
            self.call_async(
                lambda: api.request("POST", "/settings/discord", {"token": value.get().strip()}),
                lambda _: dialog.destroy()
            )
        ttk.Button(dialog, text="Guardar", command=save).pack(pady=15)

    def configure_discord(self):
        sid = self.selected_one()
        if sid is None:
            return
        def loaded(data):
            DiscordEditor(
                self, sid, data,
                lambda payload: self.call_async(
                    lambda: api.request("PUT", f"/servers/{sid}/discord", payload),
                    lambda _: self.refresh()
                )
            )
        self.call_async(lambda: api.request("GET", f"/servers/{sid}/discord"), loaded)

    def create_discord_message(self):
        sid = self.selected_one()
        if sid is None:
            return
        def created(result):
            self.refresh()
            messagebox.showinfo(
                "ASGARD",
                f'Mensaje creado correctamente.\n'
                f'Channel ID: {result.get("channel_id", "—")}\n'
                f'Message ID: {result["message_id"]}'
            )

        self.call_async(
            lambda: api.request(
                "POST",
                f"/servers/{sid}/discord-create-message",
                {},
            ),
            created,
        )

    def sync_discord(self):
        ids = self.selected_ids()
        for sid in ids:
            self.call_async(
                lambda sid=sid: api.request("POST", f"/servers/{sid}/discord-sync", {})
            )

    def show_online_players(self):
        sid = self.selected_one()
        if sid is None:
            return
        LiveListWindow(
            self,
            "Jugadores conectados — monitor vivo",
            [("player_name", "Nombre", 300), ("steam_id", "Steam / Platform ID", 330), ("connected_at", "Conectado", 180)],
            lambda: api.request("GET", f"/servers/{sid}/players/online", timeout=5),
            interval_ms=1500,
        )

    def show_player_registry(self):
        sid=self.selected_one()
        if sid is None:return
        self.call_async(
            lambda: api.request("GET",f"/servers/{sid}/players/registry"),
            lambda rows: SimpleListWindow(self,"Registro persistente de jugadores",
                [("last_name","Último nombre",260),("steam_id","Steam ID",260),
                 ("first_seen","Primera vez",150),("last_seen","Última vez",150),("seen_count","Entradas",80)],rows)
        )

    def rebuild_player_registry(self):
        sid = self.selected_one()
        if sid is None:
            return
        if not messagebox.askyesno(
            "Reconstruir registro",
            "Se borrará solamente el registro interno de nombres de este servidor y se volverá "
            "a construir leyendo su log completo. No modifica el mundo, personajes, whitelist ni bans.\n\n"
            "¿Continuar?",
        ):
            return

        def completed(result):
            messagebox.showinfo(
                "Registro reconstruido",
                f'Se reconstruyeron {result.get("players", 0)} jugador(es).\n\n'
                f'Log: {result.get("log_file", "—")}',
            )

        self.call_async(
            lambda: api.request("POST", f"/servers/{sid}/players-rebuild", {}, timeout=300),
            completed,
        )

    def send_server_message(self):
        sid=self.selected_one()
        if sid is None:return
        dialog=tk.Toplevel(self); dialog.title("Enviar mensaje al servidor"); dialog.transient(self); dialog.grab_set()
        value=tk.StringVar(); ttk.Label(dialog,text="Mensaje").pack(padx=15,pady=(15,5))
        ttk.Entry(dialog,textvariable=value,width=70).pack(padx=15)
        def send():
            self.call_async(lambda:api.request("POST",f"/servers/{sid}/say",{"message":value.get()}),
                            lambda _:dialog.destroy())
        ttk.Button(dialog,text="Enviar",command=send).pack(pady=15)

    def configure_automation(self):
        sid=self.selected_one()
        if sid is None:return
        def loaded(data):
            AutomationEditor(self,data,lambda payload:self.call_async(
                lambda:api.request("PUT",f"/servers/{sid}/automation",payload)))
        self.call_async(lambda:api.request("GET",f"/servers/{sid}/automation"),loaded)

    def manage_access(self):
        sid=self.selected_one()
        if sid is not None: AccessManagerWindow(self,sid)

    def configure_rcon(self):
        sid = self.selected_one()
        if sid is None:
            return

        def loaded(data):
            def save(payload):
                self.call_async(
                    lambda: api.request("PUT", f"/servers/{sid}/rcon", payload),
                    lambda _result: self.status_var.set("Configuración RCON guardada"),
                )

            def test(payload):
                def do_test():
                    api.request("PUT", f"/servers/{sid}/rcon", payload)
                    return api.request("POST", f"/servers/{sid}/rcon-test", {"command": "help"})
                self.call_async(
                    do_test,
                    lambda result: messagebox.showinfo(
                        "RCON", result.get("response") or "Conexión correcta"
                    ),
                )

            def auto_config(apply_result):
                if not messagebox.askyesno(
                    "RCON automático",
                    "El servidor debe estar detenido. ASGARD detectará el mod RCON, "
                    "editará su CFG con respaldo y sincronizará los datos del panel.\n\n¿Continuar?",
                ):
                    return
                self.call_async(
                    lambda: api.request("POST", f"/servers/{sid}/rcon-auto-config", {}),
                    apply_result,
                )

            RconEditor(self, data, save, test, auto_config)

        self.call_async(lambda: api.request("GET", f"/servers/{sid}/rcon"), loaded)

    def _send_command(self,command):
        ids=self.selected_ids()
        for sid in ids:
            self.call_async(
                lambda sid=sid:api.request("POST",f"/servers/{sid}/command",{"command":command}),
                lambda r: self.status_var.set(f'Comando enviado por {r.get("transport","?")}')
            )

    def command_palette(self):
        menu = tk.Toplevel(self)
        menu.title("Biblioteca de comandos RCON")
        menu.geometry("620x760")
        frame = ttk.Frame(menu, padding=15)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Comandos preestablecidos", font=("Segoe UI Semibold", 15)).pack(
            anchor="w", pady=(0, 4)
        )
        ttk.Label(
            frame,
            text="La disponibilidad exacta depende del mod RCON y de la versión del servidor.",
            foreground="#FF8A9B",
        ).pack(anchor="w", pady=(0, 12))

        groups = [
            ("Servidor", [
                ("Guardar mundo", "save", False, None),
                ("Información del servidor", "info", False, None),
                ("Lista de jugadores", "players", False, None),
                ("Ayuda de comandos", "help", False, None),
                ("Estado / status", "status", False, None),
                ("Ping", "ping", False, None),
            ]),
            ("Mensajes", [
                ("Mensaje global", "say ", True, None),
                ("Anuncio", "announce ", True, None),
                ("Aviso de reinicio", "say ⚠ Reinicio programado: ", True, None),
            ]),
            ("Moderación", [
                ("Expulsar jugador", "kick ", True, None),
                ("Banear jugador", "ban ", True, None),
                ("Desbanear jugador", "unban ", True, None),
                ("Silenciar jugador", "mute ", True, None),
                ("Desilenciar jugador", "unmute ", True, None),
            ]),
            ("Modificadores / setkey", [
                ("Activar peligro de incendios", "setkey Fire", False, None),
                ("Desactivar peligro de incendios", "removekey Fire", False, None),
                ("Activar mundo sin mapa", "setkey NoMap", False, None),
                ("Restaurar mapa", "removekey NoMap", False, None),
                ("Asaltos según jugador", "setkey PlayerEvents", False, None),
                ("Desactivar asaltos según jugador", "removekey PlayerEvents", False, None),
                ("Sin portales", "setkey NoPortals", False, None),
                ("Restaurar portales", "removekey NoPortals", False, None),
                ("Mobs pasivos", "setkey PassiveMobs", False, None),
                ("Restaurar agresividad", "removekey PassiveMobs", False, None),
                ("Configurar EventRate", "", False, "eventrate"),
                ("Quitar EventRate personalizado", "removekey EventRate", False, None),
                ("Mostrar claves activas", "listkeys", False, None),
            ]),
            ("Mantenimiento", [
                ("Forzar guardado", "save", False, None),
                ("Recargar configuración", "reload", False, None),
                ("Recolectar basura", "gc", False, None),
            ]),
        ]

        canvas = tk.Canvas(frame, bg="#090304", highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas)
        content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for group_name, commands in groups:
            box = ttk.LabelFrame(content, text=group_name, padding=8)
            box.pack(fill="x", pady=5)
            for label, command, prompt, special in commands:
                def run(c=command, needs_prompt=prompt, special_action=special):
                    if special_action == "eventrate":
                        self._prompt_event_rate()
                    elif needs_prompt:
                        self._prompt_command(c)
                    else:
                        self._send_command(c)
                ttk.Button(box, text=label, command=run).pack(fill="x", pady=2)

    def _prompt_event_rate(self):
        dialog = tk.Toplevel(self)
        dialog.title("Configurar EventRate")
        dialog.transient(self)
        dialog.grab_set()
        value = tk.StringVar(value="100")
        ttk.Label(dialog, text="Porcentaje de frecuencia de eventos").pack(padx=15, pady=(15, 5))
        entry = ttk.Entry(dialog, textvariable=value, width=28)
        entry.pack(padx=15)
        entry.focus_set()

        def send():
            try:
                number = float(value.get().strip())
                if number < 0:
                    raise ValueError
                rendered = int(number) if number.is_integer() else number
                self._send_command(f'setkey "EventRate {rendered}"')
                dialog.destroy()
            except ValueError:
                messagebox.showerror("ASGARD", "Escribe un número mayor o igual a cero.", parent=dialog)

        ttk.Button(dialog, text="Enviar", command=send).pack(pady=15)

    def _prompt_command(self,prefix):
        d=tk.Toplevel(self);d.title("Completar comando");d.transient(self);d.grab_set()
        v=tk.StringVar();ttk.Entry(d,textvariable=v,width=60).pack(padx=15,pady=15)
        ttk.Button(d,text="Enviar",command=lambda:(self._send_command(prefix+v.get()),d.destroy())).pack(pady=(0,15))

    def custom_command(self):
        self._prompt_command("")

    def open_config_manager(self):
        sid=self.selected_one()
        if sid is not None:ConfigManagerWindow(self,sid)

    def open_mod_manager(self):
        sid=self.selected_one()
        if sid is not None:ModManagerWindow(self,sid)

    def configure_world_modifiers(self):
        sid=self.selected_one()
        if sid is None:return
        def loaded(data):
            WorldModifiersWindow(self,data,lambda payload:self.call_async(
                lambda:api.request("PUT",f"/servers/{sid}/world-modifiers",payload),
                lambda _:self.refresh()
            ))
        self.call_async(lambda:api.request("GET",f"/servers/{sid}/world-modifiers"),loaded)

    def open_discord_connector_manager(self):
        sid = self.selected_one()
        if sid is not None:
            NativeIntegrationWindow(
                self, sid, "discordconnector", "DiscordConnector Manager"
            )

    def open_azu_anticheat_manager(self):
        sid = self.selected_one()
        if sid is not None:
            NativeIntegrationWindow(
                self, sid, "azuanticheat", "AzuAntiCheat Manager"
            )

    def configure_resources(self):
        sid = self.selected_one()
        if sid is None:
            return
        server = next((item for item in self.servers if int(item["id"]) == sid), {})
        ResourcePolicyWindow(
            self,
            api,
            f"Recursos — {server.get('name', 'Servidor')}",
            f"/servers/{sid}/resources",
            f"/servers/{sid}/resources",
            f"/servers/{sid}/resources-apply",
            f"/servers/{sid}/resources-autoconfigure",
        )

    def open_remote_center(self):
        RemoteCenterWindow(self, api)

    def open_remote_setup_guide(self):
        guide = APP_DIR / "RemoteSetup" / "LEEME_HOST_REMOTO.txt"
        if guide.is_file():
            try:
                os.startfile(guide)
            except OSError as exc:
                messagebox.showerror("ASGARD", str(exc), parent=self)
        else:
            messagebox.showinfo(
                "ASGARD",
                "La guía se incluye al compilar la edición portable completa.",
                parent=self,
            )

    def open_library(self, kind):
        LibraryWindow(self, kind, self.selected_one_silent)

    def open_host_monitor(self):
        MonitoringWindow(self)

    def open_server_monitor(self):
        sid = self.selected_one()
        if sid is not None:
            MonitoringWindow(self, sid)

    def open_folder(self):
        sid = self.selected_one()
        if sid is None: return
        server = next((s for s in self.servers if s["id"] == sid), None)
        if server and Path(server["working_directory"]).is_dir():
            os.startfile(server["working_directory"])

    @staticmethod
    def fmt_uptime(seconds):
        seconds = int(seconds or 0)
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _close_app(self):
        self._closing = True
        self.destroy()

    def refresh(self, force: bool = False):
        """Refresh the server table without blocking Tk's event loop."""
        now = time.monotonic()
        if self._refresh_inflight:
            return
        if not force and now - self._last_server_refresh < 2.5:
            return
        self._refresh_inflight = True

        def worker():
            try:
                data = api.request("GET", "/servers", timeout=5)
                if not self._closing:
                    self.after(0, lambda: self._render_servers(data))
            except Exception as exc:
                if not self._closing:
                    self.after(0, lambda e=exc: self._server_refresh_failed(e))

        threading.Thread(target=worker, name="AsgardGuiServerRefresh", daemon=True).start()

    def _server_refresh_failed(self, exc: Exception):
        self._refresh_inflight = False
        self._last_server_refresh = time.monotonic()
        self.status_var.set(f"Servicio desconectado: {exc}")

    def _render_servers(self, servers):
        self._refresh_inflight = False
        self._last_server_refresh = time.monotonic()
        self.servers = list(servers or [])
        existing = set(self.tree.get_children())
        selected = set(self.tree.selection())
        for server in self.servers:
            iid = str(server["id"])
            matching_pids = [str(pid) for pid in (server.get("matching_pids") or [])]
            pid_display = " / ".join(matching_pids) if matching_pids else (server.get("pid") or "—")
            values = (
                server["name"], server.get("status", "DETENIDO"),
                server.get("health_state", "—"),
                pid_display,
                f'{server.get("players", 0)}',
                server.get("join_code") or "—",
                f'{server.get("cpu_percent", 0):.1f}%',
                f'{server.get("ram_mb", 0):.1f} MB',
                self.fmt_uptime(server.get("uptime_seconds", 0)),
                server["executable"],
            )
            health = str(server.get("health_state", ""))
            if health == "SALUDABLE":
                tags = ("healthy",)
            elif health == "INICIANDO":
                tags = ("starting",)
            elif health == "DETENIDO":
                tags = ("offline",)
            else:
                tags = ("warning",)
            if iid in existing:
                # Avoid forcing a complete redraw when nothing changed.
                current = tuple(self.tree.item(iid, "values"))
                rendered = tuple(str(value) for value in values)
                if current != rendered or tuple(self.tree.item(iid, "tags")) != tags:
                    self.tree.item(iid, values=values, tags=tags)
                existing.remove(iid)
            else:
                self.tree.insert("", "end", iid=iid, values=values, tags=tags)
        for iid in existing:
            self.tree.delete(iid)
        for iid in selected:
            if self.tree.exists(iid):
                self.tree.selection_add(iid)
        online_count = sum(1 for server in self.servers if server.get("alive"))
        total_players = sum(int(server.get("players", 0) or 0) for server in self.servers)
        total_ram = sum(float(server.get("ram_mb", 0) or 0) for server in self.servers)
        self._summary_vars["total"].set(str(len(self.servers)))
        self._summary_vars["online"].set(str(online_count))
        self._summary_vars["players"].set(str(total_players))
        self._summary_vars["ram"].set(f"{total_ram:.0f} MB")
        self.status_var.set(f"Servicio conectado — {len(self.servers)} servidor(es) · modo rendimiento")

    def refresh_details(self, force: bool = False):
        """Load logs/metrics in a worker thread and at a slower cadence."""
        sid = self.selected_one_silent()
        if sid is None:
            self._clear_server_dashboard()
            return
        now = time.monotonic()
        server_changed = sid != self._details_server_id
        if self._details_inflight:
            return
        if not force and not server_changed and now - self._last_details_refresh < 6.0:
            return
        self._details_inflight = True
        load_backups = force or server_changed or now - self._last_backups_refresh >= 20.0

        def worker():
            try:
                discord_data = api.request("GET", f"/servers/{sid}/discord", timeout=5)
                log_data = api.request("GET", f"/servers/{sid}/logs?lines=220", timeout=5)
                events = api.request("GET", "/events?limit=120", timeout=5)
                metrics = api.request("GET", f"/servers/{sid}/metrics?limit=90", timeout=5)
                backups = api.request("GET", f"/servers/{sid}/backups", timeout=5) if load_backups else None
                payload = {
                    "sid": sid,
                    "discord": discord_data,
                    "log": log_data,
                    "events": events,
                    "metrics": metrics,
                    "backups": backups,
                    "loaded_backups": load_backups,
                }
                if not self._closing:
                    self.after(0, lambda: self._render_details(payload))
            except Exception as exc:
                if not self._closing:
                    self.after(0, lambda e=exc: self._details_refresh_failed(e))

        threading.Thread(target=worker, name=f"AsgardGuiDetails-{sid}", daemon=True).start()

    def _details_refresh_failed(self, exc: Exception):
        self._details_inflight = False
        self._last_details_refresh = time.monotonic()
        self._server_dashboard_note.set(f"No se pudieron actualizar los detalles: {exc}")

    def _render_details(self, payload: dict):
        self._details_inflight = False
        self._last_details_refresh = time.monotonic()
        sid = int(payload["sid"])
        if self.selected_one_silent() != sid:
            return
        self._details_server_id = sid
        runtime = payload["discord"]["runtime"]
        log_data = payload["log"]
        header = (
            f'Join Code: {runtime.get("join_code", "—")} | '
            f'Jugadores: {runtime.get("players", 0)}\n'
            f'Steam IDs: {", ".join(runtime.get("steam_ids", [])) or "—"}\n'
            f'Nombres detectados: {", ".join(runtime.get("player_names", [])) or "—"}\n'
            + ("-" * 90) + "\n"
        )
        new_log_content = header + "\n".join(log_data["lines"])
        if sid != self._last_log_server_id:
            self.log_text.delete("1.0", "end")
            self.log_text.insert("1.0", new_log_content)
            self.log_text.see("end")
            self._last_log_server_id = sid
            self._last_log_content = new_log_content
        elif new_log_content != self._last_log_content:
            top, bottom = self.log_text.yview()
            was_near_bottom = bottom >= 0.97
            self.log_text.delete("1.0", "end")
            self.log_text.insert("1.0", new_log_content)
            self.log_text.see("end") if was_near_bottom else self.log_text.yview_moveto(top)
            self._last_log_content = new_log_content

        new_events_content = "".join(
            f'[{event["created_at"]}] [{event["level"]}] '
            f'{event.get("server_name") or "HOST"}: {event["message"]}\n'
            for event in reversed(payload["events"])
        )
        if new_events_content != self._last_events_content:
            top, bottom = self.events_text.yview()
            was_near_bottom = bottom >= 0.97
            self.events_text.delete("1.0", "end")
            self.events_text.insert("1.0", new_events_content)
            self.events_text.see("end") if was_near_bottom else self.events_text.yview_moveto(top)
            self._last_events_content = new_events_content

        if payload.get("backups") is not None:
            self._last_backups_refresh = time.monotonic()
            current = [tuple(self.backups_tree.item(iid, "values")) for iid in self.backups_tree.get_children()]
            rendered = [
                (item["created_at"], item["reason"], f'{item["size_bytes"] / (1024**2):.1f} MB', item["path"])
                for item in payload["backups"]
            ]
            if current != [tuple(str(value) for value in row) for row in rendered]:
                self.backups_tree.delete(*self.backups_tree.get_children())
                for row in rendered:
                    self.backups_tree.insert("", "end", values=row)

        metrics = payload["metrics"]
        server = next((item for item in self.servers if int(item["id"]) == sid), {})
        self._server_dash_vars["name"].set(server.get("name", "—"))
        self._server_dash_vars["status"].set(server.get("status", "—"))
        self._server_dash_vars["health"].set(server.get("health_state", "—"))
        self._server_dash_vars["pid"].set(str(server.get("pid") or "—"))
        self._server_dash_vars["players"].set(str(server.get("players", 0)))
        self._server_dash_vars["join_code"].set(str(server.get("join_code") or "—"))
        self._server_dash_vars["cpu"].set(f'{float(server.get("cpu_percent", 0) or 0):.1f}%')
        self._server_dash_vars["ram"].set(f'{float(server.get("ram_mb", 0) or 0):.1f} MB')
        self.server_cpu_graph.set_values([float(item.get("cpu_percent", 0) or 0) for item in metrics])
        self.server_ram_graph.set_values([float(item.get("ram_mb", 0) or 0) for item in metrics])
        self._server_dashboard_note.set(
            f'Tiempo activo: {self.fmt_uptime(server.get("uptime_seconds", 0))} · '
            f'Salud: {server.get("health_state", "—")} · {server.get("health_detail", "Sin diagnóstico")} · '
            f'Historial: {len(metrics)} muestras · actualización ligera cada 6 s'
        )

    def _clear_server_dashboard(self):
        if not hasattr(self, "_server_dash_vars"):
            return
        for value in self._server_dash_vars.values():
            value.set("—")
        self.server_cpu_graph.set_values([])
        self.server_ram_graph.set_values([])
        self._server_dashboard_note.set("Selecciona exactamente un servidor para ver sus recursos.")

    def selected_one_silent(self):
        ids = [int(iid) for iid in self.tree.selection()]
        if len(ids) != 1:
            self._last_log_server_id = None
            self._last_log_content = ""
            return None
        return ids[0]

    def _refresh_loop(self):
        if self._closing:
            return
        self.refresh()
        self.refresh_details()
        self.after(750, self._refresh_loop)


if __name__ == "__main__":
    App().mainloop()
