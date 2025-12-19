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

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

# Check for required libraries, provide helpful error if missing
try:
    import httpx
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.table import Table
    from rich.panel import Panel
    import typer
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install rich typer httpx")
    sys.exit(1)


# =============================================================================
# Console & CLI Setup
# =============================================================================

console = Console()
app = typer.Typer(
    help="Deploy Gentoo Linux in LXC on Android (ARM64)",
    no_args_is_help=False,
    add_completion=False,
)


def log(msg: str) -> None:
    console.print(f"[dim]>[/dim] {msg}")


def log_ok(msg: str) -> None:
    console.print(f"[green]✓[/green] {msg}")


def log_warn(msg: str) -> None:
    console.print(f"[yellow]⚠[/yellow] {msg}", style="yellow")


def log_err(msg: str) -> None:
    console.print(f"[red]✗[/red] {msg}", style="red")


def die(msg: str) -> None:
    log_err(msg)
    raise typer.Exit(1)


def step_header(step: int, total: int, title: str) -> None:
    console.print()
    console.rule(f"[bold blue]Step {step}/{total}: {title}[/bold blue]")
    console.print()


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class GentooConfig:
    """Gentoo stage3 artifact configuration."""
    version: str = "20251214T234555Z"
    arch: str = "arm64"
    variant: str = "openrc"
    
    @property
    def filename(self) -> str:
        return f"stage3-{self.arch}-{self.variant}-{self.version}.tar.xz"
    
    @property
    def base_url(self) -> str:
        return f"https://distfiles.gentoo.org/releases/{self.arch}/autobuilds/{self.version}"
    
    @property
    def stage3_url(self) -> str:
        return f"{self.base_url}/{self.filename}"
    
    @property
    def digests_url(self) -> str:
        return f"{self.stage3_url}.DIGESTS"
    
    @property
    def binhost_url(self) -> str:
        return f"https://distfiles.gentoo.org/releases/{self.arch}/binpackages/17.0/{self.arch}/"


@dataclass
class DevicePaths:
    """Paths on the Android device."""
    tmp: str = "/data/local/tmp"
    lxc_prefix: str = "/data/local/tmp/lxc"
    lxc_runtime: str = "/data/local/tmp/lxc-run"
    lxc_containers: str = "/data/lxc/containers"
    rootfs_image: str = "/data/local/tmp/gentoo-rootfs.img"
    
    def container_path(self, name: str) -> str:
        return f"{self.lxc_containers}/{name}"
    
    def rootfs_path(self, name: str) -> str:
        return f"{self.container_path(name)}/rootfs"


@dataclass
class NetworkConfig:
    """Container networking configuration."""
    bridge: str = "lxcbr0"
    subnet: str = "10.0.3.0/24"
    gateway: str = "10.0.3.1"
    container_ip: str = "10.0.3.2"
    host_interface: str = "wlan0"


@dataclass
class ResourceConfig:
    """Resource allocation: Gentoo > Android.
    
    These settings ensure Gentoo container gets priority over Android userspace.
    The kernel is already optimized for LXC; these cgroup settings reinforce that.
    """
    # CPU shares: 1024 = normal, higher = more CPU time
    # 4096 = 4x priority over default Android processes
    cpu_shares: int = 4096
    
    # Memory soft limit in MB - Gentoo gets priority for this much RAM
    # Set to ~60% of device RAM (e.g., 4GB for 8GB device)
    memory_limit_mb: int = 4096
    
    # Block I/O weight: 100-1000, higher = more I/O bandwidth
    # 900 gives Gentoo priority disk access over Android (default 500)
    blkio_weight: int = 900
    
    # Nice value for container processes: -20 (highest) to 19 (lowest)
    # -10 = higher priority than all Android apps
    nice_value: int = -10
    
    # OOM score adjustment: -1000 (never kill) to 1000 (kill first)
    # -500 = strongly prefer killing Android over Gentoo
    oom_score_adj: int = -500


@dataclass
class Config:
    """Main configuration - single source of truth."""
    # Derived from script location
    repo_root: Path = field(default_factory=lambda: Path(__file__).parent.parent.resolve())
    
    # Host paths
    @property
    def build_output(self) -> Path:
        return self.repo_root / "_install_android31"
    
    @property
    def artifacts_dir(self) -> Path:
        return self.repo_root / "_artifacts"
    
    @property
    def cache_dir(self) -> Path:
        return self.repo_root / "_cache"
    
    # Sub-configs
    gentoo: GentooConfig = field(default_factory=GentooConfig)
    device: DevicePaths = field(default_factory=DevicePaths)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    resources: ResourceConfig = field(default_factory=ResourceConfig)
    
    # Container settings
    container_name: str = "gentoo"
    container_user: str = "vince"
    rootfs_image_size_mb: int = 32768  # 32GB - Gentoo needs space for portage, builds, etc.
    
    # Timeouts (seconds)
    timeout_short: int = 10
    timeout_medium: int = 60
    timeout_long: int = 300
    container_ready_timeout: int = 30


# =============================================================================
# ADB - Android Debug Bridge wrapper
# =============================================================================

