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
    """Resource allocation for Gentoo container.
    
    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    FUNDAMENTAL RULE: GENTOO > ANDROID
    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    
    This device EXISTS to run Gentoo. Android is just the bootloader.
    
    GENTOO GETS:
    - ALL CPU cores at highest priority
    - ALL RAM (no limits)
    - ALL I/O bandwidth priority
    - 100GB disk space
    - OOM immunity (Android killed first)
    
    ANDROID GETS:
    - Whatever Gentoo isn't using
    - Demoted priority on everything
    - Killed first under memory pressure
    
    IF YOU ARE TEMPTED TO "BE FAIR" TO ANDROID: DON'T.
    ANDROID IS A PARASITE HOST. GENTOO IS THE PAYLOAD.
    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    """
    # CPU shares: 4096 vs Android's 256 = 16x priority for Gentoo
    cpu_shares: int = 4096
    
    # Memory: NO LIMIT - Gentoo takes what it needs, Android gets leftovers
    memory_limit_mb: int = 0  # 0 = unlimited (GENTOO > ANDROID)
    
    # Block I/O: 800 = Gentoo wins ALL I/O contention
    blkio_weight: int = 800
    
    # Nice: -10 = Gentoo processes run before ALL Android processes
    nice_value: int = -10
    
    # OOM: -900 = Android apps/services die LONG before Gentoo is touched
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
    gentoo: GentooConfig = field(default_factory=GentooConfig)
    device: DevicePaths = field(default_factory=DevicePaths)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    resources: ResourceConfig = field(default_factory=ResourceConfig)
    
    # Container settings
    container_name: str = "gentoo"
    container_user: str = "vince"
    default_password: str = "gentoo"  # Set during deployment, user can change later
    # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # GENTOO > ANDROID - THIS IS THE FUNDAMENTAL RULE
    # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    #
    # WHY 100GB:
    # - Gentoo is the PRIMARY WORKLOAD on this device
    # - Android is just a HOST, not the purpose of the device
    # - Android AOSP sits there with 90GB of EMPTY SPACE doing NOTHING
    # - Gentoo needs space for: portage tree, distfiles, builds, packages, dev work
    #
    # PREVIOUS VALUE WAS 32GB - THIS WAS WRONG BECAUSE:
    # - It treated Gentoo as a "guest" that should be small
    # - It prioritized Android's empty space over Gentoo's actual needs
    # - It violated the GENTOO > ANDROID rule
    #
    # THE DEVICE EXISTS TO RUN GENTOO. ANDROID IS JUST THE BOOTLOADER.
    # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    rootfs_image_size_mb: int = 102400  # 100GB - GENTOO > ANDROID
    
    # Timeouts (seconds)
    timeout_short: int = 10
    timeout_medium: int = 60
    timeout_long: int = 300
    container_ready_timeout: int = 30
    container_ready_poll_interval: float = 0.5
