from __future__ import annotations

import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib.parse import quote

from common import MOD_LIBRARY_ROOT, CONFIG_LIBRARY_ROOT, REMOTE_DOWNLOADS_DIR
from resource_gui import ResourcePolicyWindow


class RemoteHostEditor(tk.Toplevel):
    def __init__(self, parent, host: dict | None, on_save):
        super().__init__(parent)
        self.title("Editar host remoto" if host else "Agregar host remoto")
        self.geometry("760x610")
        self.minsize(680, 560)
        self.transient(parent)
        self.grab_set()
        self.on_save = on_save
        host = host or {}
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        self.vars = {
            "name": tk.StringVar(value=host.get("name", "Host Chile")),
            "address": tk.StringVar(value=host.get("address", "")),
            "tailscale_ip": tk.StringVar(value=host.get("tailscale_ip", "")),
            "ssh_port": tk.StringVar(value=str(host.get("ssh_port", 22))),
            "username": tk.StringVar(value=host.get("username", "")),
            "auth_type": tk.StringVar(value=host.get("auth_type", "password")),
            "password": tk.StringVar(value=""),
            "key_path": tk.StringVar(value=host.get("key_path", "")),
            "agent_port": tk.StringVar(value=str(host.get("agent_port", 8766))),
            "remote_base": tk.StringVar(value=host.get("remote_base", "C:/ASGARDRemote")),
        }
        self.enabled = tk.BooleanVar(value=bool(host.get("enabled", True)))
        fields = [
            ("Nombre", "name"),
            ("Dirección/IP SSH", "address"),
            ("IP Tailscale (opcional)", "tailscale_ip"),
            ("Puerto SSH", "ssh_port"),
            ("Usuario Windows", "username"),
            ("Autenticación", "auth_type"),
            ("Contraseña / passphrase", "password"),
            ("Clave privada", "key_path"),
            ("Puerto agente", "agent_port"),
            ("Carpeta remota ASGARD", "remote_base"),
        ]
        for row, (label, key) in enumerate(fields):
            ttk.Label(root, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=5)
            if key == "auth_type":
                widget = ttk.Combobox(root, textvariable=self.vars[key], state="readonly", values=("password", "key"))
            else:
                widget = ttk.Entry(root, textvariable=self.vars[key], show="•" if key == "password" else "")
            widget.grid(row=row, column=1, sticky="ew", pady=5)
            if key == "key_path":
                ttk.Button(root, text="Examinar", command=self._browse_key).grid(row=row, column=2, padx=(8, 0))
        ttk.Checkbutton(root, text="Host habilitado", variable=self.enabled).grid(row=10, column=1, sticky="w", pady=7)
        note = (
            "Primera conexión: el host remoto debe tener OpenSSH activo. Después, el botón "
            "Autoconfigurar instala el agente, crea la tarea de inicio y abre el puerto privado."
        )
        ttk.Label(root, text=note, wraplength=650, foreground="#FF8A9B").grid(row=11, column=0, columnspan=3, sticky="w", pady=10)
        buttons = ttk.Frame(root)
        buttons.grid(row=12, column=0, columnspan=3, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Guardar", command=self._save).pack(side="right")

    def _browse_key(self):
        path = filedialog.askopenfilename(parent=self, title="Clave privada SSH", filetypes=[("Claves", "*.pem *.key id_*"), ("Todos", "*.*")])
        if path:
            self.vars["key_path"].set(path)

    def _save(self):
        try:
            data = {key: var.get().strip() for key, var in self.vars.items()}
            data["ssh_port"] = int(data["ssh_port"])
            data["agent_port"] = int(data["agent_port"])
            data["enabled"] = self.enabled.get()
            if not data["name"] or not data["address"] or not data["username"]:
                raise ValueError("Nombre, dirección y usuario son obligatorios")
            self.on_save(data)
            self.destroy()
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)


