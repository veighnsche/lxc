# TEAM_008: KernelSU Integration for LXC Networking
## Date: December 20, 2025

---

## Summary

Successfully integrated KernelSU with LXC to enable **isolated bridge networking** for the Gentoo container. This allows the container to have its own IP address (10.0.3.2) separate from Android's network stack - critical for the secrets vault use case.

**UPDATE (TEAM_009):** KernelSU has been moved from `/reference/KernelSU` symlink to proper git submodule in `kernel/aosp/drivers/kernelsu_repo`. IPVLAN networking now works on WiFi!

---

## Key Achievements

| Component | Status | Notes |
|-----------|--------|-------|
| KernelSU integration | ✅ | Now a git submodule in kernel repo |
| SELinux rules via ksud | ✅ | Bridge/veth/ipvlan creation works |
| Bridge networking | ✅ | Container at 10.0.3.2, isolated |
| IPVLAN on wlan0 | ✅ | **TEAM_009: Now works!** Direct IP on LAN |
| Macvlan on wlan0 | ❌ | WiFi driver limitation - use IPVLAN instead |
| SSH in container | ✅ | Port 22 listening |
| Deploy.py automation | ✅ | Full deployment is reproducible |

---

## Critical Knowledge for Future Teams

### 1. KernelSU Integration (Updated by TEAM_009)

**TEAM_009 UPDATE:** KernelSU is now properly integrated into the kernel as a git submodule:
- **Location:** `kernel/aosp/drivers/kernelsu_repo` (git submodule)
- **Symlink:** `kernel/aosp/drivers/kernelsu` → `kernelsu_repo/kernel`
- **Makefile:** Added `obj-$(CONFIG_KSU) += kernelsu/` to `drivers/Makefile`
- **Kconfig:** Added `source "drivers/kernelsu/Kconfig"` to `drivers/Kconfig`

The version is now automatically determined by the KernelSU Kbuild file. CONFIG_KSU defaults to `y` when KPROBES is enabled.

---

### 2. KernelSU SELinux Rules (ksud sepolicy)

**Correct syntax:**
```bash
ksud sepolicy patch "allow SOURCE TARGET CLASS { PERMISSIONS }"
```

**Rules needed for LXC networking:**
```bash
ksud sepolicy patch "allow shell self netlink_route_socket { create bind read write nlmsg_read nlmsg_write getattr setattr }"
ksud sepolicy patch "allow shell self capability { net_admin net_raw }"
ksud sepolicy patch "allow shell self netlink_netfilter_socket { create bind read write nlmsg_read nlmsg_write }"
ksud sepolicy patch "allow shell self tun_socket { create read write ioctl }"
```

**Location in deploy.py:** `_apply_kernelsu_selinux_rules()` method

---

### 3. Networking on WiFi (Updated by TEAM_009)

**MACVLAN:** Fails on wlan0 with "Operation not supported on transport endpoint"
- WiFi drivers cannot support multiple MAC addresses on the same interface.

**IPVLAN (TEAM_009 FIX):** Works on wlan0! 
- IPVLAN L2 mode shares the parent's MAC address
- Container gets a real IP on the home network (e.g., 192.168.178.100)
- Direct SSH access: `ssh vince@192.168.178.100`
- Requires kernel with `CONFIG_IPVLAN=y` and ABI-compatible patches
- See `kernel/.teams/TEAM_009_investigate_ipvlan_bootloop.md` for details

**Bridge (fallback):** Still works for isolated networking:
- Bridge: `lxcbr0` at 10.0.3.1/24
- Container: 10.0.3.2/24
- NAT via iptables MASQUERADE

---

### 4. LXC Lock Directory Issue

**Problem:** lxc-start fails with "Failed to create directory /.cache/"

**Cause:** Android root filesystem is read-only.

**Fix:** Set environment variables before running LXC commands:
```bash
export HOME=/data/local/tmp
export XDG_CACHE_HOME=/data/local/tmp/.cache
```

---

### 5. Deploy.py Shell Escaping Issues

**Problem:** The DeviceShell class dies when commands contain semicolons or complex shell constructs.

**Workaround:** 
- Write scripts via `adb.write_file()` (uses adb push)
- Execute scripts with simple commands
- Avoid inline shell loops in `shell.run()`

---

## File Locations

| File | Purpose |
|------|---------|
| `/home/vince/Projects/android/lxc/android/deploy.py` | Main deployment script |
| `/home/vince/Projects/android/kernel/aosp/drivers/kernelsu_repo/` | KernelSU git submodule |
| `/home/vince/Projects/android/kernel/aosp/drivers/kernelsu` | Symlink to kernelsu_repo/kernel |
| `/data/local/tmp/lxc/` | LXC installation on device |
| `/data/lxc/containers/gentoo/` | Container config and rootfs |
| `/data/local/tmp/gentoo-rootfs.img` | 32GB ext4 rootfs image |

---

## Verification Commands

```bash
# Check KernelSU version (should be 32231+)
adb shell "su -c 'cat /proc/version'" | grep -i kernelsu

# Check bridge exists
adb shell "su -c 'ip link show lxcbr0'"

# Check container running
adb shell "su -c 'export LD_LIBRARY_PATH=/data/local/tmp/lxc/lib && /data/local/tmp/lxc/bin/lxc-info -n gentoo -P /data/lxc/containers'"

# Ping container from Android
adb shell "su -c 'ping -c 1 -I lxcbr0 10.0.3.2'"

# Check SSH listening in container
adb shell "su -c 'nsenter -t \$(pgrep -f \"lxc-start.*gentoo\" | head -1) -n cat /proc/net/tcp'" | grep 0016
```

---

## Known Issues / TODO

1. **IPVLAN mode (TEAM_009 SOLVED)** - Direct SSH access now works!
   - Use `mode='ipvlan'` in NetworkConfig (now default)
   - SSH directly: `ssh vince@192.168.178.100`
   - No proxy needed!

2. **Container restart** - After Android reboot:
   - SELinux rules need reapplication (handled by deploy.py)
   - For bridge mode: bridge needs recreation
   - Consider creating a boot script

3. **lxc-attach broken** - Gets seccomp/capability errors
   - Use `nsenter` instead for now
   - Or use SSH into container (preferred with IPVLAN)

---

## Handoff Checklist

- [x] KernelSU integrated with correct version
- [x] SELinux rules codified in deploy.py
- [x] Bridge networking working
- [x] Container running with isolated network
- [x] SSH configured with host key
- [x] User `vince` with doas sudo access
- [ ] Automated boot script for persistence
- [ ] Direct SSH from computer (proxy needs work)

---

## Contact

This work was done by TEAM_008. See git history for specific changes.
