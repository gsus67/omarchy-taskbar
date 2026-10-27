# Omarchy Taskbar

**English** · [Español](README.es.md)

A clean bottom bar for [Omarchy](https://omarchy.org/), as wide as the
original bar and drawn with the same theme tokens (size, colors, font,
transparency), so it changes with your theme. It holds your pinned apps to open
them fast and shows every open app, all centered.

![Omarchy Taskbar](preview.png)

The bar up close, with pinned apps, open apps and web apps with their own
icons (WhatsApp, YouTube, Discord, Google Maps, Google Photos):

![The bar, dark](assets/bar-dark.png)

![Full screen with the dark bar](assets/screen-dark-empty.png)

Double-click empty space and it turns transparent, together with Omarchy's own
bar:

![The bar, transparent](assets/bar-transparent.png)

![Full screen with the transparent bar](assets/screen-transparent-empty.png)

![With windows open and the transparent bar](assets/screen-transparent.png)

An app with several windows, here three terminals on workspaces 8, 9 and 10:
a click shows each one with its workspace, and picking one jumps there.

![Window previews with their workspace](assets/window-previews.png)

## Features

- One bar along the bottom edge of every screen; windows make room for it.
- Pinned apps first, then any other app you open, centered and growing from
  the middle.
- A short mark under apps that have windows; the focused app gets a wider mark
  in the accent color.
- **Left click**: open the app, or focus it; if it is already focused and has
  several windows, step to the next one.
- **Middle click**: new window.
- **Drag app icons**: reorder pins with the same floating preview and insertion
  marker as Omarchy's top bar. Drop a running app into the pins to pin it there.
  The order is saved in `pinned.json` and shared by every screen. A drop outside
  the bar cancels; dropping onto the same icon changes nothing.
- **Drag files onto any bar**: pin desktop launchers, Windows files
  (`.exe`/`.msi`), and executable programs or AppImages at the end of your pins.
- **Several windows of one app**: a click shows a thumbnail of each with its
  workspace (one frame, taken only while the list is open); pick one and the bar takes you there, even on another workspace.
- **Right click**: pin/unpin, new window, close. New window works for every
  app, also windows without a desktop entry (such as a terminal started with
  its own class).
- **The right icon for apps behind other programs**: apps running inside a
  terminal (cliamp, Voxtype, Omarchy's Docker and monitor TUIs) and windows
  opened by a script (the Windows VM's FreeRDP window) show the app's own icon.
  Only process names are read, never command lines.
- **Web apps** (Omarchy's `omarchy-webapp-install`) show their own icon, get
  their own button and can be pinned, instead of appearing as the browser.
- **Double click on empty bar space**: toggle transparency, exactly like
  Omarchy's bar. Both bars share the same setting (`bar.transparent` in
  `shell.json`), so double-clicking either one changes both.
- English and Spanish, following the system language.

## Lean by design

Nothing to install and no administrator permissions needed. It only uses what
Omarchy already ships: Quickshell's window list, desktop entries and icon theme,
Omarchy's theme tokens, `omarchy bar transparent` and `uwsm-app` to start apps.
It reacts to events (windows opening/closing, file changes) and never polls.

The first time it pins your default browser (`omarchy-cmd-default-browser`),
file manager and terminal. A window whose class has no desktop entry (for
example `alacritty --class=org.omarchy.agent`) borrows the icon of the program
behind it, looked up once with `hyprctl`.

## Pin files by dragging

Drag a supported file from your file manager onto any bar. Installed `.desktop`
files use their desktop entry id; launchers from elsewhere are copied into your
user applications folder. Programs and AppImages need execute permission.
Windows files open with the system default handler for their MIME type through
`xdg-open`, including GE-Proton if that is your configured handler.

For `.exe` files, the bar extracts an icon when both `wrestool` and `icotool`
(icoutils) are already installed; otherwise it uses a generic executable icon.
It never installs packages. Paths containing `%` or control characters,
unsupported files and non-file drops are ignored. Right-click the pin and choose
**Unpin** to remove it and its generated launcher and icon; the original file
stays in place.

## Install, update and remove

```bash
omarchy plugin add https://github.com/gsus67/omarchy-taskbar.git --enable
omarchy plugin update io.github.gsus67.omarchy-taskbar
omarchy plugin remove io.github.gsus67.omarchy-taskbar
```

After an update, run `omarchy restart shell` so the shell loads the new code.

## Files

- `~/.config/omarchy-taskbar/pinned.json`: your pinned apps (desktop entry ids,
  in order). You can edit it by hand; the bar picks up changes at once.
- `~/.config/omarchy-taskbar/config.json`: optional settings; changes apply at
  once. Right-click empty bar space to set `scale` to **1x** (original size,
  default), **1.25x**, **1.5x** or **2x**. This scales the bar height and icons;
  missing or invalid `scale` uses 1x. **1x** removes `scale`, keeping other
  settings, and deletes the file if empty. Set `width` by hand in pixels
  (`{"width": 960}`) or a percentage of each screen's width (`{"width": "60%"}`).
  The bar is centered, with width clamped between twice the bar height and the
  screen width. A missing
  file, invalid JSON or an absent/invalid `width` keeps the full-width default.
- `~/.local/share/applications/omarchy-taskbar-<hash>.desktop`: launchers
  generated for dropped programs and copies of external `.desktop` files.
- `~/.local/share/icons/hicolor/256x256/apps/omarchy-taskbar-<hash>.png`:
  extracted Windows icons, when available.

Unpinning removes the generated launcher and icon. After removing the plugin,
clean up any remaining pins and generated files with:

```bash
rm -rf -- ~/.config/omarchy-taskbar
rm -f -- ~/.local/share/applications/omarchy-taskbar-*.desktop \
  ~/.local/share/icons/hicolor/256x256/apps/omarchy-taskbar-*.png
```

## License

[MIT](LICENSE)
