"""ADB and DeviceShell - device communication layer."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from .console import log, log_ok, log_warn


class DeviceShell:
    """Persistent root shell - THE way to interact with the device.
    
    TEAM_002: Complete rewrite around interactive shell paradigm.
    
    Instead of the old nightmare:
        adb shell su -c "echo 'hello'"     # Quoting hell
        adb shell su -c "cat '/path'"      # More quoting
        adb shell su -c "cmd with $vars"   # Escaping madness
    
    We now have ONE persistent shell:
        shell.run("echo 'hello'")          # Just works
        shell.run("cat /path")             # No escaping needed
        shell.run(f"cmd with {vars}")      # Python f-strings work
    
    The shell stays open for the entire session. Commands are sent
    via stdin, output read via stdout. A unique marker detects
    when each command completes.
    """
    
    _MARKER = "__END_CMD_a9f8e7d6__"
    
    def __init__(self, serial: Optional[str] = None):
        self.serial = serial
        self._proc: Optional[subprocess.Popen] = None
        self._adb_base = ["adb"] + (["-s", serial] if serial else [])
    
    def connect(self) -> bool:
        """Establish persistent root shell connection."""
        if self._proc and self._proc.poll() is None:
            return True
        
        try:
            # TEAM_004: Use 'su 0 sh' instead of 'su' to get full capabilities
            # Android's 'su' drops capabilities, but 'su 0 sh' preserves them
            # This is required for bridge/veth creation
            self._proc = subprocess.Popen(
                self._adb_base + ["shell", "su", "0", "sh"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            # Verify root
            out, rc = self._exec("id -u", timeout=5)
            return out.strip() == "0"
        except Exception as e:
            log_warn(f"Shell connect failed: {e}")
            self.disconnect()
            return False
    
    def disconnect(self) -> None:
        """Close the shell session."""
        if self._proc:
            try:
                self._proc.stdin.write("exit\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
    
    def _exec(self, cmd: str, timeout: Optional[int] = None) -> tuple[str, int]:
        """Execute command and return (stdout, returncode)."""
        if not self._proc or self._proc.poll() is not None:
            raise RuntimeError("Shell not connected")
        
        # Send command + marker with exit code
        self._proc.stdin.write(f"{cmd}; echo {self._MARKER}$?\n")
        self._proc.stdin.flush()
        
        # Read until marker
        lines = []
        start = time.time()
        while True:
            if timeout and (time.time() - start) > timeout:
                raise TimeoutError(f"Command timed out: {cmd[:60]}")
            
            line = self._proc.stdout.readline()
            if not line:
                raise RuntimeError("Shell died unexpectedly")
            
            if self._MARKER in line:
                try:
                    rc = int(line.split(self._MARKER)[1].strip())
                except (IndexError, ValueError):
                    rc = 0
                return "".join(lines), rc
            lines.append(line)
    
    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None
    
    # -------------------------------------------------------------------------
    # Shell Operations - All go through the persistent session
    # -------------------------------------------------------------------------
    
    def run(self, cmd: str, timeout: Optional[int] = None, check: bool = True) -> tuple[str, int]:
        """Run command as root. Returns (output, returncode)."""
        if not self.alive:
            if not self.connect():
                raise RuntimeError("Cannot establish root shell")
        return self._exec(cmd, timeout)
    
    def run_ok(self, cmd: str, timeout: Optional[int] = None) -> bool:
        """Run command, return True if exit code is 0."""
        _, rc = self.run(cmd, timeout, check=False)
        return rc == 0
    
    def run_output(self, cmd: str, timeout: Optional[int] = None) -> str:
        """Run command, return stdout (ignore exit code)."""
        out, _ = self.run(cmd, timeout, check=False)
        return out.strip()
    
    def exists(self, path: str, is_dir: bool = False) -> bool:
        """Check if path exists on device."""
        flag = "-d" if is_dir else "-e"
        return self.run_ok(f"[ {flag} {path} ]")
    
    def mkdir(self, path: str) -> None:
        """Create directory (and parents)."""
        self.run(f"mkdir -p {path}")
    
    def rm(self, path: str) -> None:
        """Remove file or directory."""
        self.run(f"rm -rf {path}", check=False)
    
    def cat(self, path: str) -> str:
        """Read file contents."""
        return self.run_output(f"cat {path}")
    
    def is_mounted(self, path: str) -> bool:
        """Check if path is a mountpoint."""
        return self.run_ok(f"mountpoint -q {path}")
    
    def mount(self, image: str, mountpoint: str) -> None:
        """Mount image at mountpoint."""
        self.mkdir(mountpoint)
        self.run(f"mount -o loop,rw,suid,dev,exec {image} {mountpoint}")
        log_ok(f"Mounted at {mountpoint}")
    
    def umount(self, path: str) -> bool:
        """Unmount path."""
        return self.run_ok(f"umount {path}")
    
    def create_ext4_image(self, path: str, size_mb: int) -> None:
        """Create sparse ext4 image."""
        log(f"Creating {size_mb}MB ext4 image...")
        self.run(f"dd if=/dev/zero of={path} bs=1M count=0 seek={size_mb}", timeout=60)
        self.run(f"mkfs.ext4 -F {path}", timeout=120)
        log_ok(f"Image created: {path}")


class ADB:
    """ADB wrapper - handles file transfers, delegates shell to DeviceShell."""
    
    def __init__(self, serial: Optional[str] = None):
        self.serial = serial
        self._base = ["adb"] + (["-s", serial] if serial else [])
        self.shell = DeviceShell(serial)  # THE shell interface
    
    def _adb(self, args: list[str], timeout: Optional[int] = None) -> subprocess.CompletedProcess:
        """Run raw adb command."""
        return subprocess.run(
            self._base + args,
            capture_output=True, text=True, timeout=timeout
        )
    
    def connected(self) -> bool:
        """Check if device is connected."""
        try:
            r = self._adb(["get-state"], timeout=5)
            return r.returncode == 0 and "device" in r.stdout
        except Exception:
            return False
    
    def serial_number(self) -> str:
        """Get device serial number."""
        return self._adb(["get-serialno"], timeout=5).stdout.strip()
    
    def has_root(self) -> bool:
        """Check if we can get root via su."""
        if self.shell.alive:
            return True
        return self.shell.connect()
    
    def ensure_shell(self) -> None:
        """Ensure shell is connected, raise if not."""
        if not self.shell.alive:
            if not self.shell.connect():
                raise RuntimeError("Cannot establish root shell")
    
    def close(self) -> None:
        """Close shell session."""
        self.shell.disconnect()
    
    # -------------------------------------------------------------------------
    # File Operations (these use adb push/pull, not shell)
    # -------------------------------------------------------------------------
    
    def push(self, local: Path, remote: str, timeout: int = 300) -> bool:
        """Push file to device."""
        try:
            r = self._adb(["push", str(local), remote], timeout=timeout)
            return r.returncode == 0
        except Exception:
            return False
    
    def pull(self, remote: str, local: Path, timeout: int = 300) -> bool:
        """Pull file from device."""
        try:
            r = self._adb(["pull", remote, str(local)], timeout=timeout)
            return r.returncode == 0
        except Exception:
            return False
    
    def write_file(self, path: str, content: str) -> None:
        """Write content to device file (push temp file, then mv)."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.tmp') as f:
            f.write(content)
            tmp_local = f.name
        try:
            tmp_remote = f"/data/local/tmp/.deploy_{os.getpid()}.tmp"
            if not self.push(Path(tmp_local), tmp_remote):
                raise RuntimeError("Failed to push temp file")
            self.shell.run(f"mv {tmp_remote} {path}")
        finally:
            os.unlink(tmp_local)
    
    # -------------------------------------------------------------------------
    # Convenience methods that delegate to shell
    # -------------------------------------------------------------------------
    
    def exists(self, path: str, is_dir: bool = False) -> bool:
        return self.shell.exists(path, is_dir)
    
    def mkdir(self, path: str) -> None:
        self.shell.mkdir(path)
    
    def rm(self, path: str) -> None:
        self.shell.rm(path)
    
    def is_mounted(self, path: str) -> bool:
        return self.shell.is_mounted(path)
    
    def mount(self, image: str, mountpoint: str) -> None:
        self.shell.mount(image, mountpoint)
    
    def umount(self, path: str) -> bool:
        return self.shell.umount(path)
    
    def create_image(self, path: str, size_mb: int) -> None:
        self.shell.create_ext4_image(path, size_mb)
