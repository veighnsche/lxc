# Android Layer Developer Briefing

**Workspace:** `/home/vince/Projects/android/lxc/android`  
**Focus:** Runtime Environment, Permissions, and Preventing Android from Killing Gentoo

---

## 1. Network Stability (The "Radio Sleep" Problem)

### Context
Android aggressively puts the WiFi/Cellular radio into low-power states when the screen is off. This filters out multicast/broadcast traffic (ARP requests), causing the Gentoo container (L2 IPVLAN) to lose connectivity to the gateway.

### Action Items

#### ARP Tuning
Apply these sysctl overrides on boot (via init script or Magisk):

```bash
# Keep ARP entries valid for 1 hour (default is usually ~60s)
sysctl -w net.ipv4.neigh.default.gc_stale_time=3600
# Reply only if the target IP is local (reduces noise)
sysctl -w net.ipv4.conf.all.arp_ignore=1
```

#### Wakelock Management
If Gentoo is running a critical server (Postgres), the Android side must hold a partial wakelock, or the device will enter Deep Doze and kill the TCP connections. Use a service to hold a lock *only* when the database has active connections.

**Implementation Options (TEAM_020):**

1. **Shell-based wakelock (simplest):**
   ```bash
   # Acquire wakelock (prevents Deep Doze)
   echo "gentoo_server" > /sys/power/wake_lock
   
   # Release wakelock
   echo "gentoo_server" > /sys/power/wake_unlock
   ```

2. **Termux:Boot + script:**
   - Install Termux:Boot from F-Droid
   - Create `~/.termux/boot/wakelock.sh`:
   ```bash
   termux-wake-lock
   # Keep process alive
   while true; do sleep 3600; done
   ```

3. **Android service (requires app development):**
   - Create a minimal Android app that holds `PARTIAL_WAKE_LOCK`
   - Use `PowerManager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Gentoo:Server")`
   - Bind to Gentoo container state (start/stop wakelock with container)

4. **Magisk module approach:**
   - Add to `post-fs-data.sh`:
   ```bash
   # Hold wakelock for Gentoo container
   echo "gentoo_lxc" > /sys/power/wake_lock
   ```

**Note:** Shell-based wakelocks via `/sys/power/wake_lock` require root and may not work on all Android versions. The Termux approach is most reliable for userspace.

---

## 2. Process Lifecycle (The OOM Killer)

### Context
Android's `lmkd` (Low Memory Killer Daemon) is tuned for a phone, not a server. It will kill your compilation jobs (`cc1plus`) to keep the Camera app fast.

### Action Items

#### OOM Score Adjustment
Any service launching Gentoo/LXC must explicitly set the OOM Score Adjust of the container's init process to something "safe" (e.g., `-900`, shielding it from standard kills).

```bash
# Example: Protect the LXC init process
echo -900 > /proc/<lxc_init_pid>/oom_score_adj
```

#### Cgroup Placement
Do not leave Gentoo processes in the default cgroup. Move them to appropriate stune groups:

| Use Case | Cgroup Path | Notes |
|----------|-------------|-------|
| Compilation | `/dev/stune/background` | System-background, won't compete with UI |
| Postgres (server) | `/dev/stune/top-app` | Only if prioritizing over Android UI (risky) |

---

## 3. Thermal Management (Userspace Guard)

### Context
The kernel throttles frequencies, but it doesn't stop new processes from spawning. `emerge` will keep launching jobs even as the chip overheats.

### Action Items
Implement the **Userspace Thermal Guard** script. The Android layer is responsible for:

1. Polling thermal zones (e.g., `/sys/class/thermal/thermal_zone*/temp`)
2. Sending `SIGSTOP` to Gentoo build processes when temps exceed **52°C**
3. Sending `SIGCONT` when temps drop below **48°C** (hysteresis)

**TEAM_020: Integrated into `gentoo-lxc.sh` watchdog loop**

The thermal guard runs automatically as part of the watchdog (every 30s):
- `get_cpu_temp()` - finds GS101 CPU thermal zone
- `thermal_stop_builds()` - SIGSTOP at 52°C
- `thermal_resume_builds()` - SIGCONT at 48°C
- Covers: emerge, ebuild, sandbox, cc1/cc1plus, make, ninja, cargo, rustc

No separate script needed - deploy via:
```bash
python3 deploy.py --restart
```

---

## 4. Storage Endurance (Userspace Responsibility)

### Context
Gentoo compilation generates massive metadata updates (atime, temporary files). This burns NAND write cycles.

### Action Items
- **Force builds to tmpfs:** Configure Portage to use `/var/tmp/portage` mounted as tmpfs
- **Mount options:** Use `noatime,nodiratime` on all container filesystems
- **Symlink strategy:** Keep `/var/cache/distfiles` on persistent storage (infrequent writes)

---

## Summary Table

| Goal | Action |
|------|--------|
| **Stability** | Fix ARP/Neighbor table timeouts (`sysctl`). Prevent `lmkd` from killing Gentoo. |
| **Performance** | Pin Postgres to A76 cores (`taskset 0x0C`). Use OOM score adjustment. |
| **Thermals** | Stop builds (`SIGSTOP`) when >52°C. |
| **Endurance** | Force builds to `tmpfs`. Use `noatime` mounts. |

---

## Related Documents
- Kernel Layer Briefing: `/home/vince/Projects/android/kernel/.plans/KERNEL_LAYER_BRIEFING.md`
- WiFi Auto-Enable: `/home/vince/Projects/android/lxc/.docs/ANDROID_WIFI_AUTO_ENABLE.md`

---

*Created by TEAM_019 - 2025-12-21*
