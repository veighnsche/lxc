#!/bin/bash
# lxc-doctor.sh
# Host-side diagnostic script - checks device connectivity and LXC readiness
#
# Usage:
#   ./android/lxc-doctor.sh
#
# This script:
#   - Checks adb connectivity
#   - Checks root access (su)
#   - Runs phone-side preflight checks
#   - Reports LXC readiness
#
# DOES NOT modify any state. Safe to run anytime.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors (if terminal supports it)
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    NC='\033[0m' # No Color
else
    RED=''
    GREEN=''
    YELLOW=''
    NC=''
fi

pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
}

fail() {
    echo -e "${RED}[FAIL]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

info() {
    echo -e "      $1"
}

FAILURES=0
WARNINGS=0

# === Host checks ===
echo ""
echo "=== Host Environment ==="
echo ""

# Check adb
if command -v adb &>/dev/null; then
    pass "adb found: $(which adb)"
else
    fail "adb not found in PATH"
    FAILURES=$((FAILURES+1))
    echo ""
    echo "Cannot continue without adb."
    exit 1
fi

# === Device connectivity ===
echo ""
echo "=== Device Connectivity ==="
echo ""

# Check device connection
if adb get-state &>/dev/null; then
    DEVICE=$(adb get-serialno 2>/dev/null || echo "unknown")
    pass "Device connected: $DEVICE"
else
    fail "No device connected"
    info "Run 'adb devices' to check connection"
    FAILURES=$((FAILURES+1))
    echo ""
    echo "Cannot continue without device."
    exit 1
fi

# Check device state
STATE=$(adb get-state 2>/dev/null)
if [ "$STATE" = "device" ]; then
    pass "Device state: $STATE"
else
    fail "Device state: $STATE (expected 'device')"
    FAILURES=$((FAILURES+1))
fi

# === Root access ===
echo ""
echo "=== Root Access ==="
echo ""

# Check su availability
SU_OUTPUT=$(adb shell su -c 'id' 2>&1) || true
if echo "$SU_OUTPUT" | grep -q 'uid=0'; then
    pass "Root access: working"
    info "$(echo "$SU_OUTPUT" | head -1)"
else
    fail "Root access: not available"
    info "Output: $SU_OUTPUT"
    info "Ensure device is rooted and su is granted to shell"
    FAILURES=$((FAILURES+1))
    echo ""
    echo "Cannot continue without root."
    exit 1
fi

# === Kernel info ===
echo ""
echo "=== Kernel Info ==="
echo ""

KERNEL=$(adb shell su -c 'uname -r' 2>/dev/null | tr -d '\r')
pass "Kernel: $KERNEL"

ARCH=$(adb shell su -c 'uname -m' 2>/dev/null | tr -d '\r')
if [ "$ARCH" = "aarch64" ]; then
    pass "Architecture: $ARCH"
else
    warn "Architecture: $ARCH (expected aarch64)"
    WARNINGS=$((WARNINGS+1))
fi

# === Required mounts ===
echo ""
echo "=== Required Mounts ==="
echo ""

check_mount() {
    local path="$1"
    local desc="$2"
    
    if adb shell su -c "mountpoint -q '$path'" 2>/dev/null; then
        pass "$desc: $path"
        return 0
    else
        fail "$desc: $path not mounted"
        FAILURES=$((FAILURES+1))
        return 1
    fi
}

check_mount /proc "procfs"
check_mount /sys "sysfs"

# Check cgroup mount
CGROUP_MOUNT=$(adb shell su -c 'mount | grep cgroup' 2>/dev/null | head -1 | tr -d '\r')
if [ -n "$CGROUP_MOUNT" ]; then
    if echo "$CGROUP_MOUNT" | grep -q 'cgroup2'; then
        pass "cgroup v2 mounted"
    else
        pass "cgroup v1 mounted"
    fi
    info "$CGROUP_MOUNT"
else
    fail "No cgroup mount found"
    FAILURES=$((FAILURES+1))
fi

# === SELinux ===
echo ""
echo "=== SELinux ==="
echo ""

SELINUX=$(adb shell su -c 'getenforce' 2>/dev/null | tr -d '\r')
case "$SELINUX" in
    Permissive)
        pass "SELinux: Permissive"
        ;;
    Enforcing)
        warn "SELinux: Enforcing (may cause issues)"
        info "Consider: adb shell su -c 'setenforce 0'"
        WARNINGS=$((WARNINGS+1))
        ;;
    Disabled)
        pass "SELinux: Disabled"
        ;;
    *)
        warn "SELinux: unknown state '$SELINUX'"
        WARNINGS=$((WARNINGS+1))
        ;;
