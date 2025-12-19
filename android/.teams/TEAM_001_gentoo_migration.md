# TEAM 001 — Alpine to Gentoo Migration + Code Refactor

**Created:** 2025-12-19
**Status:** Complete
**Focus:** Replace Alpine with Gentoo, refactor code, fix Android-specific issues

---

## Problem Statement

1. Alpine Linux (musl libc) causes binary incompatibility with glibc-dependent tools
2. Original deploy.py was monolithic with custom logging/CLI boilerplate
3. Android has specific restrictions that break standard LXC operations

## Solution

1. Replaced Alpine with Gentoo Linux (glibc, OpenRC)
2. Refactored using modern Python libraries for cleaner code
3. Added Android-specific workarounds for LXC and filesystem issues

**Target Artifact:** `stage3-arm64-openrc-20251214T234555Z.tar.xz`

---

## Android-Specific Issues & Fixes

### 1. LXC Capability Dropping Fails
**Problem:** `lxc-attach` fails with "Failed to drop capabilities"
**Fix:** 
- Add `lxc.cap.drop =` (empty) to container config
- Comment out `lxc.cap.drop` in `common.conf`
- Use `-e` flag (elevated privileges) with `lxc-attach`

### 2. LXC Seccomp Not Supported
**Problem:** "Unsupported config key lxc.seccomp"
**Fix:** Comment out `lxc.seccomp.profile` in `common.conf`

### 3. Android tar Doesn't Support xz
**Problem:** Device tar can't extract `.tar.xz` files
**Fix:** Extract on host, stream via `tar | adb shell su -c 'tar -xf -'`

### 4. /var/empty Ownership for sshd
**Problem:** sshd requires `/var/empty` owned by root (UID 0)
**Fix:** `chown 0:0 /var/empty && chmod 755 /var/empty` after extraction

### 5. LXC Runtime Directory Permissions
**Problem:** `lxc-attach` fails with "Permission denied" on lock files
**Fix:** `mkdir -p /data/local/tmp/lxc-run/lxc/lock && chmod -R 1777`

### 6. NDK r27+ Struct Redefinitions
**Problem:** `clone_args` and `open_how` already defined in NDK headers
**Fix:** Guard with `#if !defined(__ANDROID__)` in LXC source

---

## Refactored Architecture

### Dependencies (requirements.txt)
- `rich` — Terminal output, progress bars, tables
- `typer` — Modern CLI with type hints
- `httpx` — HTTP client (replaces curl subprocess)

### Class Hierarchy
- `ADB` — Android Debug Bridge wrapper
- `LXC` — Container management (uses `-e` flag for attach)
- `Downloader` — HTTP downloads with progress bars
- `Crypto` — SHA512 verification
- `Deployer` — Main orchestration (6 steps)

---

## Files

- `deploy.py` — Full deployment script with Android fixes
- `requirements.txt` — Python dependencies
- `README.md` — Setup and usage instructions
- `.venv/` — Virtual environment (gitignored)

---

## Usage

```bash
# Setup (one time)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Deploy
.venv/bin/python deploy.py           # Full deployment
.venv/bin/python deploy.py --step N  # Specific step (1-6)
.venv/bin/python deploy.py --status  # Status table
.venv/bin/python deploy.py --clean   # Clean everything

# Connect
ssh vince@<android-ip>
```

---

## Deployment Steps

1. **Build LXC** — Cross-compile for Android ARM64 (requires NDK)
2. **Download Stage3** — Fetch Gentoo tarball with SHA512 verification
3. **Push to Device** — Transfer LXC binaries and stage3 to device
4. **Install LXC** — Configure LXC with Android-specific patches
5. **Unpack Rootfs** — Extract stage3, fix permissions, configure Portage
6. **Configure Gentoo** — Create user, setup SSH, start sshd

---

## Handoff Notes

- [x] Full deployment tested and working
- [x] SSH connection verified: `ssh vince@192.168.178.114`
- [x] All Android-specific fixes codified in deploy.py
- [x] Idempotent - safe to re-run

### Key Code Locations

- **Android LXC patches:** `step4_install_lxc()` — patches common.conf
- **Extraction fallback:** `_extract_on_host_and_push()` — streams tar
- **sshd fix:** `step5_unpack_rootfs()` — fixes /var/empty ownership
- **Runtime dir:** `step6_configure_gentoo()` — sets up lxc-run permissions
- **Elevated attach:** `LXC.run()` — uses `-e` flag
