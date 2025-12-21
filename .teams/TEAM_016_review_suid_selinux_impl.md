# TEAM_016: Review SUID/SELinux Implementation

## Date: 2025-12-21

## Mission
Review the implementation of TEAM_014 and TEAM_015's work on solving the doas/sudo setuid problem for the Gentoo LXC container.

## Files Under Review
1. `/home/vince/Projects/android/kernel/aosp/drivers/kernelsu/selinux/rules.c` - SELinux policy changes
2. `/home/vince/Projects/android/lxc/.teams/TEAM_015_verify_loop_suid.md` - Verification findings
3. `/home/vince/Projects/android/lxc/.teams/TEAM_014_doas_setuid_catch22.md` - Problem documentation
4. `/home/vince/Projects/android/lxc/android/gentoo-lxc.sh` - LXC boot script

## Review Status
- [ ] Phase 1: Implementation status determination
- [ ] Phase 2: Gap analysis
- [ ] Phase 3: Code quality scan
- [ ] Phase 4: Architectural assessment
- [ ] Phase 5: Direction check
- [ ] Phase 6: Findings documented

---

## Phase 1: Implementation Status

**Status: WIP (Work In Progress)**

Evidence:
- TEAM_015 handoff shows: `[ ] Kernel rebuild required`, `[ ] Testing required after flash`
- SELinux rules have been added to `rules.c` but kernel not yet rebuilt
- No verification that the fix actually works

Timeline:
- TEAM_014 (Dec 21 14:55): Identified nosuid catch-22 problem
- TEAM_015 (Dec 21 15:17): Identified SELinux as root cause, implemented fix in rules.c

---

## Phase 2: Gap Analysis

### Problem Chain Identified by TEAM_014/015
1. Android `/data` mounted with `nosuid` 
2. Gentoo rootfs under `/data/lxc/containers/gentoo/rootfs`
3. `lxc.rootfs.path = dir:` inherits nosuid from parent
4. Setuid binaries (doas/sudo) don't work

### Solution Proposed
Use loop mount with explicit `suid` option to override parent nosuid.

### Solution Blocked By
SELinux: kernel context (`u:r:kernel:s0`) cannot read files for loop device I/O.

### SELinux Fix Implemented
Lines 97-118 in `rules.c` add allow rules for kernel context.

### Gap: Missing Implementation Step
- The `gentoo-lxc.sh` script does NOT pass `suid` mount option
- Line 248: `mount -o loop,rw $ROOTFS_IMAGE $ROOTFS`
- Should be: `mount -o loop,rw,suid $ROOTFS_IMAGE $ROOTFS`

---

## Phase 3: Code Quality Scan

### TODOs/Incomplete Work
- None found in code files

### Tracked Issues in Team Files
- TEAM_015 line 112: `[ ] Kernel rebuild required`
- TEAM_015 line 113: `[ ] Testing required after flash`

### Code Changes Made
`rules.c` lines 97-118: Well-commented SELinux rules with TEAM_015 attribution.

---

## Phase 4: Architectural Assessment

### Rule Compliance
- ✅ Rule 0 (Quality > Speed): Clean kernel-level fix, not a workaround
- ✅ Rule 2 (Team Registration): TEAM_015 comment in code
- ⚠️ Rule 11 (TODO Tracking): Outstanding TODOs in team file, not in code

### Architectural Concern: Incomplete Solution
The SELinux fix in `rules.c` is necessary but NOT sufficient.

The `gentoo-lxc.sh` mount command needs modification:
```bash
# Current (line 248):
mount -o loop,rw $ROOTFS_IMAGE $ROOTFS

# Needed:
mount -o loop,rw,suid $ROOTFS_IMAGE $ROOTFS
```

---

## Phase 5: Direction Check

### Is the current approach correct?
**YES** - The approach is sound:
1. Loop mount with `suid` option can override parent nosuid
2. SELinux policy needs to allow kernel context file access
3. Both pieces are needed for the solution to work

### What's missing?
1. **Kernel rebuild** - SELinux changes not deployed
2. **Mount option** - `suid` not added to gentoo-lxc.sh
3. **Verification** - No end-to-end test

---

## Phase 6: Recommendations

### CRITICAL FIX NEEDED
Add `suid` mount option to `gentoo-lxc.sh`:

```bash
# Line 248 - change from:
mount -o loop,rw $ROOTFS_IMAGE $ROOTFS

# To:
mount -o loop,rw,suid $ROOTFS_IMAGE $ROOTFS
```

### Remaining Steps
1. ✅ SELinux rules added (TEAM_015)
2. ⬜ Fix mount option in gentoo-lxc.sh (THIS TEAM)
3. ⬜ Rebuild kernel
4. ⬜ Flash kernel to device
5. ⬜ Test loop mount with suid works
6. ⬜ Verify doas works inside container

---

## Changes Made

### Fix Applied: gentoo-lxc.sh
Lines 248-252: Synced mount options with deployer (`adb.py:158`).

```bash
# Before:
mount -o loop,rw $ROOTFS_IMAGE $ROOTFS

# After (matches deployer exactly):
mount -o loop,rw,suid,dev,exec $ROOTFS_IMAGE $ROOTFS
```

### Sync Analysis Performed

| Operation | Deployer | Boot Script | Status |
|-----------|----------|-------------|--------|
| Mount options | `suid,dev,exec` | `suid,dev,exec` | ✅ Synced |
| SSH start | lxc.run sshd | lxc-attach sshd | ✅ OK |
| LD_LIBRARY_PATH | Set | Set | ✅ OK |
| Runtime dirs | Created | Created | ✅ OK |
| Resource priority | Applied | Applied | ✅ OK |
| SELinux (ksud) | Runtime patch | Not reapplied | ⚠️ Note below |

**SELinux Note:** The `ksud sepolicy patch` rules are for IPVLAN networking and are runtime-only. However, the loop/suid SELinux fix is in `rules.c` and compiled into the kernel, so it persists.

## Verification Results (Dec 21, 2025 15:43)

**SUID FIX VERIFIED - DOAS WORKS!**

```bash
$ ssh vince@192.168.178.100 '/usr/bin/doas id'
uid=0(root) gid=0(root) groups=0(root),1(bin),...
```

- Kernel rebuilt with SELinux rules ✅
- Boot script has `mount -o loop,rw,suid,dev,exec` ✅
- Container restarts correctly ✅
- doas successfully escalates to root ✅

## Handoff
- [x] Review complete
- [x] Gap identified (missing suid mount option)
- [x] Fix applied to gentoo-lxc.sh
- [x] Kernel rebuild completed
- [x] End-to-end testing PASSED
