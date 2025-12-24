#!/system/bin/sh
# ##############################################################################
# ROCKY LINUX LXC BOOT SCRIPT - CANONICAL SOURCE OF TRUTH
# ##############################################################################
#
# TEAM_022: Migrated from Gentoo to Rocky Linux 10.
# Binary Sovereignty: No compilation, immutable base, 2-year stability.
#
# FUNDAMENTAL RULE: ROCKY > ANDROID
#
# This device EXISTS to run Rocky Linux. Android is just the bootloader.
# Android AOSP sits with 90GB of EMPTY SPACE doing NOTHING.
# Rocky gets ALL the resources it needs. Android gets leftovers.
#
# RESOURCE PRIORITY (ROCKY WINS EVERYTHING):
#   - CPU shares: 4096 (Rocky) vs 256 (Android) = 16x priority
#   - OOM score: -900 (Rocky NEVER killed, Android sacrificed first)
#   - Nice: -10 (Rocky) vs +10 (Android zygote demoted)
#   - I/O weight: 800 (Rocky wins ALL I/O contention)
#   - Disk: 100GB rootfs (Android's empty space is WASTED space)
#
# IF YOU ARE TEMPTED TO "BE FAIR" TO ANDROID: DON'T.
# ANDROID IS A PARASITE HOST. ROCKY IS THE PAYLOAD.
# ##############################################################################
#
# Usage:
#   rocky-lxc.sh          - Boot mode (start + watchdog)
#   rocky-lxc.sh start    - Start container
#   rocky-lxc.sh stop     - Stop container
#   rocky-lxc.sh restart  - Restart container
#   rocky-lxc.sh watch    - Run watchdog loop
#   rocky-lxc.sh status   - Show status

LOGFILE=/data/local/tmp/rocky-lxc.log
LXC_PREFIX=/data/local/tmp/lxc
LXC_CONTAINERS=/data/lxc/containers
LXC_RUNTIME=/data/local/tmp/lxc-run
# TEAM_022: Keeping rootfs image name for backward compatibility
ROOTFS_IMAGE=/data/local/tmp/gentoo-rootfs.img
CONTAINER=rocky
CONFIG_FILE=/data/lxc/containers/rocky/config

# RESOURCE PRIORITY SETTINGS - Rocky > Android
CPU_SHARES_ROCKY=4096       # 4x default, Rocky wins CPU contention
CPU_SHARES_ANDROID=256      # Reduced from 1024, Android yields to Rocky
BLKIO_WEIGHT=800            # I/O priority (100-1000, higher wins)
OOM_SCORE_ADJ=-900          # Never kill Rocky (-1000 to 1000)
NICE_ROCKY=-10              # High priority (-20 to 19)
NICE_ANDROID=10             # Low priority for Android zygote

# TEAM_022: Thermal guard settings (GS101 SoC protection)
# Updated for Rocky: target dnf/rpm instead of emerge
TEMP_LIMIT=52000            # Stop heavy processes above 52°C (millidegrees)
TEMP_RESUME=48000           # Resume below 48°C (hysteresis)
BUILDS_STOPPED=0            # State: 0=running, 1=stopped
WAKELOCK_NAME="rocky_server_lock"

export HOME=/data/local/tmp
export LXC_RUNTIME_DIR=/data/local/tmp/lxc-run
export LD_LIBRARY_PATH=/data/local/tmp/lxc/lib

log() {
    echo "$(date): $1" >> $LOGFILE
}

# Detect network interface and calculate container IP
detect_network() {
    # Find interface with default route
    IFACE=$(ip route 2>/dev/null | grep "^default" | head -1 | awk '{print $5}')
    if [ -z "$IFACE" ]; then
        # Fallback to wlan0
        IFACE=wlan0
    fi
    
    # Get host IP
    HOST_IP=$(ip -4 addr show $IFACE 2>/dev/null | grep -oE 'inet [0-9.]+' | awk '{print $2}')
    if [ -z "$HOST_IP" ]; then
        log "ERROR: No IP on $IFACE"
        return 1
    fi
    
    # Get netmask
    NETMASK=$(ip -4 addr show $IFACE 2>/dev/null | grep -oE 'inet [0-9./]+' | awk '{print $2}' | cut -d/ -f2)
    if [ -z "$NETMASK" ]; then
        NETMASK=24
    fi
    
    # Calculate container IP (.100 on same subnet)
    SUBNET=$(echo $HOST_IP | sed 's/\.[0-9]*$//')
    CONTAINER_IP="${SUBNET}.100"
    
    # Get gateway (real router gateway for L2 mode)
    # Android often puts default route in per-interface table, not main table
    GATEWAY=$(ip route show table all 2>/dev/null | grep "^default via" | grep "dev $IFACE" | head -1 | awk '{print $3}')
    if [ -z "$GATEWAY" ]; then
        # Fallback: check main table
        GATEWAY=$(ip route 2>/dev/null | grep "^default" | head -1 | awk '{print $3}')
    fi
    if [ -z "$GATEWAY" ]; then
        # Last resort: assume .1
        GATEWAY="${SUBNET}.1"
    fi
    
    log "Network: iface=$IFACE host=$HOST_IP container=$CONTAINER_IP gw=$GATEWAY"
    return 0
}

