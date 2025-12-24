# TEAM_022: Rocky Linux 10 Migration

**Date:** December 23, 2025
**Status:** COMPLETED
**Objective:** Migrate "The Vault" from Gentoo to Rocky Linux 10 (aarch64)

## Directive Summary

Per Architecture Lead memo:
- **No Compilation:** Device is a Runtime Enclave, not a build farm
- **Immutable Base:** Rocky Linux 10, pinned versions, 2-year stability window
- **Binary Sovereignty:** Deploy pre-built packages only

## The "Sovereign Four" Stack
1. **OS:** Rocky Linux 10 (Minimal Image / GenericCloud)
2. **Code & Artifacts:** Forgejo (single binary)
3. **Secrets:** Vaultwarden (Podman Container)
4. **Access:** Tailscale + Caddy

## Implementation Tasks - ALL COMPLETED

### A. Artifact Management (`config.py` & `download.py`)
- [x] Remove GentooConfig class -> RockyConfig class
- [x] Add GenericCloud aarch64 URLs
- [x] Replace SHA512 DIGESTS with SHA256 CHECKSUM
- [x] Keep rootfs_image_size_mb at 100GB (Rocky > Android rule)

### B. Deployer (`deploy.py` & `deployer/`)
- [x] Update all step headers from "Gentoo" to "Rocky"
- [x] step2: Download Rocky GenericCloud image and extract rootfs
- [x] step3: Push Rocky tarball
- [x] step5: Remove make.conf generation (no portage)
- [x] step6: Replace rc-update (OpenRC) with systemctl (systemd)
- [x] Remove _install_doas - Rocky has sudo in repos

### C. Boot Script (`gentoo-lxc.sh` -> `rocky-lxc.sh`)
- [x] Created new rocky-lxc.sh
- [x] Init: `/sbin/init` -> `/usr/lib/systemd/systemd`
- [x] Signals: SIGTERM -> SIGRTMIN+3 (systemd halt)
- [x] Mount: Added cgroup2 for systemd
- [x] Environment: Added container=lxc for systemd detection
- [x] Thermal guard: target `dnf|rpm|yum|podman|buildah` instead of `emerge`
- [x] Keep IPVLAN L2 + hardening (OS-agnostic)
- [x] Keep resource priority (Rocky > Android)

### D. Related Updates
- [x] Update deploy.py boot script references
- [x] Update deployer/__init__.py exports (RockyConfig)
- [x] Container name changed to 'rocky'

## Files Modified
- `deployer/__init__.py` - Updated exports
- `deployer/config.py` - GentooConfig -> RockyConfig
- `deployer/download.py` - SHA256/CHECKSUM parsing
- `deployer/deployer.py` - All 6 steps updated for Rocky
- `deploy.py` - CLI updated for Rocky
- `rocky-lxc.sh` - NEW: Rocky Linux boot script (systemd)

## Key Technical Changes

### Systemd in LXC
- Init command: `/usr/lib/systemd/systemd`
- Halt signal: `SIGRTMIN+3` (not SIGTERM)
- Stop signal: `SIGRTMIN+14`
- Requires cgroup2 mount at `/sys/fs/cgroup`
- Environment: `container=lxc` for detection

### No Compilation Required
- Rocky uses dnf/rpm for package management
- sudo available in repos (no doas build)
- OpenSSH pre-installed in GenericCloud image

## Handoff Checklist
- [x] Project compiles cleanly (`python3 -m py_compile`)
- [x] Imports work (`from deployer import Config, RockyConfig, Deployer`)
- [x] Boot script syntax valid (shell)
- [ ] Full deployment test (requires device)
- [ ] Behavioral regression test (requires device)

## Notes for Future Teams
1. The old `gentoo-lxc.sh` is preserved for reference
2. Container name is now 'rocky' (not 'gentoo')
3. Boot script is at `/data/adb/service.d/rocky-lxc.sh`
4. Log file is at `/data/local/tmp/rocky-lxc.log`
5. Rootfs image kept as `gentoo-rootfs.img` for backward compatibility
