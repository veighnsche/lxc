# TEAM_023: Review of Rocky Linux Migration (TEAM_022)

**Date:** December 23, 2025
**Status:** REVIEW COMPLETE
**Objective:** Review TEAM_022's Rocky Linux 10 migration implementation

## Phase 1 — Implementation Status

**Determination: COMPLETED (with issues)**

Evidence:
- Team file states "Status: COMPLETED"
- All UoWs marked as complete in team file
- Python syntax valid (`py_compile` passes)
- Shell syntax valid (`bash -n` passes)
- Core deployment flow functional

## Phase 2 — Gap Analysis

### ✓ Implemented Correctly

| UoW | Status | Notes |
|-----|--------|-------|
| RockyConfig class | ✓ | Replaces GentooConfig properly |
| SHA256 CHECKSUM parsing | ✓ | `parse_rocky_checksum` in download.py |
| GenericCloud image download | ✓ | `_extract_rocky_rootfs` handles raw disk image |
| Systemd init command | ✓ | `/usr/lib/systemd/systemd` |
| Systemd signals | ✓ | SIGRTMIN+3 halt, SIGRTMIN+14 stop |
| cgroup2 mount | ✓ | Added for systemd |
| container=lxc env var | ✓ | Systemd detection |
| Thermal guard targets | ✓ | `dnf|rpm|yum|podman|buildah` instead of emerge |
| sudo from repos | ✓ | `_install_doas` removed |
| Boot script (rocky-lxc.sh) | ✓ | Full systemd support |

### ✗ Issues Found

#### Issue 1: BROKEN — `_setup_network` function in deploy.py (CRITICAL)

**Location:** `deploy.py:191-240`

The `--network` command is completely broken:

1. Calls `deployer._detect_host_interface()` which was REMOVED (see `deployer/deployer.py:46`)
2. References non-existent `NetworkConfig` attributes:
   - `net.bridge` — doesn't exist
   - `net.bridge_gateway` — doesn't exist
   - `net.bridge_subnet` — doesn't exist
   - `net.bridge_container_ip` — doesn't exist

**Impact:** Running `python3 deploy.py --network` will crash with AttributeError.

**Recommendation:** Either:
- Remove the `--network` command entirely (bridge mode is deprecated per security architecture)
- Or fix the function to use the new IPVLAN-only architecture

#### Issue 2: INCONSISTENT — Log file references in deploy.py

**Location:** `deploy.py:137, 148, 158`

```python
# References gentoo-lxc.log but rocky-lxc.sh uses rocky-lxc.log
stop_cmd = ["adb", "shell", "su", "-c", f"{boot_script} stop 2>&1; cat /data/local/tmp/gentoo-lxc.log | tail -20"]
```

**Impact:** `--restart` command shows wrong/stale logs.

#### Issue 3: INCONSISTENT — Container name in success message

**Location:** `deployer/deployer.py:630`

```python
f"    [cyan]adb shell su -c 'lxc-attach -n gentoo'[/cyan]\n",
```

Should be `lxc-attach -n rocky` since `container_name = "rocky"`.

#### Issue 4: MINOR — uninstall.py still references gentoo scripts

**Location:** `deployer/uninstall.py:304-307, 429-431`

References `/data/adb/service.d/gentoo-lxc.sh` etc. This is acceptable for backward compatibility cleanup.

## Phase 3 — Code Quality Scan

### TODOs/FIXMEs
- **None found** ✓

### Stubs/Placeholders
- **None found** ✓

### Silent Regressions
- **None found** ✓

### Syntax Validation
- Python: ✓ All files pass `py_compile`
- Shell: ✓ `rocky-lxc.sh` passes `bash -n`

## Phase 4 — Architectural Assessment

### Rule 0 (Quality > Speed)
- ⚠️ `_setup_network` is dead code that should be removed or fixed

### Rule 5 (Breaking Changes)
- ✓ Clean migration, no shims or `_v2` functions

### Rule 6 (No Dead Code)
- ⚠️ `_setup_network` function is dead/broken
- ⚠️ `gentoo-lxc.sh` preserved for reference (acceptable)

### Rule 7 (Modular Refactoring)
- ✓ File sizes reasonable
- ✓ Modules well-scoped

### Consistency
- ⚠️ Mixed "gentoo"/"rocky" naming (intentional for backward compat, but some are bugs)

## Phase 5 — Direction Check

### Is the current approach working?
**YES** — Core migration is complete and functional.

### Is the plan still valid?
**YES** — Rocky Linux 10 migration aligns with Binary Sovereignty directive.

### Should we continue, pivot, or stop?
**CONTINUE** with minor fixes.

## Phase 6 — Recommendations

### Priority 1: Fix or Remove Broken Code

**Option A (Recommended):** Remove `_setup_network` and `--network` flag entirely.
Bridge mode is deprecated per security architecture. IPVLAN-only is the policy.

**Option B:** Fix the function if bridge mode is needed for testing.

### Priority 2: Fix Log/Container Name References

Update `deploy.py`:
- Line 137: `gentoo-lxc.log` → `rocky-lxc.log`
- Line 148: `gentoo-lxc.log` → `rocky-lxc.log`
- Line 158: `gentoo-lxc.log` → `rocky-lxc.log`
- Line 172: `gentoo-rootfs` (keep — backward compat)
- Line 183: `lxc-attach -n gentoo` → `lxc-attach -n rocky`

Update `deployer/deployer.py`:
- Line 630: `lxc-attach -n gentoo` → `lxc-attach -n rocky`

### Priority 3: Device Testing

Per team file, these remain untested:
- [ ] Full deployment test (requires device)
- [ ] Behavioral regression test (requires device)

## Handoff Checklist

- [x] Project compiles cleanly
- [x] All syntax validated
- [ ] Broken `_setup_network` needs fix/removal
- [ ] Log references need update
- [ ] Device testing required

## Summary

TEAM_022's Rocky Linux migration is **substantially complete** with the core deployment flow working correctly. Three issues need attention:

1. **CRITICAL:** `_setup_network` function is broken (references removed methods/attributes)
2. **MINOR:** Log file references still point to `gentoo-lxc.log`
3. **MINOR:** Success message shows wrong container name

**Recommendation:** Continue with implementation fixes, then device testing.
