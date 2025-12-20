# Phase 2 - Step 1 - UoW 1: Extract config.py

**Parent:** phase-2.md → Step 1  
**Goal:** Extract all configuration dataclasses from deploy.py into deployer/config.py

## Input Context
- Read `deploy.py` lines 86-226
- Target file: `deployer/config.py`

## Tasks

### 1. Create deployer/config.py with content:

```python
"""Configuration dataclasses for Gentoo LXC deployment."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


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
    """Container networking configuration.
    
    TEAM_009: Three modes supported:
    - mode='ipvlan': Real IP on home network via IPVLAN (PREFERRED - works on WiFi!)
    - mode='macvlan': Real IP on home network via MACVLAN (fails on WiFi)
    - mode='bridge': Internal NAT network (10.0.3.x) - requires port forwarding
    
    IPVLAN is preferred for direct SSH access - it shares the parent's MAC address,
    avoiding WiFi driver limitations that block MACVLAN.
    """
    # Network mode: 'ipvlan' (PREFERRED), 'macvlan', or 'bridge'
    # TEAM_009: IPVLAN works on wlan0! ABI-compatible kernel patches applied.
    mode: str = "ipvlan"
    
    # Bridge mode settings (used when mode='bridge')
    bridge: str = "lxcbr0"
    bridge_subnet: str = "10.0.3.0/24"
    bridge_gateway: str = "10.0.3.1"
    bridge_container_ip: str = "10.0.3.2"
    
    # Macvlan mode settings (used when mode='macvlan')
    # Container gets a real IP on your home network!
    container_ip: str = "192.168.178.100"  # Pick an unused IP on your LAN
    container_gateway: str = "192.168.178.1"  # Your router IP
    container_netmask: str = "24"
    
    # Auto-detected at runtime if None; common interfaces: wlan0, rmnet_data0, eth0
    host_interface: Optional[str] = None


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
    container_ready_poll_interval: float = 0.5
```

### 2. Verify import works:
```bash
cd /home/vince/Projects/android/lxc/android
python3 -c "from deployer.config import Config, GentooConfig, DevicePaths, NetworkConfig, ResourceConfig; print('OK')"
```

## Expected Output
- File `deployer/config.py` created (~140 lines)
- Import test passes

## Exit Criteria
- [ ] File created
- [ ] No syntax errors
- [ ] Import succeeds