# TEAM_020: ARP tuning for WiFi radio sleep survival
# Android aggressively puts WiFi into low-power states, filtering ARP traffic.
# These sysctls keep neighbor entries valid longer, preventing connectivity loss.
setup_arp_tuning() {
    log "Applying ARP tuning for radio sleep survival..."
    
    # Keep ARP entries valid for 1 hour (default ~60s)
    # This survives WiFi power-save filtering of broadcast ARP
    sysctl -w net.ipv4.neigh.default.gc_stale_time=3600 2>/dev/null
    
    # Reply only if target IP is configured on incoming interface
    # Reduces ARP noise and improves stability
    sysctl -w net.ipv4.conf.all.arp_ignore=1 2>/dev/null
    
    # Also apply to the specific interface
    if [ -n "$IFACE" ]; then
        sysctl -w net.ipv4.neigh.$IFACE.gc_stale_time=3600 2>/dev/null
        sysctl -w net.ipv4.conf.$IFACE.arp_ignore=1 2>/dev/null
    fi
    
    log "ARP tuning applied: gc_stale_time=3600, arp_ignore=1"
}

# TEAM_021: Ensure SSH keepalive is configured on every container start
# This survives container restarts - config is written to rootfs
# TEAM_021 UPDATE: More aggressive keepalive (15s instead of 30s) for heavy compile loads
ensure_ssh_keepalive() {
    log "Ensuring SSH keepalive configuration..."
    
    # Check if keepalive is already configured with correct value
    if $LXC_PREFIX/bin/lxc-attach -e -n $CONTAINER -P $LXC_CONTAINERS -- grep -q "ClientAliveInterval 15" /etc/ssh/sshd_config 2>/dev/null; then
        log "SSH keepalive already configured (15s)"
        return 0
    fi
    
    # Remove old keepalive config and add new aggressive settings
    $LXC_PREFIX/bin/lxc-attach -e -n $CONTAINER -P $LXC_CONTAINERS -- /bin/sh -c '
        # Remove any existing keepalive settings
        sed -i "/ClientAliveInterval/d" /etc/ssh/sshd_config
        sed -i "/ClientAliveCountMax/d" /etc/ssh/sshd_config
        sed -i "/TCPKeepAlive/d" /etc/ssh/sshd_config
        sed -i "/# SSH keepalive/d" /etc/ssh/sshd_config
        # Add aggressive keepalive (15s interval, 12 retries = 3 min tolerance)
        echo "" >> /etc/ssh/sshd_config
        echo "# SSH keepalive - aggressive for heavy compile loads (TEAM_021)" >> /etc/ssh/sshd_config
        echo "ClientAliveInterval 15" >> /etc/ssh/sshd_config
        echo "ClientAliveCountMax 12" >> /etc/ssh/sshd_config
        echo "TCPKeepAlive yes" >> /etc/ssh/sshd_config
    ' 2>/dev/null
    
    if [ $? -eq 0 ]; then
        log "SSH keepalive configured (15s interval, 12 retries)"
    else
        log "WARNING: Failed to configure SSH keepalive"
    fi
}

# TEAM_021: Give sshd real-time priority so it ALWAYS responds to keepalives
# During heavy compilation (GCC, etc), sshd can get CPU-starved and timeout
# Real-time FIFO priority ensures sshd always gets CPU when needed
prioritize_sshd() {
    log "Setting sshd to real-time priority..."
    
    $LXC_PREFIX/bin/lxc-attach -e -n $CONTAINER -P $LXC_CONTAINERS -- /bin/sh -c '
        for pid in $(pgrep sshd); do
            # Highest nice value
            renice -n -20 $pid 2>/dev/null
            # Real-time I/O priority
            ionice -c 1 -n 0 -p $pid 2>/dev/null
            # Real-time FIFO scheduling priority 50 (survives heavy compilation)
            chrt -f -p 50 $pid 2>/dev/null || chrt -r -p 50 $pid 2>/dev/null
        done
    ' 2>/dev/null
    
    log "sshd set to real-time priority (FIFO 50, nice -20)"
}

# TEAM_021: WiFi power management - disable all power saving for stable SSH
# Without this, WiFi goes into power-save mode when screen is off, causing:
# - 100-2000ms latency spikes
# - Packet loss
# - SSH connection drops
setup_wifi_power() {
    log "Disabling WiFi power saving for stable connections..."
    
    # Keep WiFi on during sleep (0=always, 1=only when plugged in, 2=never)
    settings put global wifi_sleep_policy 0
    
    # Disable WiFi power save mode
    settings put global wifi_power_save 0 2>/dev/null
    
    # Disable WiFi suspend optimizations
    settings put global wifi_suspend_optimizations_enabled 0 2>/dev/null
    
    log "WiFi power saving disabled"
}