class RemoteServerEditor(tk.Toplevel):
    def __init__(self, parent, host_id: int, server: dict | None, on_save):
        super().__init__(parent)
        self.title("Registrar servidor remoto")
        self.geometry("900x650")
        self.transient(parent)
        self.grab_set()
        server = server or {}
        self.host_id = host_id
        self.on_save = on_save
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(4, weight=1)
        self.vars = {
            "name": tk.StringVar(value=server.get("name", "Servidor remoto")),
            "executable": tk.StringVar(value=server.get("executable", "")),
            "working_directory": tk.StringVar(value=server.get("working_directory", "")),
            "savedir": tk.StringVar(value=server.get("savedir", "")),
            "log_file": tk.StringVar(value=server.get("log_file", "")),
            "backup_directory": tk.StringVar(value=server.get("backup_directory", "")),
            "backup_retention": tk.StringVar(value=str(server.get("backup_retention", 10))),
        }
        self.auto_start = tk.BooleanVar(value=bool(server.get("auto_start", False)))
        for row, (label, key) in enumerate([
            ("Nombre", "name"), ("valheim_server.exe remoto", "executable"),
            ("Carpeta de trabajo", "working_directory"), ("Savedir", "savedir"),
        ]):
            ttk.Label(root, text=label).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 8))
            ttk.Entry(root, textvariable=self.vars[key]).grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Label(root, text="Parámetros").grid(row=4, column=0, sticky="nw", pady=5)
        self.params = tk.Text(root, wrap="word", height=12)
        self.params.insert("1.0", server.get("parameters", '-nographics -batchmode -name "Servidor remoto" -port 2456 -world "Dedicated" -password "CAMBIAR" -crossplay -public 1'))
        self.params.grid(row=4, column=1, sticky="nsew", pady=5)
        for row, (label, key) in enumerate([
            ("Archivo log", "log_file"), ("Carpeta backups", "backup_directory"),
            ("Backups a conservar", "backup_retention"),
        ], start=5):
            ttk.Label(root, text=label).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 8))
            ttk.Entry(root, textvariable=self.vars[key]).grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Checkbutton(root, text="Auto iniciar con el agente", variable=self.auto_start).grid(row=8, column=1, sticky="w", pady=6)
        buttons = ttk.Frame(root)
        buttons.grid(row=9, column=0, columnspan=2, sticky="e", pady=10)
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Registrar", command=self._save).pack(side="right")

    def _save(self):
        try:
            data = {key: var.get().strip() for key, var in self.vars.items()}
            data.update({
                "host_id": self.host_id,
                "parameters": self.params.get("1.0", "end-1c").strip(),
                "backup_retention": int(data["backup_retention"]),
                "auto_start": self.auto_start.get(),
            })
            self.on_save(data)
            self.destroy()
        except Exception as exc:
            messagebox.showerror("ASGARD", str(exc), parent=self)


class DiscoveryWindow(tk.Toplevel):
    def __init__(self, parent, host_id: int, items: list[dict], register_callback):
        super().__init__(parent)
        self.title("Servidores Valheim encontrados")
        self.geometry("1100x560")
        self.transient(parent)
        self.grab_set()
        self.host_id = host_id
        self.items = items
        self.register_callback = register_callback
        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)
        columns = ("name", "exe", "bat")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        for col, title, width in (("name", "Nombre", 180), ("exe", "Ejecutable", 600), ("bat", "BAT detectado", 260)):
            self.tree.heading(col, text=title); self.tree.column(col, width=width)
        self.tree.pack(fill="both", expand=True)
        for index, item in enumerate(items):
            self.tree.insert("", "end", iid=str(index), values=(item.get("name", ""), item.get("executable", ""), item.get("start_bat", "")))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Registrar seleccionados", command=self._register).pack(side="right")
        ttk.Button(buttons, text="Cerrar", command=self.destroy).pack(side="right", padx=8)

    def _register(self):
        selected = [self.items[int(i)] for i in self.tree.selection()]
        if not selected:
            messagebox.showinfo("ASGARD", "Selecciona uno o más servidores.", parent=self)
            return
        self.register_callback(selected)
        self.destroy()


