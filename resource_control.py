from __future__ import annotations

import ctypes
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import psutil


PRIORITIES = {
    "idle": "Baja",
    "below_normal": "Por debajo de normal",
    "normal": "Normal",
    "above_normal": "Por encima de normal",
}

DEFAULT_POLICY = {
    "enabled": False,
    "profile": "balanced",
    "cpu_affinity": [],
    "cpu_limit_percent": 0,
    "priority": "normal",
    "ram_warning_mb": 0,
    "ram_hard_limit_mb": 0,
    "ram_action": "warn",
    "apply_on_start": True,
    "auto_rebalance": False,
}


def normalize_policy(data: dict | None) -> dict:
    source = dict(DEFAULT_POLICY)
    if data:
        for key in DEFAULT_POLICY:
            if key in data:
                source[key] = data[key]
    logical = max(1, psutil.cpu_count(logical=True) or 1)
    affinity = []
    for value in source.get("cpu_affinity") or []:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= number < logical and number not in affinity:
            affinity.append(number)
    affinity.sort()
    source["enabled"] = bool(source.get("enabled"))
    source["profile"] = str(source.get("profile") or "custom")
    source["cpu_affinity"] = affinity
    source["cpu_limit_percent"] = max(0, min(100, int(source.get("cpu_limit_percent") or 0)))
    source["priority"] = str(source.get("priority") or "normal")
    if source["priority"] not in PRIORITIES:
        source["priority"] = "normal"
    source["ram_warning_mb"] = max(0, int(source.get("ram_warning_mb") or 0))
    source["ram_hard_limit_mb"] = max(0, int(source.get("ram_hard_limit_mb") or 0))
    source["ram_action"] = str(source.get("ram_action") or "warn")
    if source["ram_action"] not in {"warn", "restart_when_empty", "backup_restart"}:
        source["ram_action"] = "warn"
    source["apply_on_start"] = bool(source.get("apply_on_start", True))
    source["auto_rebalance"] = bool(source.get("auto_rebalance", False))
    return source


def _parse_windows_core_buffer(raw: bytes, pointer_size: int) -> list[dict]:
    """Interpreta SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX(RelationProcessorCore)."""
    relation_processor_core = 0
    group_affinity_size = pointer_size + 8
    offset = 0
    cores: list[dict] = []
    core_index = 0

    while offset + 8 <= len(raw):
        relationship = int.from_bytes(raw[offset : offset + 4], "little", signed=False)
        size = int.from_bytes(raw[offset + 4 : offset + 8], "little", signed=False)
        if size < 8 or offset + size > len(raw):
            break
        if relationship == relation_processor_core and size >= 32:
            processor_offset = offset + 8
            efficiency_class = raw[processor_offset + 1]
            group_count = int.from_bytes(
                raw[processor_offset + 22 : processor_offset + 24],
                "little",
                signed=False,
            )
            masks_offset = processor_offset + 24
            logical_processors: list[int] = []
            groups: list[int] = []
            for group_position in range(group_count):
                item_offset = masks_offset + group_position * group_affinity_size
                if item_offset + group_affinity_size > offset + size:
                    break
                mask = int.from_bytes(
                    raw[item_offset : item_offset + pointer_size],
                    "little",
                    signed=False,
                )
                group = int.from_bytes(
                    raw[item_offset + pointer_size : item_offset + pointer_size + 2],
                    "little",
                    signed=False,
                )
                groups.append(group)
                for bit in range(pointer_size * 8):
                    if mask & (1 << bit):
                        logical_processors.append(group * 64 + bit)
            logical_processors = sorted(set(logical_processors))
            if logical_processors:
                cpu_text = " + ".join(f"CPU {cpu}" for cpu in logical_processors)
                cores.append({
                    "id": f"core-{core_index}",
                    "core_index": core_index,
                    "logical_processors": logical_processors,
                    "processor_groups": sorted(set(groups)),
                    "efficiency_class": int(efficiency_class),
                    "label": f"Núcleo físico {core_index}  —  {cpu_text}",
                })
                core_index += 1
        offset += size
    return cores


def _windows_cpu_topology() -> list[dict]:
    """Obtiene la relación núcleo físico -> procesadores lógicos mediante WinAPI."""
    if os.name != "nt":
        return []
    from ctypes import wintypes

    relation_processor_core = 0
    error_insufficient_buffer = 122
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel.GetLogicalProcessorInformationEx
    function.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    function.restype = wintypes.BOOL

    length = wintypes.DWORD(0)
    function(relation_processor_core, None, ctypes.byref(length))
    error = ctypes.get_last_error()
    if not length.value or error not in (0, error_insufficient_buffer):
        return []

    buffer = ctypes.create_string_buffer(length.value)
    if not function(relation_processor_core, buffer, ctypes.byref(length)):
        return []
    return _parse_windows_core_buffer(
        buffer.raw[: length.value],
        ctypes.sizeof(ctypes.c_void_p),
    )


