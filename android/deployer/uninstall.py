"""Gentoo LXC Uninstall - Complete removal from Android device.

This is a first-class operation with proper error handling.
Each step is isolated, has timeouts, and reports status clearly.
Failures in one step do not prevent other steps from running.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import Config
from .adb import ADB, DeviceShell
from .lxc import LXC
from .console import step_header, log, log_ok, log_warn, log_err, die

console = Console()


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class UninstallStep:
    """Track status of each uninstall step."""
    name: str
    status: StepStatus = StepStatus.PENDING
    message: str = ""
    
    def success(self, msg: str = "") -> None:
        self.status = StepStatus.SUCCESS
        self.message = msg
    
    def skip(self, msg: str = "") -> None:
        self.status = StepStatus.SKIPPED
        self.message = msg
    
    def fail(self, msg: str = "") -> None:
        self.status = StepStatus.FAILED
        self.message = msg


class Uninstaller:
    """Handles complete removal of Gentoo from Android device.
    
    Design principles:
    - Each step is independent and has a timeout
    - Failures are logged but don't stop subsequent steps
    - All steps are tracked and summarized at the end
    - No silent failures - everything is reported
    """
    
    TIMEOUT_SHORT = 5
    TIMEOUT_MEDIUM = 30
    TIMEOUT_LONG = 120
    
    def __init__(self, cfg: Config, adb: ADB):
        self.cfg = cfg
        self.adb = adb
        self.shell: Optional[DeviceShell] = None
        self.lxc: Optional[LXC] = None
        self.steps: list[UninstallStep] = []
        
    def _add_step(self, name: str) -> UninstallStep:
        step = UninstallStep(name)
        self.steps.append(step)
        return step
    
    def _init_connection(self) -> bool:
        """Initialize device connection with proper error handling."""
        step = self._add_step("Connect to device")
        step.status = StepStatus.RUNNING
        log("Connecting to device...")
        
        try:
            if not self.adb.connected():
                step.fail("Device not connected")
                log_err("Device not connected - connect via USB and try again")
                return False
            
            if not self.adb.has_root():
                step.fail("Root access required")
                log_err("Root access required - ensure device is rooted")
                return False
            
            self.shell = self.adb.shell
            self.lxc = LXC(self.adb, self.cfg)
            step.success(f"Connected to {self.adb.serial_number()}")
            log_ok(f"Connected to {self.adb.serial_number()}")
            return True
            
        except Exception as e:
            step.fail(str(e))
            log_err(f"Connection failed: {e}")
            return False
    
    def _stop_container(self) -> None:
        """Stop the container gracefully, then forcefully if needed."""
        step = self._add_step("Stop container")
        step.status = StepStatus.RUNNING
        log("Stopping container...")
        
        container = self.cfg.container_name
        
        try:
            # Check if container exists
            if not self.lxc.exists(container):
                step.skip("Container does not exist")
                log("Container does not exist")
                return
            
            # Check if running
            if not self.lxc.running(container):
                step.skip("Container not running")
                log("Container not running")
                return
            
            # Try graceful stop first - show Gentoo shutdown output
            log("  Attempting graceful shutdown (showing Gentoo output)...")
            try:
                # Send shutdown signal and watch the output
                console.print("[dim]  --- Gentoo shutdown output ---[/dim]")
                # Run poweroff inside container and capture output
                shutdown_out, _ = self.lxc.run("poweroff 2>&1 || true", name=container, check=False, timeout=5)
                if shutdown_out:
                    for line in shutdown_out.strip().split('\n'):
                        console.print(f"[dim]  {line}[/dim]")
                # Wait for container to stop with progress
                import time
                for i in range(self.TIMEOUT_MEDIUM):
                    if not self.lxc.running(container):
                        console.print("[dim]  --- Shutdown complete ---[/dim]")
                        step.success("Stopped gracefully")
                        log_ok("Container stopped gracefully")
                        return
                    time.sleep(1)
                    if i % 5 == 0:
                        console.print(f"[dim]  Waiting for shutdown... ({i}s)[/dim]")
                # If still running after timeout, fall through to force kill
                log_warn("Graceful shutdown timed out")
            except Exception as e:
                log_warn(f"Graceful stop failed: {e}")
            
            # Force kill if graceful failed
            log("  Forcing container termination...")
            try:
                self.lxc.stop(container, kill=True)
                step.success("Force killed")
                log_ok("Container force killed")
                return
            except Exception as e:
                log_warn(f"Force kill failed: {e}")
            
            # Last resort: kill processes directly
            log("  Killing container processes directly...")
            try:
                self.shell.run(f"pkill -9 -f 'lxc-start.*{container}' 2>/dev/null || true", 
                              timeout=self.TIMEOUT_SHORT)
                # Kill any processes in container cgroup
                cgroup_procs = f"/sys/fs/cgroup/lxc.payload.{container}/cgroup.procs"
                self.shell.run(f"cat {cgroup_procs} 2>/dev/null | xargs -r kill -9 2>/dev/null || true",
                              timeout=self.TIMEOUT_SHORT)
                step.success("Processes killed directly")
                log_ok("Container processes killed")
            except Exception as e:
                step.fail(f"Could not stop: {e}")
                log_err(f"Failed to stop container: {e}")
                
        except Exception as e:
            step.fail(str(e))
            log_err(f"Error stopping container: {e}")
    
    def _remove_iptables_rules(self) -> None:
        """Remove iptables rules added by boot script."""
        step = self._add_step("Remove iptables rules")
        step.status = StepStatus.RUNNING
        log("Removing iptables rules...")
        
        container_ip = self.cfg.network.container_ip
        errors = []
        
        rules = [
            # Broadcast/multicast DROP rules (security hardening)
            "iptables -D INPUT -d 224.0.0.0/4 -j DROP",
            "iptables -D INPUT -d 255.255.255.255 -j DROP",
        ]
        
        for rule in rules:
            try:
                self.shell.run(f"{rule} 2>/dev/null || true", timeout=self.TIMEOUT_SHORT)
            except Exception as e:
                errors.append(str(e))
        
        if errors:
            step.success(f"Removed (with {len(errors)} warnings)")
            log_ok(f"iptables rules removed ({len(errors)} warnings)")
        else:
            step.success("All rules removed")
            log_ok("iptables rules removed")
    
    def _remove_arp_entries(self) -> None:
        """Remove static ARP entries."""
        step = self._add_step("Remove ARP entries")
        step.status = StepStatus.RUNNING
        log("Removing ARP entries...")
        
        gateway = self.cfg.network.container_gateway
        
        try:
            # Try common interface names
            for iface in ["wlan0", "eth0", "wlan1"]:
                self.shell.run(f"ip neigh del {gateway} dev {iface} 2>/dev/null || true",
                              timeout=self.TIMEOUT_SHORT)
            step.success()
            log_ok("ARP entries removed")
        except Exception as e:
            step.fail(str(e))
            log_warn(f"ARP removal had issues: {e}")
    
    
    def _unmount_rootfs(self) -> None:
        """Unmount rootfs filesystem."""
        step = self._add_step("Unmount rootfs")
        step.status = StepStatus.RUNNING
        log("Unmounting rootfs...")
        
        rootfs = self.cfg.device.rootfs_path(self.cfg.container_name)
        
        try:
            if not self.adb.is_mounted(rootfs):
                step.skip("Not mounted")
                log("Rootfs not mounted")
                return
            
            # Try lazy unmount first (safer)
            self.shell.run(f"umount -l {rootfs} 2>/dev/null || true", timeout=self.TIMEOUT_SHORT)
            
            # Verify
            if self.adb.is_mounted(rootfs):
                # Force unmount
                self.shell.run(f"umount -f {rootfs} 2>/dev/null || true", timeout=self.TIMEOUT_SHORT)
            
            if self.adb.is_mounted(rootfs):
                step.fail("Could not unmount")
                log_err("Failed to unmount rootfs")
            else:
                step.success()
                log_ok("Rootfs unmounted")
                
        except Exception as e:
            step.fail(str(e))
            log_err(f"Unmount error: {e}")
    
    def _detach_loop_devices(self) -> None:
        """Detach loop devices associated with rootfs image."""
        step = self._add_step("Detach loop devices")
        step.status = StepStatus.RUNNING
        log("Detaching loop devices...")
        
        rootfs_image = self.cfg.device.rootfs_image
        detached = 0
        
        try:
            loop_out, _ = self.shell.run(f"losetup -j {rootfs_image} 2>/dev/null || true",
                                         timeout=self.TIMEOUT_SHORT)
            
            for line in (loop_out or "").split('\n'):
                if not line.strip():
                    continue
                loop_dev = line.split(':')[0]
                if loop_dev:
                    self.shell.run(f"losetup -d {loop_dev} 2>/dev/null || true",
                                  timeout=self.TIMEOUT_SHORT)
                    detached += 1
                    log(f"  Detached: {loop_dev}")
            
            if detached > 0:
                step.success(f"{detached} device(s)")
                log_ok(f"Detached {detached} loop device(s)")
            else:
                step.skip("No loop devices")
                log("No loop devices to detach")
                
        except Exception as e:
            step.fail(str(e))
            log_warn(f"Loop device cleanup had issues: {e}")
    
    def _remove_boot_scripts(self) -> None:
        """Remove boot scripts from device."""
        step = self._add_step("Remove boot scripts")
        step.status = StepStatus.RUNNING
        log("Removing boot scripts...")
        
        # TEAM_025: Added Rocky scripts alongside Gentoo for backward compatibility
        scripts = [
            "/data/adb/service.d/gentoo-lxc.sh",
            "/data/adb/service.d/gentoo-shell.sh",
            "/data/adb/service.d/rocky-lxc.sh",
            "/data/local/tmp/g",
            "/data/local/tmp/gentoo-shell.sh",
            "/data/local/tmp/rocky-lxc.sh",
        ]
        
        removed = 0
        try:
            for script in scripts:
                exists = self.adb.exists(script)
                if exists:
                    self.shell.run(f"rm -f {script}", timeout=self.TIMEOUT_SHORT)
                    removed += 1
            
            step.success(f"{removed} file(s)")
            log_ok(f"Removed {removed} boot script(s)")
        except Exception as e:
            step.fail(str(e))
            log_err(f"Boot script removal failed: {e}")
    
    def _remove_container_config(self) -> None:
        """Remove container configuration directory."""
        step = self._add_step("Remove container config")
        step.status = StepStatus.RUNNING
        log("Removing container configuration...")
        
        container_path = self.cfg.device.container_path(self.cfg.container_name)
        
        try:
            if not self.adb.exists(container_path, is_dir=True):
                step.skip("Not found")
                log("Container config not found")
                return
            
            self.adb.rm(container_path)
            step.success()
            log_ok("Container config removed")
        except Exception as e:
            step.fail(str(e))
            log_err(f"Container config removal failed: {e}")
    
    def _remove_rootfs_image(self) -> None:
        """Remove rootfs image file (the big one)."""
        step = self._add_step("Remove rootfs image")
        step.status = StepStatus.RUNNING
        log("Removing rootfs image...")
        
        rootfs_image = self.cfg.device.rootfs_image
        
        try:
            if not self.adb.exists(rootfs_image):
                step.skip("Not found")
                log("Rootfs image not found")
                return
            
            # Get size before removing
            size_out, _ = self.shell.run(f"stat -c%s {rootfs_image} 2>/dev/null || echo 0",
                                         timeout=self.TIMEOUT_SHORT)
            size_mb = int(size_out.strip() or 0) // (1024 * 1024)
            
            # Remove (this may take a moment for large files)
            self.adb.rm(rootfs_image)
            
            step.success(f"{size_mb} MB freed")
            log_ok(f"Rootfs image removed ({size_mb} MB freed)")
        except Exception as e:
            step.fail(str(e))
            log_err(f"Rootfs image removal failed: {e}")
    
    def _remove_lxc_installation(self) -> None:
        """Remove LXC binaries and directories."""
        step = self._add_step("Remove LXC installation")
        step.status = StepStatus.RUNNING
        log("Removing LXC installation...")
        
        d = self.cfg.device
        paths = [d.lxc_prefix, d.lxc_runtime, d.lxc_containers, "/data/lxc"]
        removed = 0
        
        try:
            for path in paths:
                if self.adb.exists(path, is_dir=True):
                    self.adb.rm(path)
                    removed += 1
                    log(f"  Removed: {path}")
            
            step.success(f"{removed} dir(s)")
            log_ok(f"Removed {removed} LXC directory(s)")
        except Exception as e:
            step.fail(str(e))
            log_err(f"LXC removal failed: {e}")
    
    def _clean_cgroups(self) -> None:
        """Clean up cgroup entries."""
        step = self._add_step("Clean cgroups")
        step.status = StepStatus.RUNNING
        log("Cleaning cgroup entries...")
        
        container = self.cfg.container_name
        cgroups = [
            f"/sys/fs/cgroup/lxc.payload.{container}",
            f"/sys/fs/cgroup/lxc.monitor.{container}",
            "/sys/fs/cgroup/lxc",
        ]
        
        try:
            for cgroup in cgroups:
                self.shell.run(f"rmdir {cgroup} 2>/dev/null || true", timeout=self.TIMEOUT_SHORT)
            
            step.success()
            log_ok("Cgroup entries cleaned")
        except Exception as e:
            step.fail(str(e))
            log_warn(f"Cgroup cleanup had issues: {e}")
    
    def _clean_temp_files(self) -> None:
        """Remove temporary files."""
        step = self._add_step("Clean temp files")
        step.status = StepStatus.RUNNING
        log("Cleaning temp files...")
        
        d = self.cfg.device
        # TEAM_025: Added Rocky patterns alongside Gentoo for backward compatibility
        patterns = [
            f"{d.tmp}/stage3*.tar.xz",
            f"{d.tmp}/stage3*.tar.gz",
            f"{d.tmp}/rocky-*.tar.xz",
            f"{d.tmp}/gentoo-*.sh",
            f"{d.tmp}/rocky-*.sh",
            f"{d.tmp}/lxc-*.tar.gz",
            f"{d.tmp}/gentoo-lxc.log",
            f"{d.tmp}/rocky-lxc.log",
        ]
        
        try:
            for pattern in patterns:
                self.shell.run(f"rm -f {pattern} 2>/dev/null || true", timeout=self.TIMEOUT_SHORT)
            
            step.success()
            log_ok("Temp files cleaned")
        except Exception as e:
            step.fail(str(e))
            log_warn(f"Temp cleanup had issues: {e}")
    
    def _show_summary(self) -> bool:
        """Display summary of all steps."""
        console.print()
        
        table = Table(title="Uninstall Summary", border_style="cyan")
        table.add_column("Step", style="cyan")
        table.add_column("Status")
        table.add_column("Details", style="dim")
        
        success_count = 0
        fail_count = 0
        
        for step in self.steps:
            if step.status == StepStatus.SUCCESS:
                status = "[green]✓ Success[/green]"
                success_count += 1
            elif step.status == StepStatus.SKIPPED:
                status = "[yellow]○ Skipped[/yellow]"
                success_count += 1  # Skipped is OK
            elif step.status == StepStatus.FAILED:
                status = "[red]✗ Failed[/red]"
                fail_count += 1
            else:
                status = "[dim]? Unknown[/dim]"
            
            table.add_row(step.name, status, step.message)
        
        console.print(table)
        console.print()
        
        if fail_count == 0:
            console.print(Panel.fit(
                "[bold green]Gentoo Completely Uninstalled[/bold green]\n\n"
                f"All {success_count} steps completed successfully.\n\n"
                "To reinstall:\n"
                "  python3 deploy.py",
                title="✓ Complete",
                border_style="green"
            ))
            return True
        else:
            console.print(Panel.fit(
                f"[bold yellow]Uninstall Partially Complete[/bold yellow]\n\n"
                f"Success: {success_count}, Failed: {fail_count}\n\n"
                "Some components may remain on device.\n"
                "Check the summary above for details.",
                title="⚠ Warning",
                border_style="yellow"
            ))
            return False
    
    def run(self) -> bool:
        """Execute the full uninstall process.
        
        Returns True if all steps succeeded, False otherwise.
        """
        step_header(0, 0, "Uninstall Gentoo from Device")
        
        # Initialize connection
        if not self._init_connection():
            return False
        
        # Run all cleanup steps (order matters for some)
        self._stop_container()
        self._remove_iptables_rules()
        self._remove_arp_entries()
        self._unmount_rootfs()
        self._detach_loop_devices()
        self._remove_boot_scripts()
        self._remove_container_config()
        self._remove_rootfs_image()
        self._remove_lxc_installation()
        self._clean_cgroups()
        self._clean_temp_files()
        
        # Show summary
        return self._show_summary()


def uninstall(cfg: Config, adb: ADB) -> bool:
    """Uninstall Gentoo from device.
    
    This is the main entry point for uninstallation.
    Returns True if successful, False otherwise.
    """
    uninstaller = Uninstaller(cfg, adb)
    return uninstaller.run()
