# ASGARD Host Manager v7.0.10.1 — Crimson Void

Esta revisión corrige la carga del logo personalizado: el recurso ahora es PNG real y queda incrustado en el ejecutable.

# ASGARD Server Suite v7.0 Crimson Void R10 — Performance Fix

> R1 corrige el error de Windows `[Errno 22] Invalid argument: '*.py'` en `VALIDAR_PROYECTO.bat`. El nuevo validador revisa cada archivo individualmente.

Esta rama une ASGARD Host Manager, control remoto, recursos, biblioteca global y el primer núcleo del panel maestro/mod de Valheim.

## Compilar Host Manager `.exe`
Ejecuta `CREAR_EXE_PORTABLE.bat`. La salida estará en `dist\AsgardHostManager_v7_0_Void_Foundation`.

## Compilar la suite de Valheim
Entra a `ValheimSuite`, ejecuta `CONFIGURAR_RUTAS.bat` y después `BUILD_ALL.bat`.

## Anticheat Encarnado
- **Vanilla-client compatible:** el servidor sí usa BepInEx, pero los jugadores pueden ver la criatura porque se reutiliza un prefab que ya existe en el juego. No ofrece un modelo completamente nuevo.
- **Enhanced:** requiere Jötunn y `AsgardVoidAvatarClient.dll` en cada cliente para registrar el prefab sincronizado y sus efectos del vacío.

El diseño es original y solo toma la idea general de una entidad cósmica del vacío; no incluye modelos, sprites, nombres ni archivos de Terraria.

## Antes de activar castigo automático
Usa `observe` durante varios días. Revisa identidades y eventos en `ASGARD Suite`. Activa `automatic` solo cuando los detectores estén calibrados para tu modpack.
## Revisión R2 — autodetección de Valheim

Para compilar las DLL ya no escribas tres rutas. Ejecuta:

```bat
ValheimSuite\CONFIGURAR_Y_COMPILAR.bat
```

Selecciona únicamente la carpeta que contiene `valheim_server.exe`. El asistente detecta `valheim_server_Data\Managed`, `BepInEx\core` y `Jotunn.dll`. Si Jötunn no está instalado, compila los módulos base y omite solo el Avatar Enhanced.

## Revisión R3 — Unity Modules Fix

R3 corrige la compilación de `AsgardMasterUI.dll` agregando las referencias `UnityEngine.InputLegacyModule.dll` y `UnityEngine.TextRenderingModule.dll`. El configurador automático comprueba que ambas existan en `valheim_server_Data\Managed`.


## Revision R4 — Particle System y portable robusto

R4 agrega `UnityEngine.ParticleSystemModule.dll` para compilar el Avatar Enhanced. Tambien reemplaza el copiado con `xcopy` por un empaquetador Python que evita el mensaje `Memoria insuficiente` en rutas largas y no copia carpetas `bin`, `obj` ni temporales.


## Revision R5 — BepInEx Version & Installer Fix

R5 corrige las versiones invalidas que provocaban `Skipping type ... because its version is invalid`. Todas las DLL usan ahora la version numerica `7.0.6`. Incluye instaladores automaticos para el servidor y el cliente administrador, y mantiene el Avatar Enhanced separado para que el panel F8 no dependa de Jotunn.


R6 Crimson Void: Core sin System.Web.Extensions y panel F8 rojo/negro completamente rediseñado.

## Revisión R6 — Crimson Void

R6 elimina la dependencia System.Web.Extensions que Unity Mono no carga, protege el panel contra excepciones repetidas y reemplaza la GUI de prueba por una interfaz roja y negra de comando del vacío.


## Revisión R7 — Panel Sync Fix

R7 modifica exclusivamente el panel externo de Windows. Corrige colores de texto, aplica una paleta roja/negra completa, dibuja el rostro del vacío por código, añade diagnóstico de salud sincronizado y convierte la lista de jugadores conectados en una vista viva. También añade `{player_list}` a las variables disponibles para Discord. Las DLL del mod permanecen en 7.0.6.


## Revisión R9 — Process Reconciliation Fix

R9 reconstruye el estado del panel desde los procesos reales de Windows. Recupera PID perdidos, limpia telemetría obsoleta, detecta duplicados por puerto/savedir/mundo y garantiza que Detener/Reiniciar actúen sobre todas las instancias del servidor configurado.


## Revisión R10 — Performance Fix

R10 conserva la reconciliación segura de procesos de R9, pero elimina el costo que hacía lento al panel: una sola exploración compartida de procesos cada seis segundos, caché de firmas, métricas reutilizadas y refrescos de Tkinter totalmente asíncronos. La tabla principal se actualiza cada 2.5 segundos; logs, eventos y gráficas cada 6 segundos; backups cada 20 segundos.


## Logo personalizado del panel

El encabezado y el icono de la ventana cargan `Assets/void_avatar_user.png`, creado directamente a partir de la imagen entregada por el usuario. Este cambio afecta solo al panel externo.

## Documentación histórica y dependencias

- Historial y manuales: `docs/legacy/`.
- Dependencias Python: `requirements/requirements.txt` y `requirements/requirements-build.txt`.
