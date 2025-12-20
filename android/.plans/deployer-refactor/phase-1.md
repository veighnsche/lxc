# Phase 1: Discovery and Safeguards

## Refactor Summary

**Goal:** Split `deploy.py` (1908 lines) into modular `deployer/` package.

**Pain Points:**
- Monolithic file with 8+ distinct responsibilities
- Hard to test individual components
- Difficult to navigate and maintain

**Success Criteria:**
- All functionality preserved (behavioral equivalence)
- Each module < 500 lines
- Clear separation of concerns
- `deploy.py` becomes thin CLI wrapper

## Behavioral Contracts

### Public Interface (CLI)
```bash
python3 deploy.py              # Full deployment (steps 1-6)
python3 deploy.py --step N     # Run specific step (1-6)
python3 deploy.py --clean      # Clean everything
python3 deploy.py --status     # Check current status
python3 deploy.py --network    # Setup bridge network
python3 deploy.py --serial X   # Target specific device
```

### Module Boundaries (from existing __init__.py)
| Module | Exports | Lines in deploy.py |
|--------|---------|-------------------|
| `config.py` | Config, GentooConfig, DevicePaths, NetworkConfig, ResourceConfig | 86-226 |
| `console.py` | console, log, log_ok, log_warn, log_err, die, step_header | 43-79 ✓ DONE |
| `adb.py` | ADB, DeviceShell | 228-494 |
| `lxc.py` | LXC | 496-599 |
| `download.py` | Downloader, Crypto | 601-678 |
| `deployer.py` | Deployer | 680-1813 |

## Golden/Regression Tests

**No formal test suite exists.** Behavioral verification is:
1. `python3 deploy.py --status` runs without error
2. Import succeeds: `from deployer import Config, ADB, LXC, Deployer`
3. All CLI commands remain functional

## Current Architecture

```
deploy.py
├── Imports & dependency check (1-41)
├── Console & CLI setup (43-79)
├── Configuration dataclasses (82-226)
│   ├── GentooConfig
│   ├── DevicePaths
│   ├── NetworkConfig
│   ├── ResourceConfig
│   └── Config (main)
├── DeviceShell class (228-388)
├── ADB class (390-494)
├── LXC class (496-599)
├── Downloader class (601-635)
├── Crypto class (637-678)
├── Deployer class (680-1813)
│   ├── step1_build_lxc
│   ├── step2_prepare_rootfs
│   ├── step3_push_to_device
│   ├── step4_install_lxc
│   ├── step5_unpack_rootfs
│   ├── step6_configure_gentoo
│   ├── _setup_network (and variants)
│   ├── _apply_kernelsu_selinux_rules
│   ├── _apply_resource_priority
│   ├── _install_doas
│   ├── run_all, clean, status
│   └── Private helpers
└── CLI commands (1815-1908)
    ├── deploy() command
    └── _setup_network() helper
```

## Constraints

1. **No behavioral changes** - refactor only
2. **Preserve all comments** - especially TEAM_XXX annotations
3. **Keep imports at top** - no mid-file imports
4. **Circular import prevention** - config.py must be standalone

## Open Questions

None - user has already defined target structure in `__init__.py`.

---

## Steps

### Step 1: Verify Existing Extraction (console.py) ✓ DONE
The user already extracted console.py correctly.

### Step 2: Create Baseline Import Test
Before any changes, verify:
```python
# Should fail now (modules don't exist)
from deployer import Config, ADB, LXC, Deployer
```

### Step 3: Document Dependencies
Map which classes depend on which (for extraction order):
- `Config` → standalone (no deps)
- `DeviceShell` → standalone
- `ADB` → DeviceShell
- `LXC` → ADB, Config
- `Downloader` → console (log functions)
- `Crypto` → standalone
- `Deployer` → all of the above
