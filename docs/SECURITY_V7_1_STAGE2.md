# Security & Stability — Stage 2

- Actualiza juntos el panel, servicio local, controlador y agente remoto. Las versiones antiguas del panel no envían el token local.
- El token local se genera en Data/local_api.token. No compartir este archivo. En NTFS, restringir los permisos de Data al usuario que ejecuta el panel y servicio. La autenticación local no protege frente a otro proceso del mismo usuario con acceso a Data.
- Los plugins Valheim conservan sus tokens por servidor para POST de auditoría y castigos. Primero configura el token desde ASGARD Suite.
- El agente remoto escucha exclusivamente en loopback incluso con una configuración antigua; usa SSH verificado.
- Backups remotos usan el mismo motor de integridad, nombres únicos y retención aislada que los locales. Detén el servidor para una copia consistente.
- Logs principales rotan a 5 MiB con cuatro archivos históricos. Los eventos SQLite y el registro auxiliar del agente requieren política de retención posterior.
- El script antiguo de limpieza global ahora solo diagnostica, sin taskkill indiscriminado.
- Pendientes: DPAPI, ACL automáticas, pruebas reales con Windows/Valheim, endurecimiento de permisos del agente y verificación de CI.
