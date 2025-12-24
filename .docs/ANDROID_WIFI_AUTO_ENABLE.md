# Android WiFi Auto-Enable Behavior

## The Problem

After rebooting a Pixel device, WiFi does not automatically enable even if it was enabled before reboot. This breaks the Gentoo LXC container startup because:

1. Boot script runs via Magisk `service.d`
2. Script waits for network (correctly)
3. WiFi never enables → container never starts
4. User must manually go to Settings → WiFi → Enable

## Why Android Does This

### 1. **Battery Optimization (Primary Reason)**

Android aggressively manages radios to save battery:
- WiFi scanning consumes significant power
- On fresh boot, Android waits for user interaction before enabling radios
- This is part of "Doze" and battery optimization framework

### 2. **Privacy/Security Design**

- Prevents automatic connection to potentially malicious networks
- User must explicitly consent to network connectivity
- Part of Android's "user-initiated action" security model

### 3. **Airplane Mode Persistence**

- If device was in airplane mode, WiFi stays off
- Android remembers radio states across reboots (sometimes incorrectly)

### 4. **OEM Customizations**

Google Pixel specifically has conservative WiFi behavior:
- Stock Android tends to be more aggressive about power saving
- Some OEMs (Samsung, OnePlus) may auto-enable WiFi more readily

## What We Might Have "Broken"

### Likely NOT Broken - This is Default Behavior

The WiFi not auto-enabling is **stock Android behavior**, not something we broke. However, some things can make it worse:

### 1. **SELinux Contexts**

Our KernelSU SELinux rules might affect WiFi service:
```
# We added rules for LXC networking
supolicy --live "allow ... netd ..."
```
These shouldn't affect WiFi enable state, but could theoretically interfere.

### 2. **Network Namespace Interference**

IPVLAN creates network namespaces. If Android's `netd` or `wificond` see unexpected namespace state on boot, they might be conservative.

### 3. **Boot Timing**

Our `service.d` script runs early in boot. If it interferes with:
- `wificond` (WiFi HAL daemon)
- `netd` (network daemon)
- `ConnectivityService`

...it could cause WiFi to stay disabled.

### 4. **Nothing - Stock Behavior**

Most likely: **This is just how Pixel works.** Many users report WiFi not auto-enabling after reboot on stock Pixels.

## Solutions

### Option 1: Tasker/MacroDroid Automation (Recommended)

Create automation rule:
- **Trigger:** Device boot completed
- **Action:** Enable WiFi

This is the cleanest solution and doesn't require system modification.

### Option 2: ADB WiFi Enable Script

Add to `service.d`:
```bash
# Enable WiFi on boot
svc wifi enable
```

**Risk:** May not work due to timing, and `svc` requires system permissions.

### Option 3: Settings.Global Modification

```bash
settings put global wifi_on 1
```

**Risk:** May be overridden by Android's WiFi service.

### Option 4: Magisk Module for WiFi

Create/install a Magisk module that:
1. Hooks into WiFi service
2. Forces WiFi enable on boot

**Risk:** Complex, may break with Android updates.

### Option 5: Accept Manual Enable

Document that user must enable WiFi after reboot. The watchdog will then:
1. Detect network available
2. Start container automatically
3. No further manual intervention needed

## Current Workaround in gentoo-lxc.sh

Our boot script already handles this gracefully:

```bash
# Wait for network (WiFi may not be connected yet)
if ! has_network; then
    log "No network yet, waiting..."
    if ! wait_for_network 300; then
        log "ERROR: No network after 5 minutes, starting watchdog anyway"
    fi
fi
```

The watchdog then monitors for network recovery and starts the container when WiFi becomes available.

## Recommendation

**Accept the manual WiFi enable** as a one-time action after reboot. The infrastructure handles everything else automatically:

1. User reboots device
2. User enables WiFi (one tap in quick settings)
3. Boot script detects network within 30 seconds
4. Container starts automatically
5. SSH available without further intervention

This is the most reliable approach that doesn't risk breaking Android's network stack.

## References

- [Android WiFi Architecture](https://source.android.com/docs/core/connect/wifi-overview)
- [Pixel WiFi Issues - Reddit](https://www.reddit.com/r/GooglePixel/comments/wifi_not_auto_connecting/)
- [Android Doze Mode](https://developer.android.com/training/monitoring-device-state/doze-standby)
