# ASGARD Security & Stability — etapa 1

## Migración SSH obligatoria
Antes de conectar, verifica la huella SHA256 del servidor OpenSSH directamente con el administrador del host (por ejemplo, ssh-keygen -lf sobre la clave pública del host). Usa el cliente OpenSSH con la dirección y puerto configurados en ASGARD y acepta la huella solamente si coincide. Alternativamente copia la entrada verificada a Data/known_hosts. Para puertos no estándar usa [host]:puerto. No aceptes una clave cambiada sin verificarla. Paramiko ahora rechaza hosts desconocidos.

La API remota viaja por un canal SSH direct-tcpip a 127.0.0.1 del host; OpenSSH debe permitir forwarding local. No requiere exponer el puerto 8766. Recompila y redespliega los agentes existentes para que escuchen exclusivamente en loopback; las reglas de firewall antiguas de ASGARD se deshabilitan durante la configuración. Hasta entonces revisa el firewall y no expongas el agente. La dirección SSH sigue siendo el campo address, no tailscale_ip.

## Backups
Detén el mundo antes de restaurar. La extracción verifica rutas, duplicados, CRC durante lectura y espacio; el contenido se prepara fuera del mundo activo. Se conserva un ZIP preventivo y una carpeta .asgard-previous-* junto al mundo. El operador debe revisar y eliminar manualmente esa carpeta después de validar el mundo restaurado. La retención solo afecta archivos nuevos con prefijo de ID y nombre; los ZIP antiguos no se eliminan automáticamente. No se garantiza consistencia de backups tomados mientras Valheim escribe; detén el mundo para copias consistentes.

## Pendientes
DPAPI y migración del almacén Fernet, permisos ACL de claves en Windows, autenticación de API local, seguridad de backups remotos, validación de procesos externos y pruebas completas de Windows/Valheim. El túnel SSH no sustituye esas tareas. No se habilita TLS independiente en esta etapa.
