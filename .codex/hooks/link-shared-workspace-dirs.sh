#!/usr/bin/env bash
# Link a zmk-workspace Git worktree to the main checkout's local West state.
set -euo pipefail

workspace_root="$(git rev-parse --show-toplevel)"
main_worktree="$({ git -C "$workspace_root" worktree list --porcelain | sed -n 's/^worktree //p' | head -n 1; })"

if [[ -z "$main_worktree" ]]; then
    echo "could not determine this repository's main worktree" >&2
    exit 1
fi

main_worktree="$(realpath "$main_worktree")"
workspace_root="$(realpath "$workspace_root")"

if [[ "$workspace_root" == "$main_worktree" ]]; then
    exit 0
fi

for shared_dir in projects ws; do
    source_path="$main_worktree/$shared_dir"
    destination_path="$workspace_root/$shared_dir"

    if [[ ! -d "$source_path" ]]; then
        echo "shared directory is missing: $source_path" >&2
        exit 1
    fi

    if [[ -L "$destination_path" ]]; then
        if [[ "$(realpath "$destination_path")" == "$(realpath "$source_path")" ]]; then
            continue
        fi
        echo "refusing to replace symlink with a different target: $destination_path" >&2
        exit 1
    fi

    if [[ -e "$destination_path" ]]; then
        echo "refusing to replace existing path: $destination_path" >&2
        exit 1
    fi

    ln -s "$source_path" "$destination_path"
done