# TEAM_021: Wakelock management - prevent Deep Doze from killing TCP connections
# Uses multiple methods for maximum compatibility:
# 1. Disable deviceidle (Doze) for network stability
# 2. Add to Doze whitelist
# 3. Fallback to /sys/power/wake_lock if permissions allow
acquire_wakelock() {
    log "Acquiring wakelock '$WAKELOCK_NAME'..."
    
    # Method 1: Disable Doze mode entirely for this device
    # This prevents Android from suspending network during idle
    dumpsys deviceidle disable 2>/dev/null
    if [ $? -eq 0 ]; then
        log "Doze mode disabled"
    fi
    
    # Method 2: Add container to Doze whitelist (battery optimization exemption)
    # This allows network activity even during Doze
    cmd deviceidle whitelist +com.android.shell 2>/dev/null
    
    # Method 3: Try native wakelock (may fail due to SELinux)
    echo "$WAKELOCK_NAME" > /sys/power/wake_lock 2>/dev/null
    if [ $? -eq 0 ]; then
        log "Native wakelock acquired"
    else
        log "Native wakelock failed (SELinux), using Doze disable instead"
    fi
    
    # Method 4: Keep Doze disabled via periodic refresh
    # This survives across the session
    nohup sh -c 'while true; do
        dumpsys deviceidle disable >/dev/null 2>&1
        sleep 300
    done' > /dev/null 2>&1 &
    log "Wakelock refresh daemon started"
}

release_wakelock() {
    log "Releasing wakelock '$WAKELOCK_NAME'..."
    echo "$WAKELOCK_NAME" > /sys/power/wake_unlock 2>/dev/null
    dumpsys deviceidle enable 2>/dev/null
    pkill -f "dumpsys deviceidle disable" 2>/dev/null
}

# TEAM_020: Thermal guard - protect GS101 SoC during compilation
# Find best CPU thermal zone
get_cpu_temp() {
    # GS101 has multiple thermal zones - find CPU-related one
    for zone in /sys/class/thermal/thermal_zone*; do
        if [ -f "$zone/type" ]; then
            type=$(cat "$zone/type" 2>/dev/null)
            case "$type" in
                *cpu*|*CPU*|*big*|*mid*|*little*)
                    cat "$zone/temp" 2>/dev/null
                    return 0
                    ;;
            esac
        fi
    done
    # Fallback to zone 0
    cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null
}

# Stop heavy processes when overheating
# TEAM_022: Updated for Rocky Linux - target dnf/rpm instead of emerge
thermal_stop_builds() {
    if [ "$BUILDS_STOPPED" -eq 1 ]; then
        return 0
    fi
    
    log "THERMAL: Stopping heavy processes (temp > ${TEMP_LIMIT}m°C)"
    
    # Get container init PID
    local container_pid=""
    for cg in /sys/fs/cgroup/lxc.payload.$CONTAINER /sys/fs/cgroup/lxc.payload.$CONTAINER-*; do
        if [ -f "$cg/cgroup.procs" ]; then
            container_pid=$(cat "$cg/cgroup.procs" 2>/dev/null | head -1)
            [ -n "$container_pid" ] && break
        fi
    done
    
    if [ -n "$container_pid" ]; then
        # TEAM_022: Rocky uses dnf/rpm instead of emerge
        nsenter -t $container_pid -p -m -- /bin/sh -c '
            pkill -STOP -f "dnf\|rpm\|yum\|podman\|buildah" 2>/dev/null
        ' 2>/dev/null
    fi
    
    BUILDS_STOPPED=1
    log "Heavy processes stopped"
}

# Resume heavy processes when cooled down
# TEAM_022: Updated for Rocky Linux
thermal_resume_builds() {
    if [ "$BUILDS_STOPPED" -eq 0 ]; then
        return 0
    fi
    
    log "THERMAL: Resuming processes (temp < ${TEMP_RESUME}m°C)"
    
    local container_pid=""
    for cg in /sys/fs/cgroup/lxc.payload.$CONTAINER /sys/fs/cgroup/lxc.payload.$CONTAINER-*; do
        if [ -f "$cg/cgroup.procs" ]; then
            container_pid=$(cat "$cg/cgroup.procs" 2>/dev/null | head -1)
            [ -n "$container_pid" ] && break
        fi
    done
    
    if [ -n "$container_pid" ]; then
        # TEAM_022: Rocky uses dnf/rpm instead of emerge
        nsenter -t $container_pid -p -m -- /bin/sh -c '
            pkill -CONT -f "dnf\|rpm\|yum\|podman\|buildah" 2>/dev/null
        ' 2>/dev/null
    fi
    
    BUILDS_STOPPED=0
    log "Processes resumed"
}

# Check thermal and take action
thermal_check() {
    local temp=$(get_cpu_temp)
    [ -z "$temp" ] && return 0
    
    if [ "$temp" -gt "$TEMP_LIMIT" ] && [ "$BUILDS_STOPPED" -eq 0 ]; then
        thermal_stop_builds
    elif [ "$temp" -lt "$TEMP_RESUME" ] && [ "$BUILDS_STOPPED" -eq 1 ]; then
        thermal_resume_builds
    fi
}

