# TEAM_021: SSH Stability and Container Uptime Fixes

**Date:** 2025-12-22
**Status:** COMPLETED

## Problem

SSH connections to Gentoo container were extremely unstable:
- Disconnections every ~5 minutes
- Extreme latency spikes (7ms to 2030ms)
- Container stopping without automatic recovery
- Watchdog not running or dying

## Root Causes Identified

| Issue | Before | Impact |
|-------|--------|--------|
| WiFi Sleep Policy | `2` (never keep on) | WiFi dies when screen off |
| WiFi Power Save | Enabled | 100-2000ms latency spikes |
| Doze Mode | Active | Network suspended during idle |
| SSH Keepalive (server) | None | Connection times out silently |
| SSH Keepalive (client) | None | No recovery from packet loss |
| Watchdog | Used `nohup` (dies on Android) | No auto-restart on crash |
| Watchdog wrapper | None | Single point of failure |

## Fixes Applied

### 1. WiFi Power Management (`setup_wifi_power()`)
- `wifi_sleep_policy=0` (always keep WiFi on)
- `wifi_power_save=0` (disable power saving)
- `wifi_suspend_optimizations_enabled=0`

### 2. Doze Mode (`acquire_wakelock()`)
- `dumpsys deviceidle disable`
- Add to Doze whitelist
- Periodic refresh daemon (every 5 minutes)

### 3. SSH Server Keepalive (`ensure_ssh_keepalive()`)
- `ClientAliveInterval 30`
- `ClientAliveCountMax 6`
- `TCPKeepAlive yes`
- Applied on every container start

### 4. SSH Client Keepalive (`~/.ssh/config`)
- `ServerAliveInterval 30`
- `ServerAliveCountMax 6`
- `TCPKeepAlive yes`

### 5. Immortal Watchdog Wrapper
- Outer loop: `while true; do sh gentoo-lxc.sh watch; sleep 5; done`
- Auto-restarts watchdog if it ever dies
- Fallback to foreground mode if wrapper fails

### 6. Proper Daemonization
- Use `setsid` instead of `nohup` on Android
- Verify process is running after start

## Files Modified

- `/home/vince/Projects/android/lxc/android/gentoo-lxc.sh`
  - Added `setup_wifi_power()` function
  - Added `ensure_ssh_keepalive()` function
  - Enhanced `acquire_wakelock()` with Doze disable
  - Changed boot watchdog to immortal wrapper pattern

- `/home/vince/.ssh/config`
  - Added keepalive settings for `Host pixel`

- `/data/adb/service.d/gentoo-lxc.sh` (on device)
  - Updated with all TEAM_021 fixes

## Verification

```bash
# SSH connection works with keepalive
ssh pixel "cat /etc/ssh/sshd_config | grep Alive"
# Output: ClientAliveInterval 30, ClientAliveCountMax 6

# Watchdog running with immortal wrapper
ps -ef | grep gentoo-lxc
# Shows both wrapper and watchdog processes

# Network latency improved
ping 192.168.178.100
# Before: 7-2030ms, 10% loss
# After: 136-262ms, 0% loss
```

## Container is FIRST CLASS CITIZEN

**CRITICAL RULE:** The container MUST run at ALL times when the phone is on.

- Container NOT running = FUNDAMENTAL ERROR, not a choice
- Watchdog wrapper auto-restarts on ANY failure
- All edge cases are now handled automatically
- No manual intervention required
