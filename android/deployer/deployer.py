"""Deployer - main deployment orchestration."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.panel import Panel

from .config import Config
from .console import console, log, log_ok, log_warn, log_err, die, step_header
from .adb import ADB, DeviceShell
from .lxc import LXC
from .download import Downloader, Crypto


class Deployer:
    """Deployment orchestrator."""
    
    def __init__(self, cfg: Config, adb: ADB):
        self.cfg = cfg
        self.adb = adb
        self.lxc = LXC(adb, cfg)
        
        if not os.environ.get("ANDROID_NDK_HOME") and not os.environ.get("ANDROID_NDK_ROOT"):
            ndk_path = cfg.repo_root / "_ndk" / "android-ndk-r27c"
            if ndk_path.exists():
                os.environ["ANDROID_NDK_HOME"] = str(ndk_path)
    
    @property
    def shell(self) -> DeviceShell:
        return self.adb.shell
    
    def _detect_host_interface(self) -> str:
        if self.cfg.network.host_interface:
            return self.cfg.network.host_interface
        out, _ = self.shell.run("ip route show default 2>/dev/null | head -1", timeout=10)
        if out.strip():
            parts = out.strip().split()
            if "dev" in parts:
                idx = parts.index("dev")
                if idx + 1 < len(parts):
                    log(f"Auto-detected interface: {parts[idx + 1]}")
                    return parts[idx + 1]
        for iface in ["wlan0", "rmnet_data0", "eth0", "usb0", "rndis0"]:
            out, rc = self.shell.run(f"ip link show {iface} 2>/dev/null", timeout=5)
            if rc == 0 and "UP" in out:
                log(f"Found active interface: {iface}")
                return iface
        log_warn("Could not detect network interface, using wlan0")
        return "wlan0"
    
    def _apply_kernelsu_selinux_rules(self) -> bool:
        """Apply SELinux rules via KernelSU for LXC networking.
        
        TEAM_008/009: KernelSU provides ksud for runtime SELinux policy modification.
        """
        log("Applying KernelSU SELinux rules for LXC networking...")
        _, rc = self.shell.run("which ksud 2>/dev/null || test -x /data/adb/ksud", timeout=5)
        if rc != 0:
            log_warn("ksud not found - KernelSU may not be installed or working")
            log_warn("Trying to continue anyway (may fail if SELinux is enforcing)")
            return False
        rules = [
            'allow shell self netlink_route_socket "create bind read write nlmsg_read nlmsg_write getattr setattr"',
            'allow shell self netlink_tcpdiag_socket "create bind read write nlmsg_read"',
            'allow shell self tun_socket "create read write ioctl"',
            'allow shell self capability "net_admin net_raw"',
            'allow shell self capability2 "syslog"',
            'allow shell self netlink_netfilter_socket "create bind read write nlmsg_read nlmsg_write"',
            'allow shell device chr_file "read write ioctl open"',
            'allow shell tun_device chr_file "read write ioctl open"',
            'allow shell proc_net sysctl_net_type "read write"',
            'allow shell self netlink_kobject_uevent_socket "create bind read write"',
        ]
        applied = 0
        for rule in rules:
            _, rc = self.shell.run(f'ksud sepolicy {rule}', timeout=10, check=False)
            if rc == 0:
                applied += 1
            else:
                _, rc = self.shell.run(f'/data/adb/ksud sepolicy {rule}', timeout=10, check=False)
                if rc == 0:
                    applied += 1
        if applied > 0:
            log_ok(f"Applied {applied}/{len(rules)} SELinux rules via KernelSU")
            return True
        log_warn("Could not apply SELinux rules - bridge networking may fail")
        return False
    
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
    
    def step2_prepare_rootfs(self) -> None:
        step_header(2, 6, "Download Gentoo Stage3 (SHA512 verified)")
        self.cfg.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.artifacts_dir.mkdir(parents=True, exist_ok=True)
        cached = self.cfg.cache_dir / self.cfg.gentoo.filename
        artifact = self.cfg.artifacts_dir / self.cfg.gentoo.filename
        if not cached.exists():
            log(f"URL: {self.cfg.gentoo.stage3_url}")
            Downloader.download(self.cfg.gentoo.stage3_url, cached, "Downloading stage3")
        else:
            log_ok(f"Using cached: {cached.name}")
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
        if not artifact.exists():
            shutil.copy(cached, artifact)
        log_ok(f"Ready: {artifact.name}")
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
        lxc_bin = f"{self.cfg.device.lxc_prefix}/bin/lxc-start"
        if self.adb.exists(lxc_bin):
            log_ok("LXC binaries already on device")
        else:
            log("Pushing LXC binaries...")
            self.adb._adb(["shell", "mkdir", "-p", self.cfg.device.lxc_prefix])
            for subdir in ["bin", "lib", "libexec", "etc", "share"]:
                src = self.cfg.build_output / subdir
                if src.exists():
                    dst = f"{self.cfg.device.lxc_prefix}/{subdir}"
                    if not self.adb.push(src, dst):
                        log_warn(f"Could not push {subdir}/ (symlinks?)")
            if not self.adb.exists(lxc_bin):
                die("Push failed: lxc-start not found")
            log_ok("LXC binaries pushed")
        tarball_remote = f"{self.cfg.device.tmp}/{self.cfg.gentoo.filename}"
        if self.adb.exists(tarball_remote):
            log_ok("Stage3 already on device")
        else:
            log("Pushing stage3 tarball (this takes a while)...")
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as p:
                p.add_task("Pushing...", total=None)
                self.adb.push(tarball, tarball_remote)
            log_ok("Stage3 pushed")
        doas_file = "opendoas-6.8.2.tar.xz"
        doas_local = self.cfg.artifacts_dir / doas_file
        doas_remote = f"{self.cfg.device.tmp}/{doas_file}"
        if doas_local.exists() and not self.adb.exists(doas_remote):
            log("Pushing doas source...")
            self.adb.push(doas_local, doas_remote)
            log_ok("Doas source pushed")
    
    def step4_install_lxc(self) -> None:
        step_header(4, 6, "Install LXC on Device")
        d = self.cfg.device
        container = self.cfg.container_name
        config_path = f"{d.container_path(container)}/config"
        self.adb.ensure_shell()
        if self.shell.exists(config_path):
            out, rc = self.shell.run(f"LD_LIBRARY_PATH={d.lxc_prefix}/lib {d.lxc_prefix}/bin/lxc-start --version")
            if rc == 0:
                log_ok(f"Already configured (lxc-start {out.strip()})")
                return
        log("Creating directories...")
        for path in [d.lxc_runtime, d.lxc_containers, f"{d.lxc_prefix}/etc/lxc",
                     d.container_path(container), d.rootfs_path(container)]:
            self.shell.mkdir(path)
        log_ok("Directories created")
        log("Setting permissions...")
        self.shell.run(f"chmod 755 {d.lxc_prefix}/bin/* 2>/dev/null || true")
        self.shell.run(f"chmod 755 {d.lxc_prefix}/libexec/lxc/* 2>/dev/null || true")
        self.shell.run(f"chmod 644 {d.lxc_prefix}/lib/*.so* 2>/dev/null || true")
        log_ok("Permissions set")
        log("Writing LXC configuration...")
        self.adb.write_file(f"{d.lxc_prefix}/etc/lxc/default.conf", "lxc.net.0.type = none\n")
        self.adb.write_file(f"{d.lxc_prefix}/etc/lxc/lxc.conf", f"lxc.lxcpath = {d.lxc_containers}\n")
        # TEAM_008: Apply KernelSU SELinux rules BEFORE network setup
        self._apply_kernelsu_selinux_rules()
        self._setup_network()
        net = self.cfg.network
        res = self.cfg.resources
        host_iface = self._detect_host_interface()
        if net.mode == "ipvlan":
            network_config = f"""# IPVLAN L2 networking - TEAM_009
