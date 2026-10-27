# Omarchy Taskbar

[English](README.md) · **Español**

Una barra inferior limpia para [Omarchy](https://omarchy.org/), del mismo ancho
que la barra original y dibujada con los mismos valores del tema (tamaño,
colores, fuente y transparencia), así que cambia junto con tu tema. Tiene tus
aplicaciones ancladas para abrirlas rápido y muestra todas las que están
abiertas, siempre centradas.

![Omarchy Taskbar](preview.png)

La barra de cerca, con apps ancladas, apps abiertas y aplicaciones web con su
propio icono (WhatsApp, YouTube, Discord, Google Maps, Google Photos):

![La barra, oscura](assets/bar-dark.png)

![Pantalla completa con la barra oscura](assets/screen-dark-empty.png)

Con doble clic en un espacio vacío se vuelve transparente, junto con la barra
de Omarchy:

![La barra, transparente](assets/bar-transparent.png)

![Pantalla completa con la barra transparente](assets/screen-transparent-empty.png)

![Con ventanas abiertas y la barra transparente](assets/screen-transparent.png)

Una app con varias ventanas, aquí tres terminales en los escritorios 8, 9 y 10: un clic muestra cada una con su escritorio, y al elegir una te lleva a ella.

![Miniaturas de las ventanas con su escritorio](assets/window-previews.png)

## Funciones

- Una barra en el borde inferior de cada pantalla; las ventanas le dejan sitio.
- Primero las apps ancladas y después cualquier otra que abras, centradas y
  creciendo desde el medio.
- Una marca corta debajo de las apps con ventanas abiertas; la app con el foco
  tiene una marca más ancha del color de acento.
- **Clic izquierdo**: abre la app o la enfoca; si ya tiene el foco y varias
  ventanas, pasa a la siguiente.
- **Clic central**: ventana nueva.
- **Arrastrar iconos de apps**: reordena los anclajes con la misma vista flotante
  y el mismo marcador de inserción que la barra superior de Omarchy. Suelta una
  app abierta entre los anclajes para anclarla ahí. El orden se guarda en
  `pinned.json` y se comparte en todas las pantallas. Soltar fuera de la
  barra cancela; soltar sobre el mismo icono no cambia nada.
- **Arrastrar archivos a cualquier barra**: ancla accesos de escritorio,
  archivos de Windows (`.exe`/`.msi`) y programas ejecutables o AppImages al
  final de tus anclajes.
- **Varias ventanas de una app**: un clic muestra una miniatura de cada una con su escritorio (una sola captura, solo mientras la lista está abierta); eliges una y la barra te lleva a ella, aunque esté en otro escritorio.
- **Clic derecho**: anclar/desanclar, ventana nueva, cerrar. Ventana nueva funciona con todas las apps, también con ventanas sin entrada de escritorio (como una terminal abierta con su propia clase).
- **El icono correcto en apps que van detrás de otro programa**: las que corren dentro de una terminal (cliamp, Voxtype, las TUI de Docker y monitores de Omarchy) y las ventanas que abre un script (la ventana FreeRDP de la máquina virtual de Windows) muestran su propio icono. Solo se leen nombres de procesos, nunca líneas de órdenes.
- **Aplicaciones web** (las de `omarchy-webapp-install`): muestran su propio icono, tienen su propio botón y se pueden anclar, en vez de salir como el navegador.
- **Doble clic en una zona vacía**: activa o quita la transparencia, igual que
  la barra de Omarchy. Las dos barras comparten el mismo ajuste
  (`bar.transparent` en `shell.json`), así que el doble clic en cualquiera
  cambia ambas.
- Inglés y español, según el idioma del sistema.

## Ligera

No instala nada ni necesita permisos de administrador. Solo usa lo que Omarchy
ya trae: la lista de
ventanas, los accesos de aplicaciones y el tema de iconos de Quickshell, los
valores del tema de Omarchy, `omarchy bar transparent` y `uwsm-app` para abrir
apps. Reacciona a eventos (ventanas que se abren o cierran, cambios de archivo)
y nunca consulta en bucle.

La primera vez ancla tu navegador predeterminado
(`omarchy-cmd-default-browser`), el gestor de archivos y la terminal. Una
ventana cuya clase no tiene acceso de aplicación (por ejemplo
`alacritty --class=org.omarchy.agent`) usa el icono del programa que hay
detrás, consultado una sola vez con `hyprctl`.

## Anclar archivos arrastrándolos

Arrastra un archivo compatible desde el gestor de archivos a cualquier barra.
Los archivos `.desktop` instalados usan su id de entrada; los accesos que vienen
de otro sitio se copian a tu carpeta de aplicaciones de usuario. Los programas
y AppImages necesitan permiso de ejecución. Los archivos de Windows se abren
con la aplicación predeterminada del sistema para su tipo MIME mediante
`xdg-open`, incluido GE-Proton si lo tienes configurado como predeterminado.

Para los archivos `.exe`, la barra extrae un icono si `wrestool` e `icotool`
(icoutils) ya están instalados; si no, usa un icono genérico de ejecutable.
Nunca instala paquetes. Se ignoran las rutas con `%` o caracteres de control,
los archivos no compatibles y los elementos que no sean archivos. Haz clic
derecho en el anclaje y elige **Desanclar** para quitarlo junto con el acceso y
el icono generados; el archivo original permanece en su sitio.

## Instalar, actualizar y quitar

```bash
omarchy plugin add https://github.com/gsus67/omarchy-taskbar.git --enable
omarchy plugin update io.github.gsus67.omarchy-taskbar
omarchy plugin remove io.github.gsus67.omarchy-taskbar
```

Después de actualizar, ejecuta `omarchy restart shell` para que el shell cargue
el código nuevo.

## Archivos

- `~/.config/omarchy-taskbar/pinned.json`: tus apps ancladas (ids de los
  accesos, en orden). Puedes editarlo a mano; la barra recoge los cambios al
  momento.
- `~/.config/omarchy-taskbar/config.json`: ajustes opcionales; los cambios se
  aplican al momento. Haz clic derecho en un espacio vacío de la barra para poner
  `scale` en **1x** (tamaño original y predeterminado), **1.25x**, **1.5x** o
  **2x**. Esto escala la altura de la barra y los iconos; si `scale` falta o no
  es válido, se usa 1x. **1x** elimina `scale`, conserva los demás ajustes y
  borra el archivo si queda vacío. Edita `width` a mano en píxeles
  (`{"width": 960}`) o como porcentaje del ancho de cada pantalla
  (`{"width": "60%"}`). La barra queda centrada, con el ancho limitado entre el
  doble de su altura y el ancho de la pantalla. Si falta el archivo, el JSON no
  es válido o `width` falta o no es válido, se mantiene el ancho completo.
- `~/.local/share/applications/omarchy-taskbar-<hash>.desktop`: accesos
  generados para los programas arrastrados y copias de archivos `.desktop`
  externos.
- `~/.local/share/icons/hicolor/256x256/apps/omarchy-taskbar-<hash>.png`:
  iconos extraídos de archivos de Windows, cuando están disponibles.

Al desanclar se eliminan el acceso y el icono generados. Después de quitar el
plugin, borra los anclajes y archivos generados que queden con:

```bash
rm -rf -- ~/.config/omarchy-taskbar
rm -f -- ~/.local/share/applications/omarchy-taskbar-*.desktop \
  ~/.local/share/icons/hicolor/256x256/apps/omarchy-taskbar-*.png
```

## Licencia

[MIT](LICENSE)
