#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Run the parser fuzz/property tests when they exist. The module is optional:
# when test_fuzz_parsers.py is absent the step reports a skip and succeeds.
# When present, any failure (or import error) fails the job.
#
# Usage: tools/ci/run-fuzz-parsers.sh
# Environment: PYTHON (default: python3).
set -eu

python=${PYTHON:-python3}
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$root"

if [ ! -f test_fuzz_parsers.py ]; then
    echo "::notice::test_fuzz_parsers.py not present; parser fuzz tests skipped"
    exit 0
fi
exec "$python" -m unittest -q test_fuzz_parsers