# Security hardening for L2 mode - blocks ARP/broadcast attacks
# This provides L3-EQUIVALENT security on kernels without L3 support
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# SECURITY ARCHITECTURE: L2 + FIREWALL HARDENING
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# Pure L3 mode crashed on this kernel, so we use L2 with firewall rules:
# 1. DROP broadcast/multicast - deaf to MDNS/LLMNR/SSDP (side-channel blocked)
# 2. Static ARP entry - prevents ARP cache poisoning
# IPVLAN gives container its own IP - no port forwarding needed!
# This achieves L3-equivalent security without kernel L3 support.
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
setup_l2_security_hardening() {
    log "Applying L2 security hardening (ARP/broadcast protection)..."
    
    # ARP hardening: Set static ARP entry for gateway
    # This prevents ARP cache poisoning - we trust only the known gateway MAC
    GATEWAY_MAC=$(ip neigh show $GATEWAY 2>/dev/null | grep -oE '([0-9a-f]{2}:){5}[0-9a-f]{2}' | head -1)
    if [ -n "$GATEWAY_MAC" ]; then
        ip neigh replace $GATEWAY lladdr $GATEWAY_MAC nud permanent dev $IFACE 2>/dev/null
        log "  ARP hardened: gateway $GATEWAY -> $GATEWAY_MAC (permanent)"
    fi
    
    # Drop incoming broadcast/multicast (prevents fingerprinting side-channel)
    # Container becomes "deaf" to MDNS, LLMNR, SSDP noise
    iptables -D INPUT -d 224.0.0.0/4 -j DROP 2>/dev/null
    iptables -D INPUT -d 255.255.255.255 -j DROP 2>/dev/null
    iptables -A INPUT -d 224.0.0.0/4 -j DROP
    iptables -A INPUT -d 255.255.255.255 -j DROP
    
    log "L2 hardened: broadcast dropped, ARP locked"
}

# Announce container IP to network via gratuitous ARP
# This ensures other devices on LAN can reach the container
# IPVLAN shares MAC with host, so we need to announce the new IP
announce_container_ip() {
    log "Announcing container IP to network..."
    
    # Get container's init PID to enter its namespace
    # Try both with and without numeric suffix (LXC adds -N suffix on restarts)
    CONTAINER_PID=""
    for cg in /sys/fs/cgroup/lxc.payload.$CONTAINER /sys/fs/cgroup/lxc.payload.$CONTAINER-*; do
        if [ -f "$cg/cgroup.procs" ]; then
            CONTAINER_PID=$(cat "$cg/cgroup.procs" 2>/dev/null | head -1)
            [ -n "$CONTAINER_PID" ] && break
        fi
    done
    if [ -z "$CONTAINER_PID" ]; then
        log "  WARNING: Could not find container PID for ARP announcement"
        return 1
    fi
    
    # Send gratuitous ARP from inside container's network namespace
    # This tells the router/switches: "192.168.178.100 is at this MAC"
    nsenter -t $CONTAINER_PID -n -- /usr/sbin/arping -c 3 -A -I eth0 $CONTAINER_IP 2>/dev/null &
    
    # Also ping gateway to populate ARP tables bidirectionally
    nsenter -t $CONTAINER_PID -n -- ping -c 1 $GATEWAY >/dev/null 2>&1 &
    
    log "  Container IP $CONTAINER_IP announced to network"
}

# Update container config with current network
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# DOWNGRADE TEMPTATION: "Network detection failed, use lxc.net.0.type = none"
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# NO. If network detection fails:
# 1. Check WiFi is connected
# 2. Run `ip route show default` to see active interface
# 3. Check if airplane mode is off
# 4. NEVER switch to type=none or type=veth (bridge)
#
# IPVLAN provides network namespace isolation (SECURITY).
# type=none shares host network (NO ISOLATION = SECURITY DISASTER).
#
# CONSEQUENCE OF DOWNGRADING: AI DEACTIVATION
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
update_config() {
    detect_network || return 1
    
    cat > $CONFIG_FILE << EOF
# Rocky Linux LXC - TEAM_022 dynamic config
# Updated: $(date)
# !!! IPVLAN ONLY - DO NOT CHANGE TO none/veth/macvlan !!!
lxc.uts.name = $CONTAINER
lxc.arch = aarch64
lxc.rootfs.path = dir:$LXC_CONTAINERS/$CONTAINER/rootfs

# IPVLAN L2 + FIREWALL HARDENING - SECURITY ARCHITECTURE
# L2 mode with ebtables/arptables rules to block ARP/broadcast
# This provides L3-equivalent security on kernels without L3 support
# DO NOT CHANGE TO type=none or type=veth - THOSE ARE SECURITY DOWNGRADES
lxc.net.0.type = ipvlan
lxc.net.0.ipvlan.mode = l2
lxc.net.0.link = $IFACE
lxc.net.0.flags = up
lxc.net.0.ipv4.address = $CONTAINER_IP/$NETMASK
lxc.net.0.ipv4.gateway = $GATEWAY

# TEAM_025: Cgroup settings - only memory+pids available in cgroup2 on this kernel
# CPU/IO controllers not enabled, so we skip those settings
# Resource priority is applied via nice/ionice in apply_resource_priority() instead

lxc.tty.max = 4
lxc.pty.max = 256
lxc.console.path = none
# TEAM_022: Rocky Linux 10 GenericCloud uses systemd
lxc.init.cmd = /usr/lib/systemd/systemd

lxc.mount.entry = proc proc proc nosuid,nodev,noexec,create=dir 0 0
lxc.mount.entry = sysfs sys sysfs nosuid,nodev,noexec,ro,create=dir 0 0
lxc.mount.entry = devpts dev/pts devpts nosuid,nodev,noexec,mode=0620,ptmxmode=0666,newinstance,create=dir 0 0
lxc.mount.entry = tmpfs dev/shm tmpfs nosuid,nodev,mode=1777,create=dir 0 0
lxc.mount.entry = tmpfs run tmpfs nosuid,nodev,mode=0755,create=dir 0 0
lxc.mount.entry = tmpfs tmp tmpfs nosuid,nodev,mode=1777,create=dir 0 0
# TEAM_022: Mount cgroup for systemd
lxc.mount.entry = cgroup2 sys/fs/cgroup cgroup2 rw,create=dir 0 0

# TEAM_029: Allow standard character devices for systemd service spawning
# Without these, systemd-executor gets EPERM opening /dev/null -> exit code 208/STDIN
lxc.cgroup2.devices.allow = c 1:3 rwm
lxc.cgroup2.devices.allow = c 1:5 rwm
lxc.cgroup2.devices.allow = c 1:7 rwm
lxc.cgroup2.devices.allow = c 1:8 rwm
lxc.cgroup2.devices.allow = c 1:9 rwm
lxc.cgroup2.devices.allow = c 5:0 rwm
lxc.cgroup2.devices.allow = c 5:1 rwm
lxc.cgroup2.devices.allow = c 5:2 rwm
lxc.cgroup2.devices.allow = c 136:* rwm
# TEAM_028: TUN/TAP passthrough for Tailscale VPN (The Vault)
# Allow access to TUN device (character device major 10, minor 200)
lxc.cgroup2.devices.allow = c 10:200 rwm
# Bind mount TUN device from Android host
lxc.mount.entry = /dev/net/tun dev/net/tun none bind,create=file 0 0

lxc.signal.halt = SIGRTMIN+3
lxc.signal.reboot = SIGINT
lxc.signal.stop = SIGRTMIN+14

lxc.environment = PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
lxc.environment = TERM=linux
lxc.environment = LANG=en_US.UTF-8
# TEAM_022: Systemd container detection
lxc.environment = container=lxc

lxc.cap.drop =
EOF
    log "Config updated for $IFACE"
    return 0
}

