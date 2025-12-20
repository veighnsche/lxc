# Phase 2 - Step 5 - UoW 1: Extract deployer.py

**Parent:** phase-2.md → Step 5  
**Goal:** Extract Deployer class from deploy.py into deployer/deployer.py

## Input Context
- Read `deploy.py` lines 680-1813
- Target file: `deployer/deployer.py`
- Depends on: ALL other deployer modules

## Tasks

### 1. Create deployer/deployer.py

Extract:
- `Deployer` class (lines 684-1813)

**Required imports:**
```python
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
```

### 2. Key preservation notes:

**CRITICAL - Preserve all TEAM_XXX comments:**
- TEAM_004 comments in `_setup_port_forward`
- TEAM_008 comments in `_apply_kernelsu_selinux_rules`, `step6_configure_gentoo`
- TEAM_009 comments in network setup methods

**Methods to extract (in order as they appear):**
- `__init__`
- `shell` property
- `_detect_host_interface`
- `_apply_kernelsu_selinux_rules`
- `step1_build_lxc`
- `step2_prepare_rootfs`
- `step3_push_to_device`
- `step4_install_lxc`
- `_setup_network`
- `_setup_ipvlan_network`
- `_setup_macvlan_network`
- `_setup_bridge_network`
- `step5_unpack_rootfs`
- `step6_configure_gentoo`
- `_get_ssh_pubkey`
- `_setup_port_forward`
- `_install_doas`
- `_apply_resource_priority`
- `_extract_on_host_and_push`
- `run_all`
- `clean`
- `status`

### 3. Verify import works:
```bash
cd /home/vince/Projects/android/lxc/android
python3 -c "from deployer.deployer import Deployer; print('OK')"
```

### 4. Verify full module import:
```bash
cd /home/vince/Projects/android/lxc/android
python3 -c "from deployer import Config, ADB, LXC, Deployer; print('OK')"
```

## Expected Output
- File `deployer/deployer.py` created (~1150 lines)
- All import tests pass

## Exit Criteria
- [ ] File created with complete Deployer class
- [ ] All TEAM_XXX comments preserved
- [ ] All methods present
- [ ] No syntax errors
- [ ] Full module import succeeds
