#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Run the kernel's checkpatch.pl over the out-of-tree module sources.
#
# Usage: tools/ci/checkpatch.sh [substantive|full]
#   substantive (default): blocking gate. Ignores the pure-style types listed
#     below (the code base uses 4-space indentation and packed statements) and
#     the intentional out-of-tree/shared-header exceptions. Fails on any hit.
#   full: advisory report of every checkpatch type; always prints a summary.
#
# Environment: KDIR (kernel build tree with scripts/checkpatch.pl); default is
# the running kernel's build directory. Rationale per type:
# docs/STATIC_ANALYSIS.md ("checkpatch type exclusions").
set -eu

mode=${1:-substantive}
kdir=${KDIR:-/lib/modules/$(uname -r)/build}
checkpatch="$kdir/scripts/checkpatch.pl"
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$root"

# Pure formatting types (4-space indentation, `a=b;c=d;`, one-line `if (x) y;`).
STYLE_TYPES="SPACING LEADING_SPACE CODE_INDENT TRAILING_STATEMENTS LINE_SPACING
SUSPECT_CODE_INDENT BLOCK_COMMENT_STYLE OPEN_BRACE ELSE_AFTER_BRACE
FUNCTION_ARGUMENTS LONG_LINE"
# Intentional: multi-kernel LINUX_VERSION_CODE checks, root-only 0400 sysfs
# diagnostics, ARRAY_SIZE-free headers shared with userspace tests, SPDX tags
# on tests/generated files.
INTENTIONAL_TYPES="LINUX_VERSION_CODE CONSTANT_COMPARISON DEVICE_ATTR_PERMS
ARRAY_SIZE SPDX_LICENSE_TAG"

ignore=$(echo $STYLE_TYPES $INTENTIONAL_TYPES | tr ' ' ',')
files="source/zenbook_healthytable.c $(ls source/healthytable_*.h)"

if [ ! -f "$checkpatch" ]; then
    echo "checkpatch.pl not found under KDIR=$kdir" >&2
    exit 2
fi

case $mode in
substantive)
    out=$(perl "$checkpatch" --no-tree -f --terse --show-types --no-summary \
        --ignore "$ignore" $files || true)
    if [ -n "$out" ]; then
        printf '%s\n' "$out"
        echo "checkpatch: substantive findings (style types ignored: $ignore)" >&2
        exit 1
    fi
    echo "checkpatch: no substantive findings"
    ;;
full)
    report=$(mktemp)
    trap 'rm -f "$report"' EXIT
    perl "$checkpatch" --no-tree -f --terse --show-types --no-summary $files \
        >"$report" || true
    echo "checkpatch full: $(wc -l <"$report") findings by type:"
    sed -n 's/^[^:]*:[0-9]*: \(ERROR\|WARNING\|CHECK\):\([A-Z_0-9]*\):.*/\1:\2/p' \
        "$report" | sort | uniq -c | sort -rn
    ;;
*)
    echo "usage: $0 [substantive|full]" >&2
    exit 2
    ;;
esac