esac

# === LXC Installation ===
echo ""
echo "=== LXC Installation ==="
echo ""

LXC_PREFIX="/data/local/tmp/lxc"
LXC_ENV="/data/local/tmp/lxc-env.sh"

# Check LXC prefix
if adb shell su -c "[ -d '$LXC_PREFIX' ]" 2>/dev/null; then
    pass "LXC prefix exists: $LXC_PREFIX"
else
    warn "LXC prefix not found: $LXC_PREFIX"
    info "Run: ./android/push-to-phone.sh"
    WARNINGS=$((WARNINGS+1))
fi

# Check liblxc.so
if adb shell su -c "[ -f '$LXC_PREFIX/lib/liblxc.so' ]" 2>/dev/null; then
    pass "liblxc.so exists"
else
    warn "liblxc.so not found"
    WARNINGS=$((WARNINGS+1))
fi

# Check lxc-start binary
if adb shell su -c "[ -x '$LXC_PREFIX/bin/lxc-start' ]" 2>/dev/null; then
    pass "lxc-start binary exists"
else
    warn "lxc-start binary not found"
    WARNINGS=$((WARNINGS+1))
fi

# Check environment file
if adb shell su -c "[ -f '$LXC_ENV' ]" 2>/dev/null; then
    pass "Environment file exists: $LXC_ENV"
else
    warn "Environment file not found"
    info "Run: adb shell su -c 'sh /data/local/tmp/install-lxc-on-phone.sh'"
    WARNINGS=$((WARNINGS+1))
fi

# === LXC Runtime Test ===
echo ""
echo "=== LXC Runtime Test ==="
echo ""

# Try to run lxc-start --version
LXC_VERSION=$(adb shell su -c ". $LXC_ENV 2>/dev/null; lxc-start --version" 2>&1 | tr -d '\r')
if echo "$LXC_VERSION" | grep -qE '^[0-9]+\.[0-9]+'; then
    pass "lxc-start --version: $LXC_VERSION"
else
    if adb shell su -c "[ -f '$LXC_PREFIX/bin/lxc-start' ]" 2>/dev/null; then
        fail "lxc-start failed to run"
        info "Output: $LXC_VERSION"
        info "Check LD_LIBRARY_PATH and binary compatibility"
        FAILURES=$((FAILURES+1))
    else
        warn "lxc-start not installed yet"
        WARNINGS=$((WARNINGS+1))
    fi
fi

# === Container Storage ===
echo ""
echo "=== Container Storage ==="
echo ""

CONTAINERS_PATH="/data/lxc/containers"

if adb shell su -c "[ -d '$CONTAINERS_PATH' ]" 2>/dev/null; then
    pass "Container storage exists: $CONTAINERS_PATH"
    
    # List containers
    CONTAINERS=$(adb shell su -c "ls '$CONTAINERS_PATH' 2>/dev/null" | tr -d '\r' | tr '\n' ' ')
    if [ -n "$CONTAINERS" ]; then
        info "Containers: $CONTAINERS"
    else
        info "No containers found"
    fi
else
    warn "Container storage not found: $CONTAINERS_PATH"
    info "Will be created by installer"
    WARNINGS=$((WARNINGS+1))
fi

# Check alpine container specifically
if adb shell su -c "[ -d '$CONTAINERS_PATH/alpine/rootfs' ]" 2>/dev/null; then
    ROOTFS_FILES=$(adb shell su -c "ls '$CONTAINERS_PATH/alpine/rootfs' 2>/dev/null | wc -l" | tr -d '\r')
    if [ "$ROOTFS_FILES" -gt 5 ]; then
        pass "Alpine rootfs populated ($ROOTFS_FILES entries)"
    else
        warn "Alpine rootfs appears empty"
        WARNINGS=$((WARNINGS+1))
    fi
fi

if adb shell su -c "[ -f '$CONTAINERS_PATH/alpine/config' ]" 2>/dev/null; then
    pass "Alpine config exists"
fi

# === Summary ===
echo ""
echo "========================================"
if [ $FAILURES -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}All checks passed${NC}"
    echo "LXC should be ready to use"
elif [ $FAILURES -eq 0 ]; then
    echo -e "${YELLOW}$WARNINGS warning(s), no failures${NC}"
    echo "LXC may work but review warnings above"
else
    echo -e "${RED}$FAILURES failure(s), $WARNINGS warning(s)${NC}"
    echo "Fix failures before attempting to use LXC"
fi
echo "========================================"
echo ""

exit $FAILURES
