#!/bin/bash
# Build LXC for Android aarch64 API 31
# Minimal, Gentoo-style footprint
#
# Prerequisites:
#   - Android NDK r27d installed
#   - Set ANDROID_NDK_HOME or ANDROID_NDK_ROOT environment variable
#   - Meson and Ninja installed on host
#
# Usage:
#   ./build-android.sh [configure|build|install|clean|all]
#
# Output:
#   _install_android31/  - relocatable installation prefix

set -e

# === Setup ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# TEAM_000: Self-contained logging (no external dependencies)
log() { echo "[build] $*"; }
die() { echo "[build] ERROR: $*" >&2; exit 1; }
print_blocked_box() {
    echo "==========================================================================="
    for line in "$@"; do echo "  $line"; done
    echo "==========================================================================="
}
print_banner() {
    echo ""
    echo "==========================================================================="
    echo " $1"
    echo "==========================================================================="
    echo ""
}
print_complete_banner() {
    echo ""
    echo "==========================================================================="
    echo " ✓ $1"
    echo "==========================================================================="
    echo ""
}

# =============================================================================
# WORKFLOW STAGE: Step 1 of 5 - Build LXC for Android (HOST)
# =============================================================================
#
#   Step 1: build-android.sh            -> _install_android31/    <- YOU ARE HERE
#   Step 2: prepare-alpine-rootfs.sh    -> _artifacts/alpine-rootfs.tar.gz
#   Step 3: push-to-phone.sh            -> pushes to device
#   Step 4: install-lxc-on-phone.sh     (on device)
#   Step 5: unpack-rootfs.sh alpine     (on device)
#
# Prerequisites:
#   - Android NDK r27d installed
#   - ANDROID_NDK_HOME or ANDROID_NDK_ROOT set
#   - Meson and Ninja installed
#
# Output: _install_android31/ (LXC binaries for Android)
# =============================================================================

BUILD_DIR="${SCRIPT_DIR}/_build_android31"
INSTALL_DIR="${SCRIPT_DIR}/_install_android31"
CROSS_FILE="${SCRIPT_DIR}/cross/android-aarch64-api31.ini"

# TEAM_000: Use device target path as prefix so paths are correct at runtime
# The actual files go to INSTALL_DIR via DESTDIR, but compiled-in paths use TARGET_PREFIX
TARGET_PREFIX="/data/local/tmp/lxc"

# Detect NDK path
if [ -n "$ANDROID_NDK_HOME" ]; then
    NDK_PATH="$ANDROID_NDK_HOME"
elif [ -n "$ANDROID_NDK_ROOT" ]; then
    NDK_PATH="$ANDROID_NDK_ROOT"
elif [ -n "$NDK" ]; then
    NDK_PATH="$NDK"
else
    print_blocked_box "Android NDK not found" \
        "Set one of these environment variables:" \
        "  export ANDROID_NDK_HOME=/path/to/android-ndk-r27d" \
        "  export ANDROID_NDK_ROOT=/path/to/android-ndk-r27d" \
        "" \
        "Download NDK from: https://developer.android.com/ndk/downloads"
    exit 1
fi

# Verify NDK exists
if [ ! -d "$NDK_PATH/toolchains/llvm/prebuilt/linux-x86_64" ]; then
    print_blocked_box "NDK toolchain not found" \
        "Expected: $NDK_PATH/toolchains/llvm/prebuilt/linux-x86_64" \
        "" \
        "Verify your NDK path is correct and contains the toolchain."
    exit 1
fi

log "Using NDK: $NDK_PATH"

# Update cross file with actual NDK path
update_cross_file() {
    sed -i "s|ndk_path = '.*'|ndk_path = '$NDK_PATH'|" "$CROSS_FILE"
}

