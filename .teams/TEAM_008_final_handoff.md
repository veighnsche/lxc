# TEAM_008: Final Handoff
## December 20, 2025

---

## Task Completed

**Objective:** Integrate KernelSU into custom kernel to enable LXC container networking with proper SELinux handling.

**Result:** ✅ SUCCESS - Container runs with isolated bridge networking

---

## What Was Done

1. **Fixed KernelSU version** - Hardcoded version 32231 in `Kbuild` (Bazel sandbox blocks git)

2. **Implemented SELinux rules in deploy.py** - `_apply_kernelsu_selinux_rules()` grants networking permissions via `ksud sepolicy patch`

3. **Added bridge/macvlan network support** - NetworkConfig supports both modes (macvlan fails on WiFi, bridge works)

4. **Updated container config generation** - Proper veth/bridge config for isolated networking

5. **Fixed port forwarding setup** - iptables DNAT for SSH access

---

## Current State

```
Container: gentoo
State: RUNNING
IP: 10.0.3.2 (bridge network)
SSH: Port 22 listening
User: vince (with doas)
```

---

## Files Modified

| File | Changes |
|------|---------|
| `reference/KernelSU/kernel/Kbuild:52-54` | Hardcoded version 32231 |
| `lxc/android/deploy.py` | SELinux rules, bridge/macvlan support, port forwarding |

---

## To SSH Into Container

**From Android shell:**
```bash
adb shell
su
# Container is at 10.0.3.2
```

**From computer (requires proxy):**
```bash
# On device, start proxy:
su -c 'while true; do busybox nc -l -p 2222 -e busybox nc 10.0.3.2 22; done &'

# On computer:
adb forward tcp:2222 tcp:2222
ssh -p 2222 vince@localhost
```

---

## Remaining Work

1. **Boot persistence** - SELinux rules and bridge need reapplication after reboot
2. **Proxy automation** - TCP proxy for external SSH needs better integration
3. **lxc-attach fix** - Currently broken due to seccomp, use nsenter or SSH instead

---

## Key Documentation Created

- `@/home/vince/Projects/android/lxc/.teams/TEAM_008_kernelsu_lxc_networking.md` - Full technical details
- `@/home/vince/Projects/android/lxc/KERNELSU_LXC_GOTCHAS.md` - Gotchas and patterns for future teams

---

## Handoff Complete

The deploy.py script is now **reproducible** - running it on a fresh device with KernelSU kernel will:
1. Apply SELinux rules via KernelSU
2. Create bridge network
3. Start container with isolated networking
4. Configure SSH with host key
5. Set up user with doas

**Main goal achieved:** Gentoo container has isolated networking for secrets vault use case.
