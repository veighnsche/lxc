#!/system/bin/sh
# lxc-wrapper.sh
# Wrapper script for running LXC commands with proper environment
#
# Usage via adb:
#   adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh <command> [args...]'
#
# Examples:
#   adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-start -n alpine -F'
#   adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-info -n alpine'
#   adb shell su -c 'sh /data/local/tmp/lxc-wrapper.sh lxc-stop -n alpine'
#
# All environment variables are defined in lxc-env.sh (single source of truth).

set -e

# === Setup: source common device library ===
LOG_PREFIX="[lxc-wrapper]"
LXC_DEVICE_LIB="/data/local/tmp/lib/common-device.sh"
if [ ! -f "$LXC_DEVICE_LIB" ]; then
    echo "[lxc-wrapper] ERROR: Device library not found: $LXC_DEVICE_LIB" >&2
    echo "[lxc-wrapper] Run push-to-phone.sh first to push all required files." >&2
    exit 1
fi
. "$LXC_DEVICE_LIB"

# === Validate environment file exists ===
if [ ! -f "$LXC_ENV_FILE" ]; then
    die "Environment file not found: $LXC_ENV_FILE - Run install-lxc-on-phone.sh first"
fi

# === Source environment (single source of truth) ===
. "$LXC_ENV_FILE"

# === Validate critical paths ===
if [ ! -d "$LXC_PREFIX" ]; then
    die "LXC prefix not found: $LXC_PREFIX"
fi

if [ ! -f "$LXC_PREFIX/lib/liblxc.so" ]; then
    die "liblxc.so not found"
fi

# === Validate command ===
if [ $# -eq 0 ]; then
    echo "Usage: $0 <command> [args...]" >&2
    echo "" >&2
    echo "Examples:" >&2
    echo "  $0 lxc-start -n alpine -F" >&2
    echo "  $0 lxc-info -n alpine" >&2
    echo "  $0 lxc-ls -f" >&2
    exit 1
fi

# === Execute command ===
# LXC needs --lxcpath since the compiled-in default is /var/lib/lxc
CMD="$1"
shift
exec "$CMD" --lxcpath="$LXC_PATH" "$@"
