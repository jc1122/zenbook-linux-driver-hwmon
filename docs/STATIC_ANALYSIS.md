<!-- SPDX-License-Identifier: GPL-2.0-only -->
# Static analysis: gates, baselines and suppressions

The CI workflow (`.github/workflows/check.yml`) runs static analysis in two
tiers:

- **Blocking** gates were clean on the code when they were introduced, so they
  catch regressions only. A new finding fails the job.
- **Advisory** gates (`continue-on-error`) track known backlogs that are style
  or cleanup, not correctness. They report but never fail the build.

Every suppression or baseline entry below is either a reviewed false positive
or an accepted test pattern. A new suppression needs the same kind of written
justification, next to the entry and here.

## Kernel module (`source/`)

| Gate | Tier | Notes |
|---|---|---|
| Kbuild `W=1 KCFLAGS=-Werror` | blocking | `W=2` was also clean at baseline time |
| sparse `C=2` (pinned upstream revision) | blocking | default checks (address spaces, endianness, locking context) are clean. `-Wsparse-all` adds only noise: `= {0}` "missing braces", a `MODULE_IMPORT_NS()` macro mismatch, and `sizeof(void)` inside the fortify `strlen()` macro |
| gcc `-fanalyzer` | blocking | `-Wno-analyzer-too-complex` only |
| checkpatch, substantive types | blocking | `tools/ci/checkpatch.sh substantive` |
| checkpatch, all types | advisory | style backlog |

cppcheck cannot preprocess the kernel file without kernel include paths, so
sparse and gcc `-fanalyzer` cover it instead.

### checkpatch type exclusions

The code base uses 4-space indentation and packed statements (`a=b;c=d;`,
one-line `if (x) y;`). About 99.7% of checkpatch output is therefore pure
formatting. The blocking run ignores these style types:

`SPACING`, `LEADING_SPACE`, `CODE_INDENT`, `TRAILING_STATEMENTS`,
`LINE_SPACING`, `SUSPECT_CODE_INDENT`, `BLOCK_COMMENT_STYLE`, `OPEN_BRACE`,
`ELSE_AFTER_BRACE`, `FUNCTION_ARGUMENTS`, `LONG_LINE`.

Every `SUSPECT_CODE_INDENT` site in the module and shared headers was reviewed
individually: all are artifacts of 4-space indentation inside 8-column tabs and
none hides control flow. One-line bodies were checked for hidden
multi-statement bodies, and gcc `-Wmisleading-indentation` is clean.

These types are intentional for this project and are also ignored:

- `LINUX_VERSION_CODE`, `CONSTANT_COMPARISON`: out-of-tree multi-kernel
  compatibility checks.
- `DEVICE_ATTR_PERMS`: mode `0400` on root-only privileged diagnostics is
  deliberate (see `docs/THREAT_MODEL.md`).
- `ARRAY_SIZE`: the `healthytable_*.h` headers are shared with userspace test
  harnesses, which have no `ARRAY_SIZE`.
- `SPDX_LICENSE_TAG`: placement on test files and the generated `.mod.c`.

At baseline, checkpatch found no substantive issue (no unchecked
`kstrto*`/`copy_*`, no deprecated API, no `sprintf` into sysfs; the module uses
`sysfs_emit_at`).

## Userspace C (`lib/`, `source/*_test.c`)

| Gate | Tier | Notes |
|---|---|---|
| cppcheck `--enable=warning,portability` | blocking | suppressions in `tools/ci/cppcheck-suppressions.txt` |
| gcc `-fanalyzer` on the library | blocking | `-Wno-analyzer-fd-leak`, see below |
| clang `--analyze` (`tools/ci/clang-analyze.sh`) | advisory | |
| ASan/UBSan test builds | blocking | part of `make check` |

Reviewed false positives:

- cppcheck `assertWithSideEffect` in `source/*_test.c`: the protocol tests call
  the code under test inside `assert()` on purpose.
- cppcheck `legacyUninitvar` in `healthytable_diagnostics.h`: `index` and
  `mode` are read only after `ht_read()` returns 0, and a successful transfer
  always writes the answer.
- cppcheck `nullPointerArithmeticOutOfMemory` in `lib/asus_healthytable.c`: on
  ENOMEM the read loop is skipped, so `buffer+used` is never formed.
- gcc `-fanalyzer` fd leak in `lib/asus_healthytable.c`: every `goto fail`
  follows a successful `pipe2()`, and the `fail:` path closes both ends.
- clang analyzer in `lib/asus_healthytable.c`: `NullDereference` on the ENOMEM
  path (the function returns before the dereference whenever the buffer is
  NULL) and `DeadStores` on an intentional defensive reset of a closed fd.

## Python

| Gate | Tier | Notes |
|---|---|---|
| ruff, `tools/ci/ruff.toml` | blocking | correctness and security rules only; the rule list is in the file |
| ruff, `tools/ci/ruff-advisory.toml` (`E9,F,B,S`) | advisory | cleanup backlog |
| bandit Medium+ with `tools/ci/bandit-baseline.json` | blocking | tests excluded |
| mypy `--ignore-missing-imports` | advisory | modules are not type-annotated yet |

Advisory-profile ignores:

- `S603`, `S404`: every subprocess call uses a fixed argv list and none uses
  `shell=True`.
- `B023`: the loop-variable closures are called synchronously inside the same
  iteration.

Rules to promote from the advisory to the blocking profile once their backlog
is fixed: `F401` (check intentional re-exports first), `B904`, `B905`, `S101`
and `S607`.

The bandit baseline holds one entry: `B314` in `wwan.py`. It parses
ModemManager introspection XML from the trusted system bus and rejects any
`DOCTYPE`/`ENTITY` declaration before parsing.

## Not run

smatch and clang scan-build are not part of CI. smatch needs OpenSSL
development headers in the build image; a clang/LLVM kernel build job may be
added later.
