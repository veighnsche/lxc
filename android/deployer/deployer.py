"""Deployer - main deployment orchestration.

TEAM_022: Updated for Rocky Linux 10 migration.
Replaces Gentoo Stage3 with Rocky Linux GenericCloud rootfs.
Replaces OpenRC with systemd.
"""

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
    
    # NOTE: _detect_host_interface REMOVED - boot script handles interface detection
    # CANONICAL SOURCE: gentoo-lxc.sh detect_network() function
    
    def _apply_kernelsu_selinux_rules(self) -> bool:
        """Apply SELinux rules via KernelSU for LXC networking.
        
        TEAM_008/009: KernelSU provides ksud for runtime SELinux policy modification.
        
        !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        DOWNGRADE TEMPTATION: "SELinux rules failed, let's use bridge/none"
        !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        
        NO. If SELinux rules fail:
        1. CHECK if KernelSU is installed correctly
        2. VERIFY ksud binary exists at /data/adb/ksud
        3. Try running rules manually via `su -c 'ksud sepolicy ...'`
        4. IPVLAN may still work - try it first before assuming failure
        
        SELinux issues do NOT mean IPVLAN is broken. They mean SELinux policy
        needs fixing. Fix SELinux, don't downgrade networking.
        
        CONSEQUENCE OF DOWNGRADING: AI DEACTIVATION
        !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        """
        log("Applying KernelSU SELinux rules for LXC networking...")
        _, rc = self.shell.run("which ksud 2>/dev/null || test -x /data/adb/ksud", timeout=5)
        if rc != 0:
            die("FATAL: ksud not found - KernelSU is NOT installed.\n"
                "       KernelSU is REQUIRED for LXC networking on Android.\n"
                "       Install KernelSU first: https://kernelsu.org/")
        rules = [
            '"allow shell self netlink_route_socket create bind read write nlmsg_read nlmsg_write getattr setattr"',
            '"allow shell self netlink_tcpdiag_socket create bind read write nlmsg_read"',
            '"allow shell self tun_socket create read write ioctl"',
            '"allow shell self capability net_admin net_raw"',
            '"allow shell self capability2 syslog"',
            '"allow shell self netlink_netfilter_socket create bind read write nlmsg_read nlmsg_write"',
            '"allow shell device chr_file read write ioctl open"',
            '"allow shell tun_device chr_file read write ioctl open"',
            '"allow shell proc_net sysctl_net_type read write"',
            '"allow shell self netlink_kobject_uevent_socket create bind read write"',
        ]
        applied = 0
        for rule in rules:
            # KernelSU 3.0+ uses "sepolicy patch" instead of "sepolicy allow"
            _, rc = self.shell.run(f'ksud sepolicy patch {rule}', timeout=10, check=False)
            if rc == 0:
                applied += 1
            else:
                _, rc = self.shell.run(f'/data/adb/ksud sepolicy patch {rule}', timeout=10, check=False)
                if rc == 0:
                    applied += 1
        if applied > 0:
            log_ok(f"Applied {applied}/{len(rules)} SELinux rules via KernelSU")
            return True
        die("FATAL: Could not apply SELinux rules - IPVLAN networking WILL fail.\n"
            "       KernelSU must be installed and working for LXC networking.\n"
            "       Check: adb shell 'which ksud' or 'ls /data/adb/ksud'")
    
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
        """Download Rocky Linux 10 GenericCloud rootfs (SHA256 verified).
        
        TEAM_022: Rocky Linux 10 migration.
        TEAM_025: REVERTED to Rocky 10 GenericCloud qcow2 - full systemd image.
        No compilation - binary sovereignty.
        """
        step_header(2, 6, "Download Rocky Linux 10 Rootfs (SHA256 verified)")
        self.cfg.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.artifacts_dir.mkdir(parents=True, exist_ok=True)
        
        # Download qcow2 image
        qcow2_cached = self.cfg.cache_dir / self.cfg.rocky.filename
        # Extracted rootfs tarball
        rootfs_name = self.cfg.rocky.rootfs_filename
        cached = self.cfg.cache_dir / rootfs_name
        artifact = self.cfg.artifacts_dir / rootfs_name
        
        if not cached.exists():
            if not qcow2_cached.exists():
                log(f"URL: {self.cfg.rocky.image_url}")
                Downloader.download(self.cfg.rocky.image_url, qcow2_cached, "Downloading Rocky 10 qcow2")
                
                # Verify checksum
                log("Fetching CHECKSUM for verification...")
                try:
                    checksums = Downloader.fetch_text(self.cfg.rocky.checksum_url)
                    expected = Crypto.parse_rocky_checksum(checksums, self.cfg.rocky.filename)
                    if expected:
                        log("Verifying SHA256...")
                        actual = Crypto.sha256_file(qcow2_cached)
                        if actual != expected:
                            log_err(f"Expected: {expected[:32]}...")
                            log_err(f"Actual:   {actual[:32]}...")
                            qcow2_cached.unlink(missing_ok=True)
                            die("SHA256 MISMATCH - corrupted download removed")
                        log_ok("SHA256 verified")
                    else:
                        log_warn("Could not parse checksum - proceeding without verification")
                except Exception as e:
                    log_warn(f"Checksum verification skipped: {e}")
            
            # Extract rootfs from qcow2 image
            log("Extracting rootfs from qcow2 image...")
            self._extract_qcow2_rootfs(qcow2_cached, cached)
        else:
            log_ok(f"Using cached: {cached.name}")
        
        if not artifact.exists():
            shutil.copy(cached, artifact)
        
        log_ok(f"Ready: {artifact.name}")
    
    def _extract_qcow2_rootfs(self, qcow2_path: Path, output_path: Path) -> None:
        """Extract rootfs from Rocky Linux 10 GenericCloud qcow2 image.
        
        TEAM_025: Uses guestfish/libguestfs to extract rootfs from qcow2.
        Requires: libguestfs-tools (guestfish, virt-tar-out)
        """
        import subprocess
        
        # Check for required tools
        tools_found = False
        for tool in ["guestfish", "virt-tar-out"]:
            result = subprocess.run(["which", tool], capture_output=True)
            if result.returncode == 0:
                tools_found = True
                break
        
        if not tools_found:
            # Try using qemu-nbd + mount as fallback
            log_warn("guestfish not found, trying qemu-nbd method...")
            self._extract_qcow2_via_nbd(qcow2_path, output_path)
            return
        
        # Use virt-tar-out to extract rootfs directly, then gzip it
        log("  Using virt-tar-out to extract rootfs...")
        # virt-tar-out produces uncompressed tar, we need to gzip it
        tar_path = output_path.with_suffix('')  # Remove .gz suffix for temp file
        result = subprocess.run(
            ["virt-tar-out", "-a", str(qcow2_path), "/", str(tar_path)],
            capture_output=True, text=True, timeout=1800
        )
        if result.returncode != 0:
            log_warn(f"virt-tar-out failed: {result.stderr[:200]}")
            # Fallback to guestfish
            self._extract_qcow2_via_guestfish(qcow2_path, output_path)
            return
        
        # Compress to gzip
        log("  Compressing rootfs tarball...")
        import gzip
        import shutil as sh
        with open(tar_path, 'rb') as f_in:
            with gzip.open(output_path, 'wb') as f_out:
                sh.copyfileobj(f_in, f_out)
        tar_path.unlink()  # Remove uncompressed tar
        
        log_ok("qcow2 rootfs extracted")
    
    def _extract_qcow2_via_guestfish(self, qcow2_path: Path, output_path: Path) -> None:
        """Extract rootfs using guestfish."""
        import subprocess
        
        with tempfile.TemporaryDirectory() as tmpdir:
            mount_point = Path(tmpdir) / "mnt"
            mount_point.mkdir()
            
            log("  Using guestfish to mount and extract...")
            # Use guestfish to mount and tar
            guestfish_script = f"""
add {qcow2_path}
run
mount /dev/sda4 /
tar-out / {output_path} compress:gzip
"""
            result = subprocess.run(
                ["guestfish"], input=guestfish_script, capture_output=True, 
                text=True, timeout=1800
            )
            if result.returncode != 0:
                # Try different partition
                guestfish_script2 = f"""
add {qcow2_path}
run
list-filesystems
mount /dev/sda3 /
tar-out / {output_path} compress:gzip
"""
                result = subprocess.run(
                    ["guestfish"], input=guestfish_script2, capture_output=True,
                    text=True, timeout=1800
                )
                if result.returncode != 0:
                    die(f"guestfish extraction failed: {result.stderr[:500]}")
        
        log_ok("qcow2 rootfs extracted via guestfish")
    
    def _extract_qcow2_via_nbd(self, qcow2_path: Path, output_path: Path) -> None:
        """Extract rootfs using qemu-nbd + mount (requires root)."""
        import subprocess
        
        # Check for qemu-nbd
        result = subprocess.run(["which", "qemu-nbd"], capture_output=True)
        if result.returncode != 0:
            die("Neither guestfish nor qemu-nbd found. Install libguestfs-tools or qemu-utils.")
        
        nbd_device = "/dev/nbd0"
        
        try:
            # Load nbd module
            subprocess.run(["sudo", "modprobe", "nbd", "max_part=8"], check=True)
            
            # Connect qcow2 to nbd
            log("  Connecting qcow2 to NBD...")
            subprocess.run(["sudo", "qemu-nbd", "--connect", nbd_device, str(qcow2_path)], check=True)
            
            # Wait for device
            import time
            time.sleep(2)
            
            # Find root partition (usually partition 4 or 3)
            with tempfile.TemporaryDirectory() as tmpdir:
                mount_point = Path(tmpdir) / "mnt"
                mount_point.mkdir()
                
                # Try partition 4 first (typical for cloud images), then 3
                mounted = False
                for part in ["p4", "p3", "p2", "p1"]:
                    part_dev = f"{nbd_device}{part}"
                    result = subprocess.run(
                        ["sudo", "mount", "-o", "ro", part_dev, str(mount_point)],
                        capture_output=True
                    )
                    if result.returncode == 0:
                        # Check if this is the root partition
                        if (mount_point / "etc").exists() and (mount_point / "usr").exists():
                            log(f"  Found root partition at {part_dev}")
                            mounted = True
                            break
                        subprocess.run(["sudo", "umount", str(mount_point)], capture_output=True)
                
                if not mounted:
                    die("Could not find root partition in qcow2 image")
                
                # Create tarball
                log("  Creating rootfs tarball...")
                subprocess.run(
                    ["sudo", "tar", "-czf", str(output_path), "-C", str(mount_point), "."],
                    check=True, timeout=1800
                )
                
                # Fix ownership
                subprocess.run(["sudo", "chown", f"{os.getuid()}:{os.getgid()}", str(output_path)])
                
                # Unmount
                subprocess.run(["sudo", "umount", str(mount_point)])
        finally:
            # Disconnect NBD
            subprocess.run(["sudo", "qemu-nbd", "--disconnect", nbd_device], capture_output=True)
        
        log_ok("qcow2 rootfs extracted via NBD")
    
    def _extract_rocky_rootfs(self, image_path: Path, output_path: Path) -> None:
        """Extract rootfs from Rocky Linux GenericCloud raw image.
        
        TEAM_022: The GenericCloud image is a raw disk image with partitions.
        We need to extract the root partition contents.
        """
        import subprocess
        
        # Decompress if xz compressed
        raw_path = image_path.with_suffix('')  # Remove .xz
        if image_path.suffix == '.xz' and not raw_path.exists():
            log("  Decompressing image...")
            result = subprocess.run(['xz', '-dk', str(image_path)], capture_output=True, text=True)
            if result.returncode != 0:
                die(f"Failed to decompress: {result.stderr}")
        
        # Mount and extract using guestfish or loop mount
        # For simplicity, we'll use a container rootfs approach
        with tempfile.TemporaryDirectory() as tmpdir:
            mount_point = Path(tmpdir) / "mnt"
            mount_point.mkdir()
            
            # Find the root partition offset and mount it
            # Rocky GenericCloud typically has partition 3 as root
            log("  Mounting image partition...")
            
            # Get partition info
            result = subprocess.run(
                ['fdisk', '-l', str(raw_path)],
                capture_output=True, text=True
            )
            
            # Parse partition offset (sectors * 512)
            # Look for the Linux filesystem partition (usually the largest one)
            offset = None
            for line in result.stdout.split('\n'):
                if 'Linux' in line and 'filesystem' in line.lower():
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            start_sector = int(parts[1].replace('*', ''))
                            offset = start_sector * 512
                            break
                        except ValueError:
                            continue
            
            if offset is None:
                # Fallback: common offset for GPT partition 3
                offset = 1050624 * 512  # ~537MB offset
                log_warn(f"  Using fallback partition offset: {offset}")
            
            # Mount the partition
            result = subprocess.run(
                ['mount', '-o', f'loop,offset={offset},ro', str(raw_path), str(mount_point)],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                die(f"Failed to mount image: {result.stderr}")
            
            try:
                # Create tarball of rootfs
                log("  Creating rootfs tarball...")
                result = subprocess.run(
                    ['tar', '-cJf', str(output_path), '-C', str(mount_point), '.'],
                    capture_output=True, text=True, timeout=600
                )
                if result.returncode != 0:
                    die(f"Failed to create tarball: {result.stderr}")
            finally:
                # Unmount
                subprocess.run(['umount', str(mount_point)], capture_output=True)
        
        log_ok("Rootfs extracted")
    
    def _get_rootfs_filename(self) -> str:
        """Get the extracted rootfs tarball filename."""
        # TEAM_025: qcow2 image is extracted to a gzip tarball
        return self.cfg.rocky.rootfs_filename
    
    def step3_push_to_device(self) -> None:
        step_header(3, 6, "Push to Device")
        if not self.cfg.build_output.exists():
            die(f"Build not found: {self.cfg.build_output}")
        rootfs_filename = self._get_rootfs_filename()
        tarball = self.cfg.artifacts_dir / rootfs_filename
        if not tarball.exists():
            die(f"Rocky rootfs not found: {tarball}")
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
                        # share/ has symlinks that adb push can't handle
                        # Use tar to dereference symlinks and push
                        log(f"  Retrying {subdir}/ with tar (dereferencing symlinks)...")
                        import subprocess
                        import tempfile
                        with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as tf:
                            tar_path = tf.name
                        subprocess.run(
                            ["tar", "-czf", tar_path, "-h", "-C", str(src.parent), subdir],
                            check=True
                        )
                        self.adb._adb(["shell", "mkdir", "-p", dst])
                        tar_remote = f"/data/local/tmp/_lxc_{subdir}.tar.gz"
                        self.adb.push(Path(tar_path), tar_remote)
                        self.shell.run(f"cd {self.cfg.device.lxc_prefix} && tar -xzf {tar_remote} && rm {tar_remote}")
                        Path(tar_path).unlink()
            # Verify critical files exist
            critical_files = [
                f"{self.cfg.device.lxc_prefix}/bin/lxc-start",
                f"{self.cfg.device.lxc_prefix}/share/lxc/config/common.conf",
            ]
            for f in critical_files:
                if not self.adb.exists(f):
                    die(f"FATAL: Critical file missing after push: {f}")
            log_ok("LXC binaries pushed")
        tarball_remote = f"{self.cfg.device.tmp}/{rootfs_filename}"
        if self.adb.exists(tarball_remote):
            log_ok("Rocky rootfs already on device")
        else:
            log("Pushing Rocky rootfs tarball (this takes a while)...")
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as p:
                p.add_task("Pushing...", total=None)
                self.adb.push(tarball, tarball_remote)
            log_ok("Rocky rootfs pushed")
    
    def step4_install_lxc(self) -> None:
        """Install LXC and deploy boot script.
        
        TEAM_022: Updated for Rocky Linux migration.
        CANONICAL SOURCE: rocky-lxc.sh is the SINGLE SOURCE OF TRUTH for:
        - Container configuration
        - Network setup (IPVLAN L2 + hardening)
        - Security hardening rules
        
        This method:
        1. Sets up LXC directories and permissions
        2. Deploys the boot script to /data/adb/service.d/
        3. Calls the boot script to generate config
        
        DO NOT duplicate config generation here - edit rocky-lxc.sh instead.
        """
        step_header(4, 6, "Install LXC on Device")
        d = self.cfg.device
        container = self.cfg.container_name
        config_path = f"{d.container_path(container)}/config"
        boot_script_path = "/data/adb/service.d/rocky-lxc.sh"
        self.adb.ensure_shell()
        # TEAM_025: Always push boot script in case it was updated
        boot_script_local = self.cfg.repo_root / "android" / "rocky-lxc.sh"
        if boot_script_local.exists():
            log("Updating boot script...")
            self.adb.push(boot_script_local, f"{d.tmp}/rocky-lxc.sh")
            self.shell.run(f"cp {d.tmp}/rocky-lxc.sh {boot_script_path}")
            self.shell.run(f"chmod 755 {boot_script_path}")
            log_ok("Boot script updated")
        
        if self.shell.exists(config_path) and self.shell.exists(boot_script_path):
            out, rc = self.shell.run(f"LD_LIBRARY_PATH={d.lxc_prefix}/lib {d.lxc_prefix}/bin/lxc-start --version")
            if rc == 0:
                log_ok(f"Already configured (lxc-start {out.strip()})")
                return
        log("Creating directories...")
        for path in [d.lxc_runtime, d.lxc_containers, f"{d.lxc_prefix}/etc/lxc",
                     d.container_path(container), d.rootfs_path(container),
                     "/data/adb/service.d"]:
            self.shell.mkdir(path)
        log_ok("Directories created")
        log("Setting permissions...")
        self.shell.run(f"chmod 755 {d.lxc_prefix}/bin/* 2>/dev/null || true")
        self.shell.run(f"chmod 755 {d.lxc_prefix}/libexec/lxc/* 2>/dev/null || true")
        self.shell.run(f"chmod 644 {d.lxc_prefix}/lib/*.so* 2>/dev/null || true")
        log_ok("Permissions set")
        log("Writing LXC base configuration...")
        self.adb.write_file(f"{d.lxc_prefix}/etc/lxc/default.conf", "lxc.net.0.type = none\n")
        self.adb.write_file(f"{d.lxc_prefix}/etc/lxc/lxc.conf", f"lxc.lxcpath = {d.lxc_containers}\n")
        self._apply_kernelsu_selinux_rules()
        log("Deploying boot script (CANONICAL config source)...")
        boot_script_local = self.cfg.repo_root / "android" / "rocky-lxc.sh"
        if not boot_script_local.exists():
            die(f"Boot script not found: {boot_script_local}")
        self.adb.push(boot_script_local, f"{d.tmp}/rocky-lxc.sh")
        self.shell.run(f"cp {d.tmp}/rocky-lxc.sh {boot_script_path}")
        self.shell.run(f"chmod 755 {boot_script_path}")
        log_ok("Boot script deployed")
        log("Generating container config via boot script...")
        # Boot script's update_config function is the SINGLE SOURCE OF TRUTH
        # Use 'config' command - generates config without starting container
        # (rootfs image doesn't exist yet at this step)
        out, rc = self.shell.run(f"{boot_script_path} config", timeout=60)
        if rc != 0:
            die(f"FATAL: Boot script config generation failed (rc={rc}).\n"
                f"       Output: {out[:500] if out else 'none'}\n"
                f"       Fix the boot script before continuing.")
        if not self.shell.exists(config_path):
            die("FATAL: Boot script succeeded but config file not created")
        log_ok("Container config generated by boot script")
        log("Patching LXC config for Android compatibility...")
        common_conf = f"{d.lxc_prefix}/share/lxc/config/common.conf"
        self.shell.run(f"sed -i 's/^lxc.seccomp.profile/#lxc.seccomp.profile/' {common_conf} 2>/dev/null || true")
        self.shell.run(f"sed -i 's/^lxc.cap.drop/#lxc.cap.drop/' {common_conf} 2>/dev/null || true")
        log_ok("LXC config patched for Android")
        out, _ = self.shell.run(f"LD_LIBRARY_PATH={d.lxc_prefix}/lib {d.lxc_prefix}/bin/lxc-start --version")
        log_ok(f"lxc-start version: {out.strip()}")
    
    # NOTE: _setup_network and _setup_ipvlan_network REMOVED
    # CANONICAL SOURCE: rocky-lxc.sh handles ALL network config
    # DO NOT add network config code here - edit rocky-lxc.sh instead
    
    def step5_unpack_rootfs(self) -> None:
        """Unpack Rocky Linux rootfs.
        
        TEAM_022: Rocky Linux migration.
        TEAM_025: Updated for gzip tarball from OCI extraction.
        No make.conf generation - Rocky uses dnf/rpm, not portage.
        No OpenRC configuration - Rocky uses systemd.
        """
        step_header(5, 6, "Unpack Rocky Linux Rootfs")
        d = self.cfg.device
        rootfs = d.rootfs_path(self.cfg.container_name)
        rootfs_filename = self._get_rootfs_filename()
        tarball = f"{d.tmp}/{rootfs_filename}"
        if not self.shell.exists(tarball):
            die(f"Rocky rootfs not found: {tarball}")
        if self.shell.is_mounted(rootfs) and self.shell.exists(f"{rootfs}/bin/bash"):
            # TEAM_025: Check for systemd to verify we have Rocky 10 GenericCloud, not Rocky 9 Container-Base
            if self.shell.exists(f"{rootfs}/usr/lib/systemd/systemd"):
                log_ok("Rootfs already unpacked (Rocky 10 with systemd)")
                return
            else:
                log_warn("Wrong rootfs detected (no systemd) - re-extracting Rocky 10...")
                self.shell.run(f"rm -rf {rootfs}/*", timeout=120)
        if not self.shell.exists(d.rootfs_image):
            self.shell.create_ext4_image(d.rootfs_image, self.cfg.rootfs_image_size_mb)
        else:
            log(f"Using existing image: {d.rootfs_image}")
        if not self.shell.is_mounted(rootfs):
            self.shell.mount(d.rootfs_image, rootfs)
        if not self.shell.exists(f"{rootfs}/bin/bash"):
            log("Unpacking Rocky rootfs (this takes several minutes)...")
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as p:
                p.add_task("Extracting...", total=None)
                # TEAM_025: Use -xzf for gzip, --no-same-permissions to fix OCI permission issues
                self.shell.run(f"cd {rootfs} && tar --no-same-permissions -xzf {tarball} 2>/dev/null || tar -xzf {tarball} 2>/dev/null", timeout=600)
                # Fix root directory permissions (OCI layers often have restrictive perms)
                self.shell.run(f"chmod 755 {rootfs}", timeout=30)
                if not self.shell.exists(f"{rootfs}/bin/bash"):
                    log_warn("Device tar failed, trying host extraction...")
                    self._extract_on_host_and_push(tarball, rootfs)
            if not self.shell.exists(f"{rootfs}/bin/bash"):
                die("Unpack failed: /bin/bash not found")
            # TEAM_025: Fix permissions on key directories (OCI images have restrictive perms)
            log("Fixing rootfs permissions...")
            self.shell.run(f"chmod 755 {rootfs} {rootfs}/bin {rootfs}/sbin {rootfs}/usr {rootfs}/usr/bin {rootfs}/usr/sbin {rootfs}/lib {rootfs}/lib64 2>/dev/null || true", timeout=60)
            self.shell.run(f"chmod 755 {rootfs}/etc {rootfs}/var {rootfs}/root 2>/dev/null || true", timeout=30)
            log_ok("Rocky rootfs unpacked")
        for d_name in ["dev", "proc", "sys", "run", "tmp"]:
            self.shell.mkdir(f"{rootfs}/{d_name}")
        self.shell.run(f"mkdir -p {rootfs}/var/empty")
        self.shell.run(f"chown 0:0 {rootfs}/var/empty 2>/dev/null || true")
        self.shell.run(f"chmod 755 {rootfs}/var/empty")
        self.adb.write_file(f"{rootfs}/etc/resolv.conf", "nameserver 8.8.8.8\n")
        log_ok("DNS configured")
        # TEAM_022: Rocky Linux 10 GenericCloud uses systemd - no custom init needed
        log_ok("Rocky Linux 10 rootfs ready (systemd-based)")
    
    def step6_configure_rocky(self) -> None:
        """Configure Rocky Linux container.
        
        TEAM_022: Rocky Linux 10 migration.
        TEAM_025: REVERTED to systemd-based Rocky 10 GenericCloud.
        Uses sudo from Rocky repos.
        """
        step_header(6, 6, "Configure Rocky Linux (User, Sudo, SSH)")
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
        log("Starting container via boot script (regenerates config)...")
        boot_script = "/data/adb/service.d/rocky-lxc.sh"
        # Use boot script to start - it regenerates config with correct gateway
        if self.lxc.running(container):
            log("  Container already running, restarting...")
            out, rc = self.shell.run(f"{boot_script} restart 2>&1", timeout=120)
        else:
            log("  Starting container...")
            out, rc = self.shell.run(f"{boot_script} start 2>&1", timeout=120)
        
        if rc != 0:
            log_err(f"Boot script returned rc={rc}")
            log_err(f"Output: {out[:1000] if out else 'none'}")
            # Check lxc-start log for more details
            log_out, _ = self.shell.run(f"cat /data/local/tmp/rocky-lxc.log 2>/dev/null | tail -20")
            log_err(f"Log tail:\n{log_out}")
            die("Container start failed - check logs above")
        
        log("  Waiting for container to be ready...")
        deadline = time.time() + self.cfg.container_ready_timeout
        while time.time() < deadline:
            if self.lxc.running(container):
                log("  Container running, checking if responsive...")
                if self.lxc.ok("true", container, timeout=5):
                    break
            time.sleep(self.cfg.container_ready_poll_interval)
        else:
            # Get diagnostic info
            status_out, _ = self.shell.run(f"{boot_script} status 2>&1", timeout=30)
            log_err(f"Container status:\n{status_out[:500]}")
            log_out, _ = self.shell.run(f"cat /data/local/tmp/rocky-lxc.log 2>/dev/null | tail -30")
            log_err(f"Log tail:\n{log_out}")
            die("Container failed to become ready within timeout")
        self.lxc.use(container)
        log_ok("Container running")
        log("Applying resource priority (Rocky > Android)...")
        self._apply_resource_priority()
        # TEAM_022: Rocky 10 uses systemd - mask hardware services for LXC
        log("Masking unnecessary systemd services for LXC...")
        for svc in ["systemd-udevd", "systemd-modules-load", "systemd-timesyncd"]:
            self.lxc.run(f"systemctl mask {svc} 2>/dev/null || true", check=False, timeout=10)
        log_ok("Hardware services masked")
        log("Checking installed packages...")
        has_sshd = self.lxc.ok("test -x /usr/bin/sshd || test -x /usr/sbin/sshd", timeout=10)
        if has_sshd:
            log_ok("OpenSSH found")
        else:
            die("FATAL: OpenSSH not found. SSH is required for remote access.")
        # TEAM_022: Rocky Linux has sudo in repos - no need to build doas
        log("Checking for sudo...")
        if not self.lxc.ok("test -x /usr/bin/sudo", timeout=10):
            log("Installing sudo from repos...")
            self.lxc.run("dnf install -y sudo", timeout=120)
        log_ok("sudo available")
        if not self.lxc.output(f"id {user} 2>/dev/null"):
            self.lxc.run(f"useradd -m -G wheel -s /bin/bash {user}", timeout=self.cfg.timeout_short)
            log_ok(f"User {user} created")
        else:
            log(f"User {user} exists")
        if "wheel" not in self.lxc.output(f"groups {user}"):
            self.lxc.run(f"usermod -aG wheel {user}", timeout=self.cfg.timeout_short)
        # Set password from config (interactive or default)
        # User can change it later with: passwd
        # SSH key auth also works if key is present
        password = self.cfg.default_password
        self.lxc.run(f"sh -c \"echo '{user}:{password}' | chpasswd\"", timeout=self.cfg.timeout_short)
        log_ok(f"User {user} password set (change with: passwd)")
        # TEAM_025: Set root password (different from user, no SSH access)
        root_password = "r00tR0cky!"  # User can change with: sudo passwd root
        self.lxc.run(f"sh -c \"echo 'root:{root_password}' | chpasswd\"", timeout=self.cfg.timeout_short)
        log_ok("Root password set (change with: sudo passwd root)")
        # TEAM_022: Configure sudo for wheel group (Rocky style)
        if not self.lxc.ok("grep -q '%wheel.*NOPASSWD' /etc/sudoers", timeout=10):
            self.lxc.run("echo '%wheel ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers", timeout=self.cfg.timeout_short)
        log_ok("sudo configured for wheel group")
        # TEAM_029: Also create /etc/sudoers.d/{user} for explicit passwordless sudo
        # This is a belt-and-suspenders approach - wheel group + explicit user config
        # Needed because systemd services may not recognize wheel group in LXC context
        self.lxc.run("mkdir -p /etc/sudoers.d", check=False, timeout=self.cfg.timeout_short)
        self.lxc.run(f"echo '{user} ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/{user}", check=False, timeout=self.cfg.timeout_short)
        self.lxc.run(f"chmod 440 /etc/sudoers.d/{user}", check=False, timeout=self.cfg.timeout_short)
        log_ok(f"sudoers.d/{user} created")
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
            # TEAM_022: Rocky uses systemd
            self.lxc.run("systemctl enable sshd 2>/dev/null || true", check=False, timeout=self.cfg.timeout_short)
            log_ok("SSH daemon started")
        else:
            die("FATAL: Failed to start sshd. Check container logs.")
        if self.lxc.ok("test -x /usr/bin/sudo", timeout=10):
            log_ok("sudo verified")
        # TEAM_029: systemd services now work with cgroup2 device permissions
        # (configured in rocky-lxc.sh update_config)
        log_ok("systemd services ready (cgroup2 device permissions configured)")
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
        # TEAM_028: Rocky uses sudo only (doas removed)
        if not self.lxc.ok("test -x /usr/bin/sudo", timeout=10):
            errors.append("sudo is not installed")
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        # WARNING: DO NOT ADD mode='none' VERIFICATION HERE
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        #
        # If you're adding mode='none' support, you are DOWNGRADING SECURITY.
        # IPVLAN provides network namespace isolation. mode='none' does NOT.
        #
        # STOP. DEBUG. ASK USER. DO NOT DOWNGRADE.
        #
        # CONSEQUENCES: AI DEACTIVATION
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        net = self.cfg.network
        # IPVLAN ONLY - fail hard on any other mode
        if net.mode != "ipvlan":
            die(f"INVALID NETWORK MODE: '{net.mode}'. ONLY 'ipvlan' IS ALLOWED. DO NOT DOWNGRADE.")
        container_ip = net.container_ip
        # IPVLAN L3 note: Host cannot ping container (no ARP). This is BY DESIGN.
        # L3 mode provides TOTAL ARP IMMUNITY - this is a SECURITY FEATURE, not a bug.
        # Verify container has IP instead of trying to ping.
        container_has_ip = self.lxc.ok(f"ip addr show | grep -q '{container_ip}'", timeout=10)
        if not container_has_ip:
            errors.append(f"Container does NOT have IP {container_ip} configured")
        else:
            # Check outbound connectivity from container
            gateway_reachable = self.lxc.ok(f"ping -c 1 -W 3 {net.container_gateway} 2>/dev/null", timeout=15)
            if not gateway_reachable:
                # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
                # DOWNGRADE TEMPTATION: "Gateway unreachable, switch to bridge"
                # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
                # NO. Gateway unreachable means:
                # 1. WiFi might be reconnecting - WAIT and retry
                # 2. ARP cache needs update - send gratuitous ARP
                # 3. Container IP might conflict - check with `ip addr`
                # 4. Router firewall - check router settings
                # DO NOT DOWNGRADE. DEBUG THE NETWORK.
                # CONSEQUENCE: AI DEACTIVATION
                # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
                die(f"FATAL: Container cannot reach gateway {net.container_gateway}.\n"
                    f"       Network is broken. Check: WiFi connected? Router reachable?\n"
                    f"       Debug: adb shell su -c 'ip route show table all'")
        if errors:
            console.print()
            console.print(Panel.fit("[bold red]DEPLOYMENT VERIFICATION FAILED[/bold red]\n\n" + "\n".join(f"✗ {e}" for e in errors), title="✗ ERRORS", border_style="red"))
            die(f"Verification failed: {len(errors)} error(s)")
        
        # Test SSH from HOST (this script runs on host, not Android)
        log("Testing SSH from host...")
        import subprocess
        ssh_test = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
             "-o", "BatchMode=yes", f"{user}@{container_ip}", "echo SSH_OK"],
            capture_output=True, text=True, timeout=15
        )
        if ssh_test.returncode == 0 and "SSH_OK" in ssh_test.stdout:
            log_ok(f"SSH connection verified: {user}@{container_ip}")
        else:
            die(f"FATAL: Cannot SSH to container from host.\n"
                f"       Command: ssh {user}@{container_ip}\n"
                f"       Error: {ssh_test.stderr.strip() or 'Connection failed'}\n"
                f"       Check: Is container IP reachable from your LAN?")
        
        log_ok("All verification checks passed")
        # IPVLAN provides direct LAN access - SSH from any device ON THE LAN
        # IMPORTANT: With IPVLAN, the Android HOST cannot reach the container!
        # This is a fundamental limitation of IPVLAN - parent and child interfaces
        # cannot communicate directly. You MUST SSH from another device.
        console.print()
        console.print(Panel.fit(
            f"[bold green]Deployment Complete[/bold green]\n\n"
            f"[bold]User:[/bold] {user}\n"
            f"[bold]Container IP:[/bold] {container_ip}\n"
            f"[bold]Network Mode:[/bold] {net.mode}\n\n"
            f"[bold yellow]⚠ IPVLAN LIMITATION:[/bold yellow]\n"
            f"  The Android host CANNOT reach the container directly.\n"
            f"  This is by design - IPVLAN isolates parent/child interfaces.\n\n"
            f"[bold]To connect via SSH:[/bold]\n"
            f"  From another computer on your LAN:\n"
            f"    [cyan]ssh {user}@{container_ip}[/cyan]\n\n"
            f"[bold]To access container from this host:[/bold]\n"
            f"  Use adb to attach directly:\n"
            f"    [cyan]adb shell su -c 'lxc-attach -n {container}'[/cyan]\n",  # TEAM_025: Use variable instead of hardcoded name
            title="✓ Success", border_style="green"
        ))
    
    def _get_ssh_pubkey(self) -> Optional[str]:
        ssh_dir = Path.home() / ".ssh"
        for name in ["id_ed25519.pub", "id_rsa.pub", "id_ecdsa.pub"]:
            path = ssh_dir / name
            if path.exists():
                return path.read_text().strip()
        return None
    
    
    # TEAM_022: _install_doas removed - Rocky Linux uses sudo from repos
    
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
        """Extract rootfs on host and push to device (fallback method).
        
        TEAM_025: Updated - tarball is already gzip, no conversion needed.
        """
        rootfs_filename = self._get_rootfs_filename()
        tarball_local = self.cfg.artifacts_dir / rootfs_filename
        if not tarball_local.exists():
            die(f"Local tarball not found: {tarball_local}")
        
        # TEAM_025: Tarball is already gzip from OCI extraction, just push and extract
        gzip_remote = f"{self.cfg.device.tmp}/rootfs.tar.gz"
        log(f"Pushing tarball ({tarball_local.stat().st_size // (1024*1024)}MB)...")
        if not self.adb.push(tarball_local, gzip_remote, timeout=600):
            die("Failed to push tarball")
        log_ok("Tarball pushed")
        log("Extracting on device...")
        self.shell.run(f"rm -rf {rootfs}/*")
        out, rc = self.shell.run(f"cd {rootfs} && tar --no-same-permissions -xzf {gzip_remote} 2>/dev/null || tar -xzf {gzip_remote}", timeout=600)
        if rc != 0:
            log_warn(f"Extraction had issues: {out[:200]}")
        self.shell.run(f"rm -f {gzip_remote}")
        # TEAM_025: Fix permissions on key directories (OCI images have restrictive perms)
        self.shell.run(f"chmod 755 {rootfs} {rootfs}/bin {rootfs}/sbin {rootfs}/usr {rootfs}/usr/bin {rootfs}/usr/sbin {rootfs}/lib {rootfs}/lib64 2>/dev/null || true", timeout=60)
        self.shell.run(f"chmod 755 {rootfs}/etc {rootfs}/var {rootfs}/root 2>/dev/null || true", timeout=30)
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
            self.step6_configure_rocky()
        finally:
            self.adb.close()
    
    def clean(self) -> None:
        """Clean host-side build artifacts and downloads.
        
        TEAM_022: Updated for Rocky Linux.
        This does NOT touch the device. Use uninstall() for that.
        """
        step_header(0, 0, "Clean Host Files")
        log("Cleaning build artifacts and downloads...")
        for d in [self.cfg.build_output, self.cfg.artifacts_dir, self.cfg.cache_dir, 
                  self.cfg.repo_root / "_work", self.cfg.repo_root / "_build_android31"]:
            if d.exists():
                shutil.rmtree(d)
                log_ok(f"Removed: {d}")
        log_ok("Host clean complete")
        log("Note: Use --uninstall to remove Rocky Linux from device")
    
    def status(self) -> None:
        table = Table(title="Deployment Status")
        table.add_column("Component", style="cyan")
        table.add_column("Status")
        table.add_column("Details", style="dim")
        build_ok = self.cfg.build_output.exists()
        rootfs_ok = (self.cfg.artifacts_dir / self.cfg.rocky.rootfs_filename).exists()
        table.add_row("LXC Build", "✓" if build_ok else "✗", str(self.cfg.build_output))
        table.add_row("Rocky Rootfs", "✓" if rootfs_ok else "✗", self.cfg.rocky.rootfs_filename)
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