def _linux_cpu_topology() -> list[dict]:
    base = Path("/sys/devices/system/cpu")
    if not base.exists():
        return []
    grouped: dict[tuple[int, int], list[int]] = {}
    for cpu_dir in sorted(base.glob("cpu[0-9]*"), key=lambda path: int(path.name[3:])):
        try:
            cpu = int(cpu_dir.name[3:])
            package = int((cpu_dir / "topology" / "physical_package_id").read_text().strip())
            core = int((cpu_dir / "topology" / "core_id").read_text().strip())
        except (OSError, ValueError):
            continue
        grouped.setdefault((package, core), []).append(cpu)
    result = []
    for index, ((package, _core), cpus) in enumerate(sorted(grouped.items(), key=lambda item: min(item[1]))):
        cpus = sorted(set(cpus))
        cpu_text = " + ".join(f"CPU {cpu}" for cpu in cpus)
        package_text = f" · socket {package}" if len({key[0] for key in grouped}) > 1 else ""
        result.append({
            "id": f"core-{index}",
            "core_index": index,
            "logical_processors": cpus,
            "processor_groups": [package],
            "efficiency_class": None,
            "label": f"Núcleo físico {index}{package_text}  —  {cpu_text}",
        })
    return result


def _fallback_cpu_topology(logical: int, physical: int) -> list[dict]:
    logical = max(1, int(logical or 1))
    physical = max(1, min(logical, int(physical or logical)))
    result = []
    cursor = 0
    for core_index in range(physical):
        remaining_cores = physical - core_index
        remaining_logical = logical - cursor
        width = max(1, remaining_logical // remaining_cores)
        cpus = list(range(cursor, min(logical, cursor + width)))
        cursor += width
        cpu_text = " + ".join(f"CPU {cpu}" for cpu in cpus)
        result.append({
            "id": f"core-{core_index}",
            "core_index": core_index,
            "logical_processors": cpus,
            "processor_groups": [0],
            "efficiency_class": None,
            "label": f"Núcleo físico {core_index}  —  {cpu_text}",
        })
    if cursor < logical:
        result[-1]["logical_processors"].extend(range(cursor, logical))
        cpus = result[-1]["logical_processors"]
        result[-1]["label"] = (
            f"Núcleo físico {result[-1]['core_index']}  —  "
            + " + ".join(f"CPU {cpu}" for cpu in cpus)
        )
    return result


def cpu_topology() -> tuple[list[dict], str]:
    logical = max(1, psutil.cpu_count(logical=True) or 1)
    physical = max(1, psutil.cpu_count(logical=False) or logical)
    topology: list[dict] = []
    source = "estimación"
    if os.name == "nt":
        topology = _windows_cpu_topology()
        source = "Windows API" if topology else "estimación"
    elif os.name == "posix":
        topology = _linux_cpu_topology()
        source = "topología del sistema" if topology else "estimación"
    if not topology:
        topology = _fallback_cpu_topology(logical, physical)
    # Conserva solamente índices válidos para la afinidad del proceso actual.
    valid = set(range(logical))
    cleaned = []
    seen: set[int] = set()
    for item in topology:
        cpus = sorted({int(cpu) for cpu in item.get("logical_processors", []) if int(cpu) in valid})
        cpus = [cpu for cpu in cpus if cpu not in seen]
        if not cpus:
            continue
        seen.update(cpus)
        new_item = dict(item)
        new_item["logical_processors"] = cpus
        new_item["core_index"] = len(cleaned)
        new_item["id"] = f"core-{len(cleaned)}"
        new_item["label"] = (
            f"Núcleo físico {len(cleaned)}  —  "
            + " + ".join(f"CPU {cpu}" for cpu in cpus)
        )
        cleaned.append(new_item)
    for cpu in sorted(valid - seen):
        cleaned.append({
            "id": f"core-{len(cleaned)}",
            "core_index": len(cleaned),
            "logical_processors": [cpu],
            "processor_groups": [cpu // 64],
            "efficiency_class": None,
            "label": f"Núcleo físico {len(cleaned)}  —  CPU {cpu}",
        })
    return cleaned, source


def host_capacity() -> dict:
    vm = psutil.virtual_memory()
    topology, source = cpu_topology()
    return {
        "logical_cpus": max(1, psutil.cpu_count(logical=True) or 1),
        "physical_cores": len(topology) or max(1, psutil.cpu_count(logical=False) or 1),
        "cpu_topology": topology,
        "topology_source": source,
        "ram_total_mb": round(vm.total / 1024 ** 2),
        "ram_available_mb": round(vm.available / 1024 ** 2),
    }


def _flatten_core_groups(groups: list[list[int]]) -> list[int]:
    return sorted({cpu for group in groups for cpu in group})


def _slice_core_groups(
    core_groups: list[list[int]],
    server_ids: list[int],
    server_id: int,
    minimum_cores: int = 1,
) -> list[list[int]]:
    total_cores = len(core_groups)
    reserve_cores = 2 if total_cores >= 8 else 1 if total_cores >= 4 else 0
    available = core_groups[reserve_cores:] or core_groups
    count = max(1, len(server_ids))
    try:
        position = sorted(server_ids).index(server_id)
    except ValueError:
        position = 0
    width = max(minimum_cores, len(available) // count)
    width = min(len(available), width)
    if width >= len(available):
        return list(available)
    start = (position * width) % len(available)
    return [available[(start + offset) % len(available)] for offset in range(width)]


def automatic_policy(profile: str, server_id: int, server_ids: Iterable[int]) -> dict:
    profile = str(profile or "balanced")
    ids = sorted({int(value) for value in server_ids}) or [int(server_id)]
    cap = host_capacity()
    core_groups = [
        list(map(int, item.get("logical_processors", [])))
        for item in cap.get("cpu_topology", [])
        if item.get("logical_processors")
    ]
    if not core_groups:
        core_groups = [[cpu] for cpu in range(cap["logical_cpus"])]
    total_ram = cap["ram_total_mb"]
    reserve_ram = max(4096, int(total_ram * 0.20))
    distributable = max(1024, total_ram - reserve_ram)
    share = max(1024, distributable // max(1, len(ids)))

    if profile == "low_impact":
        selected_groups = _slice_core_groups(core_groups, ids, server_id, minimum_cores=1)
        if len(selected_groups) > 2:
            selected_groups = selected_groups[: max(1, len(selected_groups) // 2)]
        cpu_limit = 35
        priority = "below_normal"
        warning = int(share * 0.65)
    elif profile == "priority":
        reserve_cores = 2 if len(core_groups) >= 8 else 1 if len(core_groups) >= 4 else 0
        selected_groups = core_groups[reserve_cores:] or core_groups
        cpu_limit = 90
        priority = "above_normal"
        warning = int(share * 0.90)
    else:
        profile = "balanced"
        selected_groups = _slice_core_groups(
            core_groups,
            ids,
            server_id,
            minimum_cores=2 if len(core_groups) >= 4 else 1,
        )
        cpu_limit = 65 if len(ids) > 1 else 85
        priority = "normal"
        warning = int(share * 0.80)

    return normalize_policy({
        "enabled": True,
        "profile": profile,
        "cpu_affinity": _flatten_core_groups(selected_groups),
        "cpu_limit_percent": cpu_limit,
        "priority": priority,
        "ram_warning_mb": max(768, warning),
        "ram_hard_limit_mb": 0,
        "ram_action": "warn",
        "apply_on_start": True,
        "auto_rebalance": profile == "balanced",
    })


if os.name == "nt":
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x1
    JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x4
    JobObjectExtendedLimitInformation = 9
    JobObjectCpuRateControlInformation = 15
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
        _fields_ = [("ControlFlags", wintypes.DWORD), ("CpuRate", wintypes.DWORD)]

    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL


def _win_error(prefix: str) -> OSError:
    return ctypes.WinError(ctypes.get_last_error(), prefix)


@dataclass
class JobHandle:
    pid: int
    handle: int


class ResourceController:
    """Aplica afinidad, prioridad y límites Job Object por servidor.

    Los handles Job Object permanecen abiertos mientras el proceso vive; de otro
    modo Windows destruiría el objeto y retiraría sus límites.
    """

    def __init__(self, event_callback: Callable[[int, str, str], None]):
        self._event = event_callback
        self._jobs: dict[int, JobHandle] = {}
        self._policies: dict[int, dict] = {}
        self._lock = threading.RLock()

    def _processes(self, pid: int) -> list[psutil.Process]:
        root = psutil.Process(pid)
        result = [root]
        try:
            result.extend(root.children(recursive=True))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return result

    def _apply_affinity_priority(self, pid: int, policy: dict) -> None:
        priority_map = {
            "idle": getattr(psutil, "IDLE_PRIORITY_CLASS", None),
            "below_normal": getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", None),
            "normal": getattr(psutil, "NORMAL_PRIORITY_CLASS", None),
            "above_normal": getattr(psutil, "ABOVE_NORMAL_PRIORITY_CLASS", None),
        }
        for proc in self._processes(pid):
            try:
                if policy["cpu_affinity"]:
                    proc.cpu_affinity(policy["cpu_affinity"])
                priority = priority_map.get(policy["priority"])
                if priority is not None:
                    proc.nice(priority)
            except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
                continue

    def _ensure_job(self, server_id: int, pid: int) -> int:
        if os.name != "nt":
            raise RuntimeError("Los límites Job Object solo están disponibles en Windows")
        current = self._jobs.get(server_id)
        if current and current.pid == pid:
            return current.handle
        if current:
            kernel32.CloseHandle(current.handle)
            self._jobs.pop(server_id, None)
        name = f"ASGARD_Server_{server_id}_{pid}"
        handle = kernel32.CreateJobObjectW(None, name)
        if not handle:
            raise _win_error("CreateJobObjectW")
        process_handle = kernel32.OpenProcess(
            PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )
        if not process_handle:
            kernel32.CloseHandle(handle)
            raise _win_error("OpenProcess")
        try:
            if not kernel32.AssignProcessToJobObject(handle, process_handle):
                raise _win_error("AssignProcessToJobObject")
        except Exception:
            kernel32.CloseHandle(handle)
            raise
        finally:
            kernel32.CloseHandle(process_handle)
        self._jobs[server_id] = JobHandle(pid=pid, handle=int(handle))
        return int(handle)

    def _apply_job_limits(self, server_id: int, pid: int, policy: dict) -> None:
        if os.name != "nt":
            return
        requires_job = bool(policy["cpu_limit_percent"] or policy["ram_hard_limit_mb"] or server_id in self._jobs)
        if not requires_job:
            return
        handle = self._ensure_job(server_id, pid)

        cpu = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
        if policy["cpu_limit_percent"]:
            cpu.ControlFlags = JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
            cpu.CpuRate = int(policy["cpu_limit_percent"] * 100)
        else:
            cpu.ControlFlags = 0
            cpu.CpuRate = 0
        if not kernel32.SetInformationJobObject(
            handle,
            JobObjectCpuRateControlInformation,
            ctypes.byref(cpu),
            ctypes.sizeof(cpu),
        ):
            raise _win_error("SetInformationJobObject(CPU)")

        memory = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        if policy["ram_hard_limit_mb"]:
            memory.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_JOB_MEMORY
            memory.JobMemoryLimit = int(policy["ram_hard_limit_mb"] * 1024 * 1024)
        if not kernel32.SetInformationJobObject(
            handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(memory),
            ctypes.sizeof(memory),
        ):
            raise _win_error("SetInformationJobObject(Memory)")

    def apply(self, server_id: int, pid: int, policy: dict | None) -> dict:
        normalized = normalize_policy(policy)
        with self._lock:
            self._policies[server_id] = normalized
            if not normalized["enabled"]:
                reset = {
                    **normalized,
                    "cpu_affinity": list(range(max(1, psutil.cpu_count(logical=True) or 1))),
                    "priority": "normal",
                    "cpu_limit_percent": 0,
                    "ram_hard_limit_mb": 0,
                }
                self._apply_affinity_priority(pid, reset)
                self._apply_job_limits(server_id, pid, reset)
                return {"applied": False, "reason": "Política desactivada; afinidad y prioridad restauradas", "policy": normalized}
            self._apply_affinity_priority(pid, normalized)
            self._apply_job_limits(server_id, pid, normalized)
            self._event(
                server_id,
                "INFO",
                "Recursos aplicados: CPU %s; límite %s%%; prioridad %s; RAM dura %s MB"
                % (
                    ",".join(map(str, normalized["cpu_affinity"])) or "todos",
                    normalized["cpu_limit_percent"] or "sin límite",
                    PRIORITIES[normalized["priority"]],
                    normalized["ram_hard_limit_mb"] or "desactivada",
                ),
            )
            return {"applied": True, "pid": pid, "policy": normalized}

    def release(self, server_id: int) -> None:
        with self._lock:
            current = self._jobs.pop(server_id, None)
            self._policies.pop(server_id, None)
            if current and os.name == "nt":
                kernel32.CloseHandle(current.handle)

    def status(self, server_id: int, pid: int | None = None) -> dict:
        with self._lock:
            job = self._jobs.get(server_id)
            return {
                "policy": dict(self._policies.get(server_id, DEFAULT_POLICY)),
                "job_active": bool(job and (pid is None or job.pid == pid)),
                "job_pid": job.pid if job else None,
                "windows_job_objects": os.name == "nt",
            }
