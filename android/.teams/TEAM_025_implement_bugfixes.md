# TEAM_025: Implement Rocky Linux Stability Bugfixes

**Date:** December 23, 2025
**Status:** COMPLETED
**Objective:** Implement critical bugfixes identified by TEAM_024

## Fixes Implemented

### Fix 1: container_healthy() Ping Bug (CRITICAL)

**File:** `rocky-lxc.sh:724-743`

**Problem:** Health check used `ping` to verify container, but IPVLAN doesn't allow host to ping container.

**Solution:** Replaced ping with `lxc-attach -- /bin/true` which works regardless of network mode.

```bash
# Before (BROKEN)
ping -c 1 -W 1 $CONTAINER_IP >/dev/null 2>&1

# After (FIXED)
$LXC_PREFIX/bin/lxc-attach -n $CONTAINER -P $LXC_CONTAINERS -- /bin/true 2>/dev/null
```

**Impact:** Watchdog no longer triggers unnecessary container restarts.

---

### Fix 2: Cgroup v2 Syntax

**File:** `rocky-lxc.sh:435-446`

**Problem:** Used cgroup v1 syntax (`lxc.cgroup.*`) in a cgroup v2 environment.

**Solution:** Added cgroup v2 syntax as primary with v1 fallback:

```bash
# Cgroup v2 (primary)
lxc.cgroup2.cpu.weight = 400
lxc.cgroup2.memory.low = 0
lxc.cgroup2.io.weight = 800

# Cgroup v1 (fallback)
lxc.cgroup.cpu.shares = 4096
lxc.cgroup.memory.soft_limit_in_bytes = 0
lxc.cgroup.blkio.weight = 800
```

**Note:** cpu.weight scale is 1-10000 (default 100), vs cpu.shares 1024 default.

---

### Fix 3: Uninstall Cleanup for Rocky Scripts

**File:** `deployer/uninstall.py:303-311, 429-438`

**Problem:** Uninstall only cleaned Gentoo scripts, not Rocky scripts.

**Solution:** Added Rocky scripts and temp files to cleanup lists:

- `/data/adb/service.d/rocky-lxc.sh`
- `/data/local/tmp/rocky-lxc.sh`
- `/data/local/tmp/rocky-*.tar.xz`
- `/data/local/tmp/rocky-*.sh`
- `/data/local/tmp/rocky-lxc.log`

---

### Fix 4: Log Path References in deploy.py

**File:** `deploy.py:137-159`

**Problem:** `--restart` command referenced `gentoo-lxc.log` instead of `rocky-lxc.log`.

**Solution:** Updated all log path references:

- Line 138: `gentoo-lxc.log` → `rocky-lxc.log`
- Line 149: `gentoo-lxc.log` → `rocky-lxc.log`
- Line 159: `gentoo-lxc.log` → `rocky-lxc.log`

---

### Fix 5: Container Name in Success Messages

**Files:** `deploy.py:185`, `deployer/deployer.py:630`

**Problem:** Hardcoded `gentoo` container name in output messages.

**Solution:** 
- `deploy.py`: Changed to `rocky`
- `deployer/deployer.py`: Changed to use `{container}` variable

---

## Verification

```
Python syntax: ✓ All files pass py_compile
Shell syntax:  ✓ rocky-lxc.sh passes bash -n
```

## Files Modified

| File | Changes |
|------|---------|
| `rocky-lxc.sh` | Fixed container_healthy(), added cgroup v2 syntax |
| `deployer/uninstall.py` | Added Rocky scripts to cleanup |
| `deploy.py` | Fixed log paths, container name |
| `deployer/deployer.py` | Fixed container name in success message |

## Handoff Checklist

- [x] Project compiles cleanly
- [x] All syntax validated (Python + Shell)
- [x] Team file updated
- [ ] Device testing (requires device)

## Notes for Future Teams

1. **container_healthy()** now uses lxc-attach which is more reliable than ping
2. **Cgroup syntax** includes both v1 and v2 for maximum compatibility
3. **Uninstall** now cleans both Gentoo and Rocky artifacts
4. All naming updated to Rocky Linux

## Remaining Items (Not in Scope)

Per TEAM_024 investigation, these remain for future work:
- Enable BBR TCP congestion control in container
- Expand thermal guard process list
- Remove broken `--network` flag
- Implement tier-based resource management
