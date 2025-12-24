# TEAM_029: Investigate lxc-attach Failure

## Bug Report

### Symptoms
1. `lxc-attach` fails with errors:
   - `Unsupported config key "lxc.seccomp"`
   - `Failed to drop capabilities`
   - `Failed to attach to container`
2. `/usr/bin/sudo` is "inaccessible or not found"
3. SSH connection to Rocky container fails

### Environment
- Container IS running (PID 154499)
- Container has IP 192.168.178.100
- Network appears functional (362MB transferred)

### Error Output
```
lxc-attach: rocky: ../src/lxc/confile.c: set_config_unsupported_key: 166 Invalid argument - Unsupported config key "lxc.seccomp"
lxc-attach: rocky: ../src/lxc/attach.c: drop_capabilities: 781 Success - -1 - Failed to drop capabilities
lxc-attach: rocky: ../src/lxc/attach.c: do_attach: 1380 Failed to attach to container

/system/bin/sh: /usr/bin/sudo: inaccessible or not found
SUDO FAILED
```

### Context
- TEAM_028 just added TUN passthrough config
- Changes: `lxc.cgroup2.devices.allow = c 10:200 rwm` and TUN bind mount

## Investigation

### Phase 1: Understanding
- Container starts fine (RUNNING state)
- `lxc-attach` fails when trying to enter container
- The `lxc.seccomp` error is suspicious - we didn't add that key
- The "sudo not found" is actually coming from Android shell fallback, not the container

### Hypotheses
1. **H1**: The generated config has an `lxc.seccomp` line that wasn't there before
2. **H2**: There's a stale config or the config wasn't regenerated properly
3. **H3**: The TUN mount entry syntax is causing parsing issues
4. **H4**: LXC version mismatch - seccomp key format changed

### Root Cause (CONFIRMED)
**H4 variant**: `lxc-attach` internally tries to use seccomp and drop capabilities when entering a container. The Android kernel doesn't fully support these features for LXC.

**Evidence:**
- `lxc-attach -e` (elevated privileges) works perfectly
- Without `-e`, lxc-attach fails with seccomp/capability errors
- The `common.conf` was already patched correctly

### Fix Applied
Added `-e` flag to all `lxc-attach` calls in:
- `rocky-lxc.sh` (5 occurrences)
- `deploy.py` (1 occurrence)

The `deployer/lxc.py` already had `--elevated-privileges`.

## Status
- [x] Root cause identified
- [x] Fix applied
- [x] Bugfixes codified in deployer.py

## Deploy Script Changes (TEAM_029)

### 1. sudoers.d/{user} config (deployer.py:698-704)
```python
# Creates /etc/sudoers.d/{user} with NOPASSWD
# Belt-and-suspenders approach - wheel group + explicit user
self.lxc.run("mkdir -p /etc/sudoers.d", ...)
self.lxc.run(f"echo '{user} ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/{user}", ...)
```

### 2. tailscaled systemd override (deployer.py:746-755)
```python
# Pre-configures /etc/systemd/system/tailscaled.service.d/override.conf
# Prevents exit code 208/STDIN in LXC container
[Service]
StandardInput=null
StandardOutput=journal
StandardError=journal
```

### 3. lxc-attach -e flag (already present)
- `deployer/lxc.py:90` - uses `--elevated-privileges`
- `rocky-lxc.sh` - all calls have `-e` flag
- `deploy.py` - sudo test uses `-e` flag

## systemd 208/STDIN Bug - SOLVED

### Symptom
ALL systemd services failed with exit code 208/STDIN on Android LXC kernel.
Even simple services like `/bin/echo hello` failed.

### Root Cause (FOUND via strace)
```
openat(AT_FDCWD, "/dev/null", O_RDONLY|O_NOCTTY) = -1 EPERM (Operation not permitted)
```

systemd-executor could not open `/dev/null` because **cgroup2 device permissions
were missing**. The LXC config only allowed TUN device (10:200), but standard
devices like /dev/null (1:3) were not permitted.

### Fix (Implemented)
Added cgroup2 device permissions in `rocky-lxc.sh:update_config()`:

```
lxc.cgroup2.devices.allow = c 1:3 rwm   # /dev/null
lxc.cgroup2.devices.allow = c 1:5 rwm   # /dev/zero
lxc.cgroup2.devices.allow = c 1:7 rwm   # /dev/full
lxc.cgroup2.devices.allow = c 1:8 rwm   # /dev/random
lxc.cgroup2.devices.allow = c 1:9 rwm   # /dev/urandom
lxc.cgroup2.devices.allow = c 5:0 rwm   # /dev/tty
lxc.cgroup2.devices.allow = c 5:1 rwm   # /dev/console
lxc.cgroup2.devices.allow = c 5:2 rwm   # /dev/ptmx
lxc.cgroup2.devices.allow = c 136:* rwm # pts devices
```

### Verification
```bash
# systemd services now work properly
python3 container_shell.py "systemctl status tailscaled"

# Authenticate via SSH
ssh vince@192.168.178.100
sudo tailscale up
```

### Investigation Trail
1. Initial hypothesis: SELinux context on /dev/null - WRONG (SELinux disabled in container)
2. Checked dbus-daemon - installed but didn't fix
3. Checked /dev/console - created but didn't fix
4. **strace on systemd PID 1** revealed EPERM on /dev/null
5. Checked cgroup2 - no devices controller, but `lxc.cgroup2.devices.allow` still applies
6. Added device permissions - **FIXED**