lxc.net.0.type = ipvlan
lxc.net.0.ipvlan.mode = l2
lxc.net.0.link = {host_iface}
lxc.net.0.flags = up
lxc.net.0.ipv4.address = {net.container_ip}/{net.container_netmask}
lxc.net.0.ipv4.gateway = {net.container_gateway}"""
        elif net.mode == "macvlan":
            network_config = f"""# Macvlan networking
lxc.net.0.type = macvlan
lxc.net.0.macvlan.mode = bridge
lxc.net.0.link = {host_iface}
lxc.net.0.flags = up
lxc.net.0.ipv4.address = {net.container_ip}/{net.container_netmask}
lxc.net.0.ipv4.gateway = {net.container_gateway}"""
        else:
            network_config = f"""# Bridge networking
lxc.net.0.type = veth
lxc.net.0.link = {net.bridge}
lxc.net.0.flags = up
lxc.net.0.ipv4.address = {net.bridge_container_ip}/24
lxc.net.0.ipv4.gateway = {net.bridge_gateway}"""
        container_config = f"""# Gentoo LXC container configuration
lxc.uts.name = {container}
lxc.arch = aarch64
lxc.rootfs.path = dir:{d.rootfs_path(container)}

{network_config}

lxc.cgroup.cpu.shares = {res.cpu_shares}
lxc.cgroup.memory.soft_limit_in_bytes = {res.memory_limit_mb * 1024 * 1024}
lxc.cgroup.blkio.weight = {res.blkio_weight}
lxc.cgroup.memory.oom_control = 0

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