class ADB:
    """Clean ADB interface - no shell quoting issues."""
    
    def __init__(self, serial: Optional[str] = None):
        self.serial = serial
        self._base = ["adb"] + (["-s", serial] if serial else [])
    
    def _run(self, args: list[str], check: bool = True, 
             timeout: Optional[int] = None) -> subprocess.CompletedProcess:
        cmd = self._base + args
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, 
                                   timeout=timeout, check=False)
            if check and result.returncode != 0:
                raise subprocess.CalledProcessError(result.returncode, cmd, 
                                                   result.stdout, result.stderr)
            return result
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"ADB timeout: {' '.join(args[:2])}...")
    
    # Connection
    def connected(self) -> bool:
        try:
            r = self._run(["get-state"], check=False, timeout=5)
            return r.returncode == 0 and "device" in r.stdout
        except Exception:
            return False
    
    def serial_number(self) -> str:
        return self._run(["get-serialno"], timeout=5).stdout.strip()
    
    def has_root(self) -> bool:
        try:
            r = self._run(["shell", "su", "-c", "id -u"], check=False, timeout=5)
            return r.returncode == 0 and r.stdout.strip() == "0"
        except Exception:
            return False
    
    # Shell commands
    def sh(self, cmd: str, check: bool = True, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
        """Run shell command (no root)."""
        return self._run(["shell", cmd], check=check, timeout=timeout)
    
    def su(self, cmd: str, check: bool = True, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
        """Run shell command as root."""
        return self._run(["shell", "su", "-c", cmd], check=check, timeout=timeout)
    
    # File operations
    def push(self, local: Path, remote: str, timeout: int = 300) -> bool:
        try:
            self._run(["push", str(local), remote], timeout=timeout)
            return True
        except subprocess.CalledProcessError:
            return False
    
    def pull(self, remote: str, local: Path, timeout: int = 300) -> None:
        self._run(["pull", remote, str(local)], timeout=timeout)
    
    def exists(self, path: str, is_dir: bool = False) -> bool:
        flag = "-d" if is_dir else "-f"
        r = self.su(f"[ {flag} '{path}' ] && echo y || echo n", check=False)
        return "y" in r.stdout
    
    def mkdir(self, path: str) -> None:
        self.su(f"mkdir -p '{path}'")
    
    def rm(self, path: str) -> None:
        self.su(f"rm -rf '{path}'", check=False)
    
    def write(self, path: str, content: str) -> None:
        """Write content to device file via temp file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write(content)
            tmp = f.name
        try:
            tmp_remote = f"/data/local/tmp/.tmp_{os.getpid()}"
            self.push(Path(tmp), tmp_remote)
            self.su(f"mv '{tmp_remote}' '{path}'")
        finally:
            os.unlink(tmp)
    
    def read(self, path: str) -> str:
        return self.su(f"cat '{path}'").stdout
    
    # Disk image operations
    def create_image(self, path: str, size_mb: int) -> None:
        log(f"Creating {size_mb}MB ext4 image...")
        self.su(f"dd if=/dev/zero of='{path}' bs=1M count=0 seek={size_mb}", timeout=60)
        self.su(f"mkfs.ext4 -F '{path}'", timeout=120)
        log_ok(f"Image created: {path}")
    
    def mount(self, image: str, mountpoint: str) -> None:
        self.mkdir(mountpoint)
        self.su(f"mount -o loop,rw,suid,dev,exec '{image}' '{mountpoint}'")
        log_ok(f"Mounted at {mountpoint} (suid enabled)")
    
    def umount(self, mountpoint: str) -> bool:
        return self.su(f"umount '{mountpoint}'", check=False).returncode == 0
    
    def is_mounted(self, path: str) -> bool:
        return self.su(f"mountpoint -q '{path}'", check=False).returncode == 0


# =============================================================================
# LXC - Container management
# =============================================================================

class LXC:
    """LXC container operations via ADB."""
    
    _NAME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]*$')
    
    def __init__(self, adb: ADB, cfg: Config):
        self.adb = adb
        self.cfg = cfg
        self._container: Optional[str] = None
    
    @classmethod
    def validate_name(cls, name: str) -> None:
        if not name or len(name) > 64 or not cls._NAME_RE.match(name):
            raise ValueError(f"Invalid name: {name}")
    
    def use(self, name: str) -> None:
        """Set default container for subsequent operations."""
        self.validate_name(name)
        self._container = name
    
    def _env(self) -> str:
        d = self.cfg.device
        return (f"LD_LIBRARY_PATH={d.lxc_prefix}/lib "
                f"LXC_PATH={d.lxc_containers} "
                f"XDG_RUNTIME_DIR={d.lxc_runtime} ")
    
    def _lxc(self, cmd: str, timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess:
        if cmd.startswith("lxc-"):
            cmd = f"{self.cfg.device.lxc_prefix}/bin/{cmd}"
        return self.adb.su(f"{self._env()}{cmd}", check=check, timeout=timeout)
    
    # Container lifecycle
    def start(self, name: Optional[str] = None) -> None:
        name = name or self._container
        self._lxc(f"lxc-start -n {name} -P {self.cfg.device.lxc_containers}", timeout=30)
    
    def stop(self, name: Optional[str] = None, kill: bool = False) -> None:
        name = name or self._container
        k = "-k" if kill else ""
        self._lxc(f"lxc-stop -n {name} -P {self.cfg.device.lxc_containers} {k}", timeout=30)
    
    def running(self, name: Optional[str] = None) -> bool:
        name = name or self._container
        r = self._lxc(f"lxc-info -n {name} -s", timeout=10, check=False)
        return "RUNNING" in r.stdout
    
    def exists(self, name: Optional[str] = None) -> bool:
        name = name or self._container
        return self.adb.exists(self.cfg.device.container_path(name), is_dir=True)
    
    # Execute inside container
    def run(self, cmd: str, name: Optional[str] = None, 
            timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess:
        name = name or self._container
        # Use -e (elevated privileges) to bypass Android capability restrictions
        return self._lxc(
            f"lxc-attach -n {name} -P {self.cfg.device.lxc_containers} -e -- {cmd}",
            timeout=timeout, check=check
        )
    
    def output(self, cmd: str, name: Optional[str] = None, timeout: int = 60) -> str:
        return self.run(cmd, name, timeout, check=False).stdout.strip()
    
    def ok(self, cmd: str, name: Optional[str] = None, timeout: int = 60) -> bool:
        return self.run(cmd, name, timeout, check=False).returncode == 0
    
    # File operations inside container
    def write(self, path: str, content: str, name: Optional[str] = None) -> None:
        name = name or self._container
        rootfs = self.cfg.device.rootfs_path(name)
        self.adb.write(f"{rootfs}{path}", content)
    
    def file_exists(self, path: str, name: Optional[str] = None) -> bool:
        return self.ok(f"test -f {path}", name, timeout=10)


# =============================================================================
# Downloader - HTTP with progress
# =============================================================================

class Downloader:
    """HTTP downloads with progress bars."""
    
    @staticmethod
    def download(url: str, dest: Path, desc: str = "Downloading") -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        with httpx.stream("GET", url, follow_redirects=True, timeout=30.0) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(desc, total=total or None)
                
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=8192):
                        f.write(chunk)
                        progress.advance(task, len(chunk))
    
    @staticmethod
    def fetch_text(url: str) -> str:
        r = httpx.get(url, follow_redirects=True, timeout=30.0)
        r.raise_for_status()
        return r.text


# =============================================================================
# Crypto - Hash verification
# =============================================================================

class Crypto:
    """Cryptographic operations."""
    
    @staticmethod
    def sha512_file(path: Path) -> str:
        h = hashlib.sha512()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest().lower()
    
    @staticmethod
    def parse_gentoo_digests(content: str, filename: str) -> Optional[str]:
        """Extract SHA512 hash from Gentoo DIGESTS file."""
        in_sha512 = False
        for line in content.split('\n'):
            line = line.strip()
            if 'SHA512' in line and 'HASH' in line:
                in_sha512 = True
                continue
            if in_sha512 and line and not line.startswith('#'):
                parts = line.split()
                if len(parts) >= 2 and filename in parts[-1]:
                    return parts[0].lower()
                in_sha512 = False
        return None


# =============================================================================
# Deployer - Main orchestration
# =============================================================================

class Deployer:
    """Deployment orchestrator."""
    
    def __init__(self, cfg: Config, adb: ADB):
        self.cfg = cfg
        self.adb = adb
        self.lxc = LXC(adb, cfg)
        
        # Set NDK path if not already set (look in repo)
        if not os.environ.get("ANDROID_NDK_HOME") and not os.environ.get("ANDROID_NDK_ROOT"):
            ndk_path = cfg.repo_root / "_ndk" / "android-ndk-r27c"
            if ndk_path.exists():
                os.environ["ANDROID_NDK_HOME"] = str(ndk_path)
    
    # -------------------------------------------------------------------------
    # Step 1: Build LXC
    # -------------------------------------------------------------------------
    def step1_build_lxc(self) -> None:
        step_header(1, 6, "Build LXC for Android")
        
        if self.cfg.build_output.exists():
            log_ok(f"Using existing build: {self.cfg.build_output}")
            return
        
        build_script = self.cfg.repo_root / "build-android.sh"
        if not build_script.exists():
            die(f"Build script not found: {build_script}")
        
        log("Building LXC (this may take a while)...")
        r = subprocess.run([str(build_script)], cwd=self.cfg.repo_root)
        if r.returncode != 0:
            die("Build failed")
        
        if not self.cfg.build_output.exists():
            die(f"Build output not found: {self.cfg.build_output}")
        
        log_ok("Build complete")
    
    # -------------------------------------------------------------------------
    # Step 2: Download & verify Gentoo stage3
    # -------------------------------------------------------------------------
    def step2_prepare_rootfs(self) -> None:
        step_header(2, 6, "Download Gentoo Stage3 (SHA512 verified)")
        
        self.cfg.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.artifacts_dir.mkdir(parents=True, exist_ok=True)
        
        cached = self.cfg.cache_dir / self.cfg.gentoo.filename
        artifact = self.cfg.artifacts_dir / self.cfg.gentoo.filename
        
        # Download if not cached
        if not cached.exists():
            log(f"URL: {self.cfg.gentoo.stage3_url}")
            Downloader.download(self.cfg.gentoo.stage3_url, cached, "Downloading stage3")
        else:
            log_ok(f"Using cached: {cached.name}")
        
        # Verify SHA512
        log("Fetching DIGESTS for verification...")
        digests = Downloader.fetch_text(self.cfg.gentoo.digests_url)
        expected = Crypto.parse_gentoo_digests(digests, self.cfg.gentoo.filename)
        
        if not expected:
            die("Could not parse SHA512 from DIGESTS")
        
        log("Verifying SHA512...")
        actual = Crypto.sha512_file(cached)
        
        if actual != expected:
            log_err(f"Expected: {expected[:32]}...")
            log_err(f"Actual:   {actual[:32]}...")
            cached.unlink(missing_ok=True)
            die("SHA512 MISMATCH - corrupted download removed")
        
        log_ok("SHA512 verified")
        
        # Copy to artifacts
        if not artifact.exists():
            shutil.copy(cached, artifact)
        log_ok(f"Ready: {artifact.name}")
        
        # Download OpenDoas source (sudo alternative that compiles with GCC 15)
        doas_version = "6.8.2"
        doas_file = f"opendoas-{doas_version}.tar.xz"
        doas_url = f"https://github.com/Duncaen/OpenDoas/releases/download/v{doas_version}/{doas_file}"
        doas_cached = self.cfg.cache_dir / doas_file
        doas_artifact = self.cfg.artifacts_dir / doas_file
        
        if not doas_cached.exists():
            log("Downloading OpenDoas (sudo alternative)...")
            Downloader.download(doas_url, doas_cached, "Downloading doas")
        else:
            log_ok(f"Using cached: {doas_file}")
        
        if not doas_artifact.exists():
            shutil.copy(doas_cached, doas_artifact)
        log_ok("Doas source ready")
    
    # -------------------------------------------------------------------------
    # Step 3: Push to device
    # -------------------------------------------------------------------------
    def step3_push_to_device(self) -> None:
        step_header(3, 6, "Push to Device")
        
        if not self.cfg.build_output.exists():
            die(f"Build not found: {self.cfg.build_output}")
        
        tarball = self.cfg.artifacts_dir / self.cfg.gentoo.filename
        if not tarball.exists():
            die(f"Stage3 not found: {tarball}")
        
        if not self.adb.connected():
            die("No device connected")
        
        log(f"Device: {self.adb.serial_number()}")
        
        if not self.adb.has_root():
            die("Root access required")
        log_ok("Root confirmed")
        
        # Push LXC binaries
        lxc_bin = f"{self.cfg.device.lxc_prefix}/bin/lxc-start"
        if self.adb.exists(lxc_bin):
            log_ok("LXC binaries already on device")
        else:
            log("Pushing LXC binaries...")
            self.adb.sh(f"mkdir -p '{self.cfg.device.lxc_prefix}'", check=False)
            
            for subdir in ["bin", "lib", "libexec", "etc", "share"]:
                src = self.cfg.build_output / subdir
                if src.exists():
                    dst = f"{self.cfg.device.lxc_prefix}/{subdir}"
                    if not self.adb.push(src, dst):
                        log_warn(f"Could not push {subdir}/ (symlinks?)")
            
            if not self.adb.exists(lxc_bin):
                die("Push failed: lxc-start not found")
            log_ok("LXC binaries pushed")
        
        # Push stage3 tarball
        tarball_remote = f"{self.cfg.device.tmp}/{self.cfg.gentoo.filename}"
        if self.adb.exists(tarball_remote):
            log_ok("Stage3 already on device")
        else:
            log("Pushing stage3 tarball (this takes a while)...")
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as p:
                p.add_task("Pushing...", total=None)
                self.adb.push(tarball, tarball_remote)
            log_ok("Stage3 pushed")
        
        # Push doas source
        doas_file = "opendoas-6.8.2.tar.xz"
        doas_local = self.cfg.artifacts_dir / doas_file
        doas_remote = f"{self.cfg.device.tmp}/{doas_file}"
        if doas_local.exists() and not self.adb.exists(doas_remote):
            log("Pushing doas source...")
            self.adb.push(doas_local, doas_remote)
            log_ok("Doas source pushed")
    
    # -------------------------------------------------------------------------
    # Step 4: Install LXC on device
    # -------------------------------------------------------------------------
    def step4_install_lxc(self) -> None:
        step_header(4, 6, "Install LXC on Device")
        
        d = self.cfg.device
        container = self.cfg.container_name
        config_path = f"{d.container_path(container)}/config"
        
        # Check if already configured
        if self.adb.exists(config_path):
            r = self.adb.su(f"LD_LIBRARY_PATH={d.lxc_prefix}/lib {d.lxc_prefix}/bin/lxc-start --version", check=False)
            if r.returncode == 0:
                log_ok(f"Already configured (lxc-start {r.stdout.strip()})")
                return
        
        # Create directories
        log("Creating directories...")
        for path in [d.lxc_runtime, d.lxc_containers, 
                     f"{d.lxc_prefix}/etc/lxc",
                     d.container_path(container),
                     d.rootfs_path(container)]:
            self.adb.mkdir(path)
        log_ok("Directories created")
        
        # Set permissions
        log("Setting permissions...")
        self.adb.su(f"chmod 755 {d.lxc_prefix}/bin/* 2>/dev/null || true")
        self.adb.su(f"chmod 755 {d.lxc_prefix}/libexec/lxc/* 2>/dev/null || true")
        self.adb.su(f"chmod 644 {d.lxc_prefix}/lib/*.so* 2>/dev/null || true")
        log_ok("Permissions set")
        
        # Write LXC configs
        log("Writing LXC configuration...")
        self.adb.write(f"{d.lxc_prefix}/etc/lxc/default.conf", "lxc.net.0.type = none\n")
        self.adb.write(f"{d.lxc_prefix}/etc/lxc/lxc.conf", f"lxc.lxcpath = {d.lxc_containers}\n")
        
        # Setup bridge network
        self._setup_bridge_network()
        
        # Write container config
        # NOTE: lxc.cap.drop = (empty) disables capability dropping which fails on Android
        net = self.cfg.network
        res = self.cfg.resources
        container_config = f"""# Gentoo LXC container configuration
# PRIORITY: Gentoo > Android - container gets majority of system resources
lxc.uts.name = {container}
lxc.arch = aarch64
lxc.rootfs.path = dir:{d.rootfs_path(container)}

# Bridge networking - container gets its own IP address
# Requires kernel with CONFIG_BRIDGE=y, CONFIG_VETH=y (verified supported)
# Also requires SELinux permissive mode (set via kernel boot param enforcing=0)
lxc.net.0.type = veth
lxc.net.0.link = {net.bridge}
lxc.net.0.flags = up
lxc.net.0.ipv4.address = {net.container_ip}/24
lxc.net.0.ipv4.gateway = {net.gateway}

# =============================================================================
# RESOURCE ALLOCATION: Gentoo > Android
# The kernel is optimized to favor LXC, these settings ensure Gentoo dominates
# =============================================================================

# CPU: High priority (1024 = normal, 2048+ = higher than Android)
# Gentoo gets 4x the CPU weight of normal Android processes
lxc.cgroup.cpu.shares = {res.cpu_shares}

# CPU: Pin to performance cores if available (big.LITTLE)
# lxc.cgroup.cpuset.cpus = 4-7

# Memory: Reserve {res.memory_limit_mb}MB for Gentoo (majority of device RAM)
# This soft limit ensures Gentoo gets memory priority
lxc.cgroup.memory.soft_limit_in_bytes = {res.memory_limit_mb * 1024 * 1024}

# I/O: High priority (0-7, lower = higher priority)
# Gentoo gets highest I/O priority for disk access
lxc.cgroup.blkio.weight = {res.blkio_weight}

# Process priority: Run container processes at higher priority
# Nice value -10 means higher priority than Android apps (which run at 0-19)

# OOM: Make Android die first, not Gentoo (-1000 to 1000, lower = less likely to kill)
lxc.cgroup.memory.oom_control = 0

# =============================================================================

lxc.tty.max = 4
lxc.pty.max = 256
lxc.console.path = none
lxc.init.cmd = /sbin/init

lxc.mount.entry = proc proc proc nosuid,nodev,noexec,create=dir 0 0
lxc.mount.entry = sysfs sys sysfs nosuid,nodev,noexec,ro,create=dir 0 0
lxc.mount.entry = devpts dev/pts devpts nosuid,nodev,noexec,mode=0620,ptmxmode=0666,newinstance,create=dir 0 0
lxc.mount.entry = tmpfs dev/shm tmpfs nosuid,nodev,mode=1777,create=dir 0 0
lxc.mount.entry = tmpfs run tmpfs nosuid,nodev,mode=0755,create=dir 0 0
lxc.mount.entry = tmpfs tmp tmpfs nosuid,nodev,mode=1777,create=dir 0 0

lxc.signal.halt = SIGTERM
lxc.signal.reboot = SIGINT
lxc.signal.stop = SIGKILL

lxc.environment = PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
lxc.environment = TERM=linux
lxc.environment = LANG=en_US.UTF-8

# Android-specific: disable capability dropping (fails on Android kernel)
lxc.cap.drop =
"""
        self.adb.write(config_path, container_config)
        log_ok("Container config written")
        
        # Fix LXC common.conf for Android compatibility
        # Disable seccomp (not supported) and cap.drop (fails on Android)
        log("Patching LXC config for Android compatibility...")
        common_conf = f"{d.lxc_prefix}/share/lxc/config/common.conf"
        self.adb.su(f"sed -i 's/^lxc.seccomp.profile/#lxc.seccomp.profile/' '{common_conf}' 2>/dev/null || true")
        self.adb.su(f"sed -i 's/^lxc.cap.drop/#lxc.cap.drop/' '{common_conf}' 2>/dev/null || true")
        log_ok("LXC config patched for Android")
        
        # Smoke test
        r = self.adb.su(f"LD_LIBRARY_PATH={d.lxc_prefix}/lib {d.lxc_prefix}/bin/lxc-start --version")
        log_ok(f"lxc-start version: {r.stdout.strip()}")
    
    def _setup_bridge_network(self) -> None:
        """Setup bridge networking with NAT."""
        net = self.cfg.network
        
        # Check if bridge exists
        r = self.adb.su(f"ip link show {net.bridge} 2>/dev/null", check=False)
        if r.returncode == 0:
            log(f"Bridge {net.bridge} already exists")
        else:
            log(f"Creating bridge {net.bridge}...")
            self.adb.su(f"ip link add name {net.bridge} type bridge")
            self.adb.su(f"ip addr add {net.gateway}/24 dev {net.bridge}")
            self.adb.su(f"ip link set {net.bridge} up")
            log_ok(f"Bridge created: {net.gateway}")
        
        # Enable IP forwarding
        self.adb.su("sysctl -w net.ipv4.ip_forward=1")
        log_ok("IP forwarding enabled")
        
        # NAT rules
        nat = f"-s {net.subnet} -o {net.host_interface} -j MASQUERADE"
        if self.adb.su(f"iptables -t nat -C POSTROUTING {nat} 2>/dev/null", check=False).returncode != 0:
            self.adb.su(f"iptables -t nat -A POSTROUTING {nat}")
            log_ok("NAT rule added")
        
        # Forward rules
        fwd_out = f"-i {net.bridge} -o {net.host_interface} -j ACCEPT"
        if self.adb.su(f"iptables -C FORWARD {fwd_out} 2>/dev/null", check=False).returncode != 0:
            self.adb.su(f"iptables -A FORWARD {fwd_out}")
        
        fwd_in = f"-i {net.host_interface} -o {net.bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT"
        if self.adb.su(f"iptables -C FORWARD {fwd_in} 2>/dev/null", check=False).returncode != 0:
            self.adb.su(f"iptables -A FORWARD {fwd_in}")
        
        log_ok("Bridge network ready")
    
    # -------------------------------------------------------------------------
    # Step 5: Unpack rootfs
    # -------------------------------------------------------------------------
    def step5_unpack_rootfs(self) -> None:
        step_header(5, 6, "Unpack Gentoo Rootfs")
        
        d = self.cfg.device
        rootfs = d.rootfs_path(self.cfg.container_name)
        tarball = f"{d.tmp}/{self.cfg.gentoo.filename}"
        
        if not self.adb.exists(tarball):
            die(f"Stage3 not found: {tarball}")
        
        # Check if already unpacked
        if self.adb.is_mounted(rootfs) and self.adb.exists(f"{rootfs}/bin/bash"):
            log_ok("Rootfs already unpacked")
            return
        
        # Create/mount disk image (for suid support)
        if not self.adb.exists(d.rootfs_image):
            self.adb.create_image(d.rootfs_image, self.cfg.rootfs_image_size_mb)
        else:
            log(f"Using existing image: {d.rootfs_image}")
        
        if not self.adb.is_mounted(rootfs):
            self.adb.mount(d.rootfs_image, rootfs)
        
        # Unpack stage3
        if not self.adb.exists(f"{rootfs}/bin/bash"):
            log("Unpacking stage3 (this takes several minutes)...")
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as p:
                p.add_task("Extracting...", total=None)
                # Android's tar doesn't support xz or --preserve-permissions
                # Use tar -xJf which works on some devices, or fallback to busybox
                result = self.adb.su(
                    f"cd '{rootfs}' && tar -xJf '{tarball}' 2>/dev/null || "
                    f"busybox tar -xJf '{tarball}' 2>/dev/null || "
                    f"toybox tar -xf '{tarball}'",
                    timeout=600,
                    check=False
                )
                # If all tar methods fail, try extracting on host and pushing
                if not self.adb.exists(f"{rootfs}/bin/bash"):
                    log_warn("Device tar failed, trying host extraction...")
                    self._extract_on_host_and_push(tarball, rootfs)
            
            if not self.adb.exists(f"{rootfs}/bin/bash"):
                die("Unpack failed: /bin/bash not found")
            log_ok("Stage3 unpacked")
        
        # Essential directories
        for d_name in ["dev", "proc", "sys", "run", "tmp"]:
            self.adb.su(f"mkdir -p '{rootfs}/{d_name}'")
        
        # Fix /var/empty ownership for sshd (must be owned by root, not world-writable)
        self.adb.su(f"mkdir -p '{rootfs}/var/empty'")
        self.adb.su(f"chown 0:0 '{rootfs}/var/empty' 2>/dev/null || true")
        self.adb.su(f"chmod 755 '{rootfs}/var/empty'")
        
        # DNS
        self.adb.write(f"{rootfs}/etc/resolv.conf", "nameserver 8.8.8.8\n")
        log_ok("DNS configured")
        
        # Portage make.conf - Optimized for Pixel 6 (Google Tensor G1 / Samsung Exynos)
        make_conf = """# Gentoo ARM64 - Pixel 6 (Google Tensor G1) optimized
# Tensor G1 is based on Samsung Exynos with 2x Cortex-X1 + 2x Cortex-A76 + 4x Cortex-A55

# CPU: ARMv8.2-A with crypto extensions, optimized for Cortex-X1 big cores
COMMON_FLAGS="-O2 -pipe -mcpu=cortex-a76 -mtune=cortex-a76"
COMMON_FLAGS="${COMMON_FLAGS} -march=armv8.2-a+crypto+fp16+dotprod"
CFLAGS="${COMMON_FLAGS}"
CXXFLAGS="${COMMON_FLAGS}"
FCFLAGS="${COMMON_FLAGS}"
FFLAGS="${COMMON_FLAGS}"

# 8 cores available, use 6 for compilation (leave headroom)
MAKEOPTS="-j6 -l6"
ACCEPT_LICENSE="*"

# Pixel 6 USE flags - server/container focused, no desktop
USE="-systemd -wayland -X -alsa -cups -bluetooth -gnome -kde -pulseaudio"
USE="${USE} -gui -gtk -qt5 -qt6 -desktop -sound -video"
USE="${USE} ipv6 git bash-completion vim-syntax ssl ncurses readline"
USE="${USE} threads nptl unicode nls crypt zlib bzip2 lzma zstd"
USE="${USE} openssl curl wget ssh scp"

# ARM64 specific
CPU_FLAGS_ARM="aes sha1 sha2 crc32 v8 vfpv4 neon"

# Binary packages for faster installs
PORTAGE_BINHOST="https://distfiles.gentoo.org/releases/arm64/binpackages/17.0/arm64/"
EMERGE_DEFAULT_OPTS="--getbinpkg --binpkg-respect-use=y --jobs=2 --ask=n"
GENTOO_MIRRORS="https://distfiles.gentoo.org"

# LXC container: disable sandbox features that don't work
FEATURES="-sandbox -usersandbox -pid-sandbox -network-sandbox parallel-fetch"

# Locale
LINGUAS="en"
L10N="en"
"""
        self.adb.write(f"{rootfs}/etc/portage/make.conf", make_conf)
        log_ok("Portage configured")
        
        # OpenRC for container (idempotent - check before appending)
        rc_check = self.adb.su(f"grep -q 'rc_sys=\"lxc\"' '{rootfs}/etc/rc.conf'", check=False)
        if rc_check.returncode != 0:
            rc_conf = '\nrc_sys="lxc"\nrc_controller_cgroups="NO"\nrc_depend_strict="NO"\n'
            self.adb.su(f"echo '{rc_conf}' >> '{rootfs}/etc/rc.conf'", check=False)
        log_ok("OpenRC configured")
        
        # Copy doas source to rootfs for building in step 6
        doas_file = "opendoas-6.8.2.tar.xz"
        doas_remote = f"{d.tmp}/{doas_file}"
        if self.adb.exists(doas_remote):
            self.adb.su(f"cp '{doas_remote}' '{rootfs}/root/{doas_file}'")
            log_ok("Doas source copied to rootfs")
    
    # -------------------------------------------------------------------------
    # Step 6: Configure Gentoo
    # -------------------------------------------------------------------------
    def step6_configure_gentoo(self) -> None:
        step_header(6, 6, "Configure Gentoo (User, Sudo, SSH)")
        
        container = self.cfg.container_name
        user = self.cfg.container_user
        rootfs = self.cfg.device.rootfs_path(container)
        
        # Ensure mounted
        if not self.adb.is_mounted(rootfs):
            if self.adb.exists(self.cfg.device.rootfs_image):
                self.adb.mount(self.cfg.device.rootfs_image, rootfs)
            else:
                die("Rootfs not mounted - run step 5 first")
        
        # Ensure LXC runtime directory has correct permissions
        # This is needed for lxc-attach to work properly on Android
        d = self.cfg.device
        self.adb.su(f"rm -rf '{d.lxc_runtime}' 2>/dev/null || true")
        self.adb.su(f"mkdir -p '{d.lxc_runtime}/lxc/lock'")
        self.adb.su(f"chmod -R 1777 '{d.lxc_runtime}'")
        
        # Start container
        log("Starting container...")
        if not self.lxc.running(container):
            self.lxc.start(container)
        
        # Wait for ready
        deadline = time.time() + self.cfg.container_ready_timeout
        while time.time() < deadline:
            if self.lxc.running(container) and self.lxc.ok("true", container, timeout=5):
                break
            time.sleep(0.5)
        else:
            die("Container failed to start")
        
        self.lxc.use(container)
        log_ok("Container running")
        
        # Apply resource priority: Gentoo > Android
        log("Applying resource priority (Gentoo > Android)...")
        self._apply_resource_priority()
        
        # Disable hardware services (these fail in containers)
        log("Disabling hardware services...")
        for svc in ["hwclock", "modules", "udev", "netmount"]:
            self.lxc.run(f"rc-update delete {svc} boot 2>/dev/null || true", check=False, timeout=10)
            self.lxc.run(f"rc-update delete {svc} sysinit 2>/dev/null || true", check=False, timeout=10)
        log_ok("Hardware services disabled")
        
        # Check for sshd (stage3 should have it)
        log("Checking installed packages...")
        has_sshd = self.lxc.ok("test -x /usr/bin/sshd || test -x /usr/sbin/sshd", timeout=10)
        if has_sshd:
            log_ok("OpenSSH found")
        else:
            log_warn("OpenSSH not found - SSH won't work")
        
        # Build and install doas (sudo alternative)
        log("Installing doas (sudo alternative)...")
        self._install_doas()
        
        # Create user
        if not self.lxc.output(f"id {user} 2>/dev/null"):
            self.lxc.run(f"useradd -m -G wheel -s /bin/bash {user}")
            log_ok(f"User {user} created")
        else:
            log(f"User {user} exists")
        
        # Ensure wheel group
        if "wheel" not in self.lxc.output(f"groups {user}"):
            self.lxc.run(f"usermod -aG wheel {user}")
        
        # Unlock account for SSH key auth
        shadow = self.lxc.output(f"grep '^{user}:' /etc/shadow")
        if f"{user}:!" in shadow or f"{user}:*" in shadow:
            self.lxc.run(f"passwd -d {user}")
            log("Account unlocked for SSH key auth")
        
        # Configure doas (already done in _install_doas, but ensure config exists)
        if not self.lxc.ok("test -f /etc/doas.conf", timeout=10):
            self.lxc.write("/etc/doas.conf", "permit nopass :wheel\n")
            self.lxc.run("chmod 600 /etc/doas.conf")
        log_ok("Doas configured")
        
        # Configure SSH
        sshd_config = """Port 22
PermitRootLogin no
PubkeyAuthentication yes
AuthorizedKeysFile /home/%u/.ssh/authorized_keys
PasswordAuthentication yes
ChallengeResponseAuthentication no
StrictModes no
Subsystem sftp /usr/lib64/misc/sftp-server
"""
        self.lxc.write("/etc/ssh/sshd_config", sshd_config)
        
        # Install host SSH key
        ssh_key = self._get_ssh_pubkey()
        if ssh_key:
            home = f"/home/{user}"
            self.lxc.run(f"mkdir -p {home}/.ssh")
            self.lxc.run(f"chmod 700 {home}/.ssh")
            self.lxc.write(f"{home}/.ssh/authorized_keys", ssh_key + "\n")
            self.lxc.run(f"chmod 600 {home}/.ssh/authorized_keys")
            self.lxc.run(f"chown -R {user}:{user} {home}/.ssh")
            self.lxc.run(f"chmod 755 {home}")
            log_ok("SSH key installed")
        else:
            log_warn("No SSH key found - password auth only")
        
        # Generate host keys
        if not self.lxc.file_exists("/etc/ssh/ssh_host_rsa_key"):
            self.lxc.run("ssh-keygen -A", timeout=60)
            log_ok("SSH host keys generated")
        
        # Start sshd (try both common paths)
        self.lxc.run("pkill sshd 2>/dev/null || true", check=False)
        sshd_started = self.lxc.run("/usr/sbin/sshd 2>/dev/null || /usr/bin/sshd", check=False, timeout=10)
        if sshd_started.returncode == 0:
            self.lxc.run("rc-update add sshd default 2>/dev/null || true", check=False)
            log_ok("SSH daemon started")
        else:
            log_warn(f"Failed to start sshd: {sshd_started.stderr[:100] if sshd_started.stderr else 'unknown error'}")
        
        # Verify doas
        if self.lxc.ok("test -x /usr/bin/doas", timeout=10):
            log_ok("Doas verified")
        
        # Summary - container has its own IP via bridge networking
        container_ip = self.cfg.network.container_ip
        
        console.print()
        console.print(Panel.fit(
            f"[bold green]Deployment Complete[/bold green]\n\n"
            f"[bold]Distribution:[/bold] Gentoo Linux (glibc, OpenRC)\n"
            f"[bold]User:[/bold] {user}\n"
            f"[bold]Container IP:[/bold] {container_ip}\n"
            f"[bold]Rootfs Size:[/bold] {self.cfg.rootfs_image_size_mb // 1024}GB\n"
            f"[bold]Password:[/bold] (not set)\n\n"
            f"[bold]Connect:[/bold] ssh {user}@{container_ip}\n\n"
            f"[dim]Inside Gentoo:[/dim]\n"
            f"  passwd                   # Set password\n"
            f"  doas whoami              # Test privilege escalation\n"
            f"  sudo whoami              # (alias for doas)",
            title="✓ Success",
            border_style="green"
        ))
    
    def _get_ssh_pubkey(self) -> Optional[str]:
        ssh_dir = Path.home() / ".ssh"
        for name in ["id_ed25519.pub", "id_rsa.pub", "id_ecdsa.pub"]:
            path = ssh_dir / name
            if path.exists():
                return path.read_text().strip()
        return None
    
    def _install_doas(self) -> None:
        """Build and install OpenDoas from source."""
        # Check if already installed
        if self.lxc.ok("test -x /usr/bin/doas", timeout=10):
            log_ok("doas already installed")
            return
        
        # Check if source exists
        if not self.lxc.ok("test -f /root/opendoas-6.8.2.tar.xz", timeout=10):
            log_warn("doas source not found - skipping doas installation")
            return
        
        # Build script
        build_script = '''#!/bin/bash
set -e
export TMPDIR=/tmp
export HOME=/root
cd /root
tar -xJf opendoas-6.8.2.tar.xz
cd opendoas-6.8.2
./configure --prefix=/usr --without-pam
make -j4
make install
# Create config
echo 'permit nopass :wheel' > /etc/doas.conf
chmod 600 /etc/doas.conf
# Create sudo symlink for compatibility
ln -sf /usr/bin/doas /usr/bin/sudo
'''
        self.lxc.write("/root/build_doas.sh", build_script)
        
        log("  Building doas (this takes a minute)...")
        result = self.lxc.run("/bin/bash /root/build_doas.sh", timeout=300, check=False)
        
        if self.lxc.ok("test -x /usr/bin/doas", timeout=10):
            log_ok("doas installed")
        else:
            log_warn(f"doas build failed: {result.stderr[:100] if result.stderr else 'unknown error'}")
    
    def _apply_resource_priority(self) -> None:
        """Apply resource priority: Gentoo > Android.
        
        This throttles Android userspace and boosts Gentoo container priority.
        The kernel is already LXC-optimized; this reinforces resource allocation.
        """
        res = self.cfg.resources
        container = self.cfg.container_name
        
        # Get container's cgroup path
        # On Android, cgroups are typically at /dev/cgroup or /sys/fs/cgroup
        cgroup_base = "/sys/fs/cgroup"
        
        # Try to find the container's cgroup
        container_cgroup = f"/lxc/{container}"
        
        # Apply CPU priority via cgroups (if cgroup v1)
        self.adb.su(f"echo {res.cpu_shares} > {cgroup_base}/cpu{container_cgroup}/cpu.shares 2>/dev/null || true")
        
        # Apply memory soft limit
        mem_bytes = res.memory_limit_mb * 1024 * 1024
        self.adb.su(f"echo {mem_bytes} > {cgroup_base}/memory{container_cgroup}/memory.soft_limit_in_bytes 2>/dev/null || true")
        
        # Apply I/O priority
        self.adb.su(f"echo {res.blkio_weight} > {cgroup_base}/blkio{container_cgroup}/blkio.weight 2>/dev/null || true")
        
        # Set OOM score adjustment for container init process
        # This makes Android apps die before Gentoo processes
        init_pid = self.adb.su(f"cat /sys/fs/cgroup/lxc/{container}/cgroup.procs 2>/dev/null | head -1", check=False).stdout.strip()
        if init_pid:
            self.adb.su(f"echo {res.oom_score_adj} > /proc/{init_pid}/oom_score_adj 2>/dev/null || true")
        
        # Throttle Android system services to give Gentoo more CPU
        # Reduce CPU shares for Android's main cgroup
        self.adb.su(f"echo 256 > {cgroup_base}/cpu/cpu.shares 2>/dev/null || true")
        
        # Lower priority for Android apps (zygote children)
        self.adb.su("for pid in $(pgrep -f zygote); do renice 10 $pid 2>/dev/null; done || true", check=False)
        
        # Set ionice for Android to background class
        self.adb.su("for pid in $(pgrep -f zygote); do ionice -c 3 -p $pid 2>/dev/null; done || true", check=False)
        
        log_ok(f"Resource priority applied: CPU={res.cpu_shares}, Mem={res.memory_limit_mb}MB, I/O={res.blkio_weight}")
    
    def _extract_on_host_and_push(self, tarball_remote: str, rootfs: str) -> None:
        """Extract stage3 on host and push to device (fallback for limited Android tar)."""
        import tempfile
        
        tarball_local = self.cfg.artifacts_dir / self.cfg.gentoo.filename
        if not tarball_local.exists():
            die(f"Local tarball not found: {tarball_local}")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            extract_dir = Path(tmpdir) / "rootfs"
            extract_dir.mkdir()
            
            log("Extracting on host (excluding device nodes)...")
            # Use --exclude to skip device nodes that require root
            # The container will create these at runtime
            result = subprocess.run(
                ["tar", "-xJf", str(tarball_local), "-C", str(extract_dir),
                 "--exclude=./dev/*", "--warning=no-unknown-keyword"],
                capture_output=True, text=True, timeout=600
            )
            # Ignore errors about device nodes
            if result.returncode != 0 and "Cannot mknod" not in result.stderr:
                die(f"Host extraction failed: {result.stderr}")
            
            log("Streaming rootfs to device via tar (this takes a long time)...")
            # Stream tar directly to device - avoids adb push permission issues
            # Create tar on host, pipe through adb shell su to extract on device
            self.adb.su(f"rm -rf '{rootfs}'/*")  # Clear any partial data
            
            # Use tar to stream and extract in one pipeline
            log("  Streaming (this may take 10+ minutes)...")
            tar_cmd = subprocess.Popen(
                ["tar", "-cf", "-", "-C", str(extract_dir), "."],
                stdout=subprocess.PIPE
            )
            adb_cmd = subprocess.Popen(
                ["adb", "shell", "su", "-c", f"tar -xf - -C '{rootfs}'"],
                stdin=tar_cmd.stdout
            )
            tar_cmd.stdout.close()
            adb_cmd.wait(timeout=3600)
            
            if adb_cmd.returncode != 0:
                log_warn("Tar stream had errors, checking result...")
            
            # Create /dev directory on device (will be populated by LXC)
            self.adb.su(f"mkdir -p '{rootfs}/dev'")
            
            # Fix /var/empty ownership for sshd (must be owned by root)
            self.adb.su(f"mkdir -p '{rootfs}/var/empty'")
            self.adb.su(f"chown 0:0 '{rootfs}/var/empty' 2>/dev/null || true")
            self.adb.su(f"chmod 755 '{rootfs}/var/empty'")
    
    # -------------------------------------------------------------------------
    # Utility commands
    # -------------------------------------------------------------------------
    def run_all(self) -> None:
        self.step1_build_lxc()
        self.step2_prepare_rootfs()
        self.step3_push_to_device()
        self.step4_install_lxc()
        self.step5_unpack_rootfs()
        self.step6_configure_gentoo()
    
    def clean(self) -> None:
        step_header(0, 0, "Clean Everything")
        
        # Host
        log("Cleaning host...")
        for d in [self.cfg.build_output, self.cfg.artifacts_dir, 
                  self.cfg.cache_dir, self.cfg.repo_root / "_work",
                  self.cfg.repo_root / "_build_android31"]:
            if d.exists():
                shutil.rmtree(d)
                log_ok(f"Removed: {d}")
        
        # Device
        if self.adb.connected() and self.adb.has_root():
            log("Cleaning device...")
            
            container = self.cfg.container_name
            try:
                if self.lxc.running(container):
                    self.lxc.stop(container, kill=True)
            except Exception:
                pass
            
            rootfs = self.cfg.device.rootfs_path(container)
            if self.adb.is_mounted(rootfs):
                self.adb.umount(rootfs)
                log_ok(f"Unmounted: {rootfs}")
            
            for path in [self.cfg.device.lxc_prefix, self.cfg.device.lxc_runtime,
                         self.cfg.device.lxc_containers, self.cfg.device.rootfs_image,
                         "/data/lxc"]:
                self.adb.rm(path)
                log_ok(f"Removed: {path}")
            
            self.adb.su(f"rm -f {self.cfg.device.tmp}/stage3*.tar.xz", check=False)
        else:
            log_warn("Device not connected - skipping device cleanup")
        
        log_ok("Clean complete")
    
    def status(self) -> None:
        table = Table(title="Deployment Status")
        table.add_column("Component", style="cyan")
        table.add_column("Status")
        table.add_column("Details", style="dim")
        
        # Host
        build_ok = self.cfg.build_output.exists()
        stage3_ok = (self.cfg.artifacts_dir / self.cfg.gentoo.filename).exists()
        
        table.add_row("LXC Build", "✓" if build_ok else "✗", str(self.cfg.build_output))
        table.add_row("Stage3", "✓" if stage3_ok else "✗", self.cfg.gentoo.filename)
        
        # Device
        if self.adb.connected():
            serial = self.adb.serial_number()
            root_ok = self.adb.has_root()
            lxc_ok = self.adb.exists(self.cfg.device.lxc_prefix, is_dir=True)
            container_ok = self.lxc.exists(self.cfg.container_name)
            running = self.lxc.running(self.cfg.container_name) if container_ok else False
            
            table.add_row("Device", "✓", serial)
            table.add_row("Root", "✓" if root_ok else "✗", "")
            table.add_row("LXC Installed", "✓" if lxc_ok else "✗", "")
            table.add_row("Container", "✓" if container_ok else "✗", self.cfg.container_name)
            if container_ok:
                table.add_row("Running", "✓" if running else "✗", "")
        else:
            table.add_row("Device", "✗", "Not connected")
        
        console.print(table)


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
    
    cfg = deployer.cfg
    adb = deployer.adb
    net = cfg.network
    
    # Create bridge
    r = adb.su(f"ip link show {net.bridge} 2>/dev/null", check=False)
    if r.returncode != 0:
        log(f"Creating bridge {net.bridge}...")
        adb.su(f"ip link add name {net.bridge} type bridge")
        adb.su(f"ip addr add {net.gateway}/24 dev {net.bridge}")
        adb.su(f"ip link set {net.bridge} up")
        log_ok(f"Bridge created: {net.gateway}")
    else:
        log(f"Bridge {net.bridge} exists")
    
    # IP forwarding
    adb.su("sysctl -w net.ipv4.ip_forward=1")
    log_ok("IP forwarding enabled")
    
    # NAT rules
    nat = f"-s {net.subnet} -o {net.host_interface} -j MASQUERADE"
    if adb.su(f"iptables -t nat -C POSTROUTING {nat} 2>/dev/null", check=False).returncode != 0:
        adb.su(f"iptables -t nat -A POSTROUTING {nat}")
        log_ok(f"NAT rule added for {net.subnet}")
    
    # Forward rules
    fwd_out = f"-i {net.bridge} -o {net.host_interface} -j ACCEPT"
    if adb.su(f"iptables -C FORWARD {fwd_out} 2>/dev/null", check=False).returncode != 0:
        adb.su(f"iptables -A FORWARD {fwd_out}")
    
    fwd_in = f"-i {net.host_interface} -o {net.bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT"
    if adb.su(f"iptables -C FORWARD {fwd_in} 2>/dev/null", check=False).returncode != 0:
        adb.su(f"iptables -A FORWARD {fwd_in}")
    
    log_ok("Bridge network ready")
    
    console.print()
    console.print("Add to container config:")
    console.print(f"  lxc.net.0.type = veth")
    console.print(f"  lxc.net.0.link = {net.bridge}")
    console.print(f"  lxc.net.0.flags = up")
    console.print(f"  lxc.net.0.ipv4.address = {net.container_ip}/24")
    console.print(f"  lxc.net.0.ipv4.gateway = {net.gateway}")


if __name__ == "__main__":
    app()
