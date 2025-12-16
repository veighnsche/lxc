#!/system/bin/sh
# TEAM_001: Container Network Setup for LXC on Android
# This script sets up NAT networking for the LXC container
#
# Usage: 
#   ./setup_container_network.sh          # Setup NAT
#   ./setup_container_network.sh clean    # Remove NAT rules

set -e

# Configuration
CONTAINER_BRIDGE="lxcbr0"
CONTAINER_SUBNET="10.0.3.0/24"
CONTAINER_GATEWAY="10.0.3.1"
HOST_INTERFACE="wlan0"

log() {
    echo "[network] $1"
}

setup_bridge() {
    log "Creating bridge $CONTAINER_BRIDGE..."
    
    # Check if bridge exists
    if ip link show "$CONTAINER_BRIDGE" >/dev/null 2>&1; then
        log "Bridge $CONTAINER_BRIDGE already exists"
        return 0
    fi
    
    # Create bridge
    ip link add name "$CONTAINER_BRIDGE" type bridge
    ip addr add "$CONTAINER_GATEWAY/24" dev "$CONTAINER_BRIDGE"
    ip link set "$CONTAINER_BRIDGE" up
    
    log "Bridge $CONTAINER_BRIDGE created with IP $CONTAINER_GATEWAY"
}

setup_nat() {
    log "Setting up NAT for container network..."
    
    # Enable IP forwarding
    echo 1 > /proc/sys/net/ipv4/ip_forward
    
    # Add NAT rules (idempotent - check if exists first)
    if ! iptables -t nat -C POSTROUTING -s "$CONTAINER_SUBNET" -o "$HOST_INTERFACE" -j MASQUERADE 2>/dev/null; then
        iptables -t nat -A POSTROUTING -s "$CONTAINER_SUBNET" -o "$HOST_INTERFACE" -j MASQUERADE
        log "Added MASQUERADE rule for $CONTAINER_SUBNET"
    else
        log "MASQUERADE rule already exists"
    fi
    
    # Allow forwarding to/from container bridge
    if ! iptables -C FORWARD -i "$CONTAINER_BRIDGE" -o "$HOST_INTERFACE" -j ACCEPT 2>/dev/null; then
        iptables -A FORWARD -i "$CONTAINER_BRIDGE" -o "$HOST_INTERFACE" -j ACCEPT
        log "Added FORWARD rule: $CONTAINER_BRIDGE -> $HOST_INTERFACE"
    fi
    
    if ! iptables -C FORWARD -i "$HOST_INTERFACE" -o "$CONTAINER_BRIDGE" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null; then
        iptables -A FORWARD -i "$HOST_INTERFACE" -o "$CONTAINER_BRIDGE" -m state --state RELATED,ESTABLISHED -j ACCEPT
        log "Added FORWARD rule: $HOST_INTERFACE -> $CONTAINER_BRIDGE (established)"
    fi
}

setup_dnsmasq() {
    log "DHCP/DNS: Container should use static IP or host's DNS"
    log "  Container gateway: $CONTAINER_GATEWAY"
    log "  Container DNS: 8.8.8.8 (or $CONTAINER_GATEWAY if dnsmasq installed)"
}

cleanup() {
    log "Cleaning up container network..."
    
    # Remove NAT rules
    iptables -t nat -D POSTROUTING -s "$CONTAINER_SUBNET" -o "$HOST_INTERFACE" -j MASQUERADE 2>/dev/null || true
    iptables -D FORWARD -i "$CONTAINER_BRIDGE" -o "$HOST_INTERFACE" -j ACCEPT 2>/dev/null || true
    iptables -D FORWARD -i "$HOST_INTERFACE" -o "$CONTAINER_BRIDGE" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
    
    # Remove bridge
    ip link set "$CONTAINER_BRIDGE" down 2>/dev/null || true
    ip link del "$CONTAINER_BRIDGE" 2>/dev/null || true
    
    log "Cleanup complete"
}

show_status() {
    echo ""
    echo "=== Container Network Status ==="
    echo ""
    echo "Bridge:"
    ip addr show "$CONTAINER_BRIDGE" 2>/dev/null || echo "  (not configured)"
    echo ""
    echo "NAT Rules:"
    iptables -t nat -L POSTROUTING -n | grep -E "(MASQUERADE|$CONTAINER_SUBNET)" || echo "  (none)"
    echo ""
    echo "IP Forwarding:"
    cat /proc/sys/net/ipv4/ip_forward
    echo ""
}

print_lxc_config() {
    echo ""
    echo "=== LXC Container Network Config ==="
    echo ""
    echo "Add to your container config:"
    echo ""
    echo "# Network configuration"
    echo "lxc.net.0.type = veth"
    echo "lxc.net.0.link = $CONTAINER_BRIDGE"
    echo "lxc.net.0.flags = up"
    echo "lxc.net.0.ipv4.address = 10.0.3.2/24"
    echo "lxc.net.0.ipv4.gateway = $CONTAINER_GATEWAY"
    echo ""
}

case "${1:-setup}" in
    setup)
        setup_bridge
        setup_nat
        setup_dnsmasq
        show_status
        print_lxc_config
        ;;
    clean|cleanup)
        cleanup
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: $0 {setup|clean|status}"
        exit 1
        ;;
esac
