from __future__ import annotations

import sys
import traceback
from pathlib import Path


def _application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _report_failure(exc: BaseException) -> None:
    message = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    target = _application_dir() / "Data" / "service_logs" / "startup_error.log"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(message, encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    try:
        import host_service

        host_service.run_service()
        return 0
    except BaseException as exc:
        _report_failure(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
