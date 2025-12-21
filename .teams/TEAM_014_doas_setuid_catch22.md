# TEAM_014: Doas Setuid - UNSOLVED

## Date: 2025-12-21

## Problem Summary

After deploying Gentoo LXC, `doas` and `sudo` fail with "not installed setuid" error.
This creates a **catch-22**: you need root to fix doas, but doas is how you get root.

```
vince@gentoo ~ $ doas uname
doas: not installed setuid
vince@gentoo ~ $ sudo chmod u+s /usr/bin/doas
sudo: not installed setuid
```

## Root Cause - ACTUAL (Not chmod!)

**The setuid bit IS set on the binary:**
```
-rwsr-xr-x 1 root root 75912 Dec 21 13:41 /usr/bin/doas
```

**The REAL problem is the filesystem mount options:**
```
/dev/block/dm-52 / f2fs rw,...,nosuid,...
```

Android's `/data` partition is mounted with `nosuid` option, which **prevents ALL setuid binaries from working**, regardless of file permissions.

## Why This Happens

1. Android mounts `/data` with `nosuid` for security
2. Our rootfs image is mounted under `/data/lxc/containers/gentoo/rootfs`
3. LXC uses `dir:` rootfs type which just uses the directory as-is
4. The container inherits the `nosuid` mount option from Android's `/data`

## What Doesn't Work

| Approach | Result |
|----------|--------|
| `chmod u+s /usr/bin/doas` | Already set, doesn't help |
| `mount -o loop,suid` on Android side | LXC container still sees nosuid |
| `lxc.rootfs.options = suid` | Ignored with dir: type |
| `lxc.rootfs.path = loop:` | LXC fails to start on Android |
| Remount from inside container | Need root to remount, catch-22 |

## Why You Can't Fix It From Inside

1. **SSH gives you unprivileged user** - can't chmod system binaries
2. **doas/sudo need setuid to escalate** - but that's exactly what's broken
3. **No other way to become root from inside the container**

## Potential Solutions for Next Team

### Option 1: Mount image to different location (not under /data)
Android's `/dev` or `/mnt` might not have nosuid. Try:
```bash
mount -o loop,rw,suid /data/local/tmp/gentoo-rootfs.img /mnt/gentoo
# Then update LXC config to use /mnt/gentoo as rootfs
```

### Option 2: Use LXC pre-start hook
Add to LXC config:
```
lxc.hook.pre-start = /path/to/script_that_remounts_with_suid.sh
```

### Option 3: Init script inside container
Create `/etc/local.d/suid.start` that remounts / with suid on boot.
But this requires root to create, which is the catch-22.

### Option 4: Use block device rootfs type
Instead of `dir:`, try:
```
lxc.rootfs.path = block:/dev/loop0
```
Where loop0 is pre-setup with the image.

### Option 5: Different container runtime
Consider using a different container runtime that handles mount options better (e.g., runc with custom config).

## What TEAM_014 Tried

1. ❌ `chmod u+s` - Already set, doesn't help
2. ❌ `mount -o suid` on Android - Container doesn't see it
3. ❌ `lxc.rootfs.options` - Ignored with dir: type  
4. ❌ `loop:` rootfs type - LXC fails to start
5. ❌ `lxc-attach` to fix - LXC-attach itself fails on this Android

## Current State

- Container runs and has network access
- SSH works from LAN
- **BUT**: No privilege escalation inside container (doas/sudo broken)
- User is stuck as unprivileged user

## Files to Check

- `android/gentoo-lxc.sh` - Boot script, update_config() function
- `android/deployer/deployer.py` - _install_doas() function
- LXC config at `/data/lxc/containers/gentoo/config`

## Key Debug Commands

```bash
# Check mount options inside container
ssh user@container 'cat /proc/mounts | head -1'

# Check if setuid bit is set (it is!)
ssh user@container 'ls -la /usr/bin/doas'

# Check Android's /data mount options
adb shell 'mount | grep /data'
```
