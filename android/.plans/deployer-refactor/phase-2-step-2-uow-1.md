# Phase 2 - Step 2 - UoW 1: Extract adb.py

**Parent:** phase-2.md → Step 2  
**Goal:** Extract DeviceShell and ADB classes from deploy.py into deployer/adb.py

## Input Context
- Read `deploy.py` lines 228-494
- Target file: `deployer/adb.py`
- Depends on: `deployer/console.py` (for log functions)

## Tasks

### 1. Create deployer/adb.py

Extract these classes preserving all comments (especially TEAM_XXX annotations):
- `DeviceShell` (lines 232-388)
- `ADB` (lines 394-494)

**Required imports:**
```python
"""ADB and DeviceShell - device communication layer."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from .console import log, log_ok, log_warn
```

### 2. Key preservation notes:
- Keep `_MARKER` class variable in DeviceShell
- Keep all TEAM_002, TEAM_004 comments
- Keep docstrings intact

### 3. Verify import works:
```bash
cd /home/vince/Projects/android/lxc/android
python3 -c "from deployer.adb import ADB, DeviceShell; print('OK')"
```

## Expected Output
- File `deployer/adb.py` created (~270 lines)
- Import test passes

## Exit Criteria
- [ ] File created with DeviceShell and ADB classes
- [ ] All TEAM_XXX comments preserved
- [ ] No syntax errors
- [ ] Import succeeds
