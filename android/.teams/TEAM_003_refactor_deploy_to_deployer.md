# TEAM_003: Refactor deploy.py into deployer/ package

## Status: PLAN COMPLETE ✓

## Objective
Split the monolithic `deploy.py` (1908 lines) into a modular `deployer/` package structure.

## Context
- `deploy.py` contains everything: config, console, ADB, LXC, Downloader, Crypto, Deployer, CLI
- User has already started extraction with:
  - `deployer/__init__.py` - module exports defined
  - `deployer/console.py` - logging functions extracted

## Target Structure (from __init__.py)
```
deployer/
├── __init__.py     ✓ EXISTS - defines exports
├── console.py      ✓ EXISTS - log, log_ok, log_warn, log_err, die, step_header
├── config.py       ✗ TODO - Config, GentooConfig, DevicePaths, NetworkConfig, ResourceConfig
├── adb.py          ✗ TODO - ADB, DeviceShell
├── lxc.py          ✗ TODO - LXC
├── download.py     ✗ TODO - Downloader, Crypto
├── deployer.py     ✗ TODO - Deployer class
└── cli.py          ✗ TODO - typer app and commands (optional, could stay in deploy.py)
```

## Plan Location
`.plans/deployer-refactor/`

## Progress Log

### 2024-12-20
- Registered as TEAM_003
- Analyzed existing code structure (1908 lines in deploy.py)
- Created complete refactor plan with 5 phases and 6 UoW files
- Plan ready for execution

## Artifacts Created

### Phase Files
- `phase-1.md` - Discovery and Safeguards
- `phase-2.md` - Structural Extraction
- `phase-3.md` - Migration
- `phase-4.md` - Cleanup
- `phase-5.md` - Hardening and Handoff

### Unit of Work Files (Phase 2)
- `phase-2-step-1-uow-1.md` - Extract config.py (140 lines)
- `phase-2-step-2-uow-1.md` - Extract adb.py (270 lines)
- `phase-2-step-3-uow-1.md` - Extract lxc.py (110 lines)
- `phase-2-step-4-uow-1.md` - Extract download.py (80 lines)
- `phase-2-step-5-uow-1.md` - Extract deployer.py (1150 lines)

### Unit of Work Files (Phase 3)
- `phase-3-step-1-uow-1.md` - Update deploy.py CLI wrapper

## Execution Order
1. Execute Phase 2 UoWs in order (config → adb → lxc → download → deployer)
2. Execute Phase 3 UoW (update deploy.py)
3. Phase 4 cleanup
4. Phase 5 verification

## Open Questions
None.

## Handoff Notes
Plan is complete and ready for implementation. Next team should:
1. Read `phase-2.md` for overview
2. Execute UoWs in order starting with `phase-2-step-1-uow-1.md`
3. Verify imports after each module creation
