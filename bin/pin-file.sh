#!/usr/bin/env bash

# Add a dropped file or remove a generated entry. Only a successful add prints
# an id; unsupported files and failed file operations stay silent.
set -euo pipefail
umask 077
exec 2>/dev/null

applications=$HOME/.local/share/applications
private_applications=$applications/omarchy-taskbar
icons=$HOME/.local/share/icons/hicolor/256x256/apps
script_path=${BASH_SOURCE[0]}
if [[ $script_path == */* ]]; then
  script_dir=${script_path%/*}
else
  script_dir=.
fi
set_icon_script=$script_dir/set-icon.sh

# DesktopEntries scans application subdirectories and maps their names into
# the desktop-entry id, so this keeps omarchy-taskbar-<hash> stable.
secure_applications_dir() {
  [[ ! -L $private_applications ]] || return 1
  # shellcheck disable=SC2174  # chmod below also fixes an existing directory.
  mkdir -p -m 700 -- "$private_applications" || return 1
  [[ -d $private_applications && ! -L $private_applications && -O $private_applications ]] || return 1
  chmod 700 -- "$private_applications"
}

# Flat and nested paths have the same desktop id. Restrict a verified legacy
# file before checking migration preconditions, including a destination conflict.
# Both contents stay intact on conflict; only group/other permissions are removed
# so even owner-read-only launchers retain their original owner mode.
migrate_legacy_pin() {
  local legacy=$applications/$1.desktop entry=$private_applications/${1#omarchy-taskbar-}.desktop
  [[ -e $legacy || -L $legacy ]] || return 0
  [[ -f $legacy && ! -L $legacy && -O $legacy ]] || return 1
  chmod go-rwx -- "$legacy" || return 1
  [[ ! -e $entry && ! -L $entry ]] || return 1
  secure_applications_dir || return 1
  mv -nT -- "$legacy" "$entry" || return 1
  [[ ! -e $legacy && ! -L $legacy ]]
}

# Quote one Exec argument, then apply the desktop file's string escaping.
desktop_exec_arg() {
  local value=$1
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  value=${value//\`/\\\`}
  value=${value//\$/\\\$}
  value=${value//\\/\\\\}
  printf '"%s"' "$value"
}

desktop_value() {
  local value=$1
  value=${value//\\/\\\\}
  value=${value// /\\s}
  printf '%s' "$value"
}

valid_path() {
  local LC_ALL=C
  # Percent signs introduce Exec field codes. Reject them, along with ASCII
  # and UTF-8 C1 controls, both before and after resolving links.
  [[ $1 == /* && $1 != *%* && $1 != *[[:cntrl:]]* && $1 != *$'\xc2'[$'\x80'-$'\x9f']* && -f $1 ]]
}

# Reuse an installed entry only if DesktopEntries already knows its id.
known_desktop_id() {
  local path=$1 known=$2 dir id
  local -a dirs
  IFS=: read -r -a dirs <<< "${XDG_DATA_HOME:-$HOME/.local/share}:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
  for dir in "${dirs[@]}"; do
    [[ $dir == /* ]] || continue
    dir=$(readlink -f -- "$dir/applications") || continue
    [[ $path == "$dir/"* ]] || continue
    id=${path#"$dir/"}
    id=${id%.desktop}
    id=${id//\//-}
    if jq -e --arg id "$id" 'index($id) != null' <<< "$known" >/dev/null; then
      printf '%s\n' "$id"
      return 0
    fi
  done
  return 1
}

# Optional extraction delegates all untrusted parsing and resource limits to
# set-icon.sh, then atomically copies only its validated private PNG.
extract_icon() (
  local path=$1 id=$2 result name source destination="" validation_dir=""
  local temp_parent=${TMPDIR:-/tmp} temp_prefix validation_state validation_map validation_icons
  [[ $temp_parent == /* ]] || return 0
  temp_prefix=${temp_parent%/}/omarchy-taskbar-pin.
  validation_dir=$(mktemp -d "${temp_prefix}XXXXXX") || return 0
  [[ $validation_dir == "$temp_prefix"?????? && -d $validation_dir \
    && ! -L $validation_dir && -O $validation_dir ]] || return 0
  trap '[[ -z $destination ]] || rm -f -- "$destination"; [[ -z $validation_dir ]] || rm -rf -- "$validation_dir"' EXIT
  validation_state=$validation_dir/config/omarchy-taskbar
  validation_map=$validation_state/pinned-icons.json
  validation_icons=$validation_state/icons
  result=$(XDG_CONFIG_HOME="$validation_dir/config" "$BASH" "$set_icon_script" set "$id" "$path") || return 0
  [[ $result == ok && -f $validation_map && ! -L $validation_map && -O $validation_map ]] || return 0
  name=$(jq -er --arg key "$id" '.[$key] | select(type == "string")' -- "$validation_map") || return 0
  [[ $name =~ ^[0-9a-f]{16}-[A-Za-z0-9]{6}\.png$ ]] || return 0
  source=$validation_icons/$name
  [[ -f $source && ! -L $source && -O $source ]] || return 0
  [[ $icons == /* && ! -L $icons ]] || return 0
  mkdir -p -- "$icons" || return 0
  [[ -d $icons && ! -L $icons && -O $icons ]] || return 0
  destination=$(mktemp "$icons/.${id}.XXXXXX") || return 0
  [[ $destination == "$icons"/.${id}.?????? && -f $destination \
    && ! -L $destination && -O $destination ]] || return 0
  cp --no-dereference -- "$source" "$destination" || return 0
  chmod 600 -- "$destination" || return 0
  mv -fT -- "$destination" "$icons/$id.png" || return 0
  destination=""
  printf '%s' "$id"
)

write_launcher() {
  local path=$1 id=$2 kind=$3 name=${1##*/} exec_line icon=""
  if [[ $kind == *.exe ]]; then
    icon=$(extract_icon "$path" "$id") || icon=""
  fi
  exec_line=$(desktop_exec_arg "$path")
  if [[ $kind == *.exe || $kind == *.msi ]]; then
    # GIO parses the default handler's desktop Exec quoting correctly. The
    # generic xdg-open backend can pass literal quotes to the Proton runner.
    exec_line="gio open $exec_line"
  fi
  name=${name%.*}
  [[ -n $name ]] || return 1
  printf '[Desktop Entry]\nType=Application\nName=%s\nExec=%s\nIcon=%s\nTerminal=false\n' \
    "$(desktop_value "$name")" "$exec_line" "${icon:-application-x-executable}"
}

