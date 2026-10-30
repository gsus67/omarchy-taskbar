# Changelog

## v0.2.0 — 2026-10-30

- Add **Position** to the bar's menu: **Top**, **Right**, **Left**, **Bottom**
  (default) and **Combine**. Menus, previews and reordering follow the edge.
- **Combine** turns the taskbar into a module of Omarchy's bar. Drag its margin
  to place it between other modules, and right-click the margin for the menu.
  It grows with its icons until the next section, then scrolls with the wheel.
  **Size** is hidden there; **Style** still applies.

## v0.1.1 — 2026-10-28

- Restrict permissions on a verified owned regular legacy launcher before
  checking for a destination conflict. An existing private copy can no longer
  leave a legacy copy group/other-readable. Both contents remain unchanged.
- Add sentinel-secret regressions for both add and repair conflicts, covering
  0644, 0640, 0444, 0600 and 0400 modes. The test reproduced the public-mode
  failure on v0.1.0 before the fix.

## v0.1.0 — 2026-10-28

### Security

- Import external desktop launchers into a dedicated owner-only directory
  (`0700`), with launcher contents restricted to the owner (`0600`).
- Preserve existing permissions during Windows launcher repair. Migrating
  legacy flat launchers removes group/other permissions without adding owner
  permissions, including for owner-read-only entries.
- Keep desktop IDs stable during migration, refuse conflicting copies, and
  avoid following a substituted private-directory symlink during cleanup.
- Continue treating dropped paths as data: no program is executed by pinning,
  and existing quoting, percent-field-code and control-character guards remain.

### Appearance

- Right-click empty space for **Style** and **Size**, in English or Spanish
  according to the system locale.
- **Default** follows the native top bar; **Crystal** provides a very translucent
  rounded surface with subtle glass highlights and space around its ends.
- **Size** exposes **Length** and **Width** in both styles. Width scales the bar
  and icons from 0.75x through 2x, including the new 0.75x and 0.9x choices.
- Length ranges from Full down to 10%. A selected percentage is the minimum;
  the bar grows with its icons and shrinks again when apps close. Scrolling
  keeps icons reachable if they exceed the screen's maximum length.
- Serialize preference writes so rapid selections preserve previous choices
  and unrelated settings. Menu values are restricted to fixed allowlists.

Crystal does not enable compositor blur, edit Hyprland configuration, install
packages or add a resident process.
