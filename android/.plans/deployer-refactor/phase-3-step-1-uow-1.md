# Phase 3 - Step 1 - UoW 1: Update deploy.py to use deployer/

**Parent:** phase-3.md → Step 1  
**Goal:** Replace inline class definitions with imports from deployer/

## Input Context
- All deployer/*.py modules must exist and import successfully
- Read current `deploy.py` lines 1815-1908 (CLI section to keep)

## Tasks

### 1. Backup original deploy.py
```bash
cp deploy.py deploy.py.bak
```

### 2. Replace deploy.py with thin CLI wrapper

```python
#!/usr/bin/env python3
"""
deploy.py - Gentoo Linux LXC deployment on Android (ARM64)

Deploys a Gentoo Linux container with SSH access on a rooted Android device.

Usage:
    python3 deploy.py              # Full deployment
    python3 deploy.py --step N     # Run specific step (1-6)
    python3 deploy.py --clean      # Clean everything
    python3 deploy.py --status     # Check current status
"""

from typing import Callable, Optional

import typer
from rich.panel import Panel

from deployer import (
    Config,
    ADB,
    Deployer,
    console,
    log,
    log_ok,
    log_warn,
    die,
    step_header,
)

# =============================================================================
# CLI Setup
# =============================================================================

app = typer.Typer(
    help="Deploy Gentoo Linux in LXC on Android (ARM64)",
    no_args_is_help=False,
    add_completion=False,
)


# =============================================================================
# CLI Commands
# =============================================================================

@app.command()
def deploy(
    step: Optional[int] = typer.Option(None, "--step", "-s", help="Run specific step (1-6)"),
    clean: bool = typer.Option(False, "--clean", "-c", help="Clean everything"),
    status: bool = typer.Option(False, "--status", help="Show deployment status"),
    network: bool = typer.Option(False, "--network", help="Setup bridge network"),
    serial: Optional[str] = typer.Option(None, "--serial", "-d", help="Target device serial"),
):
    """Deploy Gentoo Linux in LXC on Android."""
    cfg = Config()
    adb = ADB(serial)
    deployer = Deployer(cfg, adb)
    
    if clean:
        deployer.clean()
    elif status:
        deployer.status()
    elif network:
        _setup_network(deployer)
    elif step:
        steps: dict[int, Callable[[], None]] = {
            1: deployer.step1_build_lxc,
            2: deployer.step2_prepare_rootfs,
            3: deployer.step3_push_to_device,
            4: deployer.step4_install_lxc,
            5: deployer.step5_unpack_rootfs,
            6: deployer.step6_configure_gentoo,
        }
        if step not in steps:
            die(f"Invalid step: {step} (must be 1-6)")
        steps[step]()
    else:
        deployer.run_all()


def _setup_network(deployer: Deployer) -> None:
    """Setup bridge networking with NAT."""
    step_header(0, 0, "Setup Bridge Network")
    
    net = deployer.cfg.network
    shell = deployer.shell
    host_iface = deployer._detect_host_interface()
    
    # Create bridge
    _, rc = shell.run(f"ip link show {net.bridge} 2>/dev/null")
    if rc != 0:
        log(f"Creating bridge {net.bridge}...")
        shell.run(f"ip link add name {net.bridge} type bridge")
        shell.run(f"ip addr add {net.bridge_gateway}/24 dev {net.bridge}")
        shell.run(f"ip link set {net.bridge} up")
        log_ok(f"Bridge created: {net.bridge_gateway}")
    else:
        log(f"Bridge {net.bridge} exists")
    
    # IP forwarding
    shell.run("sysctl -w net.ipv4.ip_forward=1")
    log_ok("IP forwarding enabled")
    
    # NAT rules
    nat = f"-s {net.bridge_subnet} -o {host_iface} -j MASQUERADE"
    _, rc = shell.run(f"iptables -t nat -C POSTROUTING {nat} 2>/dev/null")
    if rc != 0:
        shell.run(f"iptables -t nat -A POSTROUTING {nat}")
        log_ok(f"NAT rule added for {net.bridge_subnet} via {host_iface}")
    
    # Forward rules
    fwd_out = f"-i {net.bridge} -o {host_iface} -j ACCEPT"
    _, rc = shell.run(f"iptables -C FORWARD {fwd_out} 2>/dev/null")
    if rc != 0:
        shell.run(f"iptables -A FORWARD {fwd_out}")
    
    fwd_in = f"-i {host_iface} -o {net.bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT"
    _, rc = shell.run(f"iptables -C FORWARD {fwd_in} 2>/dev/null")
    if rc != 0:
        shell.run(f"iptables -A FORWARD {fwd_in}")
    
    log_ok("Bridge network ready")
    
    console.print()
    console.print("Add to container config:")
    console.print(f"  lxc.net.0.type = veth")
    console.print(f"  lxc.net.0.link = {net.bridge}")
    console.print(f"  lxc.net.0.flags = up")
    console.print(f"  lxc.net.0.ipv4.address = {net.bridge_container_ip}/24")
    console.print(f"  lxc.net.0.ipv4.gateway = {net.bridge_gateway}")


if __name__ == "__main__":
    app()
```

### 3. Verify CLI works:
```bash
python3 deploy.py --help
```

## Expected Output
- `deploy.py` reduced to ~120 lines
- CLI help displays correctly
- All imports resolve

## Exit Criteria
- [ ] deploy.py replaced with thin wrapper
- [ ] `python3 deploy.py --help` works
- [ ] Backup exists as deploy.py.bak
