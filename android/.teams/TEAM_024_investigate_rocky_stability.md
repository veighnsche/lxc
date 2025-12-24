# TEAM_024: Rocky Linux Stability Investigation

**Date:** December 23, 2025
**Status:** INVESTIGATION COMPLETE
**Objective:** Find gaps and refinements for stable Rocky Linux implementation

## Executive Summary

Found **8 issues** ranging from critical bugs to missed optimization opportunities.
Cross-referenced with kernel configurations in `/home/vince/Projects/android/kernel/private/devices/google/raviole/`.

---

## Phase 1 — Critical Bugs

### Bug 1: container_healthy() ALWAYS FAILS (CRITICAL)

**Location:** `rocky-lxc.sh:726-741`

```bash
container_healthy() {
    ...
    if [ -n "$CONTAINER_IP" ]; then
        ping -c 1 -W 1 $CONTAINER_IP >/dev/null 2>&1  # LINE 732
        return $?
    fi
    ...
}
```

**Problem:** With IPVLAN, the Android host CANNOT ping the container. This is a fundamental IPVLAN limitation documented in `deployer/deployer.py:613-615`:

> "The Android host CANNOT reach the container directly. This is by design - IPVLAN isolates parent/child interfaces."

**Impact:** The watchdog thinks container is unhealthy every 30 seconds and triggers unnecessary restarts.

**Fix:** Use `lxc-attach` to check container responsiveness instead:
```bash
container_healthy() {
    if ! is_running; then
        return 1
    fi
    # Check if container responds to commands (doesn't require network)
    $LXC_PREFIX/bin/lxc-attach -n $CONTAINER -P $LXC_CONTAINERS -- /bin/true 2>/dev/null
    return $?
}
```

---

### Bug 2: Cgroup v1 Syntax in Cgroup v2 Environment

**Location:** `rocky-lxc.sh:435-438`

```bash
lxc.cgroup.cpu.shares = 4096
lxc.cgroup.memory.soft_limit_in_bytes = 0
lxc.cgroup.blkio.weight = 800
lxc.cgroup.memory.oom_control = 0
```

**Problem:** The kernel uses **cgroup v2** (unified hierarchy) as evidenced by:
- Paths like `/sys/fs/cgroup/lxc.payload.$CONTAINER/cgroup.procs`
- `cgroup2` mount in LXC config

But the LXC config uses **cgroup v1 syntax** (`lxc.cgroup.*`).

For cgroup v2, the correct syntax is `lxc.cgroup2.*`:
```
lxc.cgroup2.cpu.weight = 400      # (not cpu.shares)
lxc.cgroup2.memory.low = 512M     # soft protection
lxc.cgroup2.memory.min = 256M     # hard reservation
lxc.cgroup2.io.weight = 800
```

**Impact:** Resource limits may not be applied correctly. LXC might fall back to defaults.

**Fix:** Update to cgroup v2 syntax. Note: `cpu.shares` → `cpu.weight` (scale is different).

---

### Bug 3: uninstall.py Doesn't Clean Rocky Scripts

**Location:** `deployer/uninstall.py:303-307`

```python
scripts = [
    "/data/adb/service.d/gentoo-lxc.sh",
    "/data/adb/service.d/gentoo-shell.sh",
    # MISSING: /data/adb/service.d/rocky-lxc.sh
    ...
]
```

**Impact:** Uninstall leaves rocky-lxc.sh on device. Also `_clean_temp_files()` at line 427-431 only cleans `gentoo-*.sh`, not `rocky-*.sh`.

**Fix:** Add Rocky Linux scripts to cleanup lists.

---

## Phase 2 — Naming Inconsistencies (From TEAM_023)

| File | Line | Issue |
|------|------|-------|
| `deploy.py` | 137,148,158 | References `gentoo-lxc.log` instead of `rocky-lxc.log` |
| `deploy.py` | 183 | `lxc-attach -n gentoo` should be `rocky` |
| `deployer/deployer.py` | 630 | `lxc-attach -n gentoo` in success message |
| `deployer/config.py` | 55 | `gentoo-rootfs.img` (intentional for backward compat) |

---

## Phase 3 — Kernel Integration Gaps

### Gap 1: IPVLAN Kernel Status Unclear

**Observation:** 
- `gentoo_lxc_powerhouse.fragment:106` says "IPVLAN: SKIPPED - causes bootloop"
- But `ipvlan_test.fragment` enables IPVLAN with ABI fix

**Question:** Is IPVLAN actually enabled in the running kernel?

**Verification needed:**
```bash
adb shell zcat /proc/config.gz | grep CONFIG_IPVLAN
```

---

### Gap 2: Tier-Based Resource Management Not Implemented

