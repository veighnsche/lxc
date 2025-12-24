# TEAM_020: Implement Android Layer Briefing

## Task
Implement the action items from ANDROID_LAYER_BRIEFING.md into gentoo-lxc.sh.

## Plan Source
`/home/vince/Projects/android/lxc/.docs/ANDROID_LAYER_BRIEFING.md` (created by TEAM_019)

## Architecture Decision
**All Android Layer fixes are integrated into `gentoo-lxc.sh`** - the single boot script
that gets deployed via `deploy.py --restart`. This follows the existing architecture
where `deploy.py` orchestrates all device operations.

## UoWs

### UoW 1: ARP Tuning for Radio Sleep ✅
- Added `setup_arp_tuning()` function to `gentoo-lxc.sh`
- Sets `net.ipv4.neigh.default.gc_stale_time=3600`
- Sets `net.ipv4.conf.all.arp_ignore=1`
- Called in boot sequence (before network wait)

### UoW 2: Thermal Guard ✅
- Added functions directly to `gentoo-lxc.sh`:
  - `get_cpu_temp()` - finds GS101 CPU thermal zone
  - `thermal_stop_builds()` - SIGSTOP at 52°C
  - `thermal_resume_builds()` - SIGCONT at 48°C
  - `thermal_check()` - called every watchdog loop (30s)
- Covers: emerge, ebuild, sandbox, cc1/cc1plus, make, ninja, cargo, rustc

### UoW 3: Wakelock Management ✅
- Added `acquire_wakelock()` / `release_wakelock()` to `gentoo-lxc.sh`
- Wakelock `gentoo_server_lock` acquired on boot
- Prevents Deep Doze from killing TCP connections

## Status
- [x] UoW 1: ARP Tuning
- [x] UoW 2: Thermal Guard
- [x] UoW 3: Wakelock Management

## Files Modified
| File | Change |
|------|--------|
| `android/gentoo-lxc.sh` | Added thermal guard, wakelock, ARP tuning |

## Deleted (architectural cleanup)
- ~~`android/thermal_guard.sh`~~ - merged into gentoo-lxc.sh
- ~~`android/gentoo_services.sh`~~ - redundant, gentoo-lxc.sh IS the boot script

## Already Implemented (verified in gentoo-lxc.sh)
- ✅ OOM Score Adjustment (-900)
- ✅ Nice priority (-10 Gentoo, +10 Android)
- ✅ I/O priority (ionice real-time for Gentoo)
- ✅ cgroup cpu.shares (4096)

## Deployment
Use existing deploy.py workflow:
```bash
python3 deploy.py --restart
```

This pushes `gentoo-lxc.sh` to `/data/adb/service.d/` and restarts the container.

## Handoff Checklist
- [x] All UoWs completed
- [x] Code changes include TEAM_020 comments
- [x] Follows existing deploy.py architecture
- [x] No standalone scripts (everything in gentoo-lxc.sh)

## Team Info
- **Team ID**: TEAM_020
- **Date**: 2025-12-21
- **Focus**: Android Layer implementation
- **Status**: ✅ Complete
