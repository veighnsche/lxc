"""Download utilities and cryptographic operations.

TEAM_022: Updated for Rocky Linux 10 migration.
Removed Gentoo-specific SHA512 DIGESTS parsing.
Added SHA256 CHECKSUM parsing for Rocky Linux.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import httpx
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .console import console


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


class Crypto:
    """Cryptographic operations."""
    
    @staticmethod
    def sha256_file(path: Path) -> str:
        """Calculate SHA256 hash of a file."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest().lower()
    
    @staticmethod
    def parse_rocky_checksum(content: str, filename: str) -> Optional[str]:
        """Extract SHA256 hash from Rocky Linux CHECKSUM file.
        
        TEAM_022: Rocky Linux CHECKSUM format:
        SHA256 (filename) = <hash>
        
        Example:
        SHA256 (Rocky-10.0-GenericCloud-Base-10.0-aarch64.raw.xz) = abc123...
        """
        for line in content.split('\n'):
            line = line.strip()
            # Match: SHA256 (filename) = hash
            if line.startswith('SHA256') and filename in line:
                parts = line.split('=')
                if len(parts) == 2:
                    return parts[1].strip().lower()
        return None
