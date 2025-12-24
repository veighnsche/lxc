#!/usr/bin/env python3
"""
TEAM_029: Reliable root access to Rocky LXC container.
Usage: python3 container_shell.py "command to run"
"""
import sys
from deployer import Config, ADB, Deployer

def run_in_container(cmd: str) -> tuple[str, int]:
    """Run command as root in container using deployer API."""
    cfg = Config()
    adb = ADB('18271FDF600EJW')
    deployer = Deployer(cfg, adb)
    deployer.lxc.use('rocky')
    return deployer.lxc.run(cmd, check=False, timeout=60)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 container_shell.py 'command'")
        sys.exit(1)
    
    cmd = sys.argv[1]
    out, rc = run_in_container(cmd)
    print(out)
    sys.exit(rc)
