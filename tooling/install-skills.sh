#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Install canonical skills from this repository for Codex or Claude Code.

Usage:
  tooling/install-skills.sh --list
  tooling/install-skills.sh --all [--client codex|claude-code] [--target DIR] [--dry-run] [--skip-existing|--merge-existing|--replace-existing]
  tooling/install-skills.sh --skill NAME [--skill NAME ...] [--client codex|claude-code] [--target DIR] [--dry-run] [--skip-existing|--merge-existing|--replace-existing]

Options:
  --all              Install all canonical skills.
  --skill NAME       Install one skill. Can be repeated.
  --client NAME      Agent client: codex (default) or claude-code. Sets the default target:
                     codex -> ${CODEX_HOME:-$HOME/.codex}/skills; claude-code -> ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills.
  --target DIR       Destination skills directory. Overrides the client default.
  --source DIR       Source skills directory. Defaults to <repo>/skills.
  --dry-run          Print actions without writing files.
  --skip-existing    Skip skills that already exist at the target.
  --merge-existing   Copy only missing files into existing target skills.
  --replace-existing Replace existing target skills with the canonical copy.
  --list             List installable skills.
  -h, --help         Show this help.

The shared _shared-project-ops bundle is installed automatically when present.
Existing target skills are never overwritten unless you choose merge or replace.
Interactive runs prompt on conflicts. Non-interactive runs skip conflicts by default.
EOF
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
source_dir="$repo_root/skills"
client="codex"
target_dir=""
dry_run=0
install_all=0
list_only=0
existing_mode="prompt"
skills=()

die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

need_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

# Remove redundant separators and dot components without resolving symlinks.
# Parent components retain their filesystem meaning until physical_path checks.
normalize_path() {
  local path="$1" part result="" remainder
  case "$path" in /*) ;; *) path="$PWD/$path" ;; esac
  remainder="$path/"
  while [ -n "$remainder" ]; do
    part="${remainder%%/*}"
    remainder="${remainder#*/}"
    case "$part" in ""|.) continue ;; esac
    result="$result/$part"
  done
  printf '%s\n' "${result:-/}"
}

# Resolve existing ancestors physically, appending missing directory components.
# No directory is created while checking source/destination containment.
physical_path() {
  local path="$1" parent leaf
  if [ -d "$path" ]; then
    (cd "$path" && pwd -P)
  else
    parent="${path%/*}"
    leaf="${path##*/}"
    [ -n "$parent" ] || parent=/
    parent="$(physical_path "$parent")" || return
    if [ "$leaf" = ".." ]; then
      parent="${parent%/*}"
      printf '%s\n' "${parent:-/}"
    else
      printf '%s/%s\n' "${parent%/}" "$leaf"
    fi
  fi
}

# Stage beside the destination so both renames stay on the same filesystem.
# Keep the original recoverable until the staged copy has been installed.
replace_without_rsync() (
  local src="$1" dst="$2" staging committed=0
  staging="$(mktemp -d "${dst%/*}/.${dst##*/}.replace.XXXXXXXX")" || return

  cleanup_replacement() {
    local status=$?
    trap - EXIT HUP INT TERM
    if [ "$committed" -eq 0 ] && [ -d "$staging/original" ]; then
      # Never overwrite a destination created while the operation was interrupted.
      if [ -e "$dst" ] || [ -L "$dst" ] || ! mv "$staging/original" "$dst"; then
        printf 'ERROR: replacement failed; original skill preserved at %s\n' "$staging/original" >&2
        exit 1
      fi
    fi
    if ! rm -rf "$staging"; then
      printf 'ERROR: cannot clean replacement staging directory: %s\n' "$staging" >&2
      exit 1
    fi
    exit "$status"
  }

  trap cleanup_replacement EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM

  mkdir "$staging/replacement" || exit $?
  cp -pR "$src/." "$staging/replacement/" || exit $?
  mv "$dst" "$staging/original" || exit $?
  mv "$staging/replacement" "$dst" || exit $?
  committed=1
)

