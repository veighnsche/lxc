# TEAM_028: TUN/TAP Passthrough for Rocky LXC

## Task
Enable TUN/TAP device passthrough for Tailscale VPN support in the Rocky container.

## Context
- **Hardware**: Pixel 6 (arm64, Tensor/Titan M2)
- **Kernel**: Linux 6.1.124-android14
- **Goal**: Full kernel-level VPN for sovereign secret management ("The Vault")
- **Blocker**: tailscaled crash-looping due to denied access to `/dev/net/tun` (Major 10, Minor 200)

## Changes Required
1. Add cgroup2 device allow rule: `lxc.cgroup2.devices.allow = c 10:200 rwm`
2. Add bind mount for TUN device: `lxc.mount.entry = /dev/net/tun dev/net/tun none bind,create=file`

## Implementation
1. Modified `update_config()` in `rocky-lxc.sh` to include TUN device settings
2. Added `--push-script` / `-p` flag to `deploy.py` for quick script updates

## Status
- [x] Team registered
- [x] Located config generation (update_config function)
- [x] Applied TUN device settings
- [x] Verified changes

## Handoff Notes
After applying, user needs to restart the container (`rocky-lxc.sh restart`) for changes to take effect.
