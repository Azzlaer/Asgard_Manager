from __future__ import annotations

import socket
import struct
import itertools


SERVERDATA_RESPONSE_VALUE = 0
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_AUTH = 3


class SourceRconClient:
    def __init__(self, host: str, port: int, password: str, timeout: float = 5.0):
        self.host = host
        self.port = int(port)
        self.password = password
        self.timeout = float(timeout)
        self.sock: socket.socket | None = None
        self._ids = itertools.count(1)

    @staticmethod
    def _packet(request_id: int, packet_type: int, body: str) -> bytes:
        payload = struct.pack("<ii", request_id, packet_type)
        payload += body.encode("utf-8") + b"\x00\x00"
        return struct.pack("<i", len(payload)) + payload

    def _recv_exact(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("RCON cerró la conexión")
            data.extend(chunk)
        return bytes(data)

    def _recv_packet(self):
        length = struct.unpack("<i", self._recv_exact(4))[0]
        if length < 10 or length > 10_000_000:
            raise ValueError(f"Paquete RCON inválido: {length}")
        data = self._recv_exact(length)
        request_id, packet_type = struct.unpack("<ii", data[:8])
        body = data[8:-2].decode("utf-8", errors="replace")
        return request_id, packet_type, body

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        request_id = next(self._ids)
        self.sock.sendall(self._packet(request_id, SERVERDATA_AUTH, self.password))
        while True:
            rid, ptype, body = self._recv_packet()
            if ptype == SERVERDATA_AUTH_RESPONSE:
                if rid == -1:
                    raise PermissionError("Contraseña RCON incorrecta")
                if rid == request_id:
                    return self

    def command(self, command: str) -> str:
        if not self.sock:
            self.connect()
        request_id = next(self._ids)
        self.sock.sendall(self._packet(request_id, SERVERDATA_EXECCOMMAND, command))
        chunks = []
        while True:
            rid, ptype, body = self._recv_packet()
            if rid == request_id:
                chunks.append(body)
                break
        return "".join(chunks)

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc, tb):
        self.close()


def execute_rcon(settings: dict, command: str) -> str:
    with SourceRconClient(
        settings["host"], settings["port"], settings["password"], settings["timeout"]
    ) as client:
        return client.command(command)
