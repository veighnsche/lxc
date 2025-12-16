#!/usr/bin/env python3
"""
deploy.py - Python-based LXC Android deployment orchestrator
TEAM_000: Replaces bash scripts with proper subprocess handling (no quoting hell)

End goal: SSH into Alpine Linux as user 'vince' with sudo access
- Preferred: Alpine gets its own IP via bridge networking
- Fallback: Port forwarding (SSH on 2222, Android forwards to 22)

Usage:
    python3 deploy.py              # Full deployment
    python3 deploy.py --step N     # Run specific step
    python3 deploy.py --clean      # Clean everything
    python3 deploy.py --status     # Check current status
"""

import argparse
import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple

# =============================================================================
# Configuration
# =============================================================================

@dataclass
class Config:
    """Single source of truth for all paths and settings."""
    # Host paths
    repo_root: Path
    build_output: Path
    artifacts_dir: Path
    cache_dir: Path
    
    # Device paths
    device_tmp: str = "/data/local/tmp"
    device_lxc_prefix: str = "/data/local/tmp/lxc"
    device_lxc_runtime: str = "/data/local/tmp/lxc-run"
    device_lxc_containers: str = "/data/lxc/containers"
    device_lib_dir: str = "/data/local/tmp/lib"
    device_env_file: str = "/data/local/tmp/lxc-env.sh"
    
    # TEAM_000: Disk image settings (to avoid nosuid on /data)
    device_rootfs_image: str = "/data/local/tmp/alpine-rootfs.img"
    rootfs_image_size_mb: int = 2048  # 2GB should be plenty
    
    # Alpine settings
    alpine_version: str = "3.21"
    alpine_arch: str = "aarch64"
    alpine_user: str = "vince"
    alpine_container: str = "alpine"
    
    # SSH settings
    ssh_port_container: int = 22
    ssh_port_forward: int = 2222
    
    # Container bridge networking
    container_bridge: str = "lxcbr0"
    container_subnet: str = "10.0.3.0/24"
    container_gateway: str = "10.0.3.1"
    container_ip: str = "10.0.3.2"
    host_interface: str = "wlan0"
    
    # Centralized timeouts (seconds)
    timeout_short: int = 10
    timeout_medium: int = 60
    timeout_long: int = 120
    timeout_build: int = 300
    container_ready_timeout: int = 30
    container_ready_poll_interval: float = 0.5
    
    def get_rootfs_path(self, container: Optional[str] = None) -> str:
        """Get the rootfs path for a container."""
        container = container or self.alpine_container
        return f"{self.device_lxc_containers}/{container}/rootfs"
    
    def get_container_path(self, container: Optional[str] = None) -> str:
        """Get the container config path."""
        container = container or self.alpine_container
        return f"{self.device_lxc_containers}/{container}"


def get_config() -> Config:
    """Build configuration from script location."""
    script_dir = Path(__file__).parent.resolve()
    repo_root = script_dir.parent
    return Config(
        repo_root=repo_root,
        build_output=repo_root / "_install_android31",
        artifacts_dir=repo_root / "_artifacts",
        cache_dir=repo_root / "_cache",
    )


# =============================================================================
# Logging
# =============================================================================

