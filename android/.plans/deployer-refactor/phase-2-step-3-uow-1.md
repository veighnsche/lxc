# Phase 2 - Step 3 - UoW 1: Extract lxc.py

**Parent:** phase-2.md → Step 3  
**Goal:** Extract LXC class from deploy.py into deployer/lxc.py

## Input Context
- Read `deploy.py` lines 496-599
- Target file: `deployer/lxc.py`
- Depends on: `deployer/adb.py`, `deployer/config.py`

## Tasks

### 1. Create deployer/lxc.py

Extract:
- `LXC` class (lines 500-599)

**Required imports:**
```python
"""LXC container management."""

from __future__ import annotations

import re
from typing import Optional

from .adb import ADB
from .config import Config
```

### 2. Key preservation notes:
- Keep `_NAME_RE` class variable
- Keep all method signatures unchanged
- Preserve docstrings

### 3. Verify import works:
```bash
cd /home/vince/Projects/android/lxc/android
python3 -c "from deployer.lxc import LXC; print('OK')"
```

## Expected Output
- File `deployer/lxc.py` created (~110 lines)
- Import test passes

## Exit Criteria
- [ ] File created with LXC class
- [ ] No syntax errors
- [ ] Import succeeds
