# TEAM_027: Investigate SSH Disconnect

## Bug Report

**Symptom**: SSH connection closed unexpectedly after `dnf install nano`
**Message**: `Connection to 192.168.178.100 closed by remote host.`

## Root Cause Analysis

### Evidence from logs:
```
Wed Dec 24 00:58:51 CET 2025: Network lost - stopping container and waiting for recovery
Wed Dec 24 00:58:57 CET 2025: Force killing container...
Wed Dec 24 00:59:01 CET 2025: Container stopped
Wed Dec 24 00:59:31 CET 2025: Network recovered - restarting container
```

### Root Cause:
The watchdog in `rocky-lxc.sh` detected "network lost" and **killed the container**.

**Why it happened:**
1. `get_net_sig()` checks for IPv4 address via `ip -4 addr show`
2. Brief WiFi fluctuation (common on Android) caused empty result
3. Watchdog immediately stops container on first network blip
4. Container restart = SSH connection killed

### Problem in code:
`@rocky-lxc.sh:780-786` - No grace period before declaring network lost:
```bash
if [ -z "$CUR_SIG" ]; then
    if [ $NETWORK_DOWN -eq 0 ]; then
        log "Network lost - stopping container and waiting for recovery"
        stop_container  # IMMEDIATELY kills container!
        NETWORK_DOWN=1
    fi
```

## Fix Applied

Added 30-second grace period with 3 retries (10s each) before declaring network lost.

**Before**: First failed network check → immediately kill container
**After**: Failed check → wait 10s → retry (3x) → only kill if still down after 30s

### Code change:
`@rocky-lxc.sh:780-801` - TEAM_027 grace period for network hiccups

### Deployed:
Fix pushed to device via `deploy.py --step 4`

## Handoff
- [x] Root cause identified
- [x] Fix implemented
- [x] Fix deployed to device
