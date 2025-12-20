# TEAM_001: Investigate deploy.py Bugs

## Task
Investigate bugs and fragilities in `/home/vince/Projects/android/lxc/android/deploy.py` by comparing with `deploy_original.py`.

## Status
- [x] Team registered
- [x] Investigation complete
- [x] Bugs identified
- [x] Fixes applied
- [x] Verification complete (syntax check passed)

## Findings

### Bugs Fixed:

1. **Missing `container_ready_poll_interval` config** (line ~203)
   - deploy_original.py had it, deploy.py didn't
   - Fixed: Added `container_ready_poll_interval: float = 0.5`

2. **`LXC.use()` didn't validate None** (line ~332-337)
   - Could silently accept None
   - Fixed: Added explicit None check with ValueError

3. **`ADB.write()` didn't handle push failures** (line ~279-290)
   - Push could fail silently
   - Fixed: Check return value and raise RuntimeError on failure

4. **`Crypto.parse_gentoo_digests` parsing fragility** (line ~447-472)
   - Would exit SHA512 section prematurely on non-matching lines
   - Fixed: Continue scanning until end of section or new hash type

5. **SFTP server path hardcoded wrong** (line ~1005-1011)
   - `/usr/lib64/misc/sftp-server` may not exist on all Gentoo installs
   - Fixed: Auto-detect from multiple candidate paths

6. **Missing home directory ownership** (line ~1033-1035)
   - deploy_original.py explicitly set home dir ownership
   - Fixed: Added `chown {user}:{user} {home}`

7. **LXC methods could use None container name** (line ~351-397)
   - `name or self._container` could still be None
   - Fixed: Added `_resolve_name()` helper that raises ValueError

8. **`_extract_on_host_and_push` poor error handling** (line ~1200-1224)
   - `tar_cmd` return code not checked, stderr not captured
   - Fixed: Capture stderr, wait for both processes, check both return codes

9. **Missing timeouts on LXC operations** (multiple lines)
   - Several `self.lxc.run()` calls lacked explicit timeouts
   - Fixed: Added `timeout=self.cfg.timeout_short` to all affected calls

10. **Wait loop used hardcoded poll interval** (line ~952)
    - Should use configurable `container_ready_poll_interval`
    - Fixed: Use `self.cfg.container_ready_poll_interval`

## Handoff Notes
- All fixes applied and syntax verified with `python3 -m py_compile deploy.py`
- No runtime testing performed (requires Android device)
- Code follows patterns from deploy_original.py for robustness
