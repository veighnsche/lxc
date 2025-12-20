# TEAM_008: KernelSU Integration for LXC Networking
## Date: December 20, 2025

---

## Summary

Successfully integrated KernelSU with LXC to enable **isolated bridge networking** for the Gentoo container. This allows the container to have its own IP address (10.0.3.2) separate from Android's network stack - critical for the secrets vault use case.

---

## Key Achievements

| Component | Status | Notes |
|-----------|--------|-------|
| KernelSU version fix | ✅ | Fixed version 16 → 32231 in Kbuild |
| SELinux rules via ksud | ✅ | Bridge/veth creation now works |
| Bridge networking | ✅ | Container at 10.0.3.2, isolated |
| Macvlan on wlan0 | ❌ | WiFi driver limitation - not supported |
| SSH in container | ✅ | Port 22 listening |
| Deploy.py automation | ✅ | Full deployment is reproducible |

---

## Critical Knowledge for Future Teams

### 1. KernelSU Version Problem

**Problem:** KernelSU defaults to version 16 when git is unavailable during Bazel build.

**Location:** `/home/vince/Projects/android/reference/KernelSU/kernel/Kbuild:51-55`

**Fix:** Hardcode the version:
```makefile
# TEAM_008: Bazel sandbox prevents git access, hardcode version
# Calculated: 30000 + 2231 (git rev-list --count HEAD) = 32231
ccflags-y += -DKSU_VERSION=32231
```

**Why:** Bazel sandboxes the build environment, preventing git access. The fallback version 16 is rejected by KernelSU Manager (requires 22000+).

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

### 3. Macvlan Does NOT Work on WiFi

**Discovery:** Macvlan fails on wlan0 with "Operation not supported on transport endpoint"

**Reason:** WiFi drivers cannot support multiple MAC addresses on the same interface.

**Solution:** Use bridge networking with NAT instead:
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
| `/home/vince/Projects/android/reference/KernelSU/kernel/Kbuild` | KernelSU build config (version fix) |
| `/data/local/tmp/lxc/` | LXC installation on device |
| `/data/lxc/containers/gentoo/` | Container config and rootfs |
| `/data/local/tmp/gentoo-rootfs.img` | 100GB ext4 rootfs image |

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

1. **External SSH access** - TCP proxy needed for `ssh -p 2222 vince@localhost`
   - Proxy script at `/data/local/tmp/ssh-proxy.sh`
   - Needs manual start: `su -c '/data/local/tmp/ssh-proxy.sh &'`

2. **Container restart** - After Android reboot:
   - Bridge needs recreation
   - SELinux rules need reapplication
   - Consider creating a boot script

3. **lxc-attach broken** - Gets seccomp/capability errors
   - Use `nsenter` instead for now
   - Or use SSH into container

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
