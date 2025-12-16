# Alpine Linux on Android via LXC

Run Alpine Linux in an LXC container on a rooted Android device.

## Quick Start

```bash
# Full deployment (builds LXC, downloads Alpine, pushes to device, configures everything)
python3 deploy.py

# Or run specific steps
python3 deploy.py --step 1   # Build LXC
python3 deploy.py --step 2   # Download Alpine rootfs
python3 deploy.py --step 3   # Push to device
python3 deploy.py --step 4   # Install LXC on device
python3 deploy.py --step 5   # Unpack rootfs
python3 deploy.py --step 6   # Configure Alpine (user, sudo, SSH)

# Other commands
python3 deploy.py --clean    # Clean everything (host + device)
python3 deploy.py --status   # Check current status
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
| 2 | Download Alpine minirootfs |
| 3 | Push LXC binaries and rootfs to device |
| 4 | Install LXC on device (directories, configs, permissions) |
| 5 | Unpack Alpine rootfs into container |
| 6 | Configure Alpine (user `vince`, sudo, SSH) |

## Networking

Currently uses **host networking** (`lxc.net.0.type = none`):
- Alpine shares Android's network stack
- SSH runs on Android's IP address
- Simple and works on all kernels

For bridge networking (Alpine gets its own IP), edit the container config at `/data/lxc/containers/alpine/config`.

## Diagnostic Tools

```bash
# Check kernel LXC support
./check-kernel-config.sh

# Debug LXC issues on device
adb shell su -c 'sh /data/local/tmp/lxc-doctor.sh'

# Run LXC commands with proper environment
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-info -n alpine'
```

## Troubleshooting

### Container Won't Start
```bash
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-start -n alpine -F -l DEBUG -o /tmp/lxc.log'
adb shell su -c 'cat /tmp/lxc.log'
```

### SSH Connection Refused
```bash
# Check SSH is running inside container
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-attach -n alpine -- pgrep sshd'

# Start SSH if not running
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-attach -n alpine -- /usr/sbin/sshd'
```

### Clean and Redeploy
```bash
python3 deploy.py --clean
python3 deploy.py
```
