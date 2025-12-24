#!/usr/bin/env python3
"""
deploy.py - Rocky Linux LXC deployment on Android (ARM64)

TEAM_022: Migrated from Gentoo to Rocky Linux 10.
Deploys a Rocky Linux container with SSH access on a rooted Android device.
Binary Sovereignty: No compilation, immutable base, 2-year stability.

Usage:
    python3 deploy.py              # Interactive deployment (prompts for config)
    python3 deploy.py --yes        # Non-interactive (use defaults)
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
    prompt_config,
    uninstall,
)

# =============================================================================
# CLI Setup
# =============================================================================

app = typer.Typer(
    help="Deploy Rocky Linux in LXC on Android (ARM64)",
    no_args_is_help=False,
    add_completion=False,
)


# =============================================================================
# CLI Commands
# =============================================================================

@app.command()
def deploy(
    step: Optional[int] = typer.Option(None, "--step", "-s", help="Run specific step (1-6)"),
    clean: bool = typer.Option(False, "--clean", "-c", help="Clean host build files"),
    uninstall_flag: bool = typer.Option(False, "--uninstall", "-u", help="Remove Rocky Linux from device"),
    status: bool = typer.Option(False, "--status", help="Show deployment status"),
    network: bool = typer.Option(False, "--network", help="Setup bridge network"),
    restart: bool = typer.Option(False, "--restart", "-r", help="Restart container with updated boot script"),
    push_script: bool = typer.Option(False, "--push-script", "-p", help="Push rocky-lxc.sh to device (no restart)"),
    serial: Optional[str] = typer.Option(None, "--serial", "-d", help="Target device serial"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive mode (use defaults)"),
):
    """Deploy Rocky Linux in LXC on Android."""
    # Interactive config unless --yes or special commands
    if not (clean or uninstall_flag or status or network or restart or push_script or step or yes):
        cfg = prompt_config()
    else:
        cfg = Config()
    
    adb = ADB(serial)
    deployer = Deployer(cfg, adb)
    
    if clean:
        deployer.clean()
    elif uninstall_flag:
        uninstall(cfg, adb)
    elif status:
        deployer.status()
    elif network:
        _setup_network(deployer)
    elif restart:
        _restart_container(deployer)
    elif push_script:
        _push_script(deployer)
    elif step:
        steps: dict[int, Callable[[], None]] = {
            1: deployer.step1_build_lxc,
            2: deployer.step2_prepare_rootfs,
            3: deployer.step3_push_to_device,
            4: deployer.step4_install_lxc,
            5: deployer.step5_unpack_rootfs,
            6: deployer.step6_configure_rocky,
        }
        if step not in steps:
            die(f"Invalid step: {step} (must be 1-6)")
        steps[step]()
    else:
        deployer.run_all()


def _push_script(deployer: Deployer) -> None:
    """Push rocky-lxc.sh to device without restarting.
    
    TEAM_028: Added for quick script updates (e.g., TUN passthrough config).
    """
    step_header(0, 0, "Push Boot Script")
    
    cfg = deployer.cfg
    shell = deployer.shell
    d = cfg.device
    boot_script = "/data/adb/service.d/rocky-lxc.sh"
    
    if not deployer.adb.connected():
        die("No device connected")
    if not deployer.adb.has_root():
        die("Root access required")
    log_ok("Device connected with root")
    
    boot_script_local = cfg.repo_root / "android" / "rocky-lxc.sh"
    if not boot_script_local.exists():
        die(f"Boot script not found: {boot_script_local}")
    
    deployer.adb.push(boot_script_local, f"{d.tmp}/rocky-lxc.sh")
    shell.run(f"cp {d.tmp}/rocky-lxc.sh {boot_script}")
    shell.run(f"chmod 755 {boot_script}")
    
    log_ok(f"Script pushed to {boot_script}")
    console.print()
    console.print("[dim]Run [bold]rocky-lxc.sh restart[/bold] on device to apply changes[/dim]")


def _restart_container(deployer: Deployer) -> None:
    """Restart container with updated boot script, showing live output.
    
    TEAM_016: Added for testing suid/selinux fixes.
    """
    import subprocess
    import time
    from pathlib import Path
    
    step_header(0, 0, "Restart Container")
    
    cfg = deployer.cfg
    shell = deployer.shell
    d = cfg.device
    boot_script = "/data/adb/service.d/rocky-lxc.sh"
    
    # Ensure device connected
    if not deployer.adb.connected():
        die("No device connected")
    if not deployer.adb.has_root():
        die("Root access required")
    log_ok("Device connected with root")
    
    # Push updated boot script
    log("Pushing updated boot script...")
    boot_script_local = cfg.repo_root / "android" / "rocky-lxc.sh"
    if not boot_script_local.exists():
        die(f"Boot script not found: {boot_script_local}")
    deployer.adb.push(boot_script_local, f"{d.tmp}/rocky-lxc.sh")
    shell.run(f"cp {d.tmp}/rocky-lxc.sh {boot_script}")
    shell.run(f"chmod 755 {boot_script}")
    log_ok("Boot script updated")
    
    # Stop container with live output
    console.print()
    console.print("[bold yellow]=== STOPPING CONTAINER ===[/bold yellow]")
    console.print()
    
    # Run stop command and stream output
    # TEAM_025: Updated log path to rocky-lxc.log
    stop_cmd = ["adb", "shell", "su", "-c", f"{boot_script} stop 2>&1; cat /data/local/tmp/rocky-lxc.log | tail -20"]
    result = subprocess.run(stop_cmd, capture_output=False, text=True)
    
    time.sleep(2)
    
    # Start container with live output
    console.print()
    console.print("[bold green]=== STARTING CONTAINER ===[/bold green]")
    console.print()
    
    # Clear old log entries so we see fresh output
    shell.run("echo '=== RESTART ===' >> /data/local/tmp/rocky-lxc.log")
    
    # Run start in background, then tail the log
    start_cmd = ["adb", "shell", "su", "-c", f"{boot_script} start 2>&1"]
    result = subprocess.run(start_cmd, capture_output=False, text=True)
    
    # Show recent log
    console.print()
    console.print("[bold cyan]=== CONTAINER LOG ===[/bold cyan]")
    console.print()
    log_cmd = ["adb", "shell", "su", "-c", "tail -30 /data/local/tmp/rocky-lxc.log"]
    subprocess.run(log_cmd, capture_output=False, text=True)
    
    # Check container status
    console.print()
    console.print("[bold cyan]=== CONTAINER STATUS ===[/bold cyan]")
    console.print()
    status_cmd = ["adb", "shell", "su", "-c", f"{boot_script} status 2>&1 | head -20"]
    subprocess.run(status_cmd, capture_output=False, text=True)
    
    # Test mount options
    console.print()
    console.print("[bold cyan]=== MOUNT OPTIONS CHECK ===[/bold cyan]")
    console.print()
    mount_cmd = ["adb", "shell", "su", "-c", "mount | grep gentoo-rootfs"]
    subprocess.run(mount_cmd, capture_output=False, text=True)
    
    # Test sudo inside container
    # TEAM_020: Added HOME env var to fix "Failed to create directory //.cache/" error
    # TEAM_028: Replaced doas with sudo
    console.print()
    console.print("[bold cyan]=== SUDO/SUID TEST ===[/bold cyan]")
    console.print()
    lxc_prefix = d.lxc_prefix
    lxc_containers = d.lxc_containers
    sudo_cmd = ["adb", "shell", "su", "-c", 
                # TEAM_025: Updated container name to rocky
                # TEAM_029: Added -e flag to bypass seccomp/capability issues on Android
                f"HOME={d.tmp} LD_LIBRARY_PATH={lxc_prefix}/lib {lxc_prefix}/bin/lxc-attach -e -n rocky -P {lxc_containers} -- "
                f"sh -c 'ls -la /usr/bin/sudo; echo; /usr/bin/sudo id 2>&1 || echo SUDO FAILED'"]
    subprocess.run(sudo_cmd, capture_output=False, text=True)
    
    console.print()
    log_ok("Restart complete - check output above for results")


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