# Copy a skill directory with rsync when it is installed, and with cp and find
# otherwise, as in minimal containers and CI images. Modes match rsync -a:
# install copies everything, merge copies only missing files, replace makes
# dst an exact copy of src.
copy_tree() {
  local mode="$1"
  local src="$2"
  local dst="$3"

  if command -v rsync >/dev/null 2>&1; then
    case "$mode" in
      install) rsync -a "$src/" "$dst/" ;;
      merge) rsync -a --ignore-existing "$src/" "$dst/" ;;
      replace) rsync -a --delete "$src/" "$dst/" ;;
    esac
    return
  fi

  case "$mode" in
    install)
      mkdir -p "$dst"
      cp -pR "$src/." "$dst/"
      ;;
    merge)
      (cd "$src" && find . -type d) | while IFS= read -r dir; do
        mkdir -p "$dst/$dir"
      done
      (cd "$src" && find . ! -type d) | while IFS= read -r file; do
        if [ ! -e "$dst/$file" ] && [ ! -L "$dst/$file" ]; then
          cp -pR "$src/$file" "$dst/$file"
        fi
      done
      ;;
    replace)
      replace_without_rsync "$src" "$dst"
      ;;
  esac
}

list_skills() {
  find "$source_dir" -mindepth 2 -maxdepth 2 -name SKILL.md -print |
    sed "s#^$source_dir/##; s#/SKILL.md\$##" |
    sort
}

choose_existing_mode() {
  local name="$1"
  local dst="$2"
  local choice

  case "$existing_mode" in
    skip|merge|replace)
      printf '%s\n' "$existing_mode"
      return
      ;;
    prompt)
      ;;
    *)
      die "invalid existing skill mode: $existing_mode"
      ;;
  esac

  if [ ! -t 0 ]; then
    printf 'Skipping %s because %s already exists and stdin is not interactive. Use --merge-existing or --replace-existing to change this.\n' "$name" "$dst" >&2
    printf 'skip\n'
    return
  fi

  while true; do
    printf 'Skill "%s" already exists at %s.\n' "$name" "$dst" >&2
    printf 'Choose: [s]kip, [m]erge missing files only, [r]eplace canonical copy: ' >&2
    read -r choice
    case "$choice" in
      s|S|skip|Skip)
        printf 'skip\n'
        return
        ;;
      m|M|merge|Merge)
        printf 'merge\n'
        return
        ;;
      r|R|replace|Replace)
        printf 'replace\n'
        return
        ;;
      *)
        printf 'Please enter s, m, or r.\n' >&2
        ;;
    esac
  done
}

