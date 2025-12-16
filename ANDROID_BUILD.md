# Building LXC for Android (aarch64, API 31)

Minimal LXC build for running containers on Android devices with custom kernels
that have full namespace, cgroup, and IPC support.

## Prerequisites

- **Android NDK r27d** (or compatible version)
- **Meson** (>= 0.61)
- **Ninja**
- Linux x86_64 host

## Quick Start

```bash
# Set NDK path
export NDK=/path/to/android-ndk-r27d

# Build everything
./build-android.sh all

# Or step by step:
./build-android.sh configure
./build-android.sh build
./build-android.sh install
```

## Output

Installation lands in `_install_android31/` with:

```
_install_android31/
├── bin/
│   ├── lxc-start
│   ├── lxc-stop
│   ├── lxc-attach
│   ├── lxc-info
│   └── ... (other tools)
├── lib/
│   └── liblxc.so
├── libexec/lxc/
│   ├── lxc-monitord
│   └── lxc-user-nic
├── etc/lxc/
│   └── default.conf
└── share/lxc/
    ├── config/
    └── templates/
```

## Deployment to Device

All deployment is done via `adb shell su -c` - no interactive shells required.

### Preflight Check (Recommended)

Run the doctor script to verify device readiness before deployment:

```bash
./android/lxc-doctor.sh
```

This checks:
- adb connectivity
- root access
- kernel mounts (/proc, /sys, cgroups)
- SELinux state
- LXC installation status

### Quick Deploy

```bash
# From repo root - push everything to device
./android/push-to-phone.sh

# Run installer on device
adb shell su -c 'sh /data/local/tmp/install-lxc-on-phone.sh'
```

### Manual Deploy

```bash
# Push build output
adb push _install_android31 /data/local/tmp/lxc

# Push helper scripts
adb push android/install-lxc-on-phone.sh /data/local/tmp/
adb push android/lxc-wrapper.sh /data/local/tmp/

# Run installer
adb shell su -c 'sh /data/local/tmp/install-lxc-on-phone.sh'
```

### Using LXC Commands

All commands follow this pattern:

```bash
adb shell su -c '. /data/local/tmp/lxc-env.sh; <command>'
```

Or use the wrapper script:

```bash
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh <command>'
```

Examples:

```bash
# Check version
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-start --version'

# List containers
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-ls -f'

# Start container (foreground)
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-start -n alpine -F'

# Container info
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-info -n alpine'

# Stop container
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-stop -n alpine'
```

## Android Directory Layout

After installation, the device has:

```
/data/local/tmp/
├── lxc/                          # LXC prefix (binaries, libs, config)
│   ├── bin/lxc-*
│   ├── lib/liblxc.so
│   ├── libexec/lxc/
│   └── etc/lxc/
├── lxc-run/                      # Runtime directory
├── lxc-env.sh                    # Environment file (source this)
├── lxc-wrapper.sh                # Command wrapper
├── install-lxc-on-phone.sh       # Installer script
├── unpack-rootfs.sh              # Rootfs tarball unpacker
└── check-kernel-config.sh        # Kernel verification (on-device)
└── alpine-rootfs.tar.gz          # Rootfs tarball (if pushed)

Host-side scripts (not pushed):
├── lxc-doctor.sh                 # Preflight diagnostics
├── push-to-phone.sh              # Push artifacts to device
└── prepare-alpine-rootfs.sh      # Build rootfs tarball

/data/lxc/
└── containers/                   # Container storage
    └── alpine/
        ├── config                # Container configuration
        └── rootfs/               # Container root filesystem
```

## Build Configuration

The build disables features not needed/available on Android:

| Feature | Status | Reason |
|---------|--------|--------|
| libcap | disabled | Not available on Android |
| seccomp | disabled | Requires cross-compiled libseccomp |
| SELinux | disabled | Android SELinux differs from standard |
| AppArmor | disabled | Not available on Android |
| OpenSSL | disabled | Not required for basic operation |
| PAM | disabled | Not available on Android |
| D-Bus | disabled | Not required |
| io_uring | disabled | Not required |
| manpages | disabled | Reduces build deps |
| tests | disabled | Not needed for deployment |
| init scripts | disabled | Android doesn't use systemd/sysvinit |

## Runtime Paths

Configured for Android filesystem:

- **Runtime path**: `/data/local/tmp/lxc/run`
- **Container storage**: `$LXC_PATH` (set via environment)
- **Config**: `$PREFIX/etc/lxc/`

## Setting Up Alpine Container

### 1. Prepare Alpine rootfs tarball (on host)

```bash
./android/prepare-alpine-rootfs.sh
```

Output: `_artifacts/alpine-rootfs.tar.gz`

### 2. Push tarball to device

```bash
adb push _artifacts/alpine-rootfs.tar.gz /data/local/tmp/
```

Or, if you run `./android/push-to-phone.sh` after preparing the rootfs, the tarball is pushed automatically.

### 3. Unpack rootfs on device

```bash
adb shell su -c 'sh /data/local/tmp/unpack-rootfs.sh alpine'
```

### 4. Start container

```bash
# Foreground (interactive shell)
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-start -n alpine -F'

# Background (daemon)
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-start -n alpine'

# Attach to running container
adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-attach -n alpine'
```

## Kernel Requirements

Your Android kernel must have:

- `CONFIG_NAMESPACES=y`
- `CONFIG_UTS_NS=y`
- `CONFIG_IPC_NS=y`
- `CONFIG_PID_NS=y`
- `CONFIG_NET_NS=y`
- `CONFIG_USER_NS=y`
- `CONFIG_CGROUPS=y`
- `CONFIG_CGROUP_*` (various cgroup controllers)

Verify with `lxc-checkconfig` on the device.

## Source Modifications

Two files were patched for NDK compatibility:

1. `src/lxc/process_utils.h` - Guard `struct clone_args` against NDK's `linux/sched.h`
2. `src/lxc/open_utils.h` - Guard `struct open_how` against NDK's `linux/openat2.h`

## Files

- `cross/android-aarch64-api31.ini` - Meson cross-compilation file
- `build-android.sh` - Build script

## Binary Sizes (stripped, LTO)

| Binary | Size |
|--------|------|
| liblxc.so | ~1.2 MB |
| lxc-start | ~72 KB |
| lxc-attach | ~80 KB |
| lxc-stop | ~72 KB |
| lxc-info | ~72 KB |

## Troubleshooting

### "cannot find -lpthread"
The NDK provides pthread in libc. This shouldn't occur with the provided cross file.

### "struct clone_args redefinition"
Ensure the patched `process_utils.h` is being used.

### Runtime: "cannot open shared object file"
Set `LD_LIBRARY_PATH` to include the lib directory.

### Runtime: "operation not permitted"
Run as root (`su`) and ensure kernel has required namespace support.