**Kernel supports:** Per `POWERHOUSE_ENHANCEMENTS.md`:
- `memory.min` - Hard reservation (cannot be reclaimed)
- `memory.low` - Soft protection
- `cpu.max` - CFS bandwidth hard limits
- `io.latency` - QoS guarantees

**Deployer uses:** Flat resource priority (Rocky > Android)

**Missing:** Tier-based management for:
- Tier-0: Vault, Vaultwarden, Podman (highest protection)
- Tier-1: Forgejo, Registry
- Tier-2: Ephemeral workloads

**Recommendation:** Future enhancement - implement tier slices inside container.

---

### Gap 3: Security Features Not Leveraged

**Kernel enables:**
- `CONFIG_SECURITY_LANDLOCK=y` - Unprivileged process sandboxing
- `CONFIG_SECURITY_YAMA=y` - Ptrace restrictions
- `CONFIG_INIT_ON_FREE_DEFAULT_ON=y` - Zero memory on free
- `CONFIG_SECRETMEM` - Secret memory for passwords

**Deployer uses:** None of these explicitly.

**Recommendation:** Document these as available for Vaultwarden hardening.

---

### Gap 4: BBR TCP Congestion Not Enabled by Default

**Kernel has:**
```
CONFIG_TCP_CONG_BBR=y
CONFIG_NET_SCH_FQ=y
# CONFIG_DEFAULT_BBR=y  # Commented out
```

**Container doesn't set:** BBR as default congestion control.

**Fix in container:**
```bash
sysctl -w net.ipv4.tcp_congestion_control=bbr
sysctl -w net.core.default_qdisc=fq
```

---

## Phase 4 — Stability Refinements

### Refinement 1: SSH Keepalive May Not Survive Heavy Load

**Current:** `ClientAliveInterval 15` (15 second keepalives)

**Observation:** During heavy compilation, even real-time priority sshd might miss keepalives if CPU is saturated.

**Recommendation:** Increase `ClientAliveCountMax` to 20 (5 min tolerance instead of 3 min).

---

### Refinement 2: Thermal Guard Only Stops dnf/rpm

**Location:** `rocky-lxc.sh:287-288`

```bash
pkill -STOP -f "dnf\|rpm\|yum\|podman\|buildah" 2>/dev/null
```

**Missing:** Other heavy processes like `gcc`, `make`, `cargo`, `npm`.

**Fix:**
```bash
pkill -STOP -f "dnf\|rpm\|yum\|podman\|buildah\|gcc\|make\|cargo\|npm\|rustc" 2>/dev/null
```

---

### Refinement 3: deploy.py --network Function Broken

**From TEAM_023:** The `_setup_network` function calls non-existent methods and attributes.

**Recommendation:** Remove the `--network` flag entirely (bridge mode deprecated per security architecture).

---

## Phase 5 — Summary of Required Actions

### Priority 1: Critical Fixes

| # | Issue | Effort |
|---|-------|--------|
| 1 | Fix `container_healthy()` ping bug | 5 lines |
| 2 | Update cgroup v1 → v2 syntax | 10 lines |
| 3 | Add Rocky scripts to uninstall.py | 5 lines |

### Priority 2: Naming Cleanup

| # | Issue | Effort |
|---|-------|--------|
| 4 | Fix log path references in deploy.py | 4 lines |
| 5 | Fix container name in success messages | 2 lines |

### Priority 3: Optimizations

| # | Issue | Effort |
|---|-------|--------|
| 6 | Enable BBR in container | Add to step6 |
| 7 | Expand thermal guard process list | 1 line |
| 8 | Remove broken --network flag | Delete function |

### Priority 4: Documentation

| # | Issue | Effort |
|---|-------|--------|
| 9 | Document kernel security features for Vaultwarden | New doc |
| 10 | Document tier-based resource management (future) | New doc |

---

## Kernel Files Reviewed

| File | Key Findings |
|------|--------------|
| `gentoo_lxc_powerhouse.fragment` | IPVLAN "skipped", extensive security configs |
| `ipvlan_test.fragment` | IPVLAN enabled with ABI fix |
| `powerhouse_enhancements.fragment` | LSM stacking, cgroup v2 complete |
| `POWERHOUSE_ENHANCEMENTS.md` | Tier-based resource docs, memory.min/low |
| `KERNEL_LXC_FEATURES.md` | Network modes, verification commands |

---

## Handoff Checklist

- [x] Investigation complete
- [x] Critical bugs identified with fixes
- [x] Kernel integration gaps documented
- [x] Stability refinements proposed
- [ ] Fixes implemented (next team)
- [ ] Device testing (requires device)

## Next Steps

1. **Immediate:** Fix `container_healthy()` - this is causing unnecessary restarts
2. **Short-term:** Update cgroup syntax, fix naming inconsistencies
3. **Medium-term:** Enable BBR, expand thermal guard
4. **Future:** Implement tier-based resource management
