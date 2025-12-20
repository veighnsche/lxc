# TEAM_002: Deploy.py Complete Rewrite - Interactive Shell Paradigm

## Task
1. Find remaining bugs/edge cases in deploy.py
2. **COMPLETE REWRITE** around interactive shell paradigm (per user request)
3. Test deployment on connected device (18271FDF600EJW)

## Status
- [x] Team registered
- [x] Read full deploy.py
- [x] Identify bugs/edge cases
- [x] **Complete rewrite** - DeviceShell is now THE primary interface
- [x] Test on device 

## Device Info
- Serial: 18271FDF600EJW
- Has root via `su` 

## Architecture Rewrite

### Old Architecture (REMOVED)
```python
# Every command spawned a new shell with quoting nightmare
adb shell su -c "echo 'hello'"     # Quoting hell
adb shell su -c "cat '/path'"      # More quoting
adb shell su -c "cmd with $vars"   # Escaping madness
```

### New Architecture
```python
# DeviceShell - ONE persistent root shell for everything
class DeviceShell:
    def connect() -> bool      # Establish persistent root session
    def disconnect() -> None   # Close session
    def run(cmd) -> (str, int) # Execute, return (output, rc)
    def run_ok(cmd) -> bool    # Execute, return success
    def run_output(cmd) -> str # Execute, return stdout
    def exists(path) -> bool   # Check path exists
    def mkdir(path) -> None    # Create directory
    def rm(path) -> None       # Remove path
    def mount/umount/...       # All device operations

class ADB:
    shell: DeviceShell         # THE interface for device commands
    def push/pull(...)         # File transfers only
    def write_file(...)        # Push temp + mv
    # All other ops delegate to self.shell

class LXC:
    shell: DeviceShell         # Direct shell access
    # All container ops via persistent shell
```

### Key Changes
1. **DeviceShell** is now the PRIMARY interface (not a helper)
2. **ADB.su()** removed - all shell ops go through `shell.run()`
3. **No quoting** - commands sent raw via stdin
4. **Faster** - one shell for entire session, no spawn overhead
5. **Simpler code** - no escaping hell, just f-strings

## Testing Results
```
Testing new DeviceShell paradigm...
 DeviceShell.connect()
 shell.run(id -u) -> '0' (rc=0)
 shell.run(echo) -> 'hello world'
 shell.exists(/data) -> True
 shell.run_ok(true) -> True
 shell.run_output(pwd) -> '/'
 DeviceShell.disconnect()

Testing ADB integration...
 Device: 18271FDF600EJW
 has_root: True
 shell.alive: True
 adb.exists(/data): True
 adb.close()

All tests passed!
```

## Files Modified
- `deploy.py`: Complete rewrite of ADB/shell architecture

## Handoff Notes
- Syntax verified: `python3 -m py_compile deploy.py` 
- All tests pass 
- `--status` command works 
- Full deployment ready to test (device needs network for stage3)