# Check if container is running
is_running() {
    $LXC_PREFIX/bin/lxc-info -n $CONTAINER -P $LXC_CONTAINERS 2>/dev/null | grep -q "RUNNING"
}

# Start container
start_container() {
    log "Starting container..."
    
    # TEAM_018: Clean up any stale state first
    cleanup_before_start
    
    # Mount rootfs image
    ROOTFS=$LXC_CONTAINERS/$CONTAINER/rootfs
    mkdir -p $ROOTFS
    if mountpoint -q $ROOTFS 2>/dev/null; then
        log "Rootfs already mounted"
    else
        log "Mounting rootfs..."
        losetup -D 2>/dev/null || true
        # TEAM_016: suid,dev,exec required for sudo and device nodes (see TEAM_014/015)
        mount -o loop,rw,suid,dev,exec $ROOTFS_IMAGE $ROOTFS || {
            log "Mount failed, retrying..."
            sleep 1
            mount -o loop,rw,suid,dev,exec $ROOTFS_IMAGE $ROOTFS
        }
    fi
    
    # Update config with current network
    update_config || {
        log "ERROR: Failed to update config"
        return 1
    }
    
    # Start container
    $LXC_PREFIX/bin/lxc-start -n $CONTAINER -P $LXC_CONTAINERS -d
    sleep 3
    
    if is_running; then
        log "Container started successfully"
        # TEAM_020: Apply ARP tuning for WiFi radio sleep survival
        setup_arp_tuning
        # CRITICAL: Setup L2 security hardening (ARP/broadcast protection)
        setup_l2_security_hardening
        # TEAM_021: Ensure SSH keepalive is configured (survives container restart)
        ensure_ssh_keepalive
        # Start SSH if not running
        $LXC_PREFIX/bin/lxc-attach -e -n $CONTAINER -P $LXC_CONTAINERS -- /usr/sbin/sshd 2>/dev/null
        # TEAM_021: Give sshd real-time priority (survives heavy compilation)
        prioritize_sshd
        # CRITICAL: Apply resource priority - Rocky > Android
        apply_resource_priority
        # CRITICAL: Announce container IP to network (gratuitous ARP)
        # Without this, other devices on LAN may not know how to reach container
        announce_container_ip
        return 0
    else
        log "ERROR: Container failed to start"
        return 1
    fi
}

