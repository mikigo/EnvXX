#!/usr/bin/env bash
# Tag a release from the version the package declares.
#
# The version lives in one place, envxx/__init__.py, because a frozen binary
# has no package metadata to read. A tag is a second copy of the same number,
# and two copies drift: bumping one and forgetting the other ships a release
# whose assets say 1.6.0 while `envxx --version` says 1.5.0. Reading the tag
# off the code removes the chance to get it wrong by hand.
#
#   scripts/release.sh            # tag the current __version__
#   scripts/release.sh --dry-run  # show what would happen
#   scripts/release.sh --push     # tag, then push the commit and the tag
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

dry_run=0
push=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) dry_run=1 ;;
        --push) push=1 ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

python="${PYTHON:-python3}"
command -v "$python" >/dev/null || {
    echo "no interpreter found; set PYTHON=/path/to/python" >&2
    exit 1
}

# Windows ships a 'python3' stub that exits without printing, so an empty
# result means the interpreter did not really run.
version="$("$python" -c 'import envxx; print(envxx.__version__)' 2>/dev/null || true)"
if [ -z "$version" ]; then
    echo "$python could not import envxx; set PYTHON to a real interpreter" >&2
    exit 1
fi
tag="v$version"

if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    echo "tag $tag already exists" >&2
    echo "bump envxx/__init__.py before tagging again" >&2
    exit 1
fi

# An uncommitted change would be left out of the release the tag points at.
if [ -n "$(git status --porcelain)" ]; then
    echo "working tree is not clean; commit first" >&2
    git status --short >&2
    exit 1
fi

echo "version $version -> tag $tag"

if [ "$dry_run" = 1 ]; then
    echo "(dry run: not tagging)"
    exit 0
fi

git tag -a "$tag" -m "$tag"
echo "tagged $tag"

if [ "$push" = 1 ]; then
    git push origin "$(git rev-parse --abbrev-ref HEAD)"
    git push origin "$tag"
    echo "pushed; the release workflow runs on tag pushes"
else
    echo "next: git push origin HEAD && git push origin $tag"
fi
