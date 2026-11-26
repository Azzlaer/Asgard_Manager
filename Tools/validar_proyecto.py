from __future__ import annotations

import py_compile
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"ERROR: {message}")
    raise SystemExit(1)


def validate_python() -> int:
    files = sorted(ROOT.glob("*.py"))
    if not files:
        fail("No se encontraron archivos Python en la carpeta principal.")

    for path in files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            fail(f"Python invalido en {path.name}:\n{exc.msg}")
        except OSError as exc:
            fail(f"No se pudo leer {path.name}: {exc}")

    print(f"[OK] Python: {len(files)} archivos validados.")
    return len(files)


def validate_xml_projects() -> int:
    suite = ROOT / "ValheimSuite"
    projects = sorted(suite.rglob("*.csproj"))
    props = sorted(suite.rglob("*.props"))
    xml_files = projects + props

    if not projects:
        fail("No se encontraron proyectos .csproj en ValheimSuite.")

    for path in xml_files:
        try:
            ET.parse(path)
        except (ET.ParseError, OSError) as exc:
            fail(f"XML invalido en {path.relative_to(ROOT)}: {exc}")

    print(
        f"[OK] Proyectos C#: {len(projects)} .csproj y "
        f"{len(props)} archivo(s) .props validados."
    )
    return len(projects)


def validate_sources() -> int:
    sources = sorted((ROOT / "ValheimSuite").rglob("*.cs"))
    if not sources:
        fail("No se encontraron fuentes C# en ValheimSuite.")

    empty = [path for path in sources if not path.read_text(encoding="utf-8-sig").strip()]
    if empty:
        fail(
            "Hay fuentes C# vacias: "
            + ", ".join(str(path.relative_to(ROOT)) for path in empty)
        )

    print(f"[OK] Fuentes C#: {len(sources)} archivos presentes.")
    return len(sources)