# A skill name is one directory name. Anything else (an empty name, ".", "..",
# or a path with "/") would point src or dst outside the skills directories,
# and --replace-existing deletes files in dst that the source does not have.
validate_skill_name() {
  case "$1" in
    ''|.|..|*/*)
      die "invalid skill name: '$1' (expected a single directory name; see --list)"
      ;;
  esac
}

sync_dir() {
  local name="$1"
  local src="$source_dir/$name"
  local dst="$target_dir/$name"
  local mode

  validate_skill_name "$name"
  [ -d "$src" ] || die "skill not found: $name"
  if [ "$name" != "_shared-project-ops" ]; then
    [ -f "$src/SKILL.md" ] || die "missing SKILL.md for skill: $name"
  fi

  if [ -e "$dst" ] && [ ! -d "$dst" ]; then
    die "target exists but is not a directory: $dst"
  fi

  if [ -d "$dst" ]; then
    mode="$(choose_existing_mode "$name" "$dst")"
  else
    mode="install"
  fi

  if [ "$dry_run" -eq 1 ]; then
    case "$mode" in
      install) printf 'Would install %s -> %s\n' "$src" "$dst" ;;
      skip) printf 'Would skip existing %s at %s\n' "$name" "$dst" ;;
      merge) printf 'Would merge missing files from %s -> %s\n' "$src" "$dst" ;;
      replace) printf 'Would replace %s with %s\n' "$dst" "$src" ;;
    esac
    return
  fi

  # Reject pre-existing links before either backend can traverse destination
  # directories. Include dangling links; find does not follow directory links.
  # Skipping an existing skill remains a read-only operation.
  if [ "$mode" != "skip" ]; then
    [ ! -L "${target_dir%/}" ] || die "target is a symlink: $target_dir"
    [ ! -L "$dst" ] || die "skill destination is a symlink: $dst"
    if [ -d "$dst" ]; then
      local destination_links
      destination_links="$(find "$dst" -type l -print)" || die "cannot inspect destination: $dst"
      [ -z "$destination_links" ] || die "skill destination contains a symlink: $dst"
    fi
  fi

  mkdir -p "$target_dir"
  case "$mode" in
    install)
      copy_tree install "$src" "$dst"
      printf 'Installed %s -> %s\n' "$name" "$dst"
      ;;
    skip)
      printf 'Skipped existing %s at %s\n' "$name" "$dst"
      ;;
    merge)
      copy_tree merge "$src" "$dst"
      printf 'Merged missing files for %s -> %s\n' "$name" "$dst"
      ;;
    replace)
      copy_tree replace "$src" "$dst"
      printf 'Replaced %s -> %s\n' "$name" "$dst"
      ;;
    *)
      die "invalid sync mode: $mode"
      ;;
  esac
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --all)
      install_all=1
      shift
      ;;
    --skill)
      [ "$#" -ge 2 ] || die "--skill requires a value"
      skills+=("$2")
      shift 2
      ;;
    --client)
      [ "$#" -ge 2 ] || die "--client requires a value"
      client="$2"
      shift 2
      ;;
    --target)
      [ "$#" -ge 2 ] || die "--target requires a value"
      target_dir="$2"
      shift 2
      ;;
    --source)
      [ "$#" -ge 2 ] || die "--source requires a value"
      source_dir="$2"
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    --skip-existing)
      existing_mode="skip"
      shift
      ;;
    --merge-existing)
      existing_mode="merge"
      shift
      ;;
    --replace-existing)
      existing_mode="replace"
      shift
      ;;
    --list)
      list_only=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

case "$client" in
  codex) default_target="${CODEX_HOME:-$HOME/.codex}/skills" ;;
  claude-code) default_target="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills" ;;
  *) die "unknown client: $client (expected codex or claude-code)" ;;
esac
[ -n "$target_dir" ] || target_dir="$default_target"

need_command find

[ -d "$source_dir" ] || die "source skills directory not found: $source_dir"

if [ "$list_only" -eq 1 ]; then
  list_skills
  exit 0
fi

if [ "$install_all" -eq 1 ] && [ "${#skills[@]}" -gt 0 ]; then
  die "use either --all or --skill, not both"
fi

if [ "$install_all" -eq 0 ] && [ "${#skills[@]}" -eq 0 ]; then
  usage
  die "choose --all, --skill, or --list"
fi

if [ "$install_all" -eq 1 ]; then
  while IFS= read -r skill; do
    skills+=("$skill")
  done < <(list_skills)
fi

for skill in "${skills[@]}"; do
  validate_skill_name "$skill"
done

# Check the complete roots before even installing the shared bundle.
target_dir="$(normalize_path "$target_dir")"
[ ! -L "$target_dir" ] || die "target is a symlink: $target_dir"
source_path="$(physical_path "$(normalize_path "$source_dir")")" || die "cannot resolve source"
target_path="$(physical_path "$target_dir")" || die "cannot resolve target"
case "${target_path%/}/" in "${source_path%/}/"*) die "source and target overlap" ;; esac
case "${source_path%/}/" in "${target_path%/}/"*) die "source and target overlap" ;; esac

if [ -d "$source_dir/_shared-project-ops" ]; then
  sync_dir "_shared-project-ops"
fi

for skill in "${skills[@]}"; do
  [ "$skill" != "_shared-project-ops" ] || continue
  sync_dir "$skill"
done
