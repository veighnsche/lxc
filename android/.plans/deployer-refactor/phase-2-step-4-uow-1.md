# Phase 2 - Step 4 - UoW 1: Extract download.py

**Parent:** phase-2.md → Step 4  
**Goal:** Extract Downloader and Crypto classes from deploy.py into deployer/download.py

## Input Context
- Read `deploy.py` lines 601-678
- Target file: `deployer/download.py`
- Depends on: `deployer/console.py` (for console object)

## Tasks

### 1. Create deployer/download.py

Extract:
- `Downloader` class (lines 605-635)
- `Crypto` class (lines 641-678)

**Required imports:**
```python
"""Download utilities and cryptographic operations."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import httpx
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .console import console
```

### 2. Key preservation notes:
- `Downloader.download()` uses `console` for progress display
- `Crypto.parse_gentoo_digests()` has detailed docstring - preserve it

### 3. Verify import works:
```bash
cd /home/vince/Projects/android/lxc/android
python3 -c "from deployer.download import Downloader, Crypto; print('OK')"
```

## Expected Output
- File `deployer/download.py` created (~80 lines)
- Import test passes

## Exit Criteria
- [ ] File created with Downloader and Crypto classes
- [ ] No syntax errors
- [ ] Import succeeds
