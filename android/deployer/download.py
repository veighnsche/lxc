"""Download utilities and cryptographic operations."""

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
    def sha512_file(path: Path) -> str:
        h = hashlib.sha512()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest().lower()
    
    @staticmethod
    def parse_gentoo_digests(content: str, filename: str) -> Optional[str]:
        """Extract SHA512 hash from Gentoo DIGESTS file.
        
        The DIGESTS file format has sections like:
        # SHA512 HASH
        <hash> <filename>
        
        We need to find the hash for our specific filename in the SHA512 section.
        """
        in_sha512 = False
        for line in content.split('\n'):
            line = line.strip()
            if 'SHA512' in line and 'HASH' in line:
                in_sha512 = True
                continue
            if in_sha512:
                if line.startswith('#') or not line:
                    # End of SHA512 section or comment - keep looking
                    if line.startswith('#') and 'HASH' in line:
                        in_sha512 = False  # New hash section started
                    continue
                parts = line.split()
                if len(parts) >= 2 and filename in parts[-1]:
                    return parts[0].lower()
        return None
