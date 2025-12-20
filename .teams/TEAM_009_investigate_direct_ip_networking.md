# TEAM_009: Investigate Direct IP Networking for LXC Container
## Date: December 20, 2025

---

## Bug Report / Feature Request

**Goal:** Container should have its own IP on home network (192.168.178.x range)

**Success Criteria:**
```bash
ssh vince@192.168.178.X  # Direct SSH to container from any device on home network
```

**Current State:**
- Container has bridge IP: 10.0.3.2
- NAT via iptables MASQUERADE
- Requires proxy/port forwarding to access

**Desired State:**
- Container gets IP from home router DHCP (192.168.178.x)
- Direct L2 connectivity to home network

---

## Phase 1: Understand the Symptom

### Expected Behavior
Container should be reachable at 192.168.178.X from any device on the home network.

### Actual Behavior
Container is on isolated bridge network (10.0.3.0/24), only reachable via NAT/proxy.

### Root Cause (from TEAM_008)
- Macvlan requires the interface to support multiple MAC addresses
- WiFi drivers (wlan0) don't support this
- Error: "Operation not supported on transport endpoint"

---

## Phase 2: Hypotheses

### Hypothesis 1: ipvlan (L3 mode)
**Idea:** ipvlan shares the parent's MAC but assigns different IPs.
**Evidence needed:** Check if kernel supports ipvlan, test on wlan0.
**Confidence:** Medium - ipvlan L3 might work where macvlan fails.

### Hypothesis 2: Proxy ARP on bridge
**Idea:** Use proxy ARP so the Android device answers ARP for container IP.
**Evidence needed:** Test proxy_arp sysctl, check if router accepts it.
**Confidence:** Low - may not work well with consumer routers.

### Hypothesis 3: USB Ethernet adapter
**Idea:** Use USB-C Ethernet adapter, macvlan works on Ethernet.
**Evidence needed:** Hardware required.
**Confidence:** High - but requires extra hardware.

### Hypothesis 4: WireGuard/VPN bridge
**Idea:** Bridge container to home network via VPN.
**Evidence needed:** Complex setup.
**Confidence:** Medium - works but adds latency/complexity.

---

## Phase 3: Investigation Progress

### Hypothesis 1: ipvlan - RULED OUT
- Tested `ip link add link wlan0 name test-ipvlan type ipvlan mode l2`
- Result: "Operation not supported on transport endpoint"
- Reason: Kernel shows `# CONFIG_IPVLAN is not set`

### Root Cause Discovery
**Device kernel (Dec 18):**
```
# CONFIG_MACVLAN is not set
# CONFIG_IPVLAN is not set
```

**Latest build (Dec 20) at `/home/vince/Projects/android/kernel/out/raviole/dist/`:**
```
CONFIG_MACVLAN=y
# CONFIG_IPVLAN is not set
```

The device is running an **older kernel** that lacks MACVLAN support. The newer build from Dec 20 has it enabled.

---

## Phase 4: Root Cause

**Root Cause:** Device running kernel from Dec 18 which lacks `CONFIG_MACVLAN=y`.

**Solution:** Flash the Dec 20 kernel build which has MACVLAN enabled.

**Causal Chain:**
1. WiFi wlan0 doesn't support multiple MAC addresses → macvlan can't create new MACs
2. BUT macvlan in "passthru" mode or ipvlan L2 could work by sharing the parent MAC
3. HOWEVER, the current kernel has neither CONFIG_MACVLAN nor CONFIG_IPVLAN compiled in
4. The Dec 20 build has CONFIG_MACVLAN=y which should enable macvlan

**Confidence:** HIGH - kernel config clearly shows the missing option

---

## Phase 5: Decision - Solution Options

### Option A: Flash Dec 20 Kernel + Test Macvlan on WiFi
1. Flash the Dec 20 kernel which has `CONFIG_MACVLAN=y`
2. Test if macvlan actually works on wlan0
3. **Risk:** WiFi driver may still reject macvlan due to MAC limitation

### Option B: Enable CONFIG_IPVLAN + Rebuild Kernel
**ipvlan L2 mode is the correct solution for WiFi** because:
- ipvlan shares the parent MAC address (no new MACs needed)
- WiFi driver doesn't need to support multiple MACs
- Container gets a unique IP on the home network

**BUT:** Fragment says "IPVLAN: SKIPPED - causes bootloop"
- Need to investigate why ipvlan caused bootloop
- Possibly a kernel config conflict

### Option C: Proxy ARP (No Kernel Change)
Use bridge networking + proxy ARP so Android answers ARP for container IP.
- Works with current kernel
- Hacky but functional

### Recommended Path
1. **First:** Flash Dec 20 kernel and test macvlan on wlan0
2. **If macvlan fails:** Add `CONFIG_IPVLAN=y` to a new fragment, rebuild, test
3. **Fallback:** Proxy ARP if both fail

---

## Next Steps for User

```bash
# 1. Flash the Dec 20 kernel
adb reboot bootloader
fastboot flash boot /home/vince/Projects/android/kernel/out/raviole/dist/boot.img
fastboot flash vendor_dlkm /home/vince/Projects/android/kernel/out/raviole/dist/vendor_dlkm.img
fastboot reboot

# 2. After boot, test macvlan support
adb shell "su -c 'zcat /proc/config.gz | grep MACVLAN'"
# Should show: CONFIG_MACVLAN=y

# 3. Test macvlan on wlan0
adb shell "su -c 'ip link add lxc-mv link wlan0 type macvlan mode bridge'"
# If this works → SUCCESS
# If "Operation not supported" → WiFi driver limitation, need ipvlan
```

---

## Files to Modify

- `/home/vince/Projects/android/lxc/android/deploy.py` - NetworkConfig and bridge setup

