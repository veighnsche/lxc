# Phase 4: Cleanup

## Dead Code Removal (Rule 6)

After migration, verify and remove:
- [ ] No duplicate class definitions
- [ ] No commented-out code blocks
- [ ] No unused imports in any module

## Temporary Adapter Removal

None expected - this is a pure extraction refactor.

## Encapsulation Tightening

Review each module for:
- Private methods that should have `_` prefix
- Unnecessary exports in `__init__.py`

## File Size Check (Rule 7)

| Module | Target | Status |
|--------|--------|--------|
| `config.py` | ~140 lines | TBD |
| `console.py` | ~50 lines | ✓ DONE |
| `adb.py` | ~270 lines | TBD |
| `lxc.py` | ~110 lines | TBD |
| `download.py` | ~80 lines | TBD |
| `deployer.py` | ~1150 lines | TBD (over 500 but acceptable) |
| `deploy.py` (CLI) | ~100 lines | TBD |

---

## Step 1: Remove dead code

Scan for:
- Unused imports
- Commented code blocks
- Orphaned helper functions

---

## Step 2: Verify no duplicate definitions

Ensure classes only exist in one place.

---

## Step 3: Final import cleanup

Each module should have minimal, sorted imports.

---

## Exit Criteria for Phase 4

- [ ] No dead code
- [ ] No duplicates
- [ ] All modules have clean imports
- [ ] Total lines across all modules ≤ original deploy.py (no bloat)
