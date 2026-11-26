from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


ATTACH_PARENT_PROCESS = -1
STD_INPUT_HANDLE = -10
KEY_EVENT = 0x0001


class KEY_EVENT_RECORD(ctypes.Structure):
    class CHAR_UNION(ctypes.Union):
        _fields_ = [("UnicodeChar", wintypes.WCHAR), ("AsciiChar", wintypes.CHAR)]
    _fields_ = [
        ("bKeyDown", wintypes.BOOL),
        ("wRepeatCount", wintypes.WORD),
        ("wVirtualKeyCode", wintypes.WORD),
        ("wVirtualScanCode", wintypes.WORD),
        ("uChar", CHAR_UNION),
        ("dwControlKeyState", wintypes.DWORD),
    ]


class EVENT_UNION(ctypes.Union):
    _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("padding", ctypes.c_byte * 16)]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", wintypes.WORD), ("Event", EVENT_UNION)]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None


def _record(char: str, down: bool) -> INPUT_RECORD:
    rec = INPUT_RECORD()
    rec.EventType = KEY_EVENT
    rec.Event.KeyEvent.bKeyDown = bool(down)
    rec.Event.KeyEvent.wRepeatCount = 1
    rec.Event.KeyEvent.wVirtualKeyCode = 13 if char == "\r" else 0
    rec.Event.KeyEvent.wVirtualScanCode = 0
    rec.Event.KeyEvent.uChar.UnicodeChar = char
    rec.Event.KeyEvent.dwControlKeyState = 0
    return rec


def send_console_command(pid: int, command: str) -> None:
    """Escribe un comando en la consola asociada al PID."""
    if kernel32 is None:
        raise RuntimeError("El control directo de consola solo está disponible en Windows")
    kernel32.FreeConsole()
    if not kernel32.AttachConsole(wintypes.DWORD(pid)):
        raise OSError(ctypes.get_last_error(), "No se pudo adjuntar a la consola del servidor")
    try:
        handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        if handle in (0, -1):
            raise OSError(ctypes.get_last_error(), "No se obtuvo STDIN de consola")
        text = command.rstrip("\r\n") + "\r"
        records = []
        for char in text:
            records.append(_record(char, True))
            records.append(_record(char, False))
        array_type = INPUT_RECORD * len(records)
        written = wintypes.DWORD()
        if not kernel32.WriteConsoleInputW(handle, array_type(*records), len(records), ctypes.byref(written)):
            raise OSError(ctypes.get_last_error(), "No se pudo escribir en la consola")
    finally:
        kernel32.FreeConsole()