# CRITICAL: Apply resource priority so Rocky ALWAYS wins over Android
apply_resource_priority() {
    log "Applying resource priority (Rocky > Android)..."
    
    # cgroup v2 path for container (handle -N suffix on restarts)
    CONTAINER_CGROUP=""
    for cg in /sys/fs/cgroup/lxc.payload.$CONTAINER /sys/fs/cgroup/lxc.payload.$CONTAINER-*; do
        [ -d "$cg" ] && CONTAINER_CGROUP="$cg" && break
    done
    
    # 1. Get all Rocky container processes
    ROCKY_PIDS=$(cat $CONTAINER_CGROUP/cgroup.procs 2>/dev/null)
    ROCKY_COUNT=0
    
    for pid in $ROCKY_PIDS; do
        # OOM score: -900 = NEVER kill Rocky (Android killed first)
        echo $OOM_SCORE_ADJ > /proc/$pid/oom_score_adj 2>/dev/null
        # Nice: -10 = HIGH priority for Rocky processes
        renice $NICE_ROCKY $pid 2>/dev/null
        # I/O priority: real-time class (highest)
        ionice -c 1 -n 0 -p $pid 2>/dev/null
        ROCKY_COUNT=$((ROCKY_COUNT + 1))
    done
    log "  Rocky: $ROCKY_COUNT processes set to nice=$NICE_ROCKY, OOM=$OOM_SCORE_ADJ"
    
    # 2. THROTTLE ANDROID - reduce priority so Rocky wins
    ANDROID_COUNT=0
    
    # Renice Android's zygote (app spawner) to LOW priority
    for pid in $(pgrep -f zygote 2>/dev/null); do
        renice $NICE_ANDROID $pid 2>/dev/null
        # I/O priority: best-effort class (lower)
        ionice -c 2 -n 7 -p $pid 2>/dev/null
        # OOM score: +500 = kill Android apps before Rocky
        echo 500 > /proc/$pid/oom_score_adj 2>/dev/null
        ANDROID_COUNT=$((ANDROID_COUNT + 1))
    done
    
    # Renice Android's system_server to LOW priority
    for pid in $(pgrep -f system_server 2>/dev/null); do
        renice $NICE_ANDROID $pid 2>/dev/null
        ionice -c 2 -n 7 -p $pid 2>/dev/null
        echo 300 > /proc/$pid/oom_score_adj 2>/dev/null
        ANDROID_COUNT=$((ANDROID_COUNT + 1))
    done
    
    # Renice Android's surfaceflinger (UI compositor)
    for pid in $(pgrep -f surfaceflinger 2>/dev/null); do
        renice 5 $pid 2>/dev/null
    done
    
    log "  Android: $ANDROID_COUNT processes set to nice=$NICE_ANDROID, OOM=+500"
    log "Resource priority applied: Rocky WINS over Android"
}