def validate_core_public_api() -> None:
    core = ROOT / "ValheimSuite" / "AsgardCore" / "AsgardCorePlugin.cs"
    text = core.read_text(encoding="utf-8-sig")
    required = [
        "public static ManualLogSource Log",
        "public static ConfigEntry<int> ServerId",
        "public static ConfigEntry<string> EnforcementMode",
        "public static BridgeClient Bridge",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        fail("La API publica de AsgardCore esta incompleta: " + ", ".join(missing))
    print("[OK] API publica de AsgardCore disponible para las DLL dependientes.")


def validate_unity_module_references() -> None:
    props = ROOT / "ValheimSuite" / "Directory.Build.props"
    text = props.read_text(encoding="utf-8-sig")
    required = [
        "UnityEngine.InputLegacyModule.dll",
        "UnityEngine.TextRenderingModule.dll",
        "UnityEngine.ParticleSystemModule.dll",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        fail("Faltan referencias Unity requeridas por la interfaz o el Avatar Enhanced: " + ", ".join(missing))
    print("[OK] Modulos Unity de entrada, texto y particulas referenciados.")



def validate_bepinex_versions() -> None:
    sources = sorted((ROOT / "ValheimSuite").rglob("*.cs"))
    plugins = []
    invalid = []
    pattern = re.compile(r'public const string Version\s*=\s*"([^"]+)"')
    numeric = re.compile(r'^\d+\.\d+\.\d+(?:\.\d+)?$')
    for path in sources:
        source = path.read_text(encoding="utf-8-sig")
        if "[BepInPlugin" not in source:
            continue
        match = pattern.search(source)
        if not match:
            invalid.append(f"{path.relative_to(ROOT)}: Version no encontrada")
            continue
        version = match.group(1)
        plugins.append((path, version))
        if not numeric.fullmatch(version):
            invalid.append(f"{path.relative_to(ROOT)}: {version}")
    if invalid:
        fail("Versiones BepInEx invalidas; usa solo numeros como 7.0.6:\n - " + "\n - ".join(invalid))
    print(f"[OK] Versiones BepInEx: {len(plugins)} plugins con version numerica valida.")


def validate_required_files() -> None:
    required = [
        "Assets/asgard_void_logo.svg",
        "Assets/void_avatar_user.png",
        "Tools/crear_portable.py",
        "ValheimSuite/BUILD_ALL.bat",
        "ValheimSuite/CONFIGURAR_Y_COMPILAR.bat",
        "ValheimSuite/Tools/configurar_rutas_valheim.ps1",
        "ValheimSuite/CONFIGURAR_RUTAS.bat",
        "ValheimSuite/INSTALAR_EN_SERVIDOR.bat",
        "ValheimSuite/INSTALAR_EN_CLIENTE_ADMIN.bat",
        "ValheimSuite/Tools/instalar_mods_asgard.ps1",
        "CREAR_EXE_PORTABLE.bat",
        "CREAR_TODO.bat",
        "requirements/requirements.txt",
        "requirements/requirements-build.txt",
        "asgard_panel.py",
        "asgard_service.py",
        "asgard_remote_agent.py",
        "asgard_suite_bridge.py",
        "LIMPIAR_DUPLICADOS_Y_ARRANCAR.bat",
        "docs/legacy/CAMBIOS_v7_0_R9.txt",
        "docs/legacy/CAMBIOS_v7_0_R10.txt",
    ]
    missing = [item for item in required if not (ROOT / item).is_file()]
    if missing:
        fail("Faltan archivos esenciales:\n - " + "\n - ".join(missing))

    print(f"[OK] Archivos esenciales: {len(required)} encontrados.")



def validate_runtime_compatibility() -> None:
    props = (ROOT / "ValheimSuite" / "Directory.Build.props").read_text(encoding="utf-8", errors="replace")
    core = (ROOT / "ValheimSuite" / "AsgardCore" / "AsgardCorePlugin.cs").read_text(encoding="utf-8", errors="replace")
    ui = (ROOT / "ValheimSuite" / "AsgardMasterUI" / "AsgardMasterUIPlugin.cs").read_text(encoding="utf-8", errors="replace")
    forbidden = []
    if "System.Web.Extensions" in props or "System.Web.Script.Serialization" in core:
        forbidden.append("Dependencia System.Web.Extensions/JavaScriptSerializer")
    if forbidden:
        fail("Dependencias incompatibles con BepInEx/Unity Mono: " + ", ".join(forbidden))
    required_ui = ["CRIMSON VOID", "DrawMetricCard", "DrawVoidSigil", "AsgardCorePlugin.IsReady", "MODO DE PROTECCIÓN"]
    missing = [marker for marker in required_ui if marker not in ui]
    if missing:
        fail("AsgardMasterUI R6 incompleta. Faltan marcadores: " + ", ".join(missing))
    if "EnforcementMode.Value" in ui or "ServerId.Value" in ui:
        fail("AsgardMasterUI usa ConfigEntry.Value directamente; debe usar la API segura del Core.")
    print("[OK] Compatibilidad runtime: sin System.Web.Extensions y GUI Crimson Void protegida.")



def validate_panel_r7() -> None:
    theme = (ROOT / "asgard_theme.py").read_text(encoding="utf-8", errors="replace")
    gui = (ROOT / "manager_gui.py").read_text(encoding="utf-8", errors="replace")
    discord = (ROOT / "discord_integration.py").read_text(encoding="utf-8", errors="replace")
    host = (ROOT / "host_service.py").read_text(encoding="utf-8", errors="replace")
    required = {
        "tema rojo/negro": ["#C8102E", "VoidAvatarFace", "TCombobox*Listbox"],
        "lista viva": ["class LiveListWindow", "actualización automática"],
        "Discord reconciliado": ["STATE_HEARTBEAT_SECONDS", "player_list", "_sync_online_table"],
        "salud viva": ["health_state", "TELEMETRÍA ATRASADA", "_server_health"],
    }
    sources = {
        "tema rojo/negro": theme,
        "lista viva": gui,
        "Discord reconciliado": discord,
        "salud viva": host,
    }
    missing = []
    for group, markers in required.items():
        for marker in markers:
            if marker not in sources[group]:
                missing.append(f"{group}: {marker}")
    if missing:
        fail("Panel R8 incompleto:\n - " + "\n - ".join(missing))
    forbidden_colors = ["#7C3AED", "#22D3EE", "#2563EB", "#38BDF8"]
    leftovers = [color for color in forbidden_colors if color in theme or color in gui]
    if leftovers:
        fail("Quedaron colores antiguos en la GUI principal: " + ", ".join(leftovers))
    print("[OK] Panel externo R8: Crimson Void, textos visibles, health vivo y jugadores sincronizados.")
    host_service = (ROOT / "host_service.py").read_text(encoding="utf-8")
    process_manager = (ROOT / "process_manager.py").read_text(encoding="utf-8")
    common = (ROOT / "common.py").read_text(encoding="utf-8")
    required_r8 = [
        "SERVICE_LOCK_PATH",
        "_acquire_single_instance_lock",
        "server = ThreadingHTTPServer",
        "threading.Thread(target=auto_start",
    ]
    missing_r8 = [item for item in required_r8 if item not in common + host_service]
    if missing_r8:
        fail("R8 incompleta: faltan protecciones de instancia: " + ", ".join(missing_r8))
    if host_service.index("server = ThreadingHTTPServer") > host_service.index("threading.Thread(target=auto_start"):
        fail("R8 insegura: auto_start aparece antes de reservar el puerto del servicio")
    for item in ("_find_matching_processes", "Instancia existente detectada", "instancias duplicadas"):
        if item not in process_manager:
            fail("R8 incompleta: falta guardia de duplicados en ProcessManager: " + item)
    print("[OK] Single Instance R8: bloqueo de servicio y guardia contra valheim_server.exe duplicados.")

    discord = (ROOT / "discord_integration.py").read_text(encoding="utf-8")
    required_r9 = {
        "ProcessManager": ["def reconcile(", "def scan_server(", "def kill_matching(", "preferred_pid", "duplicate_pids"],
        "HostService": ["process_reconciliation_loop", "reconcile_server_process", "Never display telemetry from a dead process", "DUPLICADO"],
        "Discord": ["def mark_offline", "DELETE FROM online_players", 'join_code=excluded.join_code'],
    }
    sources_r9 = {"ProcessManager": process_manager, "HostService": host_service, "Discord": discord}
    missing_r9 = []
    for group, markers in required_r9.items():
        for marker in markers:
            if marker not in sources_r9[group]:
                missing_r9.append(f"{group}: {marker}")
    if missing_r9:
        fail("R9 incompleta: falta reconciliación de procesos:\n - " + "\n - ".join(missing_r9))
    print("[OK] Process Reconciliation R9: PID reales, telemetría limpia y cierre de duplicados.")


def validate_performance_r10() -> None:
    process_manager = (ROOT / "process_manager.py").read_text(encoding="utf-8")
    host_service = (ROOT / "host_service.py").read_text(encoding="utf-8")
    manager_gui = (ROOT / "manager_gui.py").read_text(encoding="utf-8")
    metrics = (ROOT / "metrics_collector.py").read_text(encoding="utf-8")
    theme = (ROOT / "asgard_theme.py").read_text(encoding="utf-8")
    required = {
        "cache de procesos": ["_scan_cache_ttl", "force_refresh", "cached_state"],
        "snapshot compartido": ["snapshots = process_manager.all_valheim_processes(force_refresh=True)", "time.sleep(6)"],
        "métricas reutilizadas": ["metrics_collector.latest_server", "def latest_server"],
        "GUI asíncrona": ["_refresh_inflight", "AsgardGuiServerRefresh", "AsgardGuiDetails", "_last_details_refresh < 6.0"],
        "logo estático ligero": ["void_avatar_user.png", "load_window_logo"],
    }
    sources = {
        "cache de procesos": process_manager,
        "snapshot compartido": host_service,
        "métricas reutilizadas": host_service + metrics,
        "GUI asíncrona": manager_gui,
        "logo estático ligero": theme,
    }
    missing = []
    for group, markers in required.items():
        for marker in markers:
            if marker not in sources[group]:
                missing.append(f"{group}: {marker}")
    if missing:
        fail("R10 incompleta: faltan optimizaciones:\n - " + "\n - ".join(missing))
    list_body = host_service[host_service.index("def list_servers"):host_service.index("class Handler")]
    if "process_manager.reconcile(" in list_body or "all_valheim_processes(" in list_body:
        fail("R10 lenta: list_servers todavía explora/reconcilia procesos en cada petición")
    print("[OK] Performance R10: snapshots compartidos, métricas cacheadas y GUI asíncrona.")
    theme = (ROOT / "asgard_theme.py").read_text(encoding="utf-8", errors="replace")
    if "void_avatar_user.png" not in theme or "load_window_logo" not in theme:
        fail("Logo personalizado incompleto: el panel no carga Assets/void_avatar_user.png")
    print("[OK] Logo personalizado del panel incluido y referenciado.")



def validate_logo_resource() -> None:
    asset = ROOT / "Assets" / "void_avatar_user.png"
    signature = asset.read_bytes()[:8]
    if signature != b"\x89PNG\r\n\x1a\n":
        fail("void_avatar_user.png no es un PNG real; Tkinter activaria el fallback.")
    build = (ROOT / "CREAR_EXE_PORTABLE.bat").read_text(encoding="utf-8", errors="replace")
    theme = (ROOT / "asgard_theme.py").read_text(encoding="utf-8", errors="replace")
    required = ["--add-data", "void_avatar_user.png;Assets", "_MEIPASS"]
    missing = [marker for marker in required if marker not in build + theme]
    if missing:
        fail("Logo no integrado dentro del EXE. Faltan: " + ", ".join(missing))
    print("[OK] Logo: PNG real e integrado dentro del EXE.")

def main() -> int:
    print("============================================================")
    print("ASGARD SERVER SUITE v7.0 - VALIDADOR R10")
    print("============================================================")
    print(f"Ruta: {ROOT}")
    print()

    validate_required_files()
    validate_python()
    validate_xml_projects()
    validate_sources()
    validate_core_public_api()
    validate_unity_module_references()
    validate_bepinex_versions()
    validate_runtime_compatibility()
    validate_panel_r7()
    validate_performance_r10()
    validate_logo_resource()

    print()
    print("VALIDACION COMPLETA: ASGARD v7.0.10.1 LOGO RESOURCE FIX")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        fail("Validacion cancelada por el usuario.")
    except UnicodeError as exc:
        fail(f"Problema de codificacion: {exc}")
