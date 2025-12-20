# KernelSU + LXC Networking: Gotchas and Patterns

> **TEAM_008** - December 2025
> 
> This document captures hard-won knowledge about running LXC containers with isolated networking on Android using KernelSU.

---

## Gotcha #1: KernelSU Version Fallback

**Symptom:** KernelSU Manager shows "Version: 16" and refuses to work.

**Cause:** Bazel build sandbox prevents git access → version defaults to 16.

**Fix:** In `KernelSU/kernel/Kbuild`, hardcode the version:
```makefile
ccflags-y += -DKSU_VERSION=32231
```

**Calculate version:** `30000 + $(git rev-list --count HEAD)`

---

## Gotcha #2: ksud sepolicy Syntax

**Wrong:**
```bash
ksud sepolicy allow shell self capability "net_admin"  # ❌
```

**Correct:**
```bash
ksud sepolicy patch "allow shell self capability { net_admin }"  # ✅
```

The subcommand is `patch`, and permissions use curly braces `{ }`.

---

## Gotcha #3: Macvlan on WiFi

**Symptom:** `ip link add type macvlan` returns "Operation not supported"

**Cause:** WiFi drivers don't support multiple MAC addresses.

**Solution:** Use bridge networking with NAT instead. Macvlan only works on Ethernet.

---

## Gotcha #4: LXC Cache Directory

**Symptom:** `lxc-start` fails with "Failed to create directory /.cache/"

**Cause:** Android root is read-only.

**Fix:** Set environment before running LXC:
```bash
export HOME=/data/local/tmp
export XDG_CACHE_HOME=/data/local/tmp/.cache
```

---

## Gotcha #5: Deploy.py Shell Escaping

**Symptom:** Shell dies with "syntax error: unexpected ';'"

**Cause:** The interactive shell wrapper can't handle complex commands with semicolons.

**Fix:** Write scripts via `adb push`, then execute:
```python
self.adb.write_file(path, script_content)  # Uses adb push
self.shell.run(f"sh {path}")  # Simple execution
```

---

## Pattern: SELinux Rules for LXC

These rules enable bridge/veth networking:

```bash
# Network interface management
ksud sepolicy patch "allow shell self netlink_route_socket { create bind read write nlmsg_read nlmsg_write getattr setattr }"

# Network capabilities
ksud sepolicy patch "allow shell self capability { net_admin net_raw }"

# Firewall (iptables)
ksud sepolicy patch "allow shell self netlink_netfilter_socket { create bind read write nlmsg_read nlmsg_write }"
```

---

## Pattern: Bridge Network Setup

```bash
# Create bridge
ip link add lxcbr0 type bridge
ip addr add 10.0.3.1/24 dev lxcbr0
ip link set lxcbr0 up

# Enable forwarding
sysctl -w net.ipv4.ip_forward=1

# NAT
iptables -t nat -A POSTROUTING -s 10.0.3.0/24 -o wlan0 -j MASQUERADE
iptables -A FORWARD -i lxcbr0 -o wlan0 -j ACCEPT
iptables -A FORWARD -i wlan0 -o lxcbr0 -m state --state RELATED,ESTABLISHED -j ACCEPT
```

---

## Pattern: LXC Container Config for Bridge

```
lxc.net.0.type = veth
lxc.net.0.link = lxcbr0
lxc.net.0.flags = up
lxc.net.0.ipv4.address = 10.0.3.2/24
lxc.net.0.ipv4.gateway = 10.0.3.1
```

---

## Verification Commands

```bash
# Bridge exists and has IP
ip addr show lxcbr0 | grep 10.0.3.1

# Container is reachable
ping -c 1 -I lxcbr0 10.0.3.2

# SSH port listening (0016 = port 22 in hex)
nsenter -t $CONTAINER_PID -n cat /proc/net/tcp | grep 0016
```