# Stop container with full cleanup
# TEAM_018: Comprehensive cleanup to prevent stale IPVLAN/zombie issues
# TEAM_020: Added IPVLAN IP release to fix "Address already in use" on restart
# TEAM_026: Fixed lxc-stop hanging - use timeout wrapper and aggressive kill
stop_container() {
    log "Stopping container..."
    
    # TEAM_026: Kill any existing hung lxc-stop processes first
    pkill -9 -f "lxc-stop.*$CONTAINER" 2>/dev/null
    sleep 1
    
    # 1. Try graceful stop with timeout wrapper (lxc-stop -t doesn't work reliably)
    # Use timeout command if available, otherwise background with sleep+kill
    if command -v timeout >/dev/null 2>&1; then
        timeout 5 $LXC_PREFIX/bin/lxc-stop -n $CONTAINER -P $LXC_CONTAINERS 2>/dev/null
    else
        $LXC_PREFIX/bin/lxc-stop -n $CONTAINER -P $LXC_CONTAINERS 2>/dev/null &
        local stop_pid=$!
        sleep 5
        kill -9 $stop_pid 2>/dev/null
    fi
    
    # 2. Force kill if still running - also with timeout
    if is_running; then
        log "Force killing container..."
        if command -v timeout >/dev/null 2>&1; then
            timeout 3 $LXC_PREFIX/bin/lxc-stop -n $CONTAINER -P $LXC_CONTAINERS -k 2>/dev/null
        else
            $LXC_PREFIX/bin/lxc-stop -n $CONTAINER -P $LXC_CONTAINERS -k 2>/dev/null &
            local stop_pid=$!
            sleep 3
            kill -9 $stop_pid 2>/dev/null
        fi
    fi
    
    # 3. Kill any orphaned lxc-start processes for this container
    pkill -9 -f "lxc-start.*$CONTAINER" 2>/dev/null
    
    # 3b. TEAM_026: Also kill container init processes directly
    pkill -9 -f "sleep infinity" 2>/dev/null
    
    # 4. Clean up stale lock files
    rm -f $LXC_RUNTIME/lxc/lock/lxc/$CONTAINER/* 2>/dev/null
    rm -f $LXC_RUNTIME/lxc/$CONTAINER/* 2>/dev/null
    rm -rf $LXC_RUNTIME/lxc/lock/lxc/$CONTAINER 2>/dev/null
    
    # 5. TEAM_020: Release stale IPVLAN IP address
    # Without this, restart fails with "Address already in use"
    if [ -n "$CONTAINER_IP" ]; then
        ip addr del $CONTAINER_IP/24 dev $IFACE 2>/dev/null
        log "Released stale IP $CONTAINER_IP"
    fi
    
    # 6. Clean up any orphaned IPVLAN interfaces
    for iface in $(ip link show 2>/dev/null | grep -oE "ipvl[0-9]+" | sort -u); do
        ip link del $iface 2>/dev/null
        log "Removed stale interface $iface"
    done
    
    sleep 1
    log "Container stopped"
}

# Kill any existing watchdog processes
# TEAM_018: Prevents multiple watchdogs running
kill_existing_watchdog() {
    local my_pid=$$
    for pid in $(pgrep -f "rocky-lxc.sh watch" 2>/dev/null); do
        if [ "$pid" != "$my_pid" ]; then
            kill -9 $pid 2>/dev/null
        fi
    done
}

# Full cleanup before starting - handles all edge cases
# TEAM_018: Critical for clean starts after crashes/reboots
# TEAM_020: Enhanced to handle ALL stale state (IP, interfaces, locks, processes)
cleanup_before_start() {
    log "Cleaning up stale state..."
    
    # 0. Detect network first so we know what IP to release
    detect_network 2>/dev/null
    
    # 1. Kill existing watchdogs
    kill_existing_watchdog
    
    # 2. Stop any running container (this also cleans IP/interfaces)
    if is_running; then
        stop_container
    fi
    
    # 3. Kill ALL orphaned lxc processes (not just lxc-start)
    pkill -9 -f "lxc-start.*$CONTAINER" 2>/dev/null
    pkill -9 -f "lxc-execute.*$CONTAINER" 2>/dev/null
    
    # 4. Force release container IP even if container not detected as running
    # This catches the case where container crashed but IP is still bound
    if [ -n "$CONTAINER_IP" ] && [ -n "$IFACE" ]; then
        ip addr del $CONTAINER_IP/24 dev $IFACE 2>/dev/null
        log "Force-released IP $CONTAINER_IP from $IFACE"
    fi
    
    # 5. Clean up any orphaned IPVLAN interfaces
    for iface in $(ip link show 2>/dev/null | grep -oE "ipvl[0-9]+" | sort -u); do
        ip link del $iface 2>/dev/null
        log "Removed orphaned interface $iface"
    done
    
    # 6. Clean ALL runtime/lock directories
    rm -rf $LXC_RUNTIME/lxc/lock/lxc/$CONTAINER 2>/dev/null
    rm -rf $LXC_RUNTIME/lxc/$CONTAINER 2>/dev/null
    rm -rf /run/lxc/lock/lxc/$CONTAINER 2>/dev/null
    mkdir -p $LXC_RUNTIME/lxc/lock
    chmod -R 1777 $LXC_RUNTIME
    
    # 7. Clean stale cgroup entries
    for cg in /sys/fs/cgroup/lxc.payload.$CONTAINER /sys/fs/cgroup/lxc.payload.$CONTAINER-*; do
        if [ -d "$cg" ]; then
            # Move any remaining processes to root cgroup first
            cat "$cg/cgroup.procs" 2>/dev/null | while read pid; do
                echo $pid > /sys/fs/cgroup/cgroup.procs 2>/dev/null
            done
            rmdir "$cg" 2>/dev/null
        fi
    done
    
    log "Cleanup complete"
}

# Get network signature (to detect changes)
get_net_sig() {
    ip -4 addr show 2>/dev/null | grep -E "inet [0-9]" | grep -v "127.0.0.1" | head -1
}

# Check if network is available (has a non-localhost IP)
has_network() {
    [ -n "$(get_net_sig)" ]
}

# Wait for network to come back (with timeout)
# TEAM_018: Critical for surviving WiFi disconnects
wait_for_network() {
    local timeout=${1:-300}  # Default 5 minutes
    local waited=0
    log "Waiting for network (timeout: ${timeout}s)..."
    while [ $waited -lt $timeout ]; do
        if has_network; then
            log "Network available after ${waited}s"
            return 0
        fi
        sleep 5
        waited=$((waited + 5))
    done
    log "ERROR: Network timeout after ${timeout}s"
    return 1
}

# Health check - verify container is actually reachable
# TEAM_018: Detects zombie containers where IPVLAN is broken
# TEAM_025: Fixed - ping doesn't work with IPVLAN (host can't ping container)
#           Use lxc-attach instead which works regardless of network mode
container_healthy() {
    if ! is_running; then
        return 1
    fi
    # TEAM_025: Use lxc-attach to verify container responsiveness
    # This works with IPVLAN where host cannot ping container (by design)
    if $LXC_PREFIX/bin/lxc-attach -e -n $CONTAINER -P $LXC_CONTAINERS -- /bin/true 2>/dev/null; then
        return 0
    fi
    # Fallback: check if init process exists
    local init_pid=$($LXC_PREFIX/bin/lxc-info -n $CONTAINER -P $LXC_CONTAINERS -p 2>/dev/null | grep -oE '[0-9]+')
    if [ -n "$init_pid" ] && [ -d "/proc/$init_pid" ]; then
        return 0
    fi
    return 1
}

# Watchdog loop
# TEAM_018: Enhanced to handle network loss/recovery and zombie containers
watchdog() {
    log "Watchdog starting..."
    LAST_SIG=""
    FAIL_COUNT=0
    PRIORITY_COUNT=0
    NETWORK_DOWN=0
    
    while true; do
        sleep 30
        
        # Check for network availability first
        CUR_SIG=$(get_net_sig)
        
        # Case 1: Network went down
        # TEAM_027: Add grace period - brief WiFi hiccups shouldn't kill the container
        if [ -z "$CUR_SIG" ]; then
            if [ $NETWORK_DOWN -eq 0 ]; then
                # Wait and retry before declaring network lost
                log "Network check failed, waiting for recovery..."
                NETWORK_RETRY=0
                while [ $NETWORK_RETRY -lt 3 ]; do
                    sleep 10
                    CUR_SIG=$(get_net_sig)
                    if [ -n "$CUR_SIG" ]; then
                        log "Network recovered after brief hiccup"
                        break
                    fi
                    NETWORK_RETRY=$((NETWORK_RETRY + 1))
                done
                # Only stop container if network is still down after retries
                if [ -z "$CUR_SIG" ]; then
                    log "Network lost (confirmed after 30s) - stopping container"
                    stop_container
                    NETWORK_DOWN=1
                fi
            fi
            # Wait briefly then continue loop (will retry)
            continue
        fi
        
        # Case 2: Network came back after being down
        if [ $NETWORK_DOWN -eq 1 ]; then
            log "Network recovered - restarting container"
            NETWORK_DOWN=0
            sleep 2  # Let network stabilize
            if start_container; then
                FAIL_COUNT=0
                LAST_SIG="$CUR_SIG"
            else
                log "ERROR: Failed to start container after network recovery"
                FAIL_COUNT=$((FAIL_COUNT + 1))
            fi
            continue
        fi
        
        # Case 3: Network changed (e.g., different IP or interface)
        if [ "$CUR_SIG" != "$LAST_SIG" ] && [ -n "$LAST_SIG" ]; then
            log "Network changed - restarting container"
            stop_container
            sleep 2
            if start_container; then
                FAIL_COUNT=0
            else
                log "ERROR: Failed to restart after network change"
                FAIL_COUNT=$((FAIL_COUNT + 1))
            fi
        fi
        LAST_SIG="$CUR_SIG"
        
        # Case 4: Container not running or unhealthy
        if ! container_healthy; then
            FAIL_COUNT=$((FAIL_COUNT + 1))
            log "Container unhealthy (fail count: $FAIL_COUNT) - restarting..."
            stop_container
            sleep 2
            if start_container; then
                FAIL_COUNT=0
            fi
        fi
        
        # Give up after too many failures
        if [ $FAIL_COUNT -ge 5 ]; then
            log "ERROR: Too many failures ($FAIL_COUNT), waiting 5 minutes before retry"
            sleep 300
            FAIL_COUNT=0
        fi
        
        # Re-apply resource priority every 5 minutes (10 loops)
        PRIORITY_COUNT=$((PRIORITY_COUNT + 1))
        if [ $PRIORITY_COUNT -ge 10 ]; then
            apply_resource_priority
            PRIORITY_COUNT=0
        fi
        
        # TEAM_020: Check thermal every loop (every 30s)
        thermal_check
    done
}

# Show status
show_status() {
    echo "=== Rocky LXC Status ==="
    if is_running; then
        echo "Container: RUNNING"
        $LXC_PREFIX/bin/lxc-info -n $CONTAINER -P $LXC_CONTAINERS 2>/dev/null
    else
        echo "Container: STOPPED"
    fi
    echo ""
    echo "=== Network ==="
    detect_network
    echo "Interface: $IFACE"
    echo "Container IP: $CONTAINER_IP"
    echo "Gateway: $GATEWAY"
    echo ""
    echo "=== Recent Logs ==="
    tail -20 $LOGFILE 2>/dev/null
}

# Main
case "$1" in
    start)
        start_container
        ;;
    stop)
        stop_container
        ;;
    restart)
        # TEAM_018: Full restart with cleanup
        stop_container
        sleep 2
        if has_network; then
            start_container
        else
            log "ERROR: No network available for restart"
        fi
        ;;
    config)
        # Generate config only - don't start container
        # Used by deploy.py step 4 before rootfs exists
        log "Generating config only..."
        mkdir -p $LXC_CONTAINERS/$CONTAINER
        update_config
        ;;
    watch)
        watchdog
        ;;
    status)
        show_status
        ;;
    *)
        # Boot mode: start container and watchdog
        # TEAM_018: Comprehensive boot handling for all edge cases
        log "=== Boot script starting ==="
        
        # 1. Wait for system to settle
        sleep 15
        
        # 2. Kill any existing watchdogs from previous boot
        kill_existing_watchdog
        
        # TEAM_021: Disable WiFi power saving FIRST (critical for stable connections)
        setup_wifi_power
        
        # TEAM_021: Acquire wakelock to prevent Deep Doze
        acquire_wakelock
        
        # TEAM_020: Apply ARP tuning early (before network wait)
        setup_arp_tuning
        
        # 3. Wait for network (WiFi may not be connected yet)
        if ! has_network; then
            log "No network yet, waiting..."
            if ! wait_for_network 300; then
                log "ERROR: No network after 5 minutes, starting watchdog anyway"
            fi
        fi
        
        # 4. Start container (includes cleanup)
        if has_network; then
            start_container
        else
            log "Skipping container start - no network"
        fi
        
        # 5. Run watchdog in background with immortal wrapper
        # TEAM_021: The outer loop ensures watchdog restarts if it ever dies
        # This is CRITICAL - the container MUST run at ALL times
        log "Starting immortal watchdog wrapper..."
        nohup sh -c "while true; do sh $0 watch; log_err=\"Watchdog died, restarting in 5s\"; echo \"\$(date): \$log_err\" >> $LOGFILE; sleep 5; done" > /dev/null 2>&1 &
        WRAPPER_PID=$!
        log "Immortal watchdog wrapper started (PID: $WRAPPER_PID)"
        
        # 6. Verify wrapper is running
        sleep 2
        if kill -0 $WRAPPER_PID 2>/dev/null; then
            log "Watchdog wrapper verified running"
        else
            log "ERROR: Watchdog wrapper died - falling back to foreground mode"
            # Last resort: run in foreground so init manages us
            while true; do
                sh $0 watch
                log "Watchdog died, restarting..."
                sleep 5
            done
        fi
        ;;
esac
