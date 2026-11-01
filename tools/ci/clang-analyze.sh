#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Clang static analyzer over the userspace C library and the protocol test
# harnesses (which compile every source/healthytable_*.h shared with the
# kernel module). Advisory: CI runs it with continue-on-error.
#
# Usage: tools/ci/clang-analyze.sh
# Environment: CLANG (default: clang). Exit status is 1 when the analyzer
# reports any warning, 2 when a file does not compile.
#
# Known reviewed false positives on lib/asus_healthytable.c (NullDereference on
# the ENOMEM path, DeadStores on a defensive reset) are listed in
# docs/STATIC_ANALYSIS.md ("Userspace C").
set -eu

clang=${CLANG:-clang}
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$root"

"$clang" --version | head -n 1
log=$(mktemp)
trap 'rm -f "$log"' EXIT
status=0
for f in lib/asus_healthytable.c source/*_test.c; do
    if ! "$clang" --analyze -std=c11 -Iinclude -Isource -DASUS_HT_BRIDGE='"/x"' \
        -Xanalyzer -analyzer-output=text -o /dev/null "$f" >>"$log" 2>&1; then
        echo "::error file=$f::clang --analyze failed to compile"
        status=2
    fi
done
cat "$log"
warnings=$(grep -c ': warning:' "$log" || true)
echo "clang analyzer warnings: $warnings"
if [ "$status" -eq 0 ] && [ "$warnings" -gt 0 ]; then status=1; fi
exit "$status"
