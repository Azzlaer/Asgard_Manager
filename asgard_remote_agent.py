from __future__ import annotations

import sys
import traceback
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def main() -> int:
    try:
        import remote_agent
        remote_agent.run()
        return 0
    except BaseException as exc:
        target = app_dir() / "AgentData" / "startup_error.log"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
