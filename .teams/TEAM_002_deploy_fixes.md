# TEAM_002: Deploy.py Comprehensive Fixes

## Date: 2025-12-19

## Summary
Fixed multiple issues in deploy.py that were causing incomplete/broken Gentoo deployment.

## Issues Found & Fixed

### 1. Bridge Networking Assumed Broken (WRONG)
- **Problem**: Switched to host networking assuming kernel didn't support bridges
- **Reality**: Kernel HAS `CONFIG_BRIDGE=y` and `CONFIG_VETH=y`
- **Root cause**: SELinux enforcing was blocking bridge operations
- **Fix**: Added `CONFIG_SECURITY_SELINUX_BOOTPARAM=y` to kernel defconfig
- **File**: `/home/vince/android/kernel/private/devices/google/raviole/raviole_defconfig`
- **Action needed**: Rebuild kernel, boot with `enforcing=0` parameter

### 2. Storage Too Small (4GB)
- **Problem**: `rootfs_image_size_mb = 4096` (4GB) - way too small for Gentoo
- **Fix**: Changed to `rootfs_image_size_mb = 32768` (32GB)
- **File**: `deploy.py` line 196

### 3. Doas Not Installing
- **Problem**: Doas source file never downloaded/copied to rootfs
- **Root cause**: Step 2 download wasn't working, file didn't exist locally
- **Fix**: Downloaded opendoas-6.8.2.tar.xz to _cache and _artifacts
- **Verified**: Source now exists and will be pushed/copied properly

### 4. Generic USE Flags
- **Problem**: make.conf had generic ARM64 flags, not optimized for Pixel 6
- **Fix**: Added Pixel 6 (Google Tensor G1) optimized flags:
  - CPU: `-mcpu=cortex-a76 -mtune=cortex-a76 -march=armv8.2-a+crypto+fp16+dotprod`
  - MAKEOPTS: `-j6 -l6` (use 6 of 8 cores)
  - CPU_FLAGS_ARM: `aes sha1 sha2 crc32 v8 vfpv4 neon`
  - Server-focused USE flags (no desktop/GUI)

### 5. Container Config Using Host Networking
- **Problem**: Changed to `lxc.net.0.type = none` when bridge failed
- **Fix**: Restored bridge networking config with veth

## Files Modified
- `/home/vince/android/kernel/private/devices/google/raviole/raviole_defconfig`
- `/home/vince/android/lxc/android/deploy.py`

## Deployment Requirements After ROM/Kernel Refresh

1. **Kernel**: Must be rebuilt with `CONFIG_SECURITY_SELINUX_BOOTPARAM=y`
2. **Boot**: Must boot with `enforcing=0` kernel parameter for bridge networking
3. **Deploy**: Run `python3 deploy.py` from clean state

## Expected Result
- Container IP: 10.0.3.2 (via bridge network)
- Rootfs: 32GB
- doas/sudo: Working
- SSH: `ssh vince@10.0.3.2`
- Optimized for Pixel 6 Tensor G1

## Boot Parameter Requirement

After rebuilding the kernel with `CONFIG_SECURITY_SELINUX_BOOTPARAM=y`, you must boot with SELinux permissive for bridge networking to work.

**Option 1: Bootloader (recommended)**
Add to kernel cmdline: `enforcing=0`

**Option 2: At runtime (if bootparam works)**
```bash
adb shell su -c "setenforce 0"
```

Note: Option 2 only works if `CONFIG_SECURITY_SELINUX_BOOTPARAM=y` is enabled in kernel.

## Files Modified

| File | Change |
|------|--------|
| `kernel/.../raviole/raviole_defconfig` | Added `CONFIG_SECURITY_SELINUX_BOOTPARAM=y` |
| `kernel/.../raviole/powerhouse_enhancements.fragment` | Added SELinux bootparam, fixed typo |
| `lxc/android/deploy.py` | Storage 32GB, bridge networking, Pixel 6 USE flags |

## Handoff Checklist
- [x] Kernel defconfig updated with SELinux bootparam
- [x] Powerhouse fragment updated with SELinux bootparam
- [x] Fragment typo fixed (CONFIG_DAMON_LRU_SORT-y → =y)
- [x] deploy.py storage increased to 32GB
- [x] deploy.py bridge networking restored
- [x] deploy.py Pixel 6 USE flags added
- [x] doas source downloaded to _artifacts
- [ ] Kernel rebuild required
- [ ] Boot with enforcing=0
- [ ] Full deployment test required
