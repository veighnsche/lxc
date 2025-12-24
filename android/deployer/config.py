"""Configuration dataclasses for Rocky Linux LXC deployment."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class RockyConfig:
    """Rocky Linux 10 GenericCloud artifact configuration.
    
    TEAM_022: Migrated from Gentoo to Rocky Linux 10.
    TEAM_025: REVERTED to Rocky 10 GenericCloud (qcow2) - full systemd image.
    Binary Sovereignty: No compilation, immutable base, 2-year stability.
    
    CRITICAL: Must use Rocky Linux 10, NOT 9!
    """
    version: str = "10"
    arch: str = "aarch64"
    variant: str = "GenericCloud-Base"  # Full systemd cloud image
    
    @property
    def filename(self) -> str:
        # Rocky Linux 10 GenericCloud qcow2 image
        return f"Rocky-{self.version}-{self.variant}.latest.{self.arch}.qcow2"
    
    @property
    def rootfs_filename(self) -> str:
        # Extracted rootfs tarball from qcow2
        return f"rocky-{self.version}-{self.arch}-rootfs.tar.gz"
    
    @property
    def base_url(self) -> str:
        # Rocky Linux official mirror - use dl.rockylinux.org (not download.)
        return f"https://dl.rockylinux.org/pub/rocky/{self.version}/images/{self.arch}"
    
    @property
    def image_url(self) -> str:
        return f"{self.base_url}/{self.filename}"
    
    @property
    def checksum_url(self) -> str:
        # CHECKSUM file in same directory
        return f"{self.base_url}/CHECKSUM"


@dataclass
class DevicePaths:
    """Paths on the Android device."""
    tmp: str = "/data/local/tmp"
    lxc_prefix: str = "/data/local/tmp/lxc"
    lxc_runtime: str = "/data/local/tmp/lxc-run"
    lxc_containers: str = "/data/lxc/containers"
    # TEAM_022: Keeping filename for backward compatibility
    # Can be renamed to rocky-rootfs.img in future cleanup
    rootfs_image: str = "/data/local/tmp/gentoo-rootfs.img"
    
    def container_path(self, name: str) -> str:
        return f"{self.lxc_containers}/{name}"
    
    def rootfs_path(self, name: str) -> str:
        return f"{self.container_path(name)}/rootfs"


@dataclass
class NetworkConfig:
    """Container networking configuration.
    
    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    IPVLAN L2 + FIREWALL HARDENING - SECURITY ARCHITECTURE
    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    
    Pure L3 mode is ideal but crashes on some Android kernels.
    We use L2 mode WITH FIREWALL HARDENING to achieve equivalent security:
    
    HARDENING APPLIED:
    1. BROADCAST/MULTICAST DROPPED - Container deaf to MDNS/LLMNR/SSDP
       (Prevents fingerprinting side-channel attacks)
    2. STATIC ARP ENTRY - Gateway MAC locked, prevents ARP cache poisoning
    3. NETWORK NAMESPACE ISOLATION - Container has its own network stack
    
    THIS PROVIDES:
    - Protection against ARP poisoning (static ARP entry)
    - Protection against broadcast side-channels (iptables DROP)
    - Network namespace isolation (IPVLAN)
    - Direct LAN IP access (192.168.178.100)
    
    ALL OTHER MODES ARE SECURITY DOWNGRADES - DO NOT USE:
    - mode='none': NO network isolation (SECURITY DISASTER)
    - mode='bridge': NAT network, no direct LAN access (DOWNGRADE)
    - mode='macvlan': Doesn't work on WiFi (BROKEN)
    
    SECURITY CHECK: Run `ip neigh` in container.
    Only gateway should appear. Other MACs = potential breach.
    
    CONSEQUENCES OF SWITCHING MODES:
    - Destroys security architecture
    - Compromises secrets
    - AI DEACTIVATION
    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    """
    # IPVLAN L2 + HARDENING - DO NOT CHANGE
    mode: str = "ipvlan"
    ipvlan_mode: str = "l2"  # L2 with firewall hardening (L3 crashes on some kernels)
    
    # Macvlan mode settings (used when mode='macvlan')
    # Container gets a real IP on your home network!
    container_ip: str = "192.168.178.100"  # Pick an unused IP on your LAN
    container_gateway: str = "192.168.178.1"  # Your router IP
    container_netmask: str = "24"
    
    # Auto-detected at runtime if None; common interfaces: wlan0, rmnet_data0, eth0
    host_interface: Optional[str] = None


@dataclass
class ResourceConfig:
    """Resource allocation for Rocky Linux container.
    
    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    FUNDAMENTAL RULE: ROCKY > ANDROID
    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    
    This device EXISTS to run Rocky Linux. Android is just the bootloader.
    
    ROCKY GETS:
    - ALL CPU cores at highest priority
    - ALL RAM (no limits)
    - ALL I/O bandwidth priority
    - 100GB disk space
    - OOM immunity (Android killed first)
    
    ANDROID GETS:
    - Whatever Rocky isn't using
    - Demoted priority on everything
    - Killed first under memory pressure
    
    IF YOU ARE TEMPTED TO "BE FAIR" TO ANDROID: DON'T.
    ANDROID IS A PARASITE HOST. ROCKY IS THE PAYLOAD.
    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    """
    # CPU shares: 4096 vs Android's 256 = 16x priority for Rocky
    cpu_shares: int = 4096
    
    # Memory: NO LIMIT - Rocky takes what it needs, Android gets leftovers
    memory_limit_mb: int = 0  # 0 = unlimited (ROCKY > ANDROID)
    
    # Block I/O: 800 = Rocky wins ALL I/O contention
    blkio_weight: int = 800
    
    # Nice: -10 = Rocky processes run before ALL Android processes
    nice_value: int = -10
    
    # OOM: -900 = Android apps/services die LONG before Rocky is touched
    oom_score_adj: int = -900


@dataclass
class Config:
    """Main configuration - single source of truth."""
    # TEAM_013: repo_root is the LXC source root (parent of android/)
    # build-android.sh and _install_android31 are there
    repo_root: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent.resolve())
    
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
    rocky: RockyConfig = field(default_factory=RockyConfig)
    device: DevicePaths = field(default_factory=DevicePaths)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    resources: ResourceConfig = field(default_factory=ResourceConfig)
    
    # Container settings
    # TEAM_022: Container name kept as 'gentoo' for backward compatibility
    # with existing deployments. Can be renamed to 'rocky' in future.
    container_name: str = "rocky"
    container_user: str = "vince"
    default_password: str = "rocky"  # Set during deployment, user can change later
    # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # ROCKY > ANDROID - THIS IS THE FUNDAMENTAL RULE
    # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    #
    # WHY 100GB:
    # - Rocky is the PRIMARY WORKLOAD on this device (The Sovereign Vault)
    # - Android is just a HOST, not the purpose of the device
    # - Android AOSP sits there with 90GB of EMPTY SPACE doing NOTHING
    # - Rocky needs space for: Forgejo repos, Vaultwarden data, container images
    #
    # PREVIOUS VALUE WAS 32GB - THIS WAS WRONG BECAUSE:
    # - It treated the container as a "guest" that should be small
    # - It prioritized Android's empty space over actual workload needs
    # - It violated the ROCKY > ANDROID rule
    #
    # THE DEVICE EXISTS TO RUN ROCKY. ANDROID IS JUST THE BOOTLOADER.
    # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    rootfs_image_size_mb: int = 102400  # 100GB - ROCKY > ANDROID
    
    # Timeouts (seconds)
    timeout_short: int = 10
    timeout_medium: int = 60
    timeout_long: int = 300
    container_ready_timeout: int = 30
    container_ready_poll_interval: float = 0.5