add_pin() (
  local path name kind hash id entry
  valid_path "$1" || return 0
  # A NUL delimiter preserves trailing newlines so validation cannot miss them.
  IFS= read -r -d '' path < <(readlink -fz -- "$1") || return 0
  valid_path "$path" || return 0
  name=${path##*/}
  kind=${name,,}
  if [[ $kind == *.desktop ]]; then
    if id=$(known_desktop_id "$path" "$2"); then
      printf '%s\n' "$id"
      return 0
    fi
  elif [[ $kind != *.exe && $kind != *.msi && ! -x $path ]]; then
    return 0
  fi

  hash=$(printf '%s' "$path" | sha256sum) || return 0
  id=omarchy-taskbar-${hash:0:16}
  migrate_legacy_pin "$id" || return 0
  secure_applications_dir || return 0
  entry=$(mktemp "$private_applications/.omarchy-taskbar-XXXXXX") || return 0
  trap 'rm -f -- "$entry"' EXIT
  if [[ $kind == *.desktop ]]; then
    cp -- "$path" "$entry" || return 0
  else
    write_launcher "$path" "$id" "$kind" > "$entry" || return 0
  fi
  chmod 600 -- "$entry" || return 0
  mv -fT -- "$entry" "$private_applications/${id#omarchy-taskbar-}.desktop" || return 0
  printf '%s\n' "$id"
)

remove_pin() {
  "$BASH" "$set_icon_script" remove "$1" >/dev/null || true
  [[ $1 =~ ^omarchy-taskbar-[0-9a-f]{16}$ ]] || return 0
  rm -f -- "$applications/$1.desktop" "$icons/$1.png" || return 0
}

repair_pin() (
  local id=$1 entry tmp line changed=false
  local -a lines=()
  [[ $id =~ ^omarchy-taskbar-[0-9a-f]{16}$ ]] || return 0
  entry=$private_applications/${id#omarchy-taskbar-}.desktop
  migrate_legacy_pin "$id" || return 0
  [[ -f $entry && ! -L $entry ]] || return 0
  secure_applications_dir || return 0
  while IFS= read -r line || [[ -n $line ]]; do
    if [[ $line == 'Exec=xdg-open "'* && ( ${line,,} == *'.exe"' || ${line,,} == *'.msi"' ) ]]; then
      line="Exec=gio open ${line#Exec=xdg-open }"
      changed=true
    fi
    lines+=("$line")
  done < "$entry"
  [[ $changed == true ]] || return 0
  secure_applications_dir || return 0
  tmp=$(mktemp "$private_applications/.omarchy-taskbar-XXXXXX") || return 0
  trap 'rm -f -- "$tmp"' EXIT
  printf '%s\n' "${lines[@]}" > "$tmp"
  chmod --reference="$entry" -- "$tmp" && mv -fT -- "$tmp" "$entry"
)

[[ $# == 3 ]] || exit 0
case $1 in
  add) add_pin "$2" "$3" ;;
  remove) remove_pin "$2" ;;
  repair) repair_pin "$2" ;;
  icon) "$BASH" "$set_icon_script" set "$2" "$3" ;;
  unicon) "$BASH" "$set_icon_script" reset "$2" ;;
esac
