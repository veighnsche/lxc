#!/system/bin/sh
# check-kernel-config.sh
# Verify kernel has required LXC features
#
# Run via: adb shell su -c 'sh /data/local/tmp/check-kernel-config.sh'

log() {
    echo "[kernel-check] $1"
}

check_config() {
    local config="$1"
    local desc="$2"
    
    if zcat /proc/config.gz 2>/dev/null | grep -q "^${config}=y"; then
        echo "  [OK]  $config - $desc"
        return 0
    elif zcat /proc/config.gz 2>/dev/null | grep -q "^${config}=m"; then
        echo "  [OK]  $config (module) - $desc"
        return 0
    else
        echo "  [--]  $config - $desc"
        return 1
    fi
}

log "Checking kernel configuration for LXC support..."
log ""

# Check if /proc/config.gz exists
if [ ! -f /proc/config.gz ]; then
    log "WARNING: /proc/config.gz not available"
    log "Cannot verify kernel config - assuming features are present"
    exit 0
fi

MISSING=0

log "=== Namespaces ==="
check_config CONFIG_NAMESPACES "Namespace support" || MISSING=$((MISSING+1))
check_config CONFIG_UTS_NS "UTS namespace" || MISSING=$((MISSING+1))
check_config CONFIG_IPC_NS "IPC namespace" || MISSING=$((MISSING+1))
check_config CONFIG_PID_NS "PID namespace" || MISSING=$((MISSING+1))
check_config CONFIG_NET_NS "Network namespace" || MISSING=$((MISSING+1))
check_config CONFIG_USER_NS "User namespace" || MISSING=$((MISSING+1))

log ""
log "=== Cgroups ==="
check_config CONFIG_CGROUPS "Cgroup support" || MISSING=$((MISSING+1))
check_config CONFIG_CGROUP_DEVICE "Device cgroup" || true
check_config CONFIG_CGROUP_FREEZER "Freezer cgroup" || true
check_config CONFIG_CGROUP_PIDS "PIDs cgroup" || true
check_config CONFIG_CGROUP_CPUACCT "CPU accounting cgroup" || true
check_config CONFIG_MEMCG "Memory cgroup" || true

log ""
log "=== Filesystems ==="
check_config CONFIG_DEVPTS_MULTIPLE_INSTANCES "Multiple devpts instances" || true
check_config CONFIG_PROC_FS "Proc filesystem" || MISSING=$((MISSING+1))
check_config CONFIG_SYSFS "Sysfs filesystem" || MISSING=$((MISSING+1))
check_config CONFIG_TMPFS "Tmpfs filesystem" || true
check_config CONFIG_OVERLAY_FS "Overlay filesystem" || true

log ""
log "=== Security ==="
check_config CONFIG_SECCOMP "Seccomp support" || true
check_config CONFIG_SECURITY "Security framework" || true

log ""
log "=== Misc ==="
check_config CONFIG_POSIX_MQUEUE "POSIX message queues" || true
check_config CONFIG_KEYS "Kernel key management" || true
check_config CONFIG_VETH "Virtual ethernet pair" || true
check_config CONFIG_BRIDGE "Ethernet bridge" || true
check_config CONFIG_MACVLAN "MAC-VLAN support" || true

log ""
if [ $MISSING -gt 0 ]; then
    log "WARNING: $MISSING critical features may be missing"
    log "Container functionality may be limited"
else
    log "All critical kernel features present"
fi

log ""
log "Kernel version: $(uname -r)"
log ""