class RemoteLogsWindow(tk.Toplevel):
    def __init__(self, parent, title: str, lines: list[str]):
        super().__init__(parent)
        self.title(title)
        self.geometry("1100x700")
        text = tk.Text(self, wrap="none", bg="#070203", fg="#EED9DD", font=("Consolas", 9))
        text.pack(fill="both", expand=True)
        text.insert("1.0", "\n".join(lines))
        text.see("end")


class RemoteFileExplorerWindow(tk.Toplevel):
    def __init__(self, parent, api, remote_server_id: int, server_name: str):
        super().__init__(parent)
        self.title(f"Archivos SFTP — {server_name}")
        self.geometry("1100x700")
        self.api = api
        self.remote_server_id = remote_server_id
        self.scope = tk.StringVar(value="server")
        self.path = ""
        self.parent_path = ""
        self.entries: list[dict] = []
        self.status = tk.StringVar(value="Conectando por SFTP...")
        self._build()
        self.refresh()

    def _build(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)
        bar = ttk.Frame(root)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Alcance:").pack(side="left")
        combo = ttk.Combobox(
            bar, textvariable=self.scope, state="readonly",
            values=("server", "savedir", "backups"), width=14,
        )
        combo.pack(side="left", padx=6)
        combo.bind("<<ComboboxSelected>>", lambda _e: self._change_scope())
        ttk.Button(bar, text="Subir", command=self.up).pack(side="left", padx=(8, 4))
        ttk.Button(bar, text="Actualizar", command=self.refresh).pack(side="left")
        self.path_var = tk.StringVar(value="/")
        ttk.Label(bar, textvariable=self.path_var, foreground="#FF8A9B").pack(side="left", padx=14)
        ttk.Button(bar, text="Abrir descargas", command=self.open_downloads).pack(side="right")

        columns = ("name", "type", "size", "modified")
        self.tree = ttk.Treeview(root, columns=columns, show="headings", selectmode="extended")
        for col, title, width in (
            ("name", "Nombre", 520), ("type", "Tipo", 90),
            ("size", "Tamaño", 110), ("modified", "Modificado", 180),
        ):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.open_selected())

        buttons = ttk.Frame(root)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Subir archivo", command=self.upload_file).pack(side="left", padx=(0, 5))
        ttk.Button(buttons, text="Subir carpeta", command=self.upload_folder).pack(side="left", padx=(0, 5))
        ttk.Button(buttons, text="Descargar seleccionado", command=self.download_selected).pack(side="left", padx=(0, 5))
        ttk.Label(buttons, textvariable=self.status, relief="sunken", anchor="w").pack(side="right", fill="x", expand=True)

    def _async(self, work, done=None):
        self.status.set("Procesando...")
        def runner():
            try:
                result = work()
                self.after(0, lambda: self._done(result, done))
            except Exception as exc:
                self.after(0, lambda e=exc: self._error(e))
        threading.Thread(target=runner, daemon=True).start()

    def _done(self, result, done):
        self.status.set("Listo")
        if done:
            done(result)

    def _error(self, exc):
        self.status.set(f"Error: {exc}")
        messagebox.showerror("ASGARD SFTP", str(exc), parent=self)

    def _change_scope(self):
        self.path = ""
        self.refresh()

    def refresh(self):
        scope = self.scope.get()
        relative = self.path
        self._async(
            lambda: self.api.request(
                "GET",
                f"/remote/servers/{self.remote_server_id}/files?scope={quote(scope, safe='')}&path={quote(relative, safe='')}",
                timeout=60,
            ),
            self._render,
        )

    def _render(self, data):
        self.entries = data.get("entries", [])
        self.parent_path = data.get("parent", "")
        self.path = data.get("path", "")
        self.path_var.set(f"{data.get('root', '')}  /  {self.path}")
        self.tree.delete(*self.tree.get_children())
        for index, entry in enumerate(self.entries):
            modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry.get("mtime", 0)))
            size = "—" if entry.get("is_dir") else self._format_size(entry.get("size", 0))
            self.tree.insert(
                "", "end", iid=str(index),
                values=(entry["name"], "Carpeta" if entry.get("is_dir") else "Archivo", size, modified),
            )

    @staticmethod
    def _format_size(value):
        number = float(value or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if number < 1024 or unit == "TB":
                return f"{number:.1f} {unit}"
            number /= 1024

    def selected_entries(self):
        return [self.entries[int(i)] for i in self.tree.selection()]

    def open_selected(self):
        selected = self.selected_entries()
        if len(selected) == 1 and selected[0].get("is_dir"):
            self.path = selected[0]["relative_path"]
            self.refresh()

    def up(self):
        self.path = self.parent_path
        self.refresh()

    def upload_file(self):
        value = filedialog.askopenfilename(parent=self)
        if value:
            self._upload(value)

    def upload_folder(self):
        value = filedialog.askdirectory(parent=self)
        if value:
            self._upload(value)

    def _upload(self, local_path):
        self._async(
            lambda: self.api.request(
                "POST", f"/remote/servers/{self.remote_server_id}/files-upload",
                {"scope": self.scope.get(), "path": self.path, "local_path": local_path},
                timeout=1800,
            ),
            lambda result: self._upload_done(result),
        )

    def _upload_done(self, result):
        messagebox.showinfo(
            "ASGARD SFTP",
            f"Actualizados: {len(result.get('uploaded', []))}\nSin cambios: {len(result.get('skipped', []))}",
            parent=self,
        )
        self.refresh()

    def download_selected(self):
        selected = self.selected_entries()
        if not selected:
            return
        def work():
            return [
                self.api.request(
                    "POST", f"/remote/servers/{self.remote_server_id}/files-download",
                    {"scope": self.scope.get(), "path": entry["relative_path"]}, timeout=1800,
                )
                for entry in selected
            ]
        self._async(
            work,
            lambda results: messagebox.showinfo(
                "ASGARD SFTP",
                f"Descargados: {len(results)}\nCarpeta: {REMOTE_DOWNLOADS_DIR}",
                parent=self,
            ),
        )

    def open_downloads(self):
        REMOTE_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(REMOTE_DOWNLOADS_DIR)
        except OSError as exc:
            self._error(exc)


class RemoteCenterWindow(tk.Toplevel):
    def __init__(self, parent, api):
        super().__init__(parent)
        self.title("ASGARD Remote Center — SSH/SFTP + Recursos")
        self.geometry("1450x820")
        self.minsize(1050, 680)
        self.api = api
        self.hosts: list[dict] = []
        self.servers: list[dict] = []
        self.status = tk.StringVar(value="Cargando hosts remotos...")
        self._build()
        self.refresh()

    def _build(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)
        top = ttk.Frame(root)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="ASGARD REMOTE CENTER", font=("Segoe UI Semibold", 16)).pack(side="left")
        ttk.Label(top, text="Control de hosts mediante red privada, SSH/SFTP y agente seguro", foreground="#FF8A9B").pack(side="left", padx=14)
        ttk.Button(top, text="Actualizar", command=self.refresh).pack(side="right")

        split = ttk.Panedwindow(root, orient="horizontal")
        split.pack(fill="both", expand=True)
        host_box = ttk.LabelFrame(split, text="Hosts remotos", padding=7)
        server_box = ttk.LabelFrame(split, text="Servidores remotos", padding=7)
        split.add(host_box, weight=1); split.add(server_box, weight=2)

        self.host_tree = ttk.Treeview(host_box, columns=("name", "address", "ssh", "agent", "state"), show="headings", selectmode="browse")
        for col, title, width in (("name", "Host", 150), ("address", "Dirección", 170), ("ssh", "SSH", 60), ("agent", "Agente", 70), ("state", "Estado", 130)):
            self.host_tree.heading(col, text=title); self.host_tree.column(col, width=width)
        self.host_tree.pack(fill="both", expand=True)
        self.host_tree.bind("<<TreeviewSelect>>", lambda _e: self.refresh_servers())
        hb = ttk.Frame(host_box); hb.pack(fill="x", pady=(7, 0))
        for label, command in (("Agregar", self.add_host), ("Editar", self.edit_host), ("Eliminar", self.delete_host)):
            ttk.Button(hb, text=label, command=command).pack(side="left", padx=(0, 5))
        hb2 = ttk.Frame(host_box); hb2.pack(fill="x", pady=(5, 0))
        for label, command in (("Probar SSH", self.test_ssh), ("Probar agente", self.test_agent), ("Autoconfigurar", self.autoconfigure)):
            ttk.Button(hb2, text=label, command=command).pack(side="left", padx=(0, 5))
        ttk.Button(host_box, text="Buscar servidores Valheim", command=self.discover).pack(fill="x", pady=(6, 0))
        ttk.Button(host_box, text="Registrar servidor manualmente", command=self.add_server).pack(fill="x", pady=(4, 0))

        columns = ("host", "name", "status", "pid", "cpu", "ram", "exe")
        self.server_tree = ttk.Treeview(server_box, columns=columns, show="headings", selectmode="extended")
        for col, title, width in (
            ("host", "Host", 120), ("name", "Servidor", 170), ("status", "Estado", 130),
            ("pid", "PID", 70), ("cpu", "CPU", 70), ("ram", "RAM", 90), ("exe", "Ejecutable remoto", 430),
        ):
            self.server_tree.heading(col, text=title); self.server_tree.column(col, width=width)
        self.server_tree.pack(fill="both", expand=True)
        sb = ttk.Frame(server_box); sb.pack(fill="x", pady=(7, 0))
        for label, action in (("Iniciar", "start"), ("Detener", "stop"), ("Reiniciar", "restart"), ("Backup", "backup"), ("Terminar", "kill")):
            ttk.Button(sb, text=label, command=lambda a=action: self.control(a)).pack(side="left", padx=(0, 5))
        sb2 = ttk.Frame(server_box); sb2.pack(fill="x", pady=(5, 0))
        ttk.Button(sb2, text="Ver logs", command=self.logs).pack(side="left", padx=(0, 5))
        ttk.Button(sb2, text="Archivos SFTP", command=self.file_explorer).pack(side="left", padx=(0, 5))
        ttk.Button(sb2, text="CPU y memoria", command=self.resources).pack(side="left", padx=(0, 5))
        ttk.Button(sb2, text="Backup + descargar", command=self.backup_download).pack(side="left", padx=(0, 5))
        ttk.Button(sb2, text="Desplegar MOD", command=lambda: self.deploy("mods")).pack(side="left", padx=(0, 5))
        ttk.Button(sb2, text="Desplegar CONFIG", command=lambda: self.deploy("configs")).pack(side="left", padx=(0, 5))
        ttk.Button(sb2, text="Eliminar registro", command=self.delete_server).pack(side="right")

        ttk.Label(root, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x", pady=(8, 0))

    def _async(self, work, done=None):
        self.status.set("Procesando...")
        def runner():
            try:
                result = work()
                self.after(0, lambda: self._success(result, done))
            except Exception as exc:
                self.after(0, lambda e=exc: self._error(e))
        threading.Thread(target=runner, daemon=True).start()

    def _success(self, result, done):
        self.status.set("Operación completada")
        if done:
            done(result)

    def _error(self, exc):
        self.status.set(f"Error: {exc}")
        messagebox.showerror("ASGARD Remote", str(exc), parent=self)

    def selected_host_id(self):
        selected = self.host_tree.selection()
        return int(selected[0]) if selected else None

    def selected_server_ids(self):
        return [int(item) for item in self.server_tree.selection()]

    def selected_server_id(self):
        selected = self.selected_server_ids()
        return selected[0] if selected else None

    def refresh(self):
        self._async(lambda: self.api.request("GET", "/remote/hosts", timeout=15), self._set_hosts)

    def _set_hosts(self, hosts):
        self.hosts = hosts
        self.host_tree.delete(*self.host_tree.get_children())
        for host in hosts:
            self.host_tree.insert("", "end", iid=str(host["id"]), values=(host["name"], host.get("tailscale_ip") or host["address"], host["ssh_port"], host["agent_port"], "Configurado" if host.get("has_api_token") else "Pendiente"))
        if hosts:
            self.host_tree.selection_set(str(hosts[0]["id"]))
        self.refresh_servers()

    def refresh_servers(self):
        hid = self.selected_host_id()
        path = f"/remote/servers?host_id={hid}" if hid else "/remote/servers"
        self._async(lambda: self.api.request("GET", path, timeout=30), self._set_servers)

    def _set_servers(self, servers):
        self.servers = servers
        self.server_tree.delete(*self.server_tree.get_children())
        for server in servers:
            self.server_tree.insert("", "end", iid=str(server["id"]), values=(
                server.get("host_name", ""), server["name"], server.get("status", "—"), server.get("pid") or "—",
                f"{float(server.get('cpu_percent', 0)):.1f}%", f"{float(server.get('ram_mb', 0)):.1f} MB", server["executable"],
            ))

    def add_host(self):
        RemoteHostEditor(self, None, lambda data: self._async(lambda: self.api.request("POST", "/remote/hosts", data), lambda _r: self.refresh()))

    def edit_host(self):
        hid = self.selected_host_id()
        if hid is None: return
        host = next(x for x in self.hosts if int(x["id"]) == hid)
        RemoteHostEditor(self, host, lambda data: self._async(lambda: self.api.request("PUT", f"/remote/hosts/{hid}", data), lambda _r: self.refresh()))

    def delete_host(self):
        hid = self.selected_host_id()
        if hid is None: return
        if messagebox.askyesno("ASGARD", "¿Eliminar el host y sus registros remotos?", parent=self):
            self._async(lambda: self.api.request("DELETE", f"/remote/hosts/{hid}"), lambda _r: self.refresh())

    def test_ssh(self):
        hid = self.selected_host_id()
        if hid is None: return
        self._async(lambda: self.api.request("POST", f"/remote/hosts/{hid}/test-ssh", {}, timeout=30), lambda r: messagebox.showinfo("SSH correcto", f"Equipo: {r.get('computer')}\nUsuario: {r.get('user')}\nAdministrador: {r.get('admin')}\nLatencia: {r.get('latency_ms')} ms", parent=self))

    def test_agent(self):
        hid = self.selected_host_id()
        if hid is None: return
        self._async(lambda: self.api.request("POST", f"/remote/hosts/{hid}/test-agent", {}, timeout=15), lambda r: messagebox.showinfo("Agente conectado", f"Equipo: {r.get('hostname')}\nVersión: {r.get('version')}\nCPU: {r.get('cpu_percent')}%\nRAM: {r.get('ram_percent')}%", parent=self))

    def autoconfigure(self):
        hid = self.selected_host_id()
        if hid is None: return
        text = (
            "ASGARD subirá el agente por SFTP, creará una tarea de inicio automático y una regla de firewall.\n\n"
            "La cuenta SSH debe tener privilegios administrativos. ¿Continuar?"
        )
        if messagebox.askyesno("Autoconfigurar host", text, parent=self):
            self._async(lambda: self.api.request("POST", f"/remote/hosts/{hid}/autoconfigure", {}, timeout=180), lambda r: messagebox.showinfo("ASGARD", f"Agente configurado correctamente.\nEquipo: {r['health'].get('hostname')}", parent=self))

    def discover(self):
        hid = self.selected_host_id()
        if hid is None: return
        root = simpledialog.askstring("Buscar Valheim", "Raíz a revisar (vacío = C:/games, C:/servers, D:/games y D:/servers):", parent=self) or ""
        self._async(lambda: self.api.request("POST", f"/remote/hosts/{hid}/discover", {"root": root}, timeout=180), lambda items: DiscoveryWindow(self, hid, items, self._register_discovered))

    def _register_discovered(self, items):
        hid = self.selected_host_id()
        if hid is None: return
        def work():
            results=[]
            for item in items:
                item["host_id"] = hid
                results.append(self.api.request("POST", "/remote/servers", item, timeout=40))
            return results
        self._async(work, lambda _r: self.refresh_servers())

    def add_server(self):
        hid = self.selected_host_id()
        if hid is None:
            messagebox.showinfo("ASGARD", "Selecciona un host remoto.", parent=self); return
        RemoteServerEditor(self, hid, None, lambda data: self._async(lambda: self.api.request("POST", "/remote/servers", data, timeout=40), lambda _r: self.refresh_servers()))

    def control(self, action):
        ids = self.selected_server_ids()
        if not ids: return
        payload = {"backup": True, "force": True, "reason": "manual"}
        def work():
            return [self.api.request("POST", f"/remote/servers/{rid}/{action}", payload, timeout=180) for rid in ids]
        self._async(work, lambda _r: self.refresh_servers())

    def resources(self):
        rid = self.selected_server_id()
        if rid is None:
            return
        server = next(x for x in self.servers if int(x["id"]) == rid)
        ResourcePolicyWindow(
            self,
            self.api,
            f"Recursos remotos — {server['name']}",
            f"/remote/servers/{rid}/resources",
            f"/remote/servers/{rid}/resources",
            f"/remote/servers/{rid}/resources-apply",
            f"/remote/servers/{rid}/resources-autoconfigure",
        )

    def file_explorer(self):
        rid = self.selected_server_id()
        if rid is None: return
        server = next(x for x in self.servers if int(x["id"]) == rid)
        RemoteFileExplorerWindow(self, self.api, rid, server["name"])

    def backup_download(self):
        ids = self.selected_server_ids()
        if not ids: return
        if not messagebox.askyesno("ASGARD", f"Crear y descargar backup de {len(ids)} servidor(es)?", parent=self):
            return
        def work():
            return [self.api.request("POST", f"/remote/servers/{rid}/backup-download", {}, timeout=1800) for rid in ids]
        self._async(
            work,
            lambda results: messagebox.showinfo(
                "Backups descargados",
                "\n".join(r.get("local_path", "") for r in results),
                parent=self,
            ),
        )

    def logs(self):
        rid = self.selected_server_id()
        if rid is None: return
        server = next(x for x in self.servers if int(x["id"]) == rid)
        self._async(lambda: self.api.request("GET", f"/remote/servers/{rid}/logs?lines=1000", timeout=40), lambda r: RemoteLogsWindow(self, f"Log remoto — {server['name']}", r.get("lines", [])))

    def _choose_library_item(self, kind: str):
        root = MOD_LIBRARY_ROOT if kind == "mods" else CONFIG_LIBRARY_ROOT
        choice = messagebox.askyesnocancel("Biblioteca ASGARD", "Sí: seleccionar archivo\nNo: seleccionar carpeta\nCancelar: volver", parent=self)
        if choice is None: return None
        value = filedialog.askopenfilename(parent=self, initialdir=root) if choice else filedialog.askdirectory(parent=self, initialdir=root)
        if not value: return None
        path = Path(value).resolve()
        if path != root.resolve() and root.resolve() not in path.parents:
            raise ValueError("Selecciona un elemento dentro de la biblioteca portable")
        return str(path.relative_to(root))

    def deploy(self, kind):
        ids = self.selected_server_ids()
        if not ids: return
        try:
            relative = self._choose_library_item(kind)
        except Exception as exc:
            self._error(exc); return
        if not relative: return
        if not messagebox.askyesno("Despliegue remoto", f"Se creará un backup de BepInEx y se sincronizarán solo archivos modificados.\n\n{relative}\n\n¿Continuar?", parent=self):
            return
        def work():
            results = []
            for rid in ids:
                results.append(self.api.request("POST", f"/remote/servers/{rid}/deploy", {"kind": kind, "relative_path": relative}, timeout=900))
            return results
        def done(results):
            updated = sum(len(r.get("uploaded", [])) for r in results)
            skipped = sum(len(r.get("skipped", [])) for r in results)
            messagebox.showinfo("Despliegue terminado", f"Servidores: {len(results)}\nActualizados: {updated}\nSin cambios: {skipped}", parent=self)
        self._async(work, done)

    def delete_server(self):
        ids = self.selected_server_ids()
        if not ids: return
        if messagebox.askyesno("ASGARD", f"¿Eliminar {len(ids)} registro(s) remoto(s)? No borra los archivos del servidor.", parent=self):
            self._async(lambda: [self.api.request("DELETE", f"/remote/servers/{rid}") for rid in ids], lambda _r: self.refresh_servers())
