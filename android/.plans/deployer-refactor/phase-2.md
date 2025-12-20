# Phase 2: Structural Extraction

## Target Design

```
deployer/
├── __init__.py      # Re-exports (EXISTS)
├── console.py       # Logging (EXISTS)
├── config.py        # Configuration dataclasses
├── adb.py           # DeviceShell + ADB classes
├── lxc.py           # LXC container management
├── download.py      # Downloader + Crypto
└── deployer.py      # Main Deployer orchestration
```

## Extraction Order (based on dependencies)

1. **config.py** - no dependencies (extract first)
2. **adb.py** - depends only on config (DeviceShell is standalone, ADB uses DeviceShell)
3. **lxc.py** - depends on adb, config
4. **download.py** - depends on console (Downloader uses log functions)
5. **deployer.py** - depends on all above

## Modular Refactoring Rules

- Each module owns its own state
- Keep fields private, expose intentional APIs
- No deep relative imports (use `from .module import Class`)
- File sizes < 500 lines ideal

---

## Step 1: Extract config.py

**Source lines:** 86-226 (140 lines)

**Extract:**
- `GentooConfig` dataclass
- `DevicePaths` dataclass  
- `NetworkConfig` dataclass
- `ResourceConfig` dataclass
- `Config` dataclass

**Imports needed:**
```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
```

**UoW:** `phase-2-step-1-uow-1.md`

---

## Step 2: Extract adb.py

**Source lines:** 228-494 (266 lines)

**Extract:**
- `DeviceShell` class (228-388)
- `ADB` class (390-494)

**Imports needed:**
```python
from __future__ import annotations
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from .console import log, log_ok, log_warn
```

**UoW:** `phase-2-step-2-uow-1.md`

---

## Step 3: Extract lxc.py

**Source lines:** 496-599 (103 lines)

**Extract:**
- `LXC` class

**Imports needed:**
```python
from __future__ import annotations
import re
from typing import Optional

from .adb import ADB
from .config import Config
```

**UoW:** `phase-2-step-3-uow-1.md`

---

## Step 4: Extract download.py

**Source lines:** 601-678 (77 lines)

**Extract:**
- `Downloader` class
- `Crypto` class

**Imports needed:**
```python
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Optional

import httpx
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .console import console
```

**UoW:** `phase-2-step-4-uow-1.md`

---

## Step 5: Extract deployer.py

**Source lines:** 680-1813 (1133 lines - LARGE, may need internal split)

**Extract:**
- `Deployer` class with all step methods

**Imports needed:**
```python
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

**Note:** At 1133 lines, `deployer.py` exceeds ideal size but contains tightly coupled step logic. Consider future split into `deployer/steps/` if needed, but not in this refactor.

**UoW:** `phase-2-step-5-uow-1.md`

---

## Exit Criteria for Phase 2

- [ ] All 5 modules created
- [ ] `from deployer import Config, ADB, LXC, Deployer` succeeds
- [ ] No circular imports
- [ ] Each module has correct imports at top