configure() {
    echo "=== Configuring LXC for Android aarch64 API 31 ==="
    
    update_cross_file
    
    # Remove old build directory if exists
    rm -rf "$BUILD_DIR"
    
    # TEAM_000: Use TARGET_PREFIX so compiled-in paths are correct on device
    # Files are installed to INSTALL_DIR via DESTDIR
    meson setup "$BUILD_DIR" \
        --cross-file "$CROSS_FILE" \
        --prefix="$TARGET_PREFIX" \
        --buildtype=release \
        --strip \
        -Db_lto=true \
        -Db_lto_mode=thin \
        -Db_pie=true \
        \
        -Dman=false \
        -Dapi-docs=false \
        -Dtests=false \
        -Dexamples=false \
        -Dinstall-init-files=false \
        -Dinstall-state-dirs=false \
        -Dspecfile=false \
        -Dcoverity-build=false \
        \
        -Dtools=true \
        -Dtools-multicall=false \
        -Dcommands=true \
        \
        -Dcapabilities=false \
        -Dseccomp=false \
        -Dselinux=false \
        -Dapparmor=false \
        -Dopenssl=false \
        -Dpam-cgroup=false \
        -Dio-uring-event-loop=false \
        -Ddbus=false \
        -Dthread-safety=true \
        -Dmemfd-rexec=true \
        \
        -Druntime-path=/data/local/tmp/lxc/run \
        -Ddata-path=lib/lxc \
        -Dlog-path=log/lxc \
        -Dglobal-config-path=lxc
    
    echo "Configuration complete. Build directory: $BUILD_DIR"
}

build() {
    echo "=== Building LXC ==="
    
    if [ ! -d "$BUILD_DIR" ]; then
        echo "Error: Build directory not found. Run configure first."
        exit 1
    fi
    
    ninja -C "$BUILD_DIR" -j$(nproc)
    
    echo "Build complete."
}

install() {
    echo "=== Installing LXC to $INSTALL_DIR ==="
    
    if [ ! -d "$BUILD_DIR" ]; then
        echo "Error: Build directory not found. Run configure and build first."
        exit 1
    fi
    
    # Clean install directory
    rm -rf "$INSTALL_DIR"
    
    # TEAM_000: Use DESTDIR to install files to INSTALL_DIR while keeping TARGET_PREFIX paths
    DESTDIR="$INSTALL_DIR" ninja -C "$BUILD_DIR" install
    
    # Move files from INSTALL_DIR/TARGET_PREFIX to INSTALL_DIR root
    # e.g., INSTALL_DIR/data/local/tmp/lxc/* -> INSTALL_DIR/*
    if [ -d "$INSTALL_DIR$TARGET_PREFIX" ]; then
        mv "$INSTALL_DIR$TARGET_PREFIX"/* "$INSTALL_DIR/" 2>/dev/null || true
        rm -rf "$INSTALL_DIR/data"
    fi
    
    echo ""
    echo "Installation complete."
    echo ""
    echo "Installed files:"
    find "$INSTALL_DIR" -type f | head -30
    echo ""
    echo "Binary sizes:"
    find "$INSTALL_DIR" -name 'lxc-*' -o -name 'liblxc.so*' 2>/dev/null | \
        xargs -I{} sh -c 'echo "$(du -h {} | cut -f1) {}"' | sort -k2
}

clean() {
    echo "=== Cleaning build artifacts ==="
    rm -rf "$BUILD_DIR" "$INSTALL_DIR"
    echo "Clean complete."
}

show_usage() {
    echo "Usage: $0 [configure|build|install|clean|all]"
    echo ""
    echo "Commands:"
    echo "  configure  - Configure the build with Meson"
    echo "  build      - Compile the project"
    echo "  install    - Install to _install_android31/"
    echo "  clean      - Remove build artifacts"
    echo "  all        - configure + build + install (default)"
    echo ""
    echo "Environment variables:"
    echo "  ANDROID_NDK_HOME  - Path to Android NDK"
    echo "  ANDROID_NDK_ROOT  - Alternative NDK path variable"
    echo "  NDK               - Alternative NDK path variable"
}

# Show stage banner for 'all' command
if [ "${1:-all}" = "all" ]; then
    print_banner "Step 1/5: Build LXC for Android"
fi

case "${1:-all}" in
    configure)
        configure
        ;;
    build)
        build
        ;;
    install)
        install
        ;;
    clean)
        clean
        ;;
    all)
        configure
        build
        install
        print_complete_banner "Step 1/5: COMPLETE"
        log "Output: $INSTALL_DIR"
        print_next_step_box "Step 2 - Prepare Alpine rootfs" "$SCRIPT_DIR/android/prepare-alpine-rootfs.sh"
        echo ""
        ;;
    -h|--help|help)
        show_usage
        ;;
    *)
        echo "Unknown command: $1"
        show_usage
        exit 1
        ;;
esac
