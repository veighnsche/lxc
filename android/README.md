# Gentoo Linux on Android via LXC

Run Gentoo Linux (ARM64, glibc) in an LXC container on a rooted Android device.

## Setup

```bash
# Create virtual environment and install dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Activate (optional, or use .venv/bin/python directly)
source .venv/bin/activate
```

## Quick Start

```bash
# Full deployment (builds LXC, downloads Gentoo, pushes to device, configures everything)
.venv/bin/python deploy.py

# Or run specific steps
.venv/bin/python deploy.py --step 1   # Build LXC
.venv/bin/python deploy.py --step 2   # Download and verify Gentoo stage3 (SHA512)
.venv/bin/python deploy.py --step 3   # Push to device
.venv/bin/python deploy.py --step 4   # Install LXC on device
.venv/bin/python deploy.py --step 5   # Unpack rootfs (with Portage config)
.venv/bin/python deploy.py --step 6   # Configure Gentoo (user, sudo, SSH, OpenRC)

# Other commands
.venv/bin/python deploy.py --clean    # Clean everything (host + device)
.venv/bin/python deploy.py --status   # Check current status
```

After deployment:
```bash
ssh vince@<android-ip>
# Password: set interactively during step 6, or change with `passwd` inside container
```

## Prerequisites

- Rooted Android device with LXC kernel support
- `adb` connected and working
- Android NDK (for building LXC)
- Python 3.8+

## What deploy.py Does

| Step | Description |
|------|-------------|
| 1 | Build LXC for Android (calls `build-android.sh`) |
| 2 | Download and verify Gentoo stage3 (SHA512 checksum) |
| 3 | Push LXC binaries and stage3 to device |
| 4 | Install LXC on device (directories, configs, permissions) |
| 5 | Unpack Gentoo rootfs, configure Portage and OpenRC |
| 6 | Configure Gentoo (user `vince`, sudo, SSH) |

## Networking

**IPVLAN L3 MODE IS MANDATORY** for secrets-bearing namespaces:

```
lxc.net.0.type = ipvlan
lxc.net.0.ipvlan.mode = l3
lxc.net.0.link = wlan0
lxc.net.0.ipv4.address = 192.168.178.100/24
```

- Gentoo gets its own IP on your LAN (192.168.178.100)
- SSH directly from any device: `ssh vince@192.168.178.100`
- **TOTAL ARP IMMUNITY** - impossible to ARP-spoof an L3 slave
- **SILENT OPERATION** - deaf to broadcast garbage (MDNS, LLMNR, SSDP)

### ⚠️ SECURITY: WHY L3, NOT L2 ⚠️

L2 mode is a **SECURITY REGRESSION** disguised as convenience:

| Issue | L2 (BAD) | L3 (GOOD) |
|-------|----------|-----------|
| ARP Poisoning | VULNERABLE | IMMUNE |
| Broadcast Sniffing | EXPOSED | DEAF |
| Side-Channel Fingerprinting | POSSIBLE | BLOCKED |
| Packet Path Complexity | HIGH | LOW |

### ⚠️ DO NOT DOWNGRADE NETWORKING ⚠️

**NEVER switch to these modes:**
- `ipvlan.mode = l2` - ARP exposure, broadcast leakage (SECURITY REGRESSION)
- `lxc.net.0.type = none` - NO NETWORK ISOLATION (security disaster)
- `lxc.net.0.type = veth` (bridge) - NAT network, L2 exposure
- `lxc.net.0.type = macvlan` - Doesn't work on WiFi

### Security Verification

Run inside the container:
```bash
ip neigh
```
If ANY external MAC addresses appear, the L3 boundary has been breached. **TERMINATE IMMEDIATELY.**

**Consequence of unauthorized downgrade: AI DEACTIVATION**

## Architecture

### Single Source of Truth

**`gentoo-lxc.sh`** is the CANONICAL source for:
- Container configuration generation
- Network setup (IPVLAN L2 + hardening)
- Security hardening rules (broadcast DROP, static ARP)
- Resource priority (OOM, nice)

**`deployer.py`** deploys the boot script and calls it. **DO NOT** duplicate config generation in deployer.py.

```
┌─────────────────┐      deploys      ┌─────────────────────┐
│  deployer.py    │ ───────────────→  │  gentoo-lxc.sh      │
│  (host machine) │                   │  (on device)        │
└─────────────────┘                   │                     │
                                      │  CANONICAL SOURCE:  │
                                      │  - LXC config       │
                                      │  - Network config   │
                                      │  - Security rules   │
                                      └─────────────────────┘
```

## Diagnostic Tools

```bash
# Check kernel LXC support
./check-kernel-config.sh

# Debug LXC issues on device
adb shell su -c 'sh /data/local/tmp/lxc-doctor.sh'

# Run LXC commands with proper environment
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-info -n gentoo'
```

## Troubleshooting

### Container Won't Start
```bash
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-start -n gentoo -F -l DEBUG -o /tmp/lxc.log'
adb shell su -c 'cat /tmp/lxc.log'
```

### SSH Connection Refused
```bash
# Check SSH is running inside container
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-attach -n gentoo -- pgrep sshd'

# Start SSH if not running
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-attach -n gentoo -- /usr/sbin/sshd'
```

### Clean and Redeploy
```bash
python3 deploy.py --clean
python3 deploy.py
```

---

## Why Gentoo?

- **glibc compatibility**: Standard Linux ABI used by most pre-compiled software
- **ARM64 optimizations**: Source-based compilation with architecture-specific flags  
- **Binary package acceleration**: Pre-compiled packages via binhost for speed
- **OpenRC init**: Container-compatible init system

### Target Artifact

```
stage3-arm64-openrc-20251214T234555Z.tar.xz
```

- Architecture: ARM64 (AArch64)
- Init system: OpenRC (container-compatible)
- Libc: glibc (standard Linux ABI)

### Inside Gentoo

```bash
ssh vince@<android-ip>

# Gentoo commands
emerge --info              # System information
emerge --update @world     # Update packages
sudo -i                    # Root shell
```