lxc.cap.drop =
"""
        self.adb.write_file(config_path, container_config)
        log_ok("Container config written")
        log("Patching LXC config for Android compatibility...")
        common_conf = f"{d.lxc_prefix}/share/lxc/config/common.conf"
        self.shell.run(f"sed -i 's/^lxc.seccomp.profile/#lxc.seccomp.profile/' {common_conf} 2>/dev/null || true")
        self.shell.run(f"sed -i 's/^lxc.cap.drop/#lxc.cap.drop/' {common_conf} 2>/dev/null || true")
        log_ok("LXC config patched for Android")
        out, _ = self.shell.run(f"LD_LIBRARY_PATH={d.lxc_prefix}/lib {d.lxc_prefix}/bin/lxc-start --version")
        log_ok(f"lxc-start version: {out.strip()}")
    
    def _setup_network(self) -> None:
        """Setup container networking based on mode. TEAM_009"""
        net = self.cfg.network
        host_iface = self._detect_host_interface()
        if net.mode == "ipvlan":
            self._setup_ipvlan_network(host_iface)
        elif net.mode == "macvlan":
            self._setup_macvlan_network(host_iface)
        else:
            self._setup_bridge_network(host_iface)
    
    def _setup_ipvlan_network(self, host_iface: str) -> None:
        """TEAM_009: IPVLAN L2 mode works on WiFi!"""
        net = self.cfg.network
        log(f"Setting up IPVLAN L2 network on {host_iface}...")
        log(f"Container will get IP: {net.container_ip}")
        self.shell.run("sysctl -w net.ipv4.ip_forward=1")
        out, rc = self.shell.run("zcat /proc/config.gz 2>/dev/null | grep CONFIG_IPVLAN", check=False)
        if "CONFIG_IPVLAN=y" not in out:
            log_warn("CONFIG_IPVLAN not enabled in kernel - IPVLAN may not work")
            log_warn("Falling back to bridge mode")
            self._setup_bridge_network(host_iface)
            return
        _, rc = self.shell.run(f"ip link show {host_iface} 2>/dev/null | grep -q UP", check=False)
        if rc != 0:
            log_warn(f"Host interface {host_iface} is not UP")
        log_ok(f"IPVLAN network ready - container will use {net.container_ip} via {host_iface}")
    
    def _setup_macvlan_network(self, host_iface: str) -> None:
        """WARNING: MACVLAN does NOT work on WiFi (wlan0)."""
        net = self.cfg.network
        macvlan_name = "lxc-macvlan"
        log(f"Setting up macvlan network on {host_iface}...")
        log(f"Container will get IP: {net.container_ip}")
        self.shell.run("sysctl -w net.ipv4.ip_forward=1")
        _, rc = self.shell.run(f"ip link show {macvlan_name} 2>/dev/null")
        if rc == 0:
            log(f"Macvlan {macvlan_name} already exists")
        else:
            log(f"Creating macvlan {macvlan_name} on {host_iface}...")
            out, rc = self.shell.run(f"ip link add {macvlan_name} link {host_iface} type macvlan mode bridge", check=False)
            if rc != 0:
                log_warn(f"Failed to create macvlan: {out}")
                log_warn("Falling back to bridge mode")
                self._setup_bridge_network(host_iface)
                return
            self.shell.run(f"ip link set {macvlan_name} up")
            log_ok(f"Macvlan created: {macvlan_name}")
        log_ok(f"Macvlan network ready - container will use {net.container_ip}")
    
    def _setup_bridge_network(self, host_iface: str) -> None:
        """Setup bridge networking with NAT (fallback mode)."""
        net = self.cfg.network
        _, rc = self.shell.run(f"ip link show {net.bridge} 2>/dev/null")
        if rc == 0:
            log(f"Bridge {net.bridge} already exists")
        else:
            log(f"Creating bridge {net.bridge}...")
            self.shell.run(f"ip link add name {net.bridge} type bridge")
            self.shell.run(f"ip addr add {net.bridge_gateway}/24 dev {net.bridge}")
            self.shell.run(f"ip link set {net.bridge} up")
            log_ok(f"Bridge created: {net.bridge_gateway}")
        self.shell.run("sysctl -w net.ipv4.ip_forward=1")
        log_ok("IP forwarding enabled")
        nat = f"-s {net.bridge_subnet} -o {host_iface} -j MASQUERADE"
        _, rc = self.shell.run(f"iptables -t nat -C POSTROUTING {nat} 2>/dev/null")
        if rc != 0:
            self.shell.run(f"iptables -t nat -A POSTROUTING {nat}")
            log_ok(f"NAT rule added for {host_iface}")
        fwd_out = f"-i {net.bridge} -o {host_iface} -j ACCEPT"
        _, rc = self.shell.run(f"iptables -C FORWARD {fwd_out} 2>/dev/null")
        if rc != 0:
            self.shell.run(f"iptables -A FORWARD {fwd_out}")
        fwd_in = f"-i {host_iface} -o {net.bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT"
        _, rc = self.shell.run(f"iptables -C FORWARD {fwd_in} 2>/dev/null")
        if rc != 0:
            self.shell.run(f"iptables -A FORWARD {fwd_in}")
        log_ok("Bridge network ready")
    
    def step5_unpack_rootfs(self) -> None:
        step_header(5, 6, "Unpack Gentoo Rootfs")
        d = self.cfg.device
        rootfs = d.rootfs_path(self.cfg.container_name)
        tarball = f"{d.tmp}/{self.cfg.gentoo.filename}"
        if not self.shell.exists(tarball):
            die(f"Stage3 not found: {tarball}")
        if self.shell.is_mounted(rootfs) and self.shell.exists(f"{rootfs}/bin/bash"):
            log_ok("Rootfs already unpacked")
            return
        if not self.shell.exists(d.rootfs_image):
            self.shell.create_ext4_image(d.rootfs_image, self.cfg.rootfs_image_size_mb)
        else:
            log(f"Using existing image: {d.rootfs_image}")
        if not self.shell.is_mounted(rootfs):
            self.shell.mount(d.rootfs_image, rootfs)
        if not self.shell.exists(f"{rootfs}/bin/bash"):
            log("Unpacking stage3 (this takes several minutes)...")
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as p:
                p.add_task("Extracting...", total=None)
                self.shell.run(f"cd {rootfs} && tar -xJf {tarball} 2>/dev/null || busybox tar -xJf {tarball} 2>/dev/null || toybox tar -xf {tarball}", timeout=600)
                if not self.shell.exists(f"{rootfs}/bin/bash"):
                    log_warn("Device tar failed, trying host extraction...")
                    self._extract_on_host_and_push(tarball, rootfs)
            if not self.shell.exists(f"{rootfs}/bin/bash"):
                die("Unpack failed: /bin/bash not found")
            log_ok("Stage3 unpacked")
        for d_name in ["dev", "proc", "sys", "run", "tmp"]:
            self.shell.mkdir(f"{rootfs}/{d_name}")
        self.shell.run(f"mkdir -p {rootfs}/var/empty")
        self.shell.run(f"chown 0:0 {rootfs}/var/empty 2>/dev/null || true")
        self.shell.run(f"chmod 755 {rootfs}/var/empty")
        self.adb.write_file(f"{rootfs}/etc/resolv.conf", "nameserver 8.8.8.8\n")
        log_ok("DNS configured")
        make_conf = """# Gentoo ARM64 - Pixel 6 optimized
