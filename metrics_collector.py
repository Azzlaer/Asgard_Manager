from __future__ import annotations

import collections
import threading
import time

import psutil


class MetricsCollector:
    def __init__(self, process_manager, list_server_ids, history_size: int = 300):
        self.process_manager = process_manager
        self.list_server_ids = list_server_ids
        self.history_size = history_size
        self.lock = threading.RLock()
        self.server_history = {}
        self.host_history = collections.deque(maxlen=history_size)
        self.stop_event = threading.Event()
        self._last_net = psutil.net_io_counters()
        self._last_time = time.monotonic()

    def _append_server(self, server_id: int, sample: dict):
        with self.lock:
            history = self.server_history.setdefault(
                server_id, collections.deque(maxlen=self.history_size)
            )
            history.append(sample)

    def run(self):
        # Prime psutil's host CPU calculation.
        psutil.cpu_percent(interval=None)
        while not self.stop_event.is_set():
            started = time.monotonic()
            now = time.time()

            current_net = psutil.net_io_counters()
            current_time = time.monotonic()
            elapsed = max(0.001, current_time - self._last_time)
            if current_net is not None and self._last_net is not None:
                down_bps = max(
                    0.0, (current_net.bytes_recv - self._last_net.bytes_recv) / elapsed
                )
                up_bps = max(
                    0.0, (current_net.bytes_sent - self._last_net.bytes_sent) / elapsed
                )
            else:
                down_bps = 0.0
                up_bps = 0.0
            self._last_net = current_net
            self._last_time = current_time

            vm = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            host_sample = {
                "timestamp": now,
                "cpu_percent": psutil.cpu_percent(interval=None),
                "ram_percent": vm.percent,
                "ram_used_mb": round((vm.total - vm.available) / (1024 ** 2), 1),
                "ram_total_mb": round(vm.total / (1024 ** 2), 1),
                "network_down_bps": round(down_bps, 1),
                "network_up_bps": round(up_bps, 1),
                "disk_percent": disk.percent,
            }
            with self.lock:
                self.host_history.append(host_sample)

            for server_id in self.list_server_ids():
                metrics = self.process_manager.metrics(server_id)
                sample = {
                    "timestamp": now,
                    "cpu_percent": metrics.get("cpu_percent", 0.0),
                    "ram_mb": metrics.get("ram_mb", 0.0),
                    "alive": bool(metrics.get("alive")),
                    "pid": metrics.get("pid"),
                    "uptime_seconds": int(metrics.get("uptime_seconds", 0) or 0),
                }
                self._append_server(server_id, sample)

            delay = max(0.1, 1.0 - (time.monotonic() - started))
            self.stop_event.wait(delay)

    def host(self, limit: int = 120):
        with self.lock:
            return list(self.host_history)[-max(1, min(limit, self.history_size)):]

    def server(self, server_id: int, limit: int = 120):
        with self.lock:
            history = self.server_history.get(server_id, ())
            return list(history)[-max(1, min(limit, self.history_size)):]

    def latest_server(self, server_id: int) -> dict:
        with self.lock:
            history = self.server_history.get(server_id)
            if history:
                return dict(history[-1])
        return {
            "alive": False,
            "pid": None,
            "cpu_percent": 0.0,
            "ram_mb": 0.0,
            "uptime_seconds": 0,
        }
