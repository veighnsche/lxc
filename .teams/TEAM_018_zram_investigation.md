# TEAM_018: ZRAM Investigation for Gentoo Compilation

## Task
Investigate why ZRAM is not available on the Pixel 6 despite being configured in the kernel fragment.

## Investigation Summary

### Initial Symptoms
- `free -h` showed 0 swap
- No `/dev/zram*` devices
- No ZRAM in `/proc/swaps`

### Diagnostic Commands Run
1. `/proc/cpuinfo` - 8 cores, all ARMv8.2-a features
2. `free -h` - 7.4GB RAM, 631MB free, 0 swap
3. `/proc/config.gz` - Showed `CONFIG_ZRAM=m` (module, not built-in)

### Root Cause Analysis

| Check | Finding |
|-------|---------|
| Fragment `gentoo_lxc_powerhouse.fragment` | `CONFIG_ZRAM=y`, `CONFIG_ZRAM_GS=y` ✅ |
| Kconfig.ext.gs101 line 65 | Sources zram Kconfig ✅ |
| Build `.config` (Dec 21) | `CONFIG_ZRAM=y`, `CONFIG_ZRAM_GS=y` ✅ |
| Running kernel `/proc/config.gz` | `CONFIG_ZRAM=m` ❌ |
| Running kernel build date | Thu Dec 18 12:39:37 UTC 2025 |
| Latest build date | Dec 21 15:31 |

### Root Cause
**GKI defconfig had `CONFIG_ZRAM=m` (module). Device fragments cannot override GKI-level kernel options because `boot.img` comes from `//common:kernel_aarch64`, not the device build.**

The Dec 18 date in uname is the upstream commit date, not the build date.

## Resolution

Changed `CONFIG_ZRAM=m` → `CONFIG_ZRAM=y` in:
`aosp/arch/arm64/configs/gki_defconfig` (line 328)

Also removed `zram.ko` and `zsmalloc.ko` from:
`aosp/modules.bzl` (since they're now built-in, no .ko files produced)

Then rebuild and flash:
```bash
# Rebuild kernel
cd /home/vince/Projects/android/kernel
./build_raviole.sh  # or your build command

# Flash
cd out/raviole/dist
adb reboot bootloader
fastboot flash boot boot.img
fastboot flash vendor_dlkm vendor_dlkm.img
fastboot reboot
```

## Additional Context

### GKI vs Custom ZRAM
- GKI base kernel enforces `CONFIG_ZRAM=m` (module)
- Google's custom `CONFIG_ZRAM_GS=y` is a separate implementation in `private/google-modules/soc/gs/drivers/block/zram/`
- The fragment correctly enables both, and the build output confirms this
- The running kernel simply hasn't been updated

### Gentoo make.conf (Already Configured)
The container already has an optimized make.conf:
```bash
COMMON_FLAGS="-O2 -pipe -mcpu=cortex-a76 -mtune=cortex-a76"
COMMON_FLAGS="${COMMON_FLAGS} -march=armv8.2-a+crypto+fp16+dotprod"
MAKEOPTS="-j6 -l6"
```

### Memory Strategy Recommendation
Once ZRAM is active (after kernel flash):
- ~4GB ZRAM will be available (typical Android config)
- Can safely use 2-3GB tmpfs for `/var/tmp/portage`
- Heavy packages (LLVM, Rust) may still need disk-based compilation

## Handoff
- [ ] Flash new kernel (boot.img + vendor_dlkm.img)
- [ ] Verify ZRAM active: `swapon -s` should show zram0
- [ ] Configure tmpfs for Portage if desired

## Team Info
- **Team ID**: TEAM_018
- **Date**: 2025-12-21
- **Status**: Investigation complete, pending kernel flash