class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[0;33m"
    BLUE = "\033[0;34m"
    BOLD = "\033[1m"
    NC = "\033[0m"  # No Color


def log(msg: str, prefix: str = "[deploy]") -> None:
    print(f"{prefix} {msg}")


def log_ok(msg: str) -> None:
    print(f"[deploy] {Colors.GREEN}✓{Colors.NC} {msg}")


def log_warn(msg: str) -> None:
    print(f"[deploy] {Colors.YELLOW}WARNING{Colors.NC}: {msg}", file=sys.stderr)


def log_err(msg: str) -> None:
    print(f"[deploy] {Colors.RED}ERROR{Colors.NC}: {msg}", file=sys.stderr)


def log_step(step: int, total: int, title: str) -> None:
    print()
    print("=" * 75)
    print(f" Step {step}/{total}: {title}")
    print("=" * 75)
    print()


def die(msg: str) -> None:
    log_err(msg)
    sys.exit(1)


# =============================================================================
# ADB Wrapper - The core improvement over bash
# =============================================================================

class ADB:
    """
    ADB wrapper with proper subprocess handling.
    No shell quoting issues - arguments passed directly to execve.
    """
    
    def __init__(self, serial: Optional[str] = None):
        self.serial = serial
        self._base_cmd = ["adb"]
        if serial:
            self._base_cmd.extend(["-s", serial])
    
    def _run(self, args: List[str], check: bool = True, 
             capture: bool = True, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
        """Run an adb command."""
        cmd = self._base_cmd + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=capture,
                text=True,
                timeout=timeout,
                check=False,  # We handle errors ourselves
            )
            if check and result.returncode != 0:
                stderr = result.stderr.strip() if result.stderr else ""
                raise subprocess.CalledProcessError(
                    result.returncode, cmd, result.stdout, stderr
                )
            return result
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"ADB command timed out: {' '.join(cmd)}")
    
    def check_connection(self) -> bool:
        """Check if device is connected."""
        try:
            result = self._run(["get-state"], check=False, timeout=5)
            return result.returncode == 0 and "device" in result.stdout
        except Exception:
            return False
    
    def get_serial(self) -> str:
        """Get device serial number."""
        result = self._run(["get-serialno"], timeout=5)
        return result.stdout.strip()
    
    def shell(self, cmd: str, check: bool = True, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
        """
        Run a shell command on device.
        The command string is passed as a single argument - no nested quoting.
        """
        return self._run(["shell", cmd], check=check, timeout=timeout)
    
    def shell_su(self, cmd: str, check: bool = True, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
        """
        Run a shell command as root.
        This is the key improvement: cmd is passed as a single argument to su -c.
        """
        # The magic: subprocess passes this as ["adb", "shell", "su", "-c", cmd]
        # No shell interpretation on the host side!
        return self._run(["shell", "su", "-c", cmd], check=check, timeout=timeout)
    
    def check_root(self) -> bool:
        """Check if we can get root via su."""
        try:
            result = self.shell_su("id -u", check=False, timeout=5)
            return result.returncode == 0 and result.stdout.strip() == "0"
        except Exception:
            return False
    
    def push(self, local: Path, remote: str, ignore_errors: bool = False) -> bool:
        """Push a file or directory to device. Returns True on success."""
        try:
            self._run(["push", str(local), remote], timeout=300)
            return True
        except subprocess.CalledProcessError:
            if ignore_errors:
                return False
            raise
    
    def pull(self, remote: str, local: Path) -> None:
        """Pull a file from device."""
        self._run(["pull", remote, str(local)], timeout=300)
    
    def file_exists(self, path: str) -> bool:
        """Check if a file exists on device."""
        result = self.shell_su(f"[ -f '{path}' ] && echo yes || echo no", check=False)
        return "yes" in result.stdout
    
    def dir_exists(self, path: str) -> bool:
        """Check if a directory exists on device."""
        result = self.shell_su(f"[ -d '{path}' ] && echo yes || echo no", check=False)
        return "yes" in result.stdout
    
    def mkdir(self, path: str) -> None:
        """Create directory on device (as root)."""
        self.shell_su(f"mkdir -p '{path}'")
    
    def rm_rf(self, path: str) -> None:
        """Remove file or directory on device (as root)."""
        self.shell_su(f"rm -rf '{path}'", check=False)
    
    def chmod(self, path: str, mode: str) -> None:
        """Change file permissions on device."""
        self.shell_su(f"chmod {mode} '{path}'")
    
    def write_file(self, path: str, content: str) -> None:
        """
        Write content to a file on device.
        Uses a temp file to avoid any quoting issues with the content.
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tmp', delete=False) as f:
            f.write(content)
            temp_path = f.name
        try:
            # Push to a temp location first (shell user can write to /data/local/tmp)
            temp_remote = f"/data/local/tmp/.deploy_tmp_{os.getpid()}"
            self.push(Path(temp_path), temp_remote)
            # Move to final location as root
            self.shell_su(f"mv '{temp_remote}' '{path}'")
        finally:
            os.unlink(temp_path)
    
    def read_file(self, path: str) -> str:
        """Read a file from device."""
        result = self.shell_su(f"cat '{path}'", check=True)
        return result.stdout
    
    def create_disk_image(self, image_path: str, size_mb: int) -> None:
        """
        Create an ext4 disk image file.
        TEAM_000: This allows mounting without nosuid, fixing sudo.
        """
        log(f"Creating {size_mb}MB ext4 disk image...")
        # Create sparse file
        self.shell_su(f"dd if=/dev/zero of='{image_path}' bs=1M count=0 seek={size_mb}", timeout=60)
        # Format as ext4
        self.shell_su(f"mkfs.ext4 -F '{image_path}'", timeout=120)
        log_ok(f"Disk image created: {image_path}")
    
    def mount_disk_image(self, image_path: str, mount_point: str) -> None:
        """
        Mount a disk image without nosuid.
        TEAM_000: Key fix - this allows setuid binaries like sudo to work.
        """
        self.shell_su(f"mkdir -p '{mount_point}'")
        # Mount without nosuid - this is the critical fix
        self.shell_su(f"mount -o loop,rw,suid,dev,exec '{image_path}' '{mount_point}'")
        log_ok(f"Mounted {image_path} at {mount_point} (suid enabled)")
    
    def unmount(self, mount_point: str) -> bool:
        """Unmount a filesystem. Returns True if successful."""
        result = self.shell_su(f"umount '{mount_point}'", check=False)
        return result.returncode == 0
    
    def is_mounted(self, mount_point: str) -> bool:
        """Check if a path is a mount point."""
        result = self.shell_su(f"mountpoint -q '{mount_point}'", check=False)
        return result.returncode == 0


# =============================================================================
# LXC Container Management
# =============================================================================

class LXC:
    """LXC container management via ADB."""
    
    # Valid characters for container/user names (alphanumeric, underscore, hyphen)
    _VALID_NAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]*$')
    
    def __init__(self, adb: ADB, config: Config):
        self.adb = adb
        self.config = config
        self._default_container: Optional[str] = None
    
    @classmethod
    def validate_name(cls, name: str, kind: str = "name") -> None:
        """Validate container or user name to prevent shell injection."""
        if not name:
            raise ValueError(f"{kind} cannot be empty")
        if len(name) > 64:
            raise ValueError(f"{kind} too long (max 64 chars): {name}")
        if not cls._VALID_NAME_PATTERN.match(name):
            raise ValueError(f"Invalid {kind} (alphanumeric, _, - only, must start with letter): {name}")
    
    def set_default_container(self, name: str) -> None:
        """Set default container for simplified commands."""
        self.validate_name(name, "container name")
        self._default_container = name
    
    def _lxc_cmd(self, cmd: str, timeout: Optional[int] = None, check: bool = True) -> subprocess.CompletedProcess:
        """Run an LXC command with proper environment."""
        cfg = self.config
        env_vars = (
            f"LD_LIBRARY_PATH={cfg.device_lxc_prefix}/lib "
            f"LXC_PATH={cfg.device_lxc_containers} "
            f"XDG_RUNTIME_DIR={cfg.device_lxc_runtime} "
        )
        if cmd.startswith("lxc-"):
            cmd = f"{cfg.device_lxc_prefix}/bin/{cmd}"
        return self.adb.shell_su(f"{env_vars}{cmd}", check=check, timeout=timeout)
    
    def start(self, name: Optional[str] = None) -> None:
        """Start a container."""
        name = name or self._default_container
        self._lxc_cmd(f"lxc-start -n {name} -P {self.config.device_lxc_containers}", timeout=30)
    
    def stop(self, name: Optional[str] = None, kill: bool = False) -> None:
        """Stop a container."""
        name = name or self._default_container
        kill_flag = "-k" if kill else ""
        self._lxc_cmd(f"lxc-stop -n {name} -P {self.config.device_lxc_containers} {kill_flag}", timeout=30)
    
    def is_running(self, name: Optional[str] = None) -> bool:
        """Check if container is running."""
        name = name or self._default_container
        result = self._lxc_cmd(f"lxc-info -n {name} -s", timeout=10, check=False)
        return "RUNNING" in result.stdout
    
    def exists(self, name: Optional[str] = None) -> bool:
        """Check if container exists."""
        name = name or self._default_container
        return self.adb.dir_exists(f"{self.config.device_lxc_containers}/{name}")
    
    # =========================================================================
    # Container execution helpers - the main simplification
    # =========================================================================
    
    def run(self, cmd: str, name: Optional[str] = None, timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess:
        """Run a command inside container. This is the primary interface."""
        name = name or self._default_container
        return self._lxc_cmd(
            f"lxc-attach -n {name} -P {self.config.device_lxc_containers} -e -- {cmd}",
            timeout=timeout, check=check
        )
    
    def run_ok(self, cmd: str, name: Optional[str] = None, timeout: int = 60) -> bool:
        """Run command, return True if exit code 0."""
        result = self.run(cmd, name, timeout, check=False)
        return result.returncode == 0
    
    def run_output(self, cmd: str, name: Optional[str] = None, timeout: int = 60) -> str:
        """Run command, return stdout (stripped)."""
        result = self.run(cmd, name, timeout, check=False)
        return result.stdout.strip()
    
    def file_exists(self, path: str, name: Optional[str] = None) -> bool:
        """Check if file exists inside container."""
        return self.run_ok(f"test -f {path}", name, timeout=10)
    
    def dir_exists_in(self, path: str, name: Optional[str] = None) -> bool:
        """Check if directory exists inside container."""
        return self.run_ok(f"test -d {path}", name, timeout=10)
    
    def write_file(self, path: str, content: str, name: Optional[str] = None) -> None:
        """Write content to file inside container via rootfs."""
        name = name or self._default_container
        rootfs = self.config.get_rootfs_path(name)
        self.adb.write_file(f"{rootfs}{path}", content)
    
    def write_file_owned(self, path: str, content: str, owner: str, mode: str = "644", name: Optional[str] = None) -> None:
        """Write content to file and set ownership/permissions atomically."""
        name = name or self._default_container
        rootfs = self.config.get_rootfs_path(name)
        self.adb.write_file(f"{rootfs}{path}", content)
        self.run(f"chown {owner}:{owner} {path}", name, timeout=self.config.timeout_short)
        self.run(f"chmod {mode} {path}", name, timeout=self.config.timeout_short)
    
    def read_file(self, path: str, name: Optional[str] = None) -> str:
        """Read file content from inside container."""
        return self.run_output(f"cat {path}", name, timeout=10)
    
    # Legacy alias for backwards compat during refactor
    def attach(self, name: str, cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
        """Legacy: use run() instead."""
        return self.run(cmd, name, timeout)


# =============================================================================
# Deployment Steps
# =============================================================================

class Deployer:
    """Main deployment orchestrator."""
    
    def __init__(self, config: Config, adb: ADB):
        self.config = config
        self.adb = adb
        self.lxc = LXC(adb, config)
    
    def step1_build_lxc(self) -> None:
        """Step 1: Build LXC for Android."""
        log_step(1, 6, "Build LXC for Android")
        
        build_script = self.config.repo_root / "build-android.sh"
        if not build_script.exists():
            die(f"Build script not found: {build_script}")
        
        if self.config.build_output.exists():
            log("Build output already exists, skipping build")
            log_ok(f"Using existing: {self.config.build_output}")
            return
        
        log("Building LXC for Android (this may take a while)...")
        result = subprocess.run(
            [str(build_script)],
            cwd=self.config.repo_root,
            capture_output=False,  # Show build output
        )
        if result.returncode != 0:
            die("LXC build failed")
        
        if not self.config.build_output.exists():
            die(f"Build completed but output not found: {self.config.build_output}")
        
        log_ok("LXC build complete")
    
    def step2_prepare_rootfs(self) -> None:
        """Step 2: Download and prepare Alpine rootfs."""
        log_step(2, 6, "Prepare Alpine Rootfs")
        
        rootfs_tarball = self.config.artifacts_dir / "alpine-rootfs.tar.gz"
        
        if rootfs_tarball.exists():
            log("Rootfs tarball already exists, skipping download")
            log_ok(f"Using existing: {rootfs_tarball}")
            return
        
        # Create directories
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Download Alpine minirootfs
        version = self.config.alpine_version
        arch = self.config.alpine_arch
        filename = f"alpine-minirootfs-{version}.0-{arch}.tar.gz"
        url = f"https://dl-cdn.alpinelinux.org/alpine/v{version}/releases/{arch}/{filename}"
        
        cached = self.config.cache_dir / filename
        
        if not cached.exists():
            log(f"Downloading Alpine {version} for {arch}...")
            result = subprocess.run(
                ["curl", "-fSL", "-o", str(cached), url],
                capture_output=False,
            )
            if result.returncode != 0:
                die(f"Failed to download: {url}")
            log_ok("Download complete")
        else:
            log_ok(f"Using cached: {cached}")
        
        # Copy to artifacts (we could customize rootfs here if needed)
        shutil.copy(cached, rootfs_tarball)
        log_ok(f"Rootfs prepared: {rootfs_tarball}")
    
    def step3_push_to_device(self) -> None:
        """Step 3: Push LXC build and rootfs to device (idempotent)."""
        log_step(3, 6, "Push to Device")
        
        cfg = self.config
        
        # Verify prerequisites
        if not cfg.build_output.exists():
            die(f"Build output not found: {cfg.build_output}")
        
        rootfs_tarball = cfg.artifacts_dir / "alpine-rootfs.tar.gz"
        if not rootfs_tarball.exists():
            die(f"Rootfs tarball not found: {rootfs_tarball}")
        
        # Check device connection
        if not self.adb.check_connection():
            die("No device connected via ADB")
        
        serial = self.adb.get_serial()
        log(f"Connected to: {serial}")
        
        if not self.adb.check_root():
            die("Root access not available")
        log_ok("Root access confirmed")
        
        # Check if LXC already pushed (idempotent)
        lxc_start_path = f"{cfg.device_lxc_prefix}/bin/lxc-start"
        if self.adb.file_exists(lxc_start_path):
            log("LXC binaries already on device, skipping push")
            log_ok(f"Using existing: {cfg.device_lxc_prefix}")
        else:
            # Push LXC build
            log("Pushing LXC build...")
            self.adb.shell(f"mkdir -p '{cfg.device_lxc_prefix}'", check=False)
            
            # Push subdirs - some may fail due to symlinks, that's OK for non-essential dirs
            essential_dirs = ["bin", "lib", "libexec"]
            optional_dirs = ["etc", "sbin", "share"]
            
            for subdir in essential_dirs:
                src = cfg.build_output / subdir
                if src.exists():
                    dst = f"{cfg.device_lxc_prefix}/{subdir}"
                    self.adb.push(src, dst)
            
            for subdir in optional_dirs:
                src = cfg.build_output / subdir
                if src.exists():
                    dst = f"{cfg.device_lxc_prefix}/{subdir}"
                    if not self.adb.push(src, dst, ignore_errors=True):
                        log_warn(f"Could not push {subdir}/ (symlinks?) - continuing anyway")
            
            # Verify push
            if not self.adb.file_exists(lxc_start_path):
                die("Push failed: lxc-start not found on device")
            log_ok("LXC build pushed")
        
        # Push rootfs tarball (idempotent - check if exists)
        tarball_device = f"{cfg.device_tmp}/alpine-rootfs.tar.gz"
        if self.adb.file_exists(tarball_device):
            log("Rootfs tarball already on device")
            log_ok(f"Using existing: {tarball_device}")
        else:
            log("Pushing rootfs tarball...")
            self.adb.push(rootfs_tarball, tarball_device)
            log_ok("Rootfs tarball pushed")
    
    def step4_install_lxc(self) -> None:
        """Step 4: Install LXC on device (idempotent)."""
        log_step(4, 6, "Install LXC on Device")
        
        cfg = self.config
        
        # Check if already configured (idempotent)
        config_path = f"{cfg.device_lxc_containers}/{cfg.alpine_container}/config"
        if self.adb.file_exists(config_path):
            # Verify LXC works
            env_vars = f"LD_LIBRARY_PATH={cfg.device_lxc_prefix}/lib "
            result = self.adb.shell_su(f"{env_vars}{cfg.device_lxc_prefix}/bin/lxc-start --version", check=False)
            if result.returncode == 0:
                log("LXC already configured and working")
                log_ok(f"lxc-start version: {result.stdout.strip()}")
                return
        
        # Create directories (mkdir -p is idempotent)
        log("Creating directories...")
        for d in [cfg.device_lxc_runtime, cfg.device_lxc_containers, 
                  f"{cfg.device_lxc_prefix}/etc/lxc",
                  f"{cfg.device_lxc_containers}/{cfg.alpine_container}",
                  f"{cfg.device_lxc_containers}/{cfg.alpine_container}/rootfs"]:
            self.adb.mkdir(d)
        log_ok("Directories created")
        
        # Set permissions
        log("Setting permissions...")
        self.adb.shell_su(f"chmod 755 {cfg.device_lxc_prefix}/bin/* 2>/dev/null || true")
        self.adb.shell_su(f"chmod 755 {cfg.device_lxc_prefix}/libexec/lxc/* 2>/dev/null || true")
        self.adb.shell_su(f"chmod 644 {cfg.device_lxc_prefix}/lib/*.so* 2>/dev/null || true")
        log_ok("Permissions set")
        
        # Write environment file
        log("Writing environment file...")
        env_content = f'''# LXC environment for Android
# Source this file before running LXC commands
export LXC_PREFIX="{cfg.device_lxc_prefix}"
export PATH="{cfg.device_lxc_prefix}/bin:$PATH"
export LD_LIBRARY_PATH="{cfg.device_lxc_prefix}/lib:$LD_LIBRARY_PATH"
export LXC_PATH="{cfg.device_lxc_containers}"
export LXC_RUNTIME_PATH="{cfg.device_lxc_runtime}"
export XDG_RUNTIME_DIR="{cfg.device_lxc_runtime}"
'''
        self.adb.write_file(cfg.device_env_file, env_content)
        self.adb.chmod(cfg.device_env_file, "644")
        log_ok("Environment file written")
        
        # Write LXC configs
        log("Writing LXC configuration...")
        
        default_conf = "lxc.net.0.type = none\n"
        self.adb.write_file(f"{cfg.device_lxc_prefix}/etc/lxc/default.conf", default_conf)
        
        global_conf = f"lxc.lxcpath = {cfg.device_lxc_containers}\n"
        self.adb.write_file(f"{cfg.device_lxc_prefix}/etc/lxc/lxc.conf", global_conf)
        log_ok("LXC configuration written")
        
        # Write Alpine container config
        log("Writing Alpine container config...")
        # TEAM_000: Use create=dir to ensure mount points are created
        alpine_config = f'''# LXC configuration for Alpine container
lxc.uts.name = {cfg.alpine_container}
lxc.arch = aarch64
lxc.rootfs.path = dir:{cfg.device_lxc_containers}/{cfg.alpine_container}/rootfs

lxc.net.0.type = none

lxc.tty.max = 1
lxc.pty.max = 1
lxc.console.path = none
lxc.init.cmd = /sbin/init

lxc.mount.entry = proc proc proc nosuid,nodev,noexec,create=dir 0 0
lxc.mount.entry = sysfs sys sysfs nosuid,nodev,noexec,ro,create=dir 0 0
lxc.mount.entry = devpts dev/pts devpts nosuid,noexec,mode=0620,ptmxmode=0666,newinstance,create=dir 0 0
lxc.mount.entry = tmpfs dev/shm tmpfs nosuid,nodev,mode=1777,create=dir 0 0
lxc.mount.entry = tmpfs run tmpfs nosuid,nodev,mode=0755,create=dir 0 0
lxc.mount.entry = tmpfs tmp tmpfs nosuid,nodev,mode=1777,create=dir 0 0

lxc.signal.halt = SIGTERM
lxc.environment = PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
lxc.environment = TERM=linux
'''
        self.adb.write_file(f"{cfg.device_lxc_containers}/{cfg.alpine_container}/config", alpine_config)
        log_ok("Alpine container config written")
        
        # Smoke test
        log("Running smoke test...")
        env_vars = f"LD_LIBRARY_PATH={cfg.device_lxc_prefix}/lib "
        result = self.adb.shell_su(f"{env_vars}{cfg.device_lxc_prefix}/bin/lxc-start --version")
        version = result.stdout.strip()
        log_ok(f"lxc-start version: {version}")
    
    def step5_unpack_rootfs(self) -> None:
        """Step 5: Unpack Alpine rootfs into container using disk image."""
        log_step(5, 6, "Unpack Alpine Rootfs (with suid support)")
        
        cfg = self.config
        rootfs_path = f"{cfg.device_lxc_containers}/{cfg.alpine_container}/rootfs"
        tarball = f"{cfg.device_tmp}/alpine-rootfs.tar.gz"
        image_path = cfg.device_rootfs_image
        
        # Check tarball exists
        if not self.adb.file_exists(tarball):
            die(f"Rootfs tarball not found: {tarball}")
        
        # TEAM_000: Use disk image to avoid nosuid on /data partition
        # This is required for sudo to work inside the container
        
        # Check if already set up
        if self.adb.is_mounted(rootfs_path):
            if self.adb.file_exists(f"{rootfs_path}/bin/busybox"):
                log("Rootfs already mounted and unpacked, skipping")
                log_ok(f"Using existing: {rootfs_path}")
                return
        
        # Create disk image if it doesn't exist
        if not self.adb.file_exists(image_path):
            self.adb.create_disk_image(image_path, cfg.rootfs_image_size_mb)
        else:
            log(f"Using existing disk image: {image_path}")
        
        # Mount the disk image
        if not self.adb.is_mounted(rootfs_path):
            self.adb.mount_disk_image(image_path, rootfs_path)
        
        # Unpack if not already done
        if not self.adb.file_exists(f"{rootfs_path}/bin/busybox"):
            log("Unpacking rootfs (this may take a moment)...")
            self.adb.shell_su(f"tar -xzf '{tarball}' -C '{rootfs_path}'", timeout=120)
            
            # Verify
            if not self.adb.file_exists(f"{rootfs_path}/bin/busybox"):
                die("Unpack failed: busybox not found in rootfs")
            log_ok("Rootfs unpacked")
        
        # Create essential directories
        log("Creating essential directories...")
        for d in ["dev", "proc", "sys", "run", "tmp"]:
            self.adb.shell_su(f"mkdir -p '{rootfs_path}/{d}'")
        log_ok("Essential directories created")
        
        # Set up resolv.conf for DNS
        log("Setting up DNS...")
        self.adb.write_file(f"{rootfs_path}/etc/resolv.conf", "nameserver 8.8.8.8\n")
        log_ok("DNS configured")
        
        # Verify suid works
        log("Verifying suid support...")
        result = self.adb.shell_su(f"mount | grep '{rootfs_path}'", check=False)
        if "nosuid" in result.stdout:
            log_warn("Mount still has nosuid - sudo may not work")
        else:
            log_ok("Rootfs mounted with suid enabled")
    
    def _wait_for_container_ready(self, container: str) -> bool:
        """Wait for container to be ready (running and responsive)."""
        cfg = self.config
        deadline = time.time() + cfg.container_ready_timeout
        while time.time() < deadline:
            if self.lxc.is_running(container):
                # Verify container is responsive
                if self.lxc.run_ok("true", container, timeout=cfg.timeout_short):
                    return True
            time.sleep(cfg.container_ready_poll_interval)
        return False
    
    def _ensure_container_running(self, container: str) -> None:
        """Ensure container is running, start if needed."""
        LXC.validate_name(container, "container name")
        if not self.lxc.is_running(container):
            self.lxc.start(container)
        if not self._wait_for_container_ready(container):
            die(f"Container '{container}' failed to start or become ready within {self.config.container_ready_timeout}s")
    
    def _install_packages(self, packages: List[str]) -> None:
        """Install packages inside container (idempotent)."""
        for pkg in packages:
            if not self.lxc.run_output(f"apk info -e {pkg} 2>/dev/null"):
                log(f"Installing {pkg}...")
                self.lxc.run(f"apk add {pkg}", timeout=60)
            else:
                log(f"{pkg} already installed")
    
    def _ensure_user(self, user: str) -> None:
        """Ensure user exists, is in wheel group, and account is unlocked."""
        LXC.validate_name(user, "username")
        cfg = self.config
        
        if not self.lxc.run_output(f"id {user} 2>/dev/null"):
            self.lxc.run(f"adduser -D -s /bin/ash {user}", timeout=cfg.timeout_short)
            log_ok(f"User {user} created")
        else:
            log(f"User {user} already exists")
        
        if "wheel" not in self.lxc.run_output(f"groups {user}"):
            self.lxc.run(f"addgroup {user} wheel", timeout=cfg.timeout_short)
            log_ok(f"Added {user} to wheel group")
        
        # Unlock account (required for SSH key auth to work)
        # Check if already unlocked (no '!' prefix in shadow)
        shadow_entry = self.lxc.run_output(f"grep '^{user}:' /etc/shadow")
        if f"{user}:!" in shadow_entry or f"{user}:*" in shadow_entry:
            self.lxc.run(f"passwd -d {user}", timeout=cfg.timeout_short)
            log(f"Account {user} unlocked for SSH key auth")
        else:
            log(f"Account {user} already unlocked")
    
    def _configure_sudo(self, user: str) -> None:
        """Configure passwordless sudo for wheel group."""
        cfg = self.config
        self.lxc.run("mkdir -p /etc/sudoers.d", timeout=cfg.timeout_short)
        # NOPASSWD since user account has no password (SSH key auth only)
        self.lxc.write_file_owned("/etc/sudoers.d/wheel", "%wheel ALL=(ALL) NOPASSWD: ALL\n", "root", "440")
    
    def _configure_ssh(self, user: str) -> None:
        """Configure SSH inside container with key-based auth."""
        cfg = self.config
        
        # Write sshd_config
        sshd_config = '''Port 22
PermitRootLogin no
PubkeyAuthentication yes
AuthorizedKeysFile /home/%u/.ssh/authorized_keys
PasswordAuthentication yes
ChallengeResponseAuthentication no
StrictModes no
Subsystem sftp /usr/lib/ssh/sftp-server
'''
        self.lxc.write_file_owned("/etc/ssh/sshd_config", sshd_config, "root", "644")
        
        # Install user's SSH public key
        ssh_pub_key = self._get_host_ssh_pubkey()
        if ssh_pub_key:
            user_home = f"/home/{user}"
            # Create .ssh dir and set ownership
            self.lxc.run(f"mkdir -p {user_home}/.ssh", timeout=cfg.timeout_short)
            self.lxc.run(f"chmod 700 {user_home}/.ssh", timeout=cfg.timeout_short)
            self.lxc.run(f"chown {user}:{user} {user_home}/.ssh", timeout=cfg.timeout_short)
            # Write key file with correct ownership
            self.lxc.write_file_owned(f"{user_home}/.ssh/authorized_keys", ssh_pub_key + "\n", user, "600")
            # Fix home dir permissions
            self.lxc.run(f"chmod 755 {user_home}", timeout=cfg.timeout_short)
            self.lxc.run(f"chown {user}:{user} {user_home}", timeout=cfg.timeout_short)
            log_ok("SSH public key installed")
        else:
            log_warn("No SSH public key found on host - password auth only")
        
        # Generate host keys if missing
        if not self.lxc.file_exists("/etc/ssh/ssh_host_rsa_key"):
            self.lxc.run("ssh-keygen -A", timeout=cfg.timeout_medium)
            log_ok("SSH host keys generated")
        
        # Restart sshd
        self.lxc.run("pkill sshd 2>/dev/null || true", check=False, timeout=cfg.timeout_short)
        self.lxc.run("/usr/sbin/sshd", timeout=cfg.timeout_short)
        log_ok("SSH daemon (re)started")
        
        # Enable at boot
        self.lxc.run("rc-update add sshd default 2>/dev/null || true", check=False, timeout=cfg.timeout_short)
    
    def _get_host_ssh_pubkey(self) -> Optional[str]:
        """Get the host user's SSH public key."""
        ssh_dir = Path.home() / ".ssh"
        for key_file in ["id_ed25519.pub", "id_rsa.pub", "id_ecdsa.pub"]:
            key_path = ssh_dir / key_file
            if key_path.exists():
                return key_path.read_text().strip()
        return None
    
    def setup_bridge_network(self) -> None:
        """Set up bridge networking with NAT for container."""
        log_step(0, 0, "Setup Bridge Network")
        cfg = self.config
        
        # Check if bridge already exists
        result = self.adb.shell_su(f"ip link show {cfg.container_bridge} 2>/dev/null", check=False)
        if result.returncode == 0:
            log(f"Bridge {cfg.container_bridge} already exists")
        else:
            # Create bridge
            log(f"Creating bridge {cfg.container_bridge}...")
            self.adb.shell_su(f"ip link add name {cfg.container_bridge} type bridge")
            self.adb.shell_su(f"ip addr add {cfg.container_gateway}/24 dev {cfg.container_bridge}")
            self.adb.shell_su(f"ip link set {cfg.container_bridge} up")
            log_ok(f"Bridge created with IP {cfg.container_gateway}")
        
        # Enable IP forwarding
        self.adb.shell_su("sysctl -w net.ipv4.ip_forward=1")
        log_ok("IP forwarding enabled")
        
        # Add NAT rules (idempotent)
        nat_rule = f"-s {cfg.container_subnet} -o {cfg.host_interface} -j MASQUERADE"
        result = self.adb.shell_su(f"iptables -t nat -C POSTROUTING {nat_rule} 2>/dev/null", check=False)
        if result.returncode != 0:
            self.adb.shell_su(f"iptables -t nat -A POSTROUTING {nat_rule}")
            log_ok(f"Added NAT MASQUERADE for {cfg.container_subnet}")
        else:
            log("NAT rule already exists")
        
        # Add forwarding rules
        fwd_out = f"-i {cfg.container_bridge} -o {cfg.host_interface} -j ACCEPT"
        result = self.adb.shell_su(f"iptables -C FORWARD {fwd_out} 2>/dev/null", check=False)
        if result.returncode != 0:
            self.adb.shell_su(f"iptables -A FORWARD {fwd_out}")
            log_ok("Added FORWARD rule for outbound traffic")
        
        fwd_in = f"-i {cfg.host_interface} -o {cfg.container_bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT"
        result = self.adb.shell_su(f"iptables -C FORWARD {fwd_in} 2>/dev/null", check=False)
        if result.returncode != 0:
            self.adb.shell_su(f"iptables -A FORWARD {fwd_in}")
            log_ok("Added FORWARD rule for established connections")
        
        log_ok("Bridge network ready")
        print()
        print("Container network config (add to LXC config):")
        print(f"  lxc.net.0.type = veth")
        print(f"  lxc.net.0.link = {cfg.container_bridge}")
        print(f"  lxc.net.0.flags = up")
        print(f"  lxc.net.0.ipv4.address = {cfg.container_ip}/24")
        print(f"  lxc.net.0.ipv4.gateway = {cfg.container_gateway}")
        print()
    
    def step6_configure_alpine(self) -> None:
        """Step 6: Configure Alpine with user, sudo, and SSH (idempotent)."""
        log_step(6, 6, "Configure Alpine (User, Sudo, SSH)")
        
        cfg = self.config
        container = cfg.alpine_container
        user = cfg.alpine_user
        rootfs = cfg.get_rootfs_path(container)
        
        # Ensure rootfs is mounted
        if not self.adb.is_mounted(rootfs):
            if self.adb.file_exists(cfg.device_rootfs_image):
                self.adb.mount_disk_image(cfg.device_rootfs_image, rootfs)
            else:
                die("Rootfs not mounted and no disk image found - run step 5 first")
        
        # Start container and set as default for simplified commands
        log("Starting container...")
        self._ensure_container_running(container)
        self.lxc.set_default_container(container)
        log_ok("Container running")
        
        # Update package index
        log("Updating package index...")
        self.lxc.run("apk update", timeout=60)
        
        # Install required packages
        log("Checking packages...")
        self._install_packages(["openssh", "sudo", "shadow", "openssl"])
        log_ok("Packages installed")
        
        # Configure user
        log("Configuring user...")
        self._ensure_user(user)
        
        # Configure sudo
        log("Configuring sudo...")
        self._configure_sudo(user)
        log_ok("Sudo configured")
        
        # Configure SSH
        log("Configuring SSH...")
        self._configure_ssh(user)
        log_ok("SSH configured")
        
        # Verify sudo
        sudo_ver = self.lxc.run_output("sudo --version 2>&1 | head -1")
        if "Sudo version" in sudo_ver:
            log_ok(f"Sudo verified: {sudo_ver}")
        else:
            log_warn(f"Sudo check failed: {sudo_ver}")
        
        # Get network info for summary
        ip_addr = self.lxc.run_output("ip -4 addr show wlan0 2>/dev/null | grep inet | awk '{print $2}' | cut -d/ -f1") or "<android-ip>"
        
        # Summary
        print()
        print("=" * 75)
        print(" DEPLOYMENT COMPLETE")
        print("=" * 75)
        print()
        print(f"User: {user}")
        print(f"Password: (not set - use 'passwd' inside container)")
        print()
        print("Connect via SSH:")
        print(f"  ssh {user}@{ip_addr}")
        print()
        print("Inside Alpine, set password and test sudo:")
        print(f"  passwd")
        print(f"  sudo whoami")
        print()
    
    def run_all(self) -> None:
        """Run all deployment steps."""
        self.step1_build_lxc()
        self.step2_prepare_rootfs()
        self.step3_push_to_device()
        self.step4_install_lxc()
        self.step5_unpack_rootfs()
        self.step6_configure_alpine()
    
    def clean(self) -> None:
        """Clean everything on host and device."""
        log_step(0, 0, "Cleaning Everything")
        
        # Host cleanup
        log("Cleaning host...")
        for d in [self.config.build_output, 
                  self.config.repo_root / "_build_android31",
                  self.config.artifacts_dir,
                  self.config.cache_dir,
                  self.config.repo_root / "_work"]:
            if d.exists():
                shutil.rmtree(d)
                log_ok(f"Removed: {d}")
        
        # Device cleanup
        if self.adb.check_connection() and self.adb.check_root():
            log("Cleaning device...")
            
            # Stop container first
            try:
                if self.lxc.is_running(self.config.alpine_container):
                    self.lxc.stop(self.config.alpine_container, kill=True)
            except Exception:
                pass
            
            # TEAM_000: Unmount disk image before cleanup
            rootfs_path = f"{self.config.device_lxc_containers}/{self.config.alpine_container}/rootfs"
            if self.adb.is_mounted(rootfs_path):
                self.adb.unmount(rootfs_path)
                log_ok(f"Unmounted: {rootfs_path}")
            
            for path in [self.config.device_lxc_prefix,
                         self.config.device_lxc_runtime,
                         self.config.device_lxc_containers,
                         self.config.device_lib_dir,
                         self.config.device_rootfs_image,
                         "/data/lxc"]:
                self.adb.rm_rf(path)
                log_ok(f"Removed: {path}")
            
            # Clean scripts and tarballs
            self.adb.shell_su("rm -f /data/local/tmp/*.sh /data/local/tmp/alpine*.tar.gz", check=False)
            log_ok("Removed scripts and tarballs")
        else:
            log_warn("Device not connected or no root - skipping device cleanup")
        
        log_ok("Clean complete")
    
    def status(self) -> None:
        """Show current deployment status."""
        log_step(0, 0, "Deployment Status")
        
        # Host status
        log("Host:")
        log(f"  Build output: {'✓' if self.config.build_output.exists() else '✗'} {self.config.build_output}")
        log(f"  Rootfs:       {'✓' if (self.config.artifacts_dir / 'alpine-rootfs.tar.gz').exists() else '✗'}")
        
        # Device status
        if not self.adb.check_connection():
            log("Device: Not connected")
            return
        
        log(f"Device: {self.adb.get_serial()}")
        log(f"  Root:      {'✓' if self.adb.check_root() else '✗'}")
        log(f"  LXC:       {'✓' if self.adb.dir_exists(self.config.device_lxc_prefix) else '✗'}")
        log(f"  Container: {'✓' if self.lxc.exists(self.config.alpine_container) else '✗'}")
        
        if self.lxc.exists(self.config.alpine_container):
            running = self.lxc.is_running(self.config.alpine_container)
            log(f"  Running:   {'✓' if running else '✗'}")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Deploy Alpine Linux in LXC on Android",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 deploy.py              # Full deployment
  python3 deploy.py --step 3     # Run only step 3 (push to device)
  python3 deploy.py --clean      # Clean everything
  python3 deploy.py --status     # Check current status
  python3 deploy.py -s SERIAL    # Target specific device
"""
    )
    parser.add_argument("--step", type=int, help="Run specific step (1-6)")
    parser.add_argument("--clean", action="store_true", help="Clean everything")
    parser.add_argument("--status", action="store_true", help="Show deployment status")
    parser.add_argument("--network", action="store_true", help="Setup bridge network with NAT")
    parser.add_argument("-s", "--serial", help="Target specific device by serial")
    
    args = parser.parse_args()
    
    config = get_config()
    adb = ADB(serial=args.serial)
    deployer = Deployer(config, adb)
    
    if args.clean:
        deployer.clean()
    elif args.status:
        deployer.status()
    elif args.network:
        deployer.setup_bridge_network()
    elif args.step:
        steps = {
            1: deployer.step1_build_lxc,
            2: deployer.step2_prepare_rootfs,
            3: deployer.step3_push_to_device,
            4: deployer.step4_install_lxc,
            5: deployer.step5_unpack_rootfs,
            6: deployer.step6_configure_alpine,
        }
        if args.step not in steps:
            die(f"Invalid step: {args.step} (must be 1-6)")
        steps[args.step]()
    else:
        deployer.run_all()


if __name__ == "__main__":
    main()
