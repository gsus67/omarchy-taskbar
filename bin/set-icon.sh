#!/usr/bin/env bash

# Store a validated private PNG for one pinned-app key, or remove it again.
# Every result uses the stdout protocol consumed by the taskbar.
set -uo pipefail
umask 077
exec 2>/dev/null

config_home=${XDG_CONFIG_HOME:-$HOME/.config}
state_dir=$config_home/omarchy-taskbar
icons_dir=$state_dir/icons
map_file=$state_dir/pinned-icons.json
lock_file=$state_dir/.lock
max_source_size=$((20 * 1024 * 1024))
max_icon_entries=1024
lock_timeout=10
private_applications=$HOME/.local/share/applications/omarchy-taskbar
tmp_dir=""
tmp_map=""
new_icon=""
lock_fd=""

release_map_lock() {
  [[ -n $lock_fd ]] || return 0
  flock -u "$lock_fd" || return 1
  exec {lock_fd}>&-
  lock_fd=""
}

# shellcheck disable=SC2329  # Invoked indirectly by the EXIT trap below.
cleanup() {
  release_map_lock || true
  [[ -z $tmp_map ]] || rm -f -- "$tmp_map"
  [[ -z $new_icon ]] || rm -f -- "$new_icon"
  [[ -z $tmp_dir ]] || rm -rf -- "$tmp_dir"
}
trap cleanup EXIT

fail() {
  printf 'error:%s\n' "$1"
  exit 0
}

ok() {
  printf 'ok\n'
  exit 0
}

