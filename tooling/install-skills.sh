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

sync_dir() {
  local name="$1"
  local src="$source_dir/$name"
  local dst="$target_dir/$name"
  local mode

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

  mkdir -p "$target_dir"
  case "$mode" in
    install)
      rsync -a "$src/" "$dst/"
      printf 'Installed %s -> %s\n' "$name" "$dst"
      ;;
    skip)
      printf 'Skipped existing %s at %s\n' "$name" "$dst"
      ;;
    merge)
      rsync -a --ignore-existing "$src/" "$dst/"
      printf 'Merged missing files for %s -> %s\n' "$name" "$dst"
      ;;
    replace)
      rsync -a --delete "$src/" "$dst/"
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
need_command rsync

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

if [ -d "$source_dir/_shared-project-ops" ]; then
  sync_dir "_shared-project-ops"
fi

for skill in "${skills[@]}"; do
  [ "$skill" != "_shared-project-ops" ] || continue
  sync_dir "$skill"
done
