#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  build_zmk_config.sh [--repo URL] [--config-dir DIR] [--workdir DIR]
                      [--nix-flake DIR] [--manifest FILE]
                      [--build-dir DIR] [--skip-update] [--skip-build]
                      [--] [extra west zmk-build args...]

Defaults:
  --workdir    .work
  --nix-flake  ../../../nix, relative to this script
  --build-dir  ./build

The script implements the clone-root layout:
  cd <zmk-config>
  west init -l config --mf west-isolated.yml
  west update --narrow
  west zephyr-export
  west zmk-build -d ./build -q
EOF
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../../.." && pwd)"

repo_url=""
config_dir=""
workdir=".work"
nix_flake="$repo_root/nix"
manifest=""
build_dir="./build"
skip_update=0
skip_build=0
extra_args=()

while (($#)); do
  case "$1" in
    --repo)
      repo_url="${2:?missing value for --repo}"
      shift 2
      ;;
    --config-dir)
      config_dir="${2:?missing value for --config-dir}"
      shift 2
      ;;
    --workdir)
      workdir="${2:?missing value for --workdir}"
      shift 2
      ;;
    --nix-flake)
      nix_flake="${2:?missing value for --nix-flake}"
      shift 2
      ;;
    --manifest)
      manifest="${2:?missing value for --manifest}"
      shift 2
      ;;
    --build-dir)
      build_dir="${2:?missing value for --build-dir}"
      shift 2
      ;;
    --skip-update)
      skip_update=1
      shift
      ;;
    --skip-build)
      skip_build=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      extra_args=("$@")
      break
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$config_dir" && -z "$repo_url" ]]; then
  config_dir="$PWD"
fi

if [[ -n "$repo_url" ]]; then
  mkdir -p "$workdir"
  name="$(basename "$repo_url")"
  name="${name%.git}"
  config_dir="${config_dir:-$workdir/$name}"
  if [[ ! -d "$config_dir/.git" ]]; then
    git clone "$repo_url" "$config_dir"
  fi
fi

config_dir="$(cd -- "$config_dir" && pwd)"
nix_flake="$(cd -- "$nix_flake" && pwd)"

inner="$(mktemp)"
trap 'rm -f "$inner"' EXIT

cat >"$inner" <<'INNER'
#!/usr/bin/env bash
set -euo pipefail

config_dir="$1"
manifest="$2"
build_dir="$3"
skip_update="$4"
skip_build="$5"
shift 5

cd "$config_dir"

if [[ ! -d .west ]]; then
  if [[ -n "$manifest" ]]; then
    manifest_dir="$(dirname "$manifest")"
    manifest_file="$(basename "$manifest")"
    west init -l "$manifest_dir" --mf "$manifest_file"
  elif [[ -f config/west-isolated.yml ]]; then
    west init -l config --mf west-isolated.yml
  elif [[ -f config/west.yml ]]; then
    west init -l config
  else
    echo "Could not find a clone-root manifest. Expected config/west-isolated.yml or config/west.yml." >&2
    exit 3
  fi
fi

topdir="$(west topdir)"
if [[ "$topdir" != "$config_dir" ]]; then
  echo "Refusing to build: west topdir is '$topdir', expected '$config_dir'." >&2
  exit 4
fi

if [[ "$skip_update" != 1 ]]; then
  west update --narrow
  west zephyr-export
fi

if [[ "$skip_build" != 1 ]]; then
  west zmk-build -d "$build_dir" -q "$@"
fi
INNER
chmod +x "$inner"

nix --extra-experimental-features 'nix-command flakes' \
  develop "$nix_flake" \
  --command bash "$inner" \
  "$config_dir" "$manifest" "$build_dir" "$skip_update" "$skip_build" "${extra_args[@]}"
