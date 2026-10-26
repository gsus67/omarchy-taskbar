# Omarchy Taskbar

**English** · [Español](README.es.md)

A clean bottom bar for [Omarchy](https://omarchy.org/), as wide as the
original bar and drawn with the same theme tokens (size, colors, font,
transparency), so it changes with your theme. It holds your pinned apps to open
them fast and shows every open app, all centered.

![Omarchy Taskbar](preview.png)

## Features

- One bar along the bottom edge of every screen; windows make room for it.
- Pinned apps first, then any other app you open, centered and growing from
  the middle.
- A short mark under apps that have windows; the focused app gets a wider mark
  in the accent color.
- **Left click**: open the app, or focus it; if it is already focused and has
  several windows, step to the next one.
- **Middle click**: new window.
- **Right click**: pin/unpin, new window, close. New window works for every
  app, also windows without a desktop entry (such as a terminal started with
  its own class).
- **Web apps** (Omarchy's `omarchy-webapp-install`) show their own icon, get
  their own button and can be pinned, instead of appearing as the browser.
- **Double click on empty bar space**: toggle transparency, exactly like
  Omarchy's bar. Both bars share the same setting (`bar.transparent` in
  `shell.json`), so double-clicking either one changes both.
- English and Spanish, following the system language.

## Lean by design

Nothing to install and no sudo. It only uses what Omarchy already ships:
Quickshell's window list, desktop entries and icon theme, Omarchy's theme
tokens, `omarchy bar transparent` and `uwsm-app` to start apps. It reacts to
events (windows opening/closing, file changes) and never polls.

The first time it pins your default browser (`omarchy-cmd-default-browser`),
file manager and terminal. A window whose class has no desktop entry (for
example `alacritty --class=org.omarchy.agent`) borrows the icon of the program
behind it, looked up once with `hyprctl`.

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
- Nothing else is written outside the plugin folder. To remove every trace
  after `omarchy plugin remove`: `rm -r ~/.config/omarchy-taskbar`.

## License

[MIT](LICENSE)