COMMON_FLAGS="-O2 -pipe -mcpu=cortex-a76 -mtune=cortex-a76"
COMMON_FLAGS="${COMMON_FLAGS} -march=armv8.2-a+crypto+fp16+dotprod"
CFLAGS="${COMMON_FLAGS}"
CXXFLAGS="${COMMON_FLAGS}"
FCFLAGS="${COMMON_FLAGS}"
FFLAGS="${COMMON_FLAGS}"
MAKEOPTS="-j6 -l6"
ACCEPT_LICENSE="*"
USE="-systemd -wayland -X -alsa -cups -bluetooth -gnome -kde -pulseaudio"
USE="${USE} -gui -gtk -qt5 -qt6 -desktop -sound -video"
USE="${USE} ipv6 git bash-completion vim-syntax ssl ncurses readline"
USE="${USE} threads nptl unicode nls crypt zlib bzip2 lzma zstd openssl curl wget ssh scp"
CPU_FLAGS_ARM="aes sha1 sha2 crc32 v8 vfpv4 neon"
PORTAGE_BINHOST="https://distfiles.gentoo.org/releases/arm64/binpackages/17.0/arm64/"
EMERGE_DEFAULT_OPTS="--getbinpkg --binpkg-respect-use=y --jobs=2 --ask=n"
GENTOO_MIRRORS="https://distfiles.gentoo.org"
FEATURES="-sandbox -usersandbox -pid-sandbox -network-sandbox parallel-fetch"
LINGUAS="en"
L10N="en"
"""
        self.adb.write_file(f"{rootfs}/etc/portage/make.conf", make_conf)
        log_ok("Portage configured")
        _, rc = self.shell.run(f'grep -q \'rc_sys="lxc"\' {rootfs}/etc/rc.conf')
        if rc != 0:
            rc_conf = 'rc_sys="lxc"\nrc_controller_cgroups="NO"\nrc_depend_strict="NO"'
            self.shell.run(f"echo -e '\n{rc_conf}' >> {rootfs}/etc/rc.conf")
        log_ok("OpenRC configured")
        doas_file = "opendoas-6.8.2.tar.xz"
        doas_remote = f"{d.tmp}/{doas_file}"
        if self.shell.exists(doas_remote):
            self.shell.run(f"cp {doas_remote} {rootfs}/root/{doas_file}")
            log_ok("Doas source copied to rootfs")
    
    def step6_configure_gentoo(self) -> None:
        step_header(6, 6, "Configure Gentoo (User, Sudo, SSH)")
        container = self.cfg.container_name
        user = self.cfg.container_user
        rootfs = self.cfg.device.rootfs_path(container)
        if not self.shell.is_mounted(rootfs):
            if self.shell.exists(self.cfg.device.rootfs_image):
                self.shell.mount(self.cfg.device.rootfs_image, rootfs)
            else:
                die("Rootfs not mounted - run step 5 first")
        d = self.cfg.device
        self.shell.run(f"rm -rf {d.lxc_runtime} 2>/dev/null || true")
        self.shell.run(f"mkdir -p {d.lxc_runtime}/lxc/lock")
        self.shell.run(f"chmod -R 1777 {d.lxc_runtime}")
        log("Starting container...")
        if not self.lxc.running(container):
            self.lxc.start(container)
        deadline = time.time() + self.cfg.container_ready_timeout
        while time.time() < deadline:
            if self.lxc.running(container) and self.lxc.ok("true", container, timeout=5):
                break
            time.sleep(self.cfg.container_ready_poll_interval)
        else:
            die("Container failed to start")
        self.lxc.use(container)
        log_ok("Container running")
        log("Applying resource priority (Gentoo > Android)...")
        self._apply_resource_priority()
        log("Disabling hardware services...")
        for svc in ["hwclock", "modules", "udev", "netmount"]:
            self.lxc.run(f"rc-update delete {svc} boot 2>/dev/null || true", check=False, timeout=10)
            self.lxc.run(f"rc-update delete {svc} sysinit 2>/dev/null || true", check=False, timeout=10)
        log_ok("Hardware services disabled")
        log("Checking installed packages...")
        has_sshd = self.lxc.ok("test -x /usr/bin/sshd || test -x /usr/sbin/sshd", timeout=10)
        if has_sshd:
            log_ok("OpenSSH found")
        else:
            log_warn("OpenSSH not found - SSH won't work")
        log("Installing doas (sudo alternative)...")
        self._install_doas()
        if not self.lxc.output(f"id {user} 2>/dev/null"):
            self.lxc.run(f"useradd -m -G wheel -s /bin/bash {user}", timeout=self.cfg.timeout_short)
            log_ok(f"User {user} created")
        else:
            log(f"User {user} exists")
        if "wheel" not in self.lxc.output(f"groups {user}"):
            self.lxc.run(f"usermod -aG wheel {user}", timeout=self.cfg.timeout_short)
        shadow = self.lxc.output(f"grep '^{user}:' /etc/shadow")
        if f"{user}:!" in shadow or f"{user}:*" in shadow:
            self.lxc.run(f"passwd -d {user}", timeout=self.cfg.timeout_short)
            log("Account unlocked for SSH key auth")
        if not self.lxc.ok("test -f /etc/doas.conf", timeout=10):
            self.lxc.write("/etc/doas.conf", "permit nopass :wheel\n")
            self.lxc.run("chmod 600 /etc/doas.conf", timeout=self.cfg.timeout_short)
        log_ok("Doas configured")
        sftp_path = "/usr/lib64/misc/sftp-server"
        for candidate in ["/usr/lib64/misc/sftp-server", "/usr/lib/misc/sftp-server", "/usr/libexec/sftp-server", "/usr/lib/ssh/sftp-server"]:
            if self.lxc.ok(f"test -x {candidate}", timeout=5):
                sftp_path = candidate
                break
        sshd_config = f"""Port 22
