from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


EXCLUDED_DIRS = {
    "bin",
    "obj",
    "Dist",
    "_build_venv",
    "_exe_build",
    "__pycache__",
    ".vs",
    ".git",
}
EXCLUDED_FILES = {
    "UserPaths.props",
}


def ignore_generated(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in EXCLUDED_DIRS or name in EXCLUDED_FILES:
            ignored.add(name)
        elif name.endswith((".pyc", ".pyo", ".user", ".suo")):
            ignored.add(name)
    return ignored


def copy_file(source: Path, destination: Path, required: bool = True) -> None:
    if not source.is_file():
        if required:
            raise FileNotFoundError(f"Falta el archivo requerido: {source}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_directory(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"Falta la carpeta requerida: {source}")
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=ignore_generated,
    )


def build_portable(root: Path, binaries: Path, release: Path) -> None:
    if release.exists():
        shutil.rmtree(release)
    release.mkdir(parents=True, exist_ok=True)

    for exe in (
        "ASGARD_Host_Manager.exe",
        "ASGARD_Service.exe",
        "ASGARD_Service_Control.exe",
    ):
        copy_file(binaries / exe, release / exe)

    copy_file(
        binaries / "ASGARD_Remote_Agent.exe",
        release / "RemoteAgentPackage" / "ASGARD_Remote_Agent.exe",
    )

    for folder in ("RemoteSetup", "Assets", "ValheimSuite"):
        copy_directory(root / folder, release / folder)

    root_files = (
        "INICIAR_ASGARD.bat",
        "DETENER_SERVICIO_ASGARD.bat",
        "REINICIAR_SERVICIO_ASGARD.bat",
        "ESTADO_SERVICIO_ASGARD.bat",
        "ABRIR_BIBLIOTECA.bat",
        "MIGRAR_DATOS_PORTABLES.bat",
        "MIGRAR_DATOS_PORTABLES.ps1",
        "README.md",
        "ROADMAP_CONTROL_REMOTO.md",
        "DIAGNOSTICAR_SERVIDORES_DUPLICADOS.bat",
        "DIAGNOSTICAR_SERVIDORES_DUPLICADOS.ps1",
        "LIMPIAR_DUPLICADOS_Y_ARRANCAR.bat",
        "ROADMAP_V7_COMPLETO.md",
    )
    copy_directory(root / "docs" / "legacy", release / "docs" / "legacy")

    for name in root_files:
        copy_file(root / name, release / name, required=False)

    for folder in (
        release / "Library" / "Mods",
        release / "Library" / "Configs",
        release / "Data" / "backups",
        release / "Data" / "service_logs",
        release / "RemoteDownloads",
    ):
        folder.mkdir(parents=True, exist_ok=True)

    copy_file(root / "Library" / "README.txt", release / "Library" / "README.txt", required=False)
    copy_file(root / "Data" / "README.txt", release / "Data" / "README.txt", required=False)
    copy_file(root / "RemoteDownloads" / "README.txt", release / "RemoteDownloads" / "README.txt", required=False)

    print(f"[OK] Carpeta portable creada: {release}")
    print("[OK] Se excluyeron bin, obj, Dist, UserPaths.props y temporales de compilacion.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Crea la carpeta portable de ASGARD sin xcopy.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--bin", required=True)
    parser.add_argument("--release", required=True)
    args = parser.parse_args()

    build_portable(
        Path(args.root).resolve(),
        Path(args.bin).resolve(),
        Path(args.release).resolve(),
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR AL CREAR PORTABLE: {exc}", file=sys.stderr)
        raise SystemExit(1)