valid_key() {
  local LC_ALL=C key=$1
  [[ -n $key && $key != *'..'* && $key != *[[:cntrl:]]* \
    && $key != *$'\xc2'[$'\x80'-$'\x9f']* ]] || return 1
  [[ $key =~ ^[A-Za-z0-9._+@-]+$ || $key == /* ]]
}

secure_dir() {
  local dir=$1
  [[ $dir == /* && ! -L $dir ]] || return 1
  mkdir -p -- "$dir" || return 1
  [[ -d $dir && ! -L $dir && -O $dir ]] || return 1
  chmod 700 -- "$dir"
}

secure_existing_dir() {
  local dir=$1
  [[ $dir == /* && -d $dir && ! -L $dir && -O $dir ]] || return 1
  chmod 700 -- "$dir"
}

hex_bytes() {
  local path=$1 offset=$2 count=$3
  od -An -tx1 -j "$offset" -N "$count" -- "$path" | tr -d ' \n'
}

png_magic() {
  local path=$1 size signature offset=8 chunks=0 chunk_header length_hex length type next format
  local saw_idat=false
  size=$(stat -c %s -- "$path") || return 1
  ((size >= 45)) || return 1
  signature=$(hex_bytes "$path" 0 8) || return 1
  [[ $signature == 89504e470d0a1a0a ]] || return 1
  while ((offset + 12 <= size && chunks < 4096)); do
    chunk_header=$(hex_bytes "$path" "$offset" 8) || return 1
    [[ $chunk_header =~ ^[0-9a-f]{16}$ ]] || return 1
    length_hex=${chunk_header:0:8}
    type=${chunk_header:8:8}
    length=$((16#$length_hex))
    next=$((offset + 12 + length))
    ((next <= size)) || return 1
    if ((chunks == 0)); then
      [[ $length == 13 && $type == 49484452 ]] || return 1
      format=$(hex_bytes "$path" 24 5) || return 1
      case $format in
        010000000[01]|020000000[01]|040000000[01]|080000000[01]|100000000[01]|080200000[01]|100200000[01]|010300000[01]|020300000[01]|040300000[01]|080300000[01]|080400000[01]|100400000[01]|080600000[01]|100600000[01]) ;;
        *) return 1 ;;
      esac
    elif [[ $type == 49444154 ]]; then
      saw_idat=true
    elif [[ $type == 49454e44 ]]; then
      [[ $length == 0 && $saw_idat == true && $next == "$size" ]] || return 1
      [[ $(hex_bytes "$path" "$((offset + 8))" 4) == ae426082 ]]
      return
    fi
    offset=$next
    chunks=$((chunks + 1))
  done
  return 1
}

valid_png_dimensions() {
  local path=$1 width height
  read -r width height < <(png_dimensions "$path") || return 1
  ((width > 0 && height > 0 && width <= 1024 && height <= 1024))
}

png_dimensions() {
  local path=$1 width_hex height_hex width height
  png_magic "$path" || return 1
  width_hex=$(hex_bytes "$path" 16 4) || return 1
  height_hex=$(hex_bytes "$path" 20 4) || return 1
  [[ $width_hex =~ ^[0-9a-f]{8}$ && $height_hex =~ ^[0-9a-f]{8}$ ]] || return 1
  width=$((16#$width_hex))
  height=$((16#$height_hex))
  printf '%d %d\n' "$width" "$height"
}

ico_magic() {
  local path=$1 header count
  header=$(hex_bytes "$path" 0 4) || return 1
  count=$(hex_bytes "$path" 4 2) || return 1
  [[ $header == 00000100 && $count != 0000 ]]
}

pe_magic() {
  local path=$1 size mz raw offset_hex offset signature
  size=$(stat -c %s -- "$path") || return 1
  ((size >= 68)) || return 1
  mz=$(hex_bytes "$path" 0 2) || return 1
  [[ $mz == 4d5a ]] || return 1
  raw=$(hex_bytes "$path" 60 4) || return 1
  [[ $raw =~ ^[0-9a-f]{8}$ ]] || return 1
  offset_hex=${raw:6:2}${raw:4:2}${raw:2:2}${raw:0:2}
  offset=$((16#$offset_hex))
  ((offset >= 64 && offset <= size - 4)) || return 1
  signature=$(hex_bytes "$path" "$offset" 4) || return 1
  [[ $signature == 50450000 ]]
}

looks_like_svg() {
  LC_ALL=C grep -aEq '<svg([[:space:]>])' -- "$1"
}

normalize_svg() {
  tr '\n\r\t' '   ' < "$1" > "$2"
}

safe_svg() {
  local LC_ALL=C path=$1 validated=$tmp_dir/validated.svg without_nul=$tmp_dir/without-nul.svg
  local normalized=$tmp_dir/normalized.svg markers_file=$tmp_dir/encoding-markers
  local assignments_file=$tmp_dir/encoding-assignments
  local prefix original_size clean_size declaration assignment value grep_status
  local -a encoding_markers=() encoding_assignments=()
  prefix=$(hex_bytes "$path" 0 4) || return 1
  case $prefix in
    efbbbf*|fffe*|feff*|0000feff|2b2f76??|f7644c*|dd736673|0efeff*|fbee28*|84319533)
      return 1
      ;;
  esac
  command -v iconv >/dev/null || return 1
  iconv -f UTF-8 -t UTF-8 -- "$path" > "$validated" || return 1
  tr -d '\000' < "$validated" > "$without_nul" || return 1
  original_size=$(stat -c %s -- "$validated") || return 1
  clean_size=$(stat -c %s -- "$without_nul") || return 1
  ((original_size == clean_size)) || return 1
  normalize_svg "$validated" "$normalized" || return 1
  declaration=$(grep -aEio -m 1 '^[[:space:]]*<\?xml([[:space:]][^?]*)?\?>' -- "$normalized")
  grep_status=$?
  ((grep_status <= 1)) || return 1
  grep -aEio 'encoding[[:space:]]*=' <<< "$declaration" > "$markers_file"
  grep_status=$?
  ((grep_status <= 1)) || return 1
  mapfile -t encoding_markers < "$markers_file"
  if ((${#encoding_markers[@]} > 0)); then
    grep -aEio "encoding[[:space:]]*=[[:space:]]*(\"[^\"]*\"|'[^']*'|[^[:space:]?>]+)" \
      <<< "$declaration" > "$assignments_file"
    grep_status=$?
    ((grep_status <= 1)) || return 1
    mapfile -t encoding_assignments < "$assignments_file"
  fi
  ((${#encoding_markers[@]} == ${#encoding_assignments[@]})) || return 1
  for assignment in "${encoding_assignments[@]}"; do
    value=${assignment#*=}
    value=${value//[[:space:]]/}
    if [[ $value == \"*\" || $value == \'*\' ]]; then
      value=${value:1:${#value}-2}
    fi
    value=${value,,}
    [[ $value == utf-8 || $value == us-ascii ]] || return 1
  done
  looks_like_svg "$normalized" || return 1
  svg_pattern_absent -aEiq \
    '<[^[:space:]/>]*:?(script|foreignobject)([[:space:]/>])' -- "$normalized" || return 1
  svg_pattern_absent -aEiq \
    '<!(doctype|entity)|<\?xml-stylesheet|<[^[:space:]/>]*:?style([[:space:]>])|style[[:space:]]*=|on[a-z]+[[:space:]]*=|url[[:space:]]*\(' \
    -- "$normalized" || return 1
  svg_pattern_absent -aEiq \
    "(^|[^[:alnum:]_.-])([[:alnum:]_.-]+:)?href[[:space:]]*=[[:space:]]*[\"'][[:space:]]*[^#[:space:]]" \
    -- "$normalized"
}

svg_pattern_absent() {
  local status
  LC_ALL=C grep "$@"
  status=$?
  ((status == 1))
}

run_limited() (
  ulimit -f 40960
  ulimit -v 524288
  timeout -k 2 5 "$@"
)

candidate_error=extract
copy_extracted_png() {
  local destination=$1 candidate dimensions width height area best_area=-1 best_candidate=""
  shift
  for candidate in "$@"; do
    [[ -f $candidate && ! -L $candidate ]] || continue
    if png_magic "$candidate"; then
      if dimensions=$(png_dimensions "$candidate") \
        && read -r width height <<< "$dimensions" \
        && ((width > 0 && height > 0 && width <= 1024 && height <= 1024)); then
        area=$((width * height))
        if ((area > best_area)); then
          best_area=$area
          best_candidate=$candidate
        fi
      else
        candidate_error=dimensions
      fi
    fi
  done
  [[ -n $best_candidate ]] || return 1
  cp --no-dereference -- "$best_candidate" "$destination"
}

extract_ico() {
  local source=$1 output=$2 extract_dir=$tmp_dir/ico candidate
  command -v timeout >/dev/null && command -v icotool >/dev/null || return 2
  mkdir -m 700 -- "$extract_dir" || return 1
  run_limited icotool -x -o "$extract_dir" -- "$source" >/dev/null || return 1
  shopt -s nullglob
  local -a candidates=("$extract_dir"/*.png)
  copy_extracted_png "$output" "${candidates[@]}"
}

extract_pe() {
  local source=$1 output=$2 extract_dir=$tmp_dir/pe ico
  command -v timeout >/dev/null && command -v wrestool >/dev/null \
    && command -v icotool >/dev/null || return 2
  mkdir -m 700 -- "$extract_dir" || return 1
  run_limited wrestool -x -t 14 -o "$extract_dir" -- "$source" >/dev/null || return 1
  shopt -s nullglob
  local -a groups=("$extract_dir"/*.ico)
  ((${#groups[@]} > 0)) || return 1
  for ico in "${groups[@]}"; do
    [[ -f $ico && ! -L $ico ]] || continue
    run_limited icotool -x -o "$extract_dir" -- "$ico" >/dev/null || continue
  done
  local -a candidates=("$extract_dir"/*.png)
  copy_extracted_png "$output" "${candidates[@]}"
}

rasterize_svg() {
  local source=$1 output=$2
  safe_svg "$source" || return 3
  command -v timeout >/dev/null && command -v rsvg-convert >/dev/null || return 2
  run_limited rsvg-convert --keep-aspect-ratio --width 1024 --height 1024 \
    -o "$output" "$tmp_dir/validated.svg" >/dev/null || return 1
}

map_json='{}'
read_map() {
  local size
  if [[ -L $map_file ]]; then
    return 1
  elif [[ ! -e $map_file ]]; then
    map_json='{}'
    return 0
  fi
  [[ -f $map_file && -O $map_file ]] || return 1
  size=$(stat -c %s -- "$map_file") || return 1
  ((size <= 20 * 1024 * 1024)) || return 1
  map_json=$(jq -ce --argjson max "$max_icon_entries" \
    'if type == "object" and length <= $max and all(.[]; type == "string") then . else error("map") end' \
    -- "$map_file") || return 1
  chmod 600 -- "$map_file"
}

write_map() {
  local contents=$1 candidate
  candidate=$(mktemp "$state_dir/.pinned-icons.XXXXXX") || return 1
  [[ $candidate == "$state_dir"/.pinned-icons.?????? && -f $candidate \
    && ! -L $candidate && -O $candidate ]] || return 1
  tmp_map=$candidate
  printf '%s\n' "$contents" > "$tmp_map" || return 1
  chmod 600 -- "$tmp_map" || return 1
  mv -fT -- "$tmp_map" "$map_file" || return 1
  tmp_map=""
}

acquire_map_lock() {
  local status
  command -v flock >/dev/null || return 1
  if [[ ! -e $lock_file && ! -L $lock_file ]]; then
    (set -o noclobber; : > "$lock_file") 2>/dev/null || true
  fi
  [[ -f $lock_file && ! -L $lock_file && -O $lock_file ]] || return 1
  chmod 600 -- "$lock_file" || return 1
  exec {lock_fd}<> "$lock_file" || return 1
  flock -x -w "$lock_timeout" "$lock_fd"
  status=$?
  ((status == 0)) && return 0
  ((status == 1)) && return 2
  return 1
}

acquire_map_lock_or_fail() {
  local status
  acquire_map_lock
  status=$?
  ((status != 2)) || fail busy
  ((status == 0)) || fail storage
}

set_icon() {
  local key=$1 source=$2 snapshot output size kind_status hash old_name new_name new_json
  local tmp_parent created_tmp created_icon
  valid_key "$key" || fail key
  [[ -f $source && ! -L $source ]] || fail source
  size=$(stat -c %s -- "$source") || fail source
  ((size <= max_source_size)) || fail size

  tmp_parent=${TMPDIR:-/tmp}
  [[ $tmp_parent == /* ]] || fail temp
  if [[ $tmp_parent != / ]]; then
    tmp_parent=${tmp_parent%/}
  fi
  created_tmp=$(mktemp -d "$tmp_parent/omarchy-taskbar-icon.XXXXXX") || fail temp
  [[ $created_tmp == "$tmp_parent"/omarchy-taskbar-icon.?????? && -d $created_tmp \
    && ! -L $created_tmp && -O $created_tmp ]] || fail temp
  tmp_dir=$created_tmp
  chmod 700 -- "$tmp_dir" || fail temp
  snapshot=$tmp_dir/source
  run_limited head -c "$((max_source_size + 1))" -- "$source" > "$snapshot" || fail source
  [[ -f $snapshot && ! -L $snapshot && -O $snapshot ]] || fail source
  size=$(stat -c %s -- "$snapshot") || fail source
  ((size <= max_source_size)) || fail size
  output=$tmp_dir/output.png

  if png_magic "$snapshot"; then
    valid_png_dimensions "$snapshot" || fail dimensions
    cp --no-dereference -- "$snapshot" "$output" || fail extract
  elif ico_magic "$snapshot"; then
    candidate_error=extract
    extract_ico "$snapshot" "$output"
    kind_status=$?
    ((kind_status != 2)) || fail tool
    ((kind_status == 0)) || fail "$candidate_error"
  elif pe_magic "$snapshot"; then
    candidate_error=extract
    extract_pe "$snapshot" "$output"
    kind_status=$?
    ((kind_status != 2)) || fail tool
    ((kind_status == 0)) || fail "$candidate_error"
  elif normalize_svg "$snapshot" "$tmp_dir/normalized.svg" \
    && looks_like_svg "$tmp_dir/normalized.svg"; then
    rasterize_svg "$snapshot" "$output"
    kind_status=$?
    ((kind_status != 3)) || fail svg
    ((kind_status != 2)) || fail tool
    ((kind_status == 0)) || fail extract
  else
    fail type
  fi
  [[ -f $output && ! -L $output && -O $output ]] || fail extract
  png_magic "$output" || fail extract
  valid_png_dimensions "$output" || fail dimensions
  chmod 600 -- "$output" || fail extract

  [[ $config_home == /* ]] || fail storage
  secure_dir "$state_dir" || fail storage
  secure_dir "$icons_dir" || fail storage
  acquire_map_lock_or_fail
  read_map || fail map
  hash=$(printf '%s' "$key" | sha256sum) || fail storage
  hash=${hash%% *}
  [[ $hash =~ ^[0-9a-f]{64}$ ]] || fail storage
  old_name=$(jq -r --arg key "$key" '.[$key] // ""' <<< "$map_json") || fail map

  created_icon=$(mktemp "$icons_dir/${hash:0:16}-XXXXXX.png") || fail storage
  [[ $created_icon == "$icons_dir"/${hash:0:16}-??????.png && -f $created_icon \
    && ! -L $created_icon && -O $created_icon ]] || fail storage
  new_icon=$created_icon
  cp --no-dereference -- "$output" "$new_icon" || fail storage
  chmod 600 -- "$new_icon" || fail storage
  new_name=${new_icon##*/}
  new_json=$(jq -c --arg key "$key" --arg value "$new_name" --argjson max "$max_icon_entries" \
    'if has($key) or length < $max then .[$key] = $value else error("map") end' \
    <<< "$map_json") || fail map
  write_map "$new_json" || fail map

  if [[ $old_name =~ ^${hash:0:16}-[A-Za-z0-9]{6}\.png$ && $old_name != "$new_name" ]]; then
    rm -f -- "$icons_dir/$old_name"
  fi
  new_icon=""
  release_map_lock || fail storage
  ok
}

remove_generated_entry() {
  local key=$1 entry
  [[ $key =~ ^omarchy-taskbar-[0-9a-f]{16}$ ]] || return 0
  [[ $HOME == /* ]] || return 1
  if [[ -d $private_applications && ! -L $private_applications && -O $private_applications ]]; then
    entry=$private_applications/${key#omarchy-taskbar-}.desktop
    rm -f -- "$entry"
  fi
}

reset_icon() {
  local key=$1 remove_entry=${2:-false} hash old_name new_json
  valid_key "$key" || fail key
  if [[ ! -e $state_dir && ! -L $state_dir ]]; then
    [[ $remove_entry == true ]] || ok
    secure_dir "$state_dir" || fail storage
  else
    secure_existing_dir "$state_dir" || fail storage
  fi
  acquire_map_lock_or_fail
  if [[ -L $icons_dir ]]; then
    fail storage
  elif [[ -e $icons_dir ]]; then
    secure_existing_dir "$icons_dir" || fail storage
  fi
  read_map || fail map
  if [[ -e $map_file ]]; then
    hash=$(printf '%s' "$key" | sha256sum) || fail storage
    hash=${hash%% *}
    [[ $hash =~ ^[0-9a-f]{64}$ ]] || fail storage
    old_name=$(jq -r --arg key "$key" '.[$key] // ""' <<< "$map_json") || fail map
    if [[ -n $old_name ]]; then
      new_json=$(jq -c --arg key "$key" 'del(.[$key])' <<< "$map_json") || fail map
      write_map "$new_json" || fail map
      if [[ -d $icons_dir && $old_name =~ ^${hash:0:16}-[A-Za-z0-9]{6}\.png$ ]]; then
        rm -f -- "$icons_dir/$old_name"
      fi
    fi
  fi
  [[ $remove_entry != true ]] || remove_generated_entry "$key" || fail storage
  release_map_lock || fail storage
  ok
}

case ${1:-} in
  set)
    [[ $# == 3 ]] || fail usage
    set_icon "$2" "$3"
    ;;
  reset)
    [[ $# == 2 ]] || fail usage
    reset_icon "$2"
    ;;
  remove)
    [[ $# == 2 ]] || fail usage
    reset_icon "$2" true
    ;;
  *) fail usage ;;
esac
