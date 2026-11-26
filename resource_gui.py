from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk


PROFILE_LABELS = {
    "balanced": "Automático equilibrado",
    "low_impact": "Bajo impacto",
    "priority": "Servidor prioritario",
    "custom": "Personalizado",
}
PRIORITY_LABELS = {
    "idle": "Baja",
    "below_normal": "Por debajo de normal",
    "normal": "Normal",
    "above_normal": "Por encima de normal",
}
ACTION_LABELS = {
    "warn": "Solo advertir",
    "restart_when_empty": "Reiniciar cuando quede vacío",
    "backup_restart": "Backup y reinicio inmediato (avanzado)",
}


class ResourcePolicyWindow(tk.Toplevel):
    def __init__(
        self,
        parent,
        api,
        title: str,
        get_path: str,
        save_path: str,
        apply_path: str,
        autoconfigure_path: str,
    ):
        super().__init__(parent)
        self.title(title)
        self.geometry("1040x830")
        self.minsize(920, 740)
        self.transient(parent)
        self.grab_set()
        self.api = api
        self.get_path = get_path
        self.save_path = save_path
        self.apply_path = apply_path
        self.autoconfigure_path = autoconfigure_path
        self.data: dict = {}
        self.current_ram_mb = 0.0
        self.cpu_topology: list[dict] = []
        self.allowed_core_ids: set[str] = set()
        self.available_row_ids: list[str] = []
        self.allowed_row_ids: list[str] = []

        self.status = tk.StringVar(value="Cargando configuración...")
        self.enabled = tk.BooleanVar(value=False)
        self.apply_on_start = tk.BooleanVar(value=True)
        self.auto_rebalance = tk.BooleanVar(value=False)
        self.profile = tk.StringVar(value="balanced")
        self.cpu_limit = tk.StringVar(value="0")
        self.priority = tk.StringVar(value="normal")
        self.ram_warning = tk.StringVar(value="0")
        self.ram_hard = tk.StringVar(value="0")
        self.ram_action = tk.StringVar(value="warn")
        self.cpu_summary = tk.StringVar(value="Detectando topología del procesador...")

        self._build()
        self._async(lambda: self.api.request("GET", self.get_path, timeout=30), self._load)

    def _build(self):
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(header, text="CONTROL DE RECURSOS", font=("Segoe UI Semibold", 16)).pack(anchor="w")
        ttk.Label(
            header,
            text="Asigna núcleos físicos completos, prioridad, porcentaje de CPU y protección de memoria por servidor.",
            foreground="#FF8A9B",
        ).pack(anchor="w")

        general = ttk.LabelFrame(root, text="Política", padding=10)
        general.grid(row=1, column=0, sticky="ew", pady=5)
        general.columnconfigure(1, weight=1)
        ttk.Checkbutton(general, text="Habilitar límites de recursos", variable=self.enabled).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=3
        )
        ttk.Label(general, text="Perfil").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        profile_box = ttk.Combobox(general, state="readonly", width=34)
        profile_box["values"] = list(PROFILE_LABELS.values())
        profile_box.grid(row=1, column=1, sticky="w", pady=4)
        profile_box.set(PROFILE_LABELS["balanced"])
        self.profile_box = profile_box
        ttk.Checkbutton(
            general,
            text="Aplicar en cada inicio y recuperación",
            variable=self.apply_on_start,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Checkbutton(
            general,
            text="Permitir rebalanceo automático",
            variable=self.auto_rebalance,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=3)

        cpu = ttk.LabelFrame(root, text="CPU — afinidad por núcleo físico", padding=10)
        cpu.grid(row=2, column=0, sticky="ew", pady=5)
        cpu.columnconfigure(0, weight=1)
        cpu.columnconfigure(2, weight=1)

        ttk.Label(
            cpu,
            text="Núcleos físicos disponibles\n(cada fila incluye sus procesadores lógicos)",
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 5))
        ttk.Label(
            cpu,
            text="Núcleos físicos permitidos\n(el servidor solo podrá usar estos hilos)",
            justify="left",
        ).grid(row=0, column=2, sticky="w", pady=(0, 5))

        available_frame = ttk.Frame(cpu)
        available_frame.grid(row=1, column=0, sticky="nsew")
        available_frame.columnconfigure(0, weight=1)
        available_frame.rowconfigure(0, weight=1)
        self.available_cpu_list = tk.Listbox(
            available_frame,
            selectmode="extended",
            exportselection=False,
            height=8,
        )
        self.available_cpu_list.grid(row=0, column=0, sticky="nsew")
        available_scroll = ttk.Scrollbar(
            available_frame,
            orient="vertical",
            command=self.available_cpu_list.yview,
        )
        available_scroll.grid(row=0, column=1, sticky="ns")
        self.available_cpu_list.configure(yscrollcommand=available_scroll.set)
        self.available_cpu_list.bind("<Double-Button-1>", lambda _event: self._add_selected_cores())

        move_buttons = ttk.Frame(cpu, padding=(10, 0))
        move_buttons.grid(row=1, column=1, sticky="ns")
        ttk.Button(move_buttons, text="Agregar  >", width=15, command=self._add_selected_cores).pack(pady=(8, 5))
        ttk.Button(move_buttons, text="<  Eliminar", width=15, command=self._remove_selected_cores).pack(pady=5)
        ttk.Separator(move_buttons, orient="horizontal").pack(fill="x", pady=8)
        ttk.Button(move_buttons, text="Agregar todos  >>", width=15, command=self._add_all_cores).pack(pady=5)
        ttk.Button(move_buttons, text="<<  Quitar todos", width=15, command=self._remove_all_cores).pack(pady=5)
        ttk.Button(move_buttons, text="Actualizar lista", width=15, command=self._refresh_detection).pack(pady=(14, 5))

        allowed_frame = ttk.Frame(cpu)
        allowed_frame.grid(row=1, column=2, sticky="nsew")
        allowed_frame.columnconfigure(0, weight=1)
        allowed_frame.rowconfigure(0, weight=1)
        self.allowed_cpu_list = tk.Listbox(
            allowed_frame,
            selectmode="extended",
            exportselection=False,
            height=8,
        )
        self.allowed_cpu_list.grid(row=0, column=0, sticky="nsew")
        allowed_scroll = ttk.Scrollbar(
            allowed_frame,
            orient="vertical",
            command=self.allowed_cpu_list.yview,
        )
        allowed_scroll.grid(row=0, column=1, sticky="ns")
        self.allowed_cpu_list.configure(yscrollcommand=allowed_scroll.set)
        self.allowed_cpu_list.bind("<Double-Button-1>", lambda _event: self._remove_selected_cores())

        ttk.Label(
            cpu,
            textvariable=self.cpu_summary,
            foreground="#FF8A9B",
            wraplength=930,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 8))

        cpu_options = ttk.Frame(cpu)
        cpu_options.grid(row=3, column=0, columnspan=3, sticky="ew")
        cpu_options.columnconfigure(1, weight=1)
        ttk.Label(cpu_options, text="Límite máximo de CPU (%)").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=4
        )
        ttk.Spinbox(
            cpu_options,
            from_=0,
            to=100,
            increment=5,
            textvariable=self.cpu_limit,
            width=12,
        ).grid(row=0, column=1, sticky="w", pady=4)
        ttk.Label(cpu_options, text="0 = sin límite duro").grid(
            row=0, column=1, sticky="w", padx=(110, 0)
        )
        ttk.Label(cpu_options, text="Prioridad").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=4
        )
        priority_box = ttk.Combobox(
            cpu_options,
            state="readonly",
            values=list(PRIORITY_LABELS.values()),
            width=32,
        )
        priority_box.grid(row=1, column=1, sticky="w", pady=4)
        priority_box.set(PRIORITY_LABELS["normal"])
        self.priority_box = priority_box

        ram = ttk.LabelFrame(root, text="Memoria RAM", padding=10)
        ram.grid(row=3, column=0, sticky="nsew", pady=5)
        ram.columnconfigure(1, weight=1)
        ttk.Label(ram, text="Advertir al superar (MB)").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=5
        )
        ttk.Entry(ram, textvariable=self.ram_warning, width=18).grid(
            row=0, column=1, sticky="w", pady=5
        )
        ttk.Label(ram, text="Acción por exceso").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=5
        )
        action_box = ttk.Combobox(
            ram,
            state="readonly",
            values=list(ACTION_LABELS.values()),
            width=42,
        )
        action_box.grid(row=1, column=1, sticky="w", pady=5)
        action_box.set(ACTION_LABELS["warn"])
        self.action_box = action_box
        ttk.Label(ram, text="Límite duro de RAM (MB)").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=5
        )
        ttk.Entry(ram, textvariable=self.ram_hard, width=18).grid(
            row=2, column=1, sticky="w", pady=5
        )
        ttk.Label(
            ram,
            text=(
                "Recomendado: deja el límite duro en 0. Si se alcanza un límite duro, "
                "Windows puede negar memoria a Valheim y provocar cierre o congelamiento."
            ),
            wraplength=890,
            foreground="#FBBF24",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 4))
        self.capacity_label = ttk.Label(
            ram,
            text="Detectando capacidad del host...",
            foreground="#FF8A9B",
        )
        self.capacity_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.runtime_label = ttk.Label(ram, text="", wraplength=890)
        self.runtime_label.grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))

        footer = ttk.Frame(root)
        footer.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(footer, textvariable=self.status, relief="sunken", anchor="w").pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(footer, text="Cerrar", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="Guardar", command=self.save).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="Aplicar ahora", command=self.apply_now).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="Autoconfigurar perfil", command=self.autoconfigure).pack(side="right")

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
        self.status.set("Listo")
        if done:
            done(result)

    def _error(self, exc):
        self.status.set(f"Error: {exc}")
        messagebox.showerror("ASGARD Recursos", str(exc), parent=self)

    @staticmethod
    def _reverse(mapping: dict, label: str, default: str) -> str:
        return next((key for key, value in mapping.items() if value == label), default)

    @staticmethod
    def _fallback_topology(logical: int, physical: int) -> list[dict]:
        logical = max(1, int(logical or 1))
        physical = max(1, min(logical, int(physical or logical)))
        per_core = max(1, logical // physical)
        result = []
        cursor = 0
        for core_index in range(physical):
            remaining_cores = physical - core_index
            remaining_logical = logical - cursor
            width = max(1, remaining_logical // remaining_cores)
            cpus = list(range(cursor, min(logical, cursor + width)))
            cursor += width
            result.append({
                "id": f"core-{core_index}",
                "core_index": core_index,
                "logical_processors": cpus,
                "label": "",
            })
        if cursor < logical:
            result[-1]["logical_processors"].extend(range(cursor, logical))
        return result

    def _normalize_topology(self, host: dict) -> list[dict]:
        logical = max(1, int(host.get("logical_cpus", 1) or 1))
        physical = max(1, int(host.get("physical_cores", logical) or logical))
        raw = host.get("cpu_topology") or self._fallback_topology(logical, physical)
        result = []
        used_cpus: set[int] = set()
        for position, item in enumerate(raw):
            cpus = []
            for value in item.get("logical_processors", []):
                try:
                    cpu = int(value)
                except (TypeError, ValueError):
                    continue
                if 0 <= cpu < logical and cpu not in cpus:
                    cpus.append(cpu)
            if not cpus:
                continue
            cpus.sort()
            used_cpus.update(cpus)
            core_index = int(item.get("core_index", position))
            core_id = str(item.get("id") or f"core-{core_index}")
            result.append({
                "id": core_id,
                "core_index": core_index,
                "logical_processors": cpus,
                "label": str(item.get("label") or ""),
                "efficiency_class": item.get("efficiency_class"),
            })
        # Si la API no pudo asociar algún procesador lógico, se conserva como núcleo individual.
        for cpu in range(logical):
            if cpu not in used_cpus:
                result.append({
                    "id": f"logical-{cpu}",
                    "core_index": len(result),
                    "logical_processors": [cpu],
                    "label": "",
                    "efficiency_class": None,
                })
        result.sort(key=lambda item: (item["core_index"], item["logical_processors"]))
        return result

    @staticmethod
    def _core_text(item: dict) -> str:
        cpus = item.get("logical_processors", [])
        cpu_text = " + ".join(f"CPU {cpu}" for cpu in cpus)
        custom = str(item.get("label") or "").strip()
        if custom:
            return custom
        return f"Núcleo físico {item.get('core_index', 0)}  —  {cpu_text}"

    def _topology_by_id(self) -> dict[str, dict]:
        return {str(item["id"]): item for item in self.cpu_topology}

    def _allowed_affinity(self) -> list[int]:
        mapping = self._topology_by_id()
        cpus: set[int] = set()
        for core_id in self.allowed_core_ids:
            item = mapping.get(core_id)
            if item:
                cpus.update(int(cpu) for cpu in item.get("logical_processors", []))
        return sorted(cpus)

    def _refresh_cpu_lists(self):
        self.available_cpu_list.delete(0, "end")
        self.allowed_cpu_list.delete(0, "end")
        self.available_row_ids = []
        self.allowed_row_ids = []

        for item in self.cpu_topology:
            core_id = str(item["id"])
            text = self._core_text(item)
            if core_id in self.allowed_core_ids:
                self.allowed_row_ids.append(core_id)
                self.allowed_cpu_list.insert("end", text)
            else:
                self.available_row_ids.append(core_id)
                self.available_cpu_list.insert("end", text)

        affinity = self._allowed_affinity()
        if affinity:
            self.cpu_summary.set(
                f"Permitidos: {len(self.allowed_core_ids)} núcleo(s) físico(s), "
                f"{len(affinity)} procesador(es) lógico(s): "
                + ", ".join(f"CPU {cpu}" for cpu in affinity)
            )
        else:
            self.cpu_summary.set(
                "No hay núcleos en la lista de permitidos: la afinidad queda sin restricción y "
                "Windows podrá usar todos los procesadores lógicos."
            )

    def _selected_ids(self, listbox: tk.Listbox, row_ids: list[str]) -> list[str]:
        return [row_ids[index] for index in listbox.curselection() if 0 <= index < len(row_ids)]

    def _add_selected_cores(self):
        for core_id in self._selected_ids(self.available_cpu_list, self.available_row_ids):
            self.allowed_core_ids.add(core_id)
        self._refresh_cpu_lists()

    def _remove_selected_cores(self):
        for core_id in self._selected_ids(self.allowed_cpu_list, self.allowed_row_ids):
            self.allowed_core_ids.discard(core_id)
        self._refresh_cpu_lists()

    def _add_all_cores(self):
        self.allowed_core_ids = {str(item["id"]) for item in self.cpu_topology}
        self._refresh_cpu_lists()

    def _remove_all_cores(self):
        self.allowed_core_ids.clear()
        self._refresh_cpu_lists()

    def _load(self, data, affinity_override: list[int] | None = None, preserve_controls: bool = False):
        self.data = data
        policy = data.get("policy", {})
        host = data.get("host", {})
        runtime = data.get("runtime", {})
        logical = int(host.get("logical_cpus", 1) or 1)
        self.cpu_topology = self._normalize_topology(host)
        selected = {
            int(value)
            for value in (affinity_override if affinity_override is not None else policy.get("cpu_affinity", []))
        }
        # Una selección antigua de un solo hilo se expande al núcleo físico completo.
        self.allowed_core_ids = {
            str(item["id"])
            for item in self.cpu_topology
            if selected.intersection(set(item.get("logical_processors", [])))
        }
        self._refresh_cpu_lists()

        if not preserve_controls:
            self.enabled.set(bool(policy.get("enabled")))
            self.apply_on_start.set(bool(policy.get("apply_on_start", True)))
            self.auto_rebalance.set(bool(policy.get("auto_rebalance", False)))
            self.profile_box.set(PROFILE_LABELS.get(policy.get("profile"), PROFILE_LABELS["custom"]))
            self.cpu_limit.set(str(policy.get("cpu_limit_percent", 0)))
            self.priority_box.set(PRIORITY_LABELS.get(policy.get("priority"), PRIORITY_LABELS["normal"]))
            self.ram_warning.set(str(policy.get("ram_warning_mb", 0)))
            self.ram_hard.set(str(policy.get("ram_hard_limit_mb", 0)))
            self.action_box.set(ACTION_LABELS.get(policy.get("ram_action"), ACTION_LABELS["warn"]))

        source = str(host.get("topology_source") or "detección automática")
        self.capacity_label.configure(
            text=(
                f"Host: {logical} procesadores lógicos / {host.get('physical_cores', '—')} núcleos físicos · "
                f"RAM total {host.get('ram_total_mb', '—')} MB · disponible {host.get('ram_available_mb', '—')} MB · "
                f"Topología: {source}"
            )
        )
        self.current_ram_mb = float(runtime.get("ram_mb", 0) or 0)
        self.runtime_label.configure(
            text=(
                f"Proceso: {'activo' if runtime.get('alive') else 'detenido'} · "
                f"RAM actual {self.current_ram_mb:.1f} MB · "
                f"Job Object activo: {'Sí' if runtime.get('job_active') else 'No'} · "
                f"PID aplicado: {runtime.get('job_pid') or '—'}"
            )
        )

    def _refresh_detection(self):
        current_affinity = self._allowed_affinity()
        self._async(
            lambda: self.api.request("GET", self.get_path, timeout=30),
            lambda data: self._load(data, affinity_override=current_affinity, preserve_controls=True),
        )

    def payload(self):
        cpu_limit = int(self.cpu_limit.get().strip() or 0)
        ram_warning = int(self.ram_warning.get().strip() or 0)
        ram_hard = int(self.ram_hard.get().strip() or 0)
        if not 0 <= cpu_limit <= 100:
            raise ValueError("El porcentaje de CPU debe estar entre 0 y 100")
        if min(ram_warning, ram_hard) < 0:
            raise ValueError("Los valores de RAM no pueden ser negativos")
        if ram_hard and ram_warning and ram_hard < ram_warning:
            raise ValueError("El límite duro de RAM no debe ser menor que el umbral de advertencia")
        if ram_hard and self.current_ram_mb and ram_hard <= self.current_ram_mb + 128:
            raise ValueError(
                f"El proceso usa {self.current_ram_mb:.0f} MB. El límite duro debe dejar al menos 128 MB de margen."
            )
        return {
            "enabled": self.enabled.get(),
            "profile": self._reverse(PROFILE_LABELS, self.profile_box.get(), "custom"),
            "cpu_affinity": self._allowed_affinity(),
            "cpu_limit_percent": cpu_limit,
            "priority": self._reverse(PRIORITY_LABELS, self.priority_box.get(), "normal"),
            "ram_warning_mb": ram_warning,
            "ram_hard_limit_mb": ram_hard,
            "ram_action": self._reverse(ACTION_LABELS, self.action_box.get(), "warn"),
            "apply_on_start": self.apply_on_start.get(),
            "auto_rebalance": self.auto_rebalance.get(),
        }

    def save(self):
        try:
            data = self.payload()
        except Exception as exc:
            self._error(exc)
            return
        self._async(lambda: self.api.request("PUT", self.save_path, data, timeout=45), self._load)

    def apply_now(self):
        try:
            data = self.payload()
        except Exception as exc:
            self._error(exc)
            return

        def work():
            # Guardar aplica inmediatamente cuando el servidor está activo.
            return self.api.request("PUT", self.save_path, data, timeout=45)

        self._async(
            work,
            lambda _result: self._async(
                lambda: self.api.request("GET", self.get_path, timeout=30),
                self._load,
            ),
        )

    def autoconfigure(self):
        profile = self._reverse(PROFILE_LABELS, self.profile_box.get(), "balanced")
        if profile == "custom":
            profile = "balanced"
        self._async(
            lambda: self.api.request(
                "POST",
                self.autoconfigure_path,
                {"profile": profile},
                timeout=60,
            ),
            self._load,
        )
