# ASGARD Valheim Suite v7.0 Foundation

## Dos versiones del Anticheat Encarnado

### Vanilla-compatible / server-side
Usa un prefab que ya existe en Valheim. No requiere que jugadores normales instalen el avatar. La apariencia está limitada a modelos y efectos vanilla; se elige automáticamente entre Fader, Seeker Queen, Yagluth/Bonemass y otros fallbacks disponibles.

### Enhanced / cliente + servidor
Todos los clientes deben instalar `AsgardVoidAvatarClient.dll` y Jötunn. Registra `AsgardVoidAvatar`, clona un jefe vanilla y aplica escala, materiales oscuros, emisión violeta/cian, luces y partículas del vacío. No incluye contenido de Terraria ni copia su diseño: es una interpretación original temática del vacío.

## Seguridad
El modo inicial es `observe`. Cambia a `automatic` solo después de revisar eventos reales. El auto-baneo exige Platform ID exacto por defecto. El Avatar no daña estructuras por defecto.

## Compilación automática

1. Instala .NET SDK 8.
2. Instala BepInEx en el servidor.
3. Ejecuta `CONFIGURAR_Y_COMPILAR.bat`.
4. Selecciona únicamente la carpeta donde está `valheim_server.exe`.
5. ASGARD detectará automáticamente `valheim_server_Data\Managed`, `BepInEx\core` y `Jotunn.dll`.

Si Jötunn no está instalado, se compilan normalmente `ServerBase` y `AdminClient`; solamente se omite el Avatar Enhanced.

La salida queda en:

- `Dist/ServerBase`: copiar a `BepInEx/plugins` del servidor.
- `Dist/AdminClient`: copiar solamente a clientes administradores.
- `Dist/EnhancedShared`: servidor y todos los clientes cuando se use el Avatar Enhanced.


## R4

El configurador tambien valida `UnityEngine.ParticleSystemModule.dll`. Las carpetas `Dist\ServerBase` y `Dist\AdminClient` se generan antes de compilar el modulo Enhanced, por lo que permanecen disponibles si falla solamente esa variante.


## R5 - Versiones BepInEx e instalacion automatica

Todas las DLL declaran una version numerica valida `7.0.6`. BepInEx 5 no acepta sufijos como `-foundation-r4`.

Despues de compilar puedes ejecutar:

- `INSTALAR_EN_SERVIDOR.bat`: usa automaticamente el servidor seleccionado.
- `INSTALAR_EN_CLIENTE_ADMIN.bat`: selecciona la carpeta que contiene `valheim.exe`.

`AdminClient` contiene solamente Core y Master UI. El Avatar Enhanced permanece separado en `EnhancedShared` y solo se instala si eliges Enhanced y Jotunn esta presente.


R6 Crimson Void: Core sin System.Web.Extensions y panel F8 rojo/negro completamente rediseñado.
