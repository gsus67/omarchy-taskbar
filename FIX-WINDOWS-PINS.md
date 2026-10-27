# Corrección local: apertura y agrupación de EXE anclados

27 de octubre de 2026. Rama `fix/windows-file-pins`, basada en v0.0.10.

El anclaje existente de Cities2 apuntaba a un lanzador generado con
`Exec=xdg-open "/mnt/2tb/Cities Skylines II/Cities2.exe"`. El journal confirma
que la barra sí enviaba esa orden a UWSM. En esta sesión Hyprland, el backend
genérico de xdg-open divide el `Exec` del controlador predeterminado sin
interpretar correctamente las comillas de su ruta. El controlador de Tool
usa `/usr/bin/bash ".../exe-proton/run-exe" %f`; su registro no se actualizaba
con esos clics.

Los nuevos anclajes usan `gio open`, que reutiliza la misma asociación MIME
y analiza correctamente el lanzador del controlador. Al cargar los anclajes,
la barra repara de forma atómica únicamente las líneas antiguas de apertura
EXE/MSI en su espacio de nombres `omarchy-taskbar-<hash>`. No cambia la lista,
el orden, los iconos, las asociaciones MIME ni los archivos originales.
La reparación es idempotente y no sigue lanzadores que sean enlaces simbólicos.

El segundo fallo era la identidad: el lanzador tiene un identificador con
hash, pero Wine suele publicar una clase como `Cities2.exe`. Ahora la barra
asocia una clase o nombre de proceso coincidente con el EXE del anclaje,
respetando su icono. Las ventanas con clases Wine genéricas se consultan por
dirección individual. No se leen líneas de comandos de procesos, que podrían
contener secretos. Ante dos anclajes con el mismo nombre de EXE, no se adivina
cuál corresponde; tampoco se asocia por títulos o coincidencias parciales.

Validación: 59 unittest correctas; incluye lanzamiento real con GIO hacia un
controlador de prueba cuya ruta contiene espacios, reparación idempotente,
protección de enlaces y pruebas del JavaScript real de agrupación. `bash -n`
y `git diff --check` correctos. ShellCheck no está instalado localmente; no se
instaló ninguna dependencia. No había un juego abierto al consultar las
ventanas, por lo que la agrupación de una ventana real del juego queda por
comprobar en uso. No se lanzó el juego como parte de las pruebas.
