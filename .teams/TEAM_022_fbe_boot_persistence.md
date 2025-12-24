# TEAM_022: FBE-Aware Boot Persistence

## Objective
Implement a Magisk `service.d` boot hook that respects Pixel 6's File-Based Encryption (FBE) while guaranteeing `rocky-lxc.sh` fires automatically on device boot.

## Problem
- Android encryption locks `/data` until the first PIN entry
- Standard init scripts fail if they fire before FBE unlock
- Rocky Linux container must start automatically after unlock

## Solution
Create `/data/adb/service.d/99-rocky-boot.sh`:
- **FBE Barrier**: Block until `/sdcard/Android` is available (indicates unlock)
- **Delay**: 5-second grace period for Android networking stack
- **Handoff**: Fork `rocky-lxc.sh` (Boot Mode) and exit cleanly

## Implementation

### Boot Hook Script
Location: `/data/adb/service.d/99-rocky-boot.sh`
- Polls for `/sdcard/Android` directory (appears after FBE unlock)
- Hands off to `rocky-lxc.sh` Boot Mode (no arguments)
- Forks to background so Magisk service queue isn't blocked

### Why This Works
1. `service.d` runs later than `post-fs-data` - after mount but still before unlock
2. The wait loop uses negligible CPU while waiting for unlock
3. `rocky-lxc.sh` Boot Mode handles all complexity (15s settle, network wait, wakelocks, watchdog)

## Installation Commands (for developer reference)
```bash
# Write the ignition script
cat << 'EOF' > /data/adb/service.d/99-rocky-boot.sh
#!/system/bin/sh
while [ ! -d "/sdcard/Android" ]; do sleep 2; done
sleep 5
/data/local/tmp/rocky-lxc.sh > /dev/null 2>&1 &
EOF

# Mark as executable (MANDATORY)
chmod +x /data/adb/service.d/99-rocky-boot.sh

# Verify payload location
chmod +x /data/local/tmp/rocky-lxc.sh
```

## Files Created
- `lxc/android/99-rocky-boot.sh` - The Magisk service.d boot hook (source copy)

## Handoff Notes
- Script tested conceptually; deploy via ADB to `/data/adb/service.d/`
- Requires Magisk or KernelSU with service.d support
- No changes to `rocky-lxc.sh` required - Boot Mode already handles everything

## Status
- [x] Team file created
- [x] Boot hook script created (`lxc/android/99-rocky-boot.sh`)
- [ ] Deployment (requires physical device access via ADB)

## Handoff Checklist
- [x] Script created at `lxc/android/99-rocky-boot.sh`
- [x] FBE barrier implemented (polls `/sdcard/Android`)
- [x] 5s grace period for network stack
- [x] Forks `rocky-lxc.sh` Boot Mode and exits cleanly
- [ ] Deploy to device: `adb push 99-rocky-boot.sh /data/adb/service.d/`
- [ ] Set permissions: `chmod +x /data/adb/service.d/99-rocky-boot.sh`
- [ ] Verify payload: `chmod +x /data/local/tmp/rocky-lxc.sh`
- [ ] Reboot and test
