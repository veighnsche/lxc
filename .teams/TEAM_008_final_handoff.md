# TEAM_008: Final Handoff
## December 20, 2025

---

## Task Completed

**Objective:** Integrate KernelSU into custom kernel to enable LXC container networking with proper SELinux handling.

**Result:** ✅ SUCCESS - Container runs with networking (bridge or IPVLAN)

**UPDATE (TEAM_009):** KernelSU moved to kernel repo as git submodule. IPVLAN now works on WiFi!

---

## What Was Done

1. **KernelSU integration** - Now a git submodule at `kernel/aosp/drivers/kernelsu_repo`
   - TEAM_009 moved from `/reference/KernelSU` symlink to proper submodule
   - Added to `drivers/Makefile` and `drivers/Kconfig`

2. **Implemented SELinux rules in deploy.py** - `_apply_kernelsu_selinux_rules()` grants networking permissions via `ksud sepolicy patch`

3. **Added IPVLAN/bridge/macvlan network support** - NetworkConfig supports three modes:
   - **ipvlan** (PREFERRED) - Works on WiFi! Direct IP on LAN
   - **macvlan** - Fails on WiFi, works on ethernet
   - **bridge** - Internal NAT network, requires port forwarding

4. **Updated container config generation** - Proper ipvlan/veth/bridge config

5. **Fixed port forwarding setup** - iptables DNAT for SSH access (bridge mode only)

---

## Current State

```
Container: gentoo
State: RUNNING
Network: IPVLAN (default) or Bridge
IP: 192.168.178.100 (ipvlan) or 10.0.3.2 (bridge)
SSH: Port 22 listening
User: vince (with doas)
```

---

## Files Modified

| File | Changes |
|------|---------|
| `kernel/aosp/drivers/kernelsu_repo/` | KernelSU git submodule (TEAM_009) |
| `kernel/aosp/drivers/Makefile` | Added KernelSU build (TEAM_009) |
| `kernel/aosp/drivers/Kconfig` | Added KernelSU Kconfig (TEAM_009) |
| `lxc/android/deploy.py` | SELinux rules, IPVLAN/bridge/macvlan support |

---

## To SSH Into Container

**With IPVLAN (PREFERRED - direct access):**
```bash
# From any computer on your network:
ssh vince@192.168.178.100
```

**With Bridge (requires proxy):**
```bash
# On device, start proxy:
su -c 'while true; do busybox nc -l -p 2222 -e busybox nc 10.0.3.2 22; done &'

# On computer:
adb forward tcp:2222 tcp:2222
ssh -p 2222 vince@localhost
```

---

## Remaining Work

1. **Boot persistence** - SELinux rules need reapplication after reboot
2. **lxc-attach fix** - Currently broken due to seccomp, use nsenter or SSH instead
3. ~~Proxy automation~~ - **SOLVED by IPVLAN** - direct SSH access works!

---

## Key Documentation Created

- `@/home/vince/Projects/android/lxc/.teams/TEAM_008_kernelsu_lxc_networking.md` - Full technical details
- `@/home/vince/Projects/android/kernel/.teams/TEAM_009_investigate_ipvlan_bootloop.md` - IPVLAN ABI fix

---

## Handoff Complete

The deploy.py script is now **reproducible** - running it on a fresh device with KernelSU kernel will:
1. Apply SELinux rules via KernelSU
2. Setup IPVLAN network (or bridge as fallback)
3. Start container with direct network access
4. Configure SSH with host key
5. Set up user with doas

**Main goal achieved:** Gentoo container has direct network access via IPVLAN for secrets vault use case.

**Direct SSH:** `ssh vince@192.168.178.100` (no proxy needed!)
