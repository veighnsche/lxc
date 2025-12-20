# Phase 3: Migration

## Migration Strategy

After all modules are extracted, `deploy.py` becomes a thin CLI wrapper that:
1. Imports from `deployer/`
2. Defines the typer CLI app
3. Routes commands to `Deployer` methods

## Call Site Inventory

### In deploy.py (lines 1815-1908)
- `Config()` instantiation
- `ADB(serial)` instantiation
- `Deployer(cfg, adb)` instantiation
- All CLI routing

### External callers
None known - `deploy.py` is the entry point.

## Rollback Plan

Keep original `deploy.py` as `deploy.py.bak` until verification passes.

---

## Step 1: Update deploy.py to import from deployer/

**Before:**
```python
# All classes defined inline
@dataclass
class Config: ...
class DeviceShell: ...
class ADB: ...
# etc.
```

**After:**
```python
#!/usr/bin/env python3
"""deploy.py - CLI entry point for Gentoo LXC deployment."""

from deployer import (
    Config, ADB, Deployer,
    console, log, log_ok, log_warn, log_err, die, step_header
)
from deployer.console import typer
from rich.panel import Panel

app = typer.Typer(
    help="Deploy Gentoo Linux in LXC on Android (ARM64)",
    no_args_is_help=False,
    add_completion=False,
)

# ... CLI commands unchanged ...
```

**UoW:** `phase-3-step-1-uow-1.md`

---

## Step 2: Verify CLI functionality

Test all commands:
```bash
python3 deploy.py --help
python3 deploy.py --status
# Don't run --clean or actual deploy without device
```

---

## Step 3: Remove dead code from deploy.py

After imports work, delete all class definitions from deploy.py, leaving only:
- Imports
- CLI app definition
- CLI command functions

**Target:** deploy.py should be ~100 lines (was 1908).

---

## Exit Criteria for Phase 3

- [ ] `python3 deploy.py --help` works
- [ ] `python3 deploy.py --status` works (if device connected)
- [ ] `deploy.py` is < 150 lines
- [ ] All imports come from `deployer/`
