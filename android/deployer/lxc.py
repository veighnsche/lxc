"""LXC container management."""

from __future__ import annotations

import re
from typing import Optional

from .adb import ADB
from .config import Config


class LXC:
    """LXC container operations - all commands via persistent shell."""
    
    _NAME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]*$')
    
    def __init__(self, adb: ADB, cfg: Config):
        self.adb = adb
        self.shell = adb.shell  # Direct shell access
        self.cfg = cfg
        self._container: Optional[str] = None
    
    @classmethod
    def validate_name(cls, name: str) -> None:
        if not name or len(name) > 64 or not cls._NAME_RE.match(name):
            raise ValueError(f"Invalid name: {name}")
    
    def use(self, name: str) -> None:
        """Set default container for subsequent operations."""
        if name is None:
            raise ValueError("Container name cannot be None")
        self.validate_name(name)
        self._container = name
    
    def _env(self) -> str:
        """LXC environment variables."""
        d = self.cfg.device
        return (f"HOME={d.tmp} "
                f"PATH={d.lxc_prefix}/bin:$PATH "
                f"LD_LIBRARY_PATH={d.lxc_prefix}/lib "
                f"LXC_PATH={d.lxc_containers} "
                f"XDG_RUNTIME_DIR={d.lxc_runtime}")
    
    def _lxc_cmd(self, cmd: str) -> str:
        """Build full LXC command with env and path."""
        if cmd.startswith("lxc-"):
            cmd = f"{self.cfg.device.lxc_prefix}/bin/{cmd}"
        return f"{self._env()} {cmd}"
    
    def _run(self, cmd: str, timeout: int = 60) -> tuple[str, int]:
        """Run LXC command via shell."""
        return self.shell.run(self._lxc_cmd(cmd), timeout=timeout, check=False)
    
    def _resolve_name(self, name: Optional[str]) -> str:
        """Resolve container name."""
        resolved = name or self._container
        if resolved is None:
            raise ValueError("No container name provided and no default set")
        return resolved
    
    # Container lifecycle
    def start(self, name: Optional[str] = None) -> None:
        name = self._resolve_name(name)
        out, rc = self._run(f"lxc-start -n {name} -P {self.cfg.device.lxc_containers}", timeout=30)
        if rc != 0:
            raise RuntimeError(f"lxc-start failed: {out}")
    
    def stop(self, name: Optional[str] = None, kill: bool = False) -> None:
        name = self._resolve_name(name)
        flag = "-k" if kill else ""
        self._run(f"lxc-stop -n {name} -P {self.cfg.device.lxc_containers} {flag}", timeout=30)
    
    def running(self, name: Optional[str] = None) -> bool:
        name = self._resolve_name(name)
        out, _ = self._run(f"lxc-info -n {name} -s", timeout=10)
        return "RUNNING" in out
    
    def exists(self, name: Optional[str] = None) -> bool:
        name = self._resolve_name(name)
        return self.shell.exists(self.cfg.device.container_path(name), is_dir=True)
    
    # Execute inside container
    def run(self, cmd: str, name: Optional[str] = None, 
            timeout: int = 60, check: bool = True) -> tuple[str, int]:
        """Run command inside container. Returns (output, returncode)."""
        name = self._resolve_name(name)
        full_cmd = f"lxc-attach -n {name} -P {self.cfg.device.lxc_containers} -e -- {cmd}"
        out, rc = self._run(full_cmd, timeout=timeout)
        if check and rc != 0:
            raise RuntimeError(f"Container command failed (rc={rc}): {out[:200]}")
        return out, rc
    
    def output(self, cmd: str, name: Optional[str] = None, timeout: int = 60) -> str:
        """Run command, return stdout."""
        out, _ = self.run(cmd, name, timeout, check=False)
        return out.strip()
    
    def ok(self, cmd: str, name: Optional[str] = None, timeout: int = 60) -> bool:
        """Run command, return True if success."""
        _, rc = self.run(cmd, name, timeout, check=False)
        return rc == 0
    
    # File operations inside container
    def write(self, path: str, content: str, name: Optional[str] = None) -> None:
        """Write file inside container via rootfs."""
        name = self._resolve_name(name)
        rootfs = self.cfg.device.rootfs_path(name)
        self.adb.write_file(f"{rootfs}{path}", content)
    
    def file_exists(self, path: str, name: Optional[str] = None) -> bool:
        """Check if file exists inside container."""
        return self.ok(f"test -f {path}", name, timeout=10)