PermitRootLogin no
PubkeyAuthentication yes
AuthorizedKeysFile /home/%u/.ssh/authorized_keys
PasswordAuthentication yes
ChallengeResponseAuthentication no
StrictModes no
Subsystem sftp {sftp_path}
"""
        self.lxc.write("/etc/ssh/sshd_config", sshd_config)
        ssh_key = self._get_ssh_pubkey()
        if ssh_key:
            home = f"/home/{user}"
            self.lxc.run(f"mkdir -p {home}/.ssh", timeout=self.cfg.timeout_short)
            self.lxc.run(f"chmod 700 {home}/.ssh", timeout=self.cfg.timeout_short)
            self.lxc.write(f"{home}/.ssh/authorized_keys", ssh_key + "\n")
            self.lxc.run(f"chmod 600 {home}/.ssh/authorized_keys", timeout=self.cfg.timeout_short)
            self.lxc.run(f"chown -R {user}:{user} {home}/.ssh", timeout=self.cfg.timeout_short)
            self.lxc.run(f"chmod 755 {home}", timeout=self.cfg.timeout_short)
            self.lxc.run(f"chown {user}:{user} {home}", timeout=self.cfg.timeout_short)
            log_ok("SSH key installed")
        else:
            log_warn("No SSH key found - password auth only")
        if not self.lxc.file_exists("/etc/ssh/ssh_host_rsa_key"):
            self.lxc.run("ssh-keygen -A", timeout=60)
            log_ok("SSH host keys generated")
        self.lxc.run("pkill sshd 2>/dev/null || true", check=False, timeout=self.cfg.timeout_short)
        _, rc = self.lxc.run("/usr/sbin/sshd 2>/dev/null || /usr/bin/sshd", check=False, timeout=10)
        if rc == 0:
            self.lxc.run("rc-update add sshd default 2>/dev/null || true", check=False, timeout=self.cfg.timeout_short)
            log_ok("SSH daemon started")
        else:
            log_warn("Failed to start sshd")
        if self.lxc.ok("test -x /usr/bin/doas", timeout=10):
            log_ok("Doas verified")
            if not self.lxc.ok("test -x /usr/bin/sudo", timeout=5):
                self.lxc.run("ln -sf /usr/bin/doas /usr/bin/sudo", timeout=self.cfg.timeout_short)
                log_ok("sudo -> doas symlink created")
        log("Setting up port forwarding...")
        self._setup_port_forward(user)
        self._verify_deployment(container, user)
    
    def _verify_deployment(self, container: str, user: str) -> None:
        """Verification gate - fail loudly if anything is broken."""
        log("Verifying deployment...")
        errors = []
        if not self.lxc.running(container):
            errors.append("Container is NOT running")
        if not self.lxc.ok("netstat -tln 2>/dev/null | grep -q ':22 ' || ss -tln | grep -q ':22 '", timeout=10):
            errors.append("SSH is NOT listening on port 22")
        if not self.lxc.ok(f"id {user}", timeout=10):
            errors.append(f"User '{user}' does NOT exist")
        if not self.lxc.ok("test -x /usr/bin/doas || test -x /usr/bin/sudo", timeout=10):
            errors.append("Neither doas nor sudo is installed")
        net = self.cfg.network
        container_ip = net.container_ip
        if net.mode == "ipvlan":
            # TEAM_013: IPVLAN verification - ping container IP directly
            if not self.shell.run_ok(f"ping -c 1 -W 3 {container_ip} 2>/dev/null"):
                errors.append(f"Container IP {container_ip} is NOT reachable via IPVLAN")
        elif net.mode == "macvlan":
            if not self.shell.run_ok(f"ping -c 1 -W 3 {container_ip} 2>/dev/null"):
                errors.append(f"Container IP {container_ip} is NOT reachable via macvlan")
        else:
            if not self.shell.run_ok(f"ping -c 1 -W 2 -I {net.bridge} {net.bridge_container_ip} 2>/dev/null"):
                errors.append(f"Container IP {net.bridge_container_ip} is NOT reachable")
        # TEAM_013: Only check port forward for bridge mode (IPVLAN/macvlan have direct access)
        if net.mode == "bridge":
            result = self.adb._adb(["forward", "--list"], timeout=5)
            if "tcp:2222" not in result.stdout:
                errors.append("Port forward tcp:2222 is NOT set up")
        if errors:
            console.print()
            console.print(Panel.fit("[bold red]DEPLOYMENT VERIFICATION FAILED[/bold red]\n\n" + "\n".join(f"✗ {e}" for e in errors), title="✗ ERRORS", border_style="red"))
            die(f"Verification failed: {len(errors)} error(s)")
        log_ok("All verification checks passed")
        if net.mode == "ipvlan":
            # TEAM_013: IPVLAN gives direct LAN access
            connect_info = f"[bold]Connect from ANY device on your LAN:[/bold]\n  ssh {user}@{container_ip}"
        elif net.mode == "macvlan":
            connect_info = f"[bold]Connect from ANY device:[/bold]\n  ssh {user}@{container_ip}"
        else:
            connect_info = f"[bold]Connect via adb forward:[/bold]\n  ssh -p 2222 {user}@localhost"
        console.print()
        console.print(Panel.fit(f"[bold green]Deployment Complete[/bold green]\n\n[bold]User:[/bold] {user}\n[bold]Container IP:[/bold] {container_ip}\n[bold]Network Mode:[/bold] {net.mode}\n\n{connect_info}", title="✓ Success", border_style="green"))
    
    def _get_ssh_pubkey(self) -> Optional[str]:
        ssh_dir = Path.home() / ".ssh"
        for name in ["id_ed25519.pub", "id_rsa.pub", "id_ecdsa.pub"]:
            path = ssh_dir / name
            if path.exists():
                return path.read_text().strip()
        return None
    
    def _setup_port_forward(self, user: str) -> None:
        """TEAM_004: Setup port forwarding via iptables DNAT."""
        container_ip = self.cfg.network.container_ip
        self.shell.run(f"iptables -t nat -D PREROUTING -p tcp --dport 2222 -j DNAT --to-destination {container_ip}:22 2>/dev/null || true")
        self.shell.run(f"iptables -t nat -D OUTPUT -p tcp --dport 2222 -j DNAT --to-destination {container_ip}:22 2>/dev/null || true")
        self.shell.run(f"iptables -t nat -A PREROUTING -p tcp --dport 2222 -j DNAT --to-destination {container_ip}:22")
        self.shell.run(f"iptables -t nat -A OUTPUT -p tcp --dport 2222 -j DNAT --to-destination {container_ip}:22")
        self.shell.run("echo 1 > /proc/sys/net/ipv4/ip_forward")
        self.adb._adb(["forward", "--remove", "tcp:2222"], timeout=5)
        self.adb._adb(["forward", "tcp:2222", "tcp:2222"], timeout=10)
        log_ok(f"Port forwarding: localhost:2222 -> {container_ip}:22")
    
    def _install_doas(self) -> None:
        if self.lxc.ok("test -x /usr/bin/doas", timeout=10):
            log_ok("doas already installed")
            return
        if not self.lxc.ok("test -f /root/opendoas-6.8.2.tar.xz", timeout=10):
            log_warn("doas source not found - skipping")
            return
        build_script = '#!/bin/bash\nset -e\nexport TMPDIR=/tmp\nexport HOME=/root\ncd /root\ntar -xJf opendoas-6.8.2.tar.xz\ncd opendoas-6.8.2\n./configure --prefix=/usr --without-pam\nmake -j4\nmake install\necho "permit nopass :wheel" > /etc/doas.conf\nchmod 600 /etc/doas.conf\nln -sf /usr/bin/doas /usr/bin/sudo\n'
        self.lxc.write("/root/build_doas.sh", build_script)
        log("  Building doas (this takes a minute)...")
        result = self.lxc.run("/bin/bash /root/build_doas.sh", timeout=300, check=False)
        if self.lxc.ok("test -x /usr/bin/doas", timeout=10):
            log_ok("doas installed")
        else:
            log_warn(f"doas build failed: {result[0][:100] if result[0] else 'unknown error'}")
    
    def _apply_resource_priority(self) -> None:
        res = self.cfg.resources
        container = self.cfg.container_name
        cgroup_base = "/sys/fs/cgroup"
        container_cgroup = f"/lxc/{container}"
        self.shell.run(f"echo {res.cpu_shares} > {cgroup_base}/cpu{container_cgroup}/cpu.shares 2>/dev/null || true", timeout=10)
        mem_bytes = res.memory_limit_mb * 1024 * 1024
        self.shell.run(f"echo {mem_bytes} > {cgroup_base}/memory{container_cgroup}/memory.soft_limit_in_bytes 2>/dev/null || true", timeout=10)
        self.shell.run(f"echo {res.blkio_weight} > {cgroup_base}/blkio{container_cgroup}/blkio.weight 2>/dev/null || true", timeout=10)
        init_pid = self.shell.run_output(f"cat /sys/fs/cgroup/lxc/{container}/cgroup.procs 2>/dev/null | head -1")
        if init_pid and init_pid.isdigit():
            self.shell.run(f"echo {res.oom_score_adj} > /proc/{init_pid}/oom_score_adj 2>/dev/null || true", timeout=10)
        try:
            self.shell.run(f"echo 256 > {cgroup_base}/cpu/cpu.shares 2>/dev/null || true", timeout=10)
            self.shell.run("pgrep -f zygote | head -5 | xargs -I{} renice 10 {} 2>/dev/null || true", timeout=10)
        except TimeoutError:
            log_warn("Resource throttling timed out - skipping")
        log_ok(f"Resource priority applied: CPU={res.cpu_shares}, Mem={res.memory_limit_mb}MB")
    
    def _extract_on_host_and_push(self, tarball_remote: str, rootfs: str) -> None:
        tarball_local = self.cfg.artifacts_dir / self.cfg.gentoo.filename
        if not tarball_local.exists():
            die(f"Local tarball not found: {tarball_local}")
        with tempfile.TemporaryDirectory() as tmpdir:
            gzip_tarball = Path(tmpdir) / "stage3.tar.gz"
            gzip_remote = f"{self.cfg.device.tmp}/stage3.tar.gz"
            log("Converting xz to gzip (this takes a few minutes)...")
            result = subprocess.run(f"xz -dc '{tarball_local}' | gzip -1 > '{gzip_tarball}'", shell=True, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                die(f"Conversion failed: {result.stderr}")
            log(f"Pushing gzip tarball ({gzip_tarball.stat().st_size // (1024*1024)}MB)...")
            if not self.adb.push(gzip_tarball, gzip_remote, timeout=600):
                die("Failed to push gzip tarball")
            log_ok("Gzip tarball pushed")
            log("Extracting on device...")
            self.shell.run(f"rm -rf {rootfs}/*")
            out, rc = self.shell.run(f"cd {rootfs} && tar -xzf {gzip_remote}", timeout=600)
            if rc != 0:
                log_warn(f"Extraction had issues: {out[:200]}")
            self.shell.run(f"rm -f {gzip_remote}")
            self.shell.mkdir(f"{rootfs}/dev")
            self.shell.run(f"mkdir -p {rootfs}/var/empty")
            self.shell.run(f"chown 0:0 {rootfs}/var/empty 2>/dev/null || true")
            self.shell.run(f"chmod 755 {rootfs}/var/empty")
    
    def run_all(self) -> None:
        try:
            self.step1_build_lxc()
            self.step2_prepare_rootfs()
            self.step3_push_to_device()
            self.step4_install_lxc()
            self.step5_unpack_rootfs()
            self.step6_configure_gentoo()
        finally:
            self.adb.close()
    
    def clean(self) -> None:
        step_header(0, 0, "Clean Everything")
        log("Cleaning host...")
        for d in [self.cfg.build_output, self.cfg.artifacts_dir, self.cfg.cache_dir, self.cfg.repo_root / "_work", self.cfg.repo_root / "_build_android31"]:
            if d.exists():
                shutil.rmtree(d)
                log_ok(f"Removed: {d}")
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
            for path in [self.cfg.device.lxc_prefix, self.cfg.device.lxc_runtime, self.cfg.device.lxc_containers, self.cfg.device.rootfs_image, "/data/lxc"]:
                self.adb.rm(path)
                log_ok(f"Removed: {path}")
            self.shell.run(f"rm -f {self.cfg.device.tmp}/stage3*.tar.xz")
        else:
            log_warn("Device not connected - skipping device cleanup")
        log_ok("Clean complete")
    
    def status(self) -> None:
        table = Table(title="Deployment Status")
        table.add_column("Component", style="cyan")
        table.add_column("Status")
        table.add_column("Details", style="dim")
        build_ok = self.cfg.build_output.exists()
        stage3_ok = (self.cfg.artifacts_dir / self.cfg.gentoo.filename).exists()
        table.add_row("LXC Build", "✓" if build_ok else "✗", str(self.cfg.build_output))
        table.add_row("Stage3", "✓" if stage3_ok else "✗", self.cfg.gentoo.filename)
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
