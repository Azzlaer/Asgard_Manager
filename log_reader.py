from __future__ import annotations

from pathlib import Path


def tail_file(path: str, max_lines: int = 300) -> list[str]:
    file_path = Path(path)
    if not file_path.is_file():
        return []
    with file_path.open("r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    return [line.rstrip("\r\n") for line in lines[-max_lines:]]
