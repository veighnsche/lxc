# Refactor Plan: deploy.py → deployer/

**Team:** TEAM_003  
**Status:** Plan Complete - Ready for Execution

## Overview

Split `deploy.py` (1908 lines) into modular `deployer/` package.

## Quick Start

Execute UoWs in this order:

1. `phase-2-step-1-uow-1.md` → creates `config.py`
2. `phase-2-step-2-uow-1.md` → creates `adb.py`
3. `phase-2-step-3-uow-1.md` → creates `lxc.py`
4. `phase-2-step-4-uow-1.md` → creates `download.py`
5. `phase-2-step-5-uow-1.md` → creates `deployer.py`
6. `phase-3-step-1-uow-1.md` → updates `deploy.py` to thin CLI

## Files

### Phases (high-level context)
| File | Purpose |
|------|---------|
| `phase-1.md` | Discovery, constraints, architecture analysis |
| `phase-2.md` | Extraction strategy and module boundaries |
| `phase-3.md` | Migration strategy for deploy.py |
| `phase-4.md` | Dead code removal, cleanup |
| `phase-5.md` | Final verification, handoff checklist |

### Units of Work (executable tasks)
| File | Output | Lines |
|------|--------|-------|
| `phase-2-step-1-uow-1.md` | `deployer/config.py` | ~140 |
| `phase-2-step-2-uow-1.md` | `deployer/adb.py` | ~270 |
| `phase-2-step-3-uow-1.md` | `deployer/lxc.py` | ~110 |
| `phase-2-step-4-uow-1.md` | `deployer/download.py` | ~80 |
| `phase-2-step-5-uow-1.md` | `deployer/deployer.py` | ~1150 |
| `phase-3-step-1-uow-1.md` | `deploy.py` (thin CLI) | ~120 |

## Existing Files

```
deployer/
├── __init__.py   ✓ (user created)
├── console.py    ✓ (user created)
├── config.py     ✗ (phase-2-step-1)
├── adb.py        ✗ (phase-2-step-2)
├── lxc.py        ✗ (phase-2-step-3)
├── download.py   ✗ (phase-2-step-4)
└── deployer.py   ✗ (phase-2-step-5)
```

## Verification

After each UoW, run:
```bash
python3 -c "from deployer import Config, ADB, LXC, Deployer"
```

Final verification:
```bash
python3 deploy.py --help
python3 deploy.py --status
```
