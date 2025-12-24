# TEAM_026: Investigate Step 6 Hang Issue

## Bug Report
- **Symptom**: Deploy script hangs at Step 6 when starting container via boot script
- **Expected**: Container starts within timeout and deployment continues
- **Actual**: Script hangs indefinitely at `boot_script start/restart` command

## Phase 1: Understanding the Symptom

### What happens:
1. Steps 1-5 complete successfully
2. Step 6 calls `rocky-lxc.sh start` or `rocky-lxc.sh restart`
3. The shell.run() call never returns
4. No error output, just hangs

### Key code location:
- `deployer/deployer.py` line ~628-631
- `self.shell.run(f"{boot_script} restart 2>&1", timeout=120)`

### Questions to answer:
1. Why does the boot script hang?
2. What command inside boot script is blocking?
3. Is it lxc-start itself? Network config? Something else?

## Phase 2: Hypotheses

### H1: lxc-start is hanging (waiting for systemd init)
- systemd inside container may be waiting for something
- Confidence: HIGH
- Evidence needed: Check if lxc-start process exists and what it's waiting for

### H2: Boot script has infinite loop or blocking command
- Some command in rocky-lxc.sh never returns
- Confidence: MEDIUM
- Evidence needed: Trace which command in boot script hangs

### H3: Container starts but lxc-attach fails in ready check
- Container may start but become unresponsive
- Confidence: LOW
- Evidence needed: Check if container PID exists

## Investigation Progress

### ROOT CAUSE FOUND

**Problem**: `lxc-stop -t 5` doesn't honor timeout on Android
- Multiple `lxc-stop` processes pile up, all hanging
- Each restart/start calls stop first, which never returns
- Container PID exists but lxc-stop waits forever

**Evidence** (from `ps -ef`):
```
root  7042  lxc-start -n rocky (original container)
root  7043  sleep infinity (container init)
root  7276  lxc-stop -n rocky -t 5 (HUNG)
root  8655  lxc-stop -n rocky -t 5 (HUNG)
root  9973  lxc-stop -n rocky -t 5 (HUNG)
... 6+ hung lxc-stop processes
```

### Fix Applied

Modified `stop_container()` in `rocky-lxc.sh`:
1. Kill any existing hung lxc-stop processes first
2. Use `timeout` command wrapper instead of `-t` flag
3. Fallback to background + sleep + kill if no timeout command
4. Also kill `sleep infinity` processes directly

### Additional Fix: lxc-attach capability issues

Modified `deployer/lxc.py`:
- Use `--keep-env --elevated-privileges` instead of `--clear-env`
- Explicitly use `/bin/bash -c` with proper PATH export

## DEPLOYMENT SUCCESSFUL

All fixes applied and verified:
- ✅ Rocky Linux 10 GenericCloud deployed
- ✅ Container starts with systemd
- ✅ IPVLAN L2 networking working
- ✅ User `vince` created with password
- ✅ Root password set
- ✅ SSH key installed for vince
- ✅ sudo working
- ✅ SSH connection verified from host

## Handoff Checklist

- [x] Project builds cleanly
- [x] All deployment steps pass
- [x] Container running with systemd
- [x] Team file updated
- [x] Breadcrumbs in code (TEAM_026 comments)
