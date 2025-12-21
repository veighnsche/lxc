#!/system/bin/sh
# Programmatic root shell into Gentoo container
# Usage: gentoo-shell.sh [command]
#   No args: interactive bash shell as root
#   With args: run command as root and exit
#
# This uses nsenter to enter ALL container namespaces properly:
# - Mount namespace (sees container's filesystem)
# - UTS namespace (sees container's hostname)
# - Network namespace (sees container's network stack)  
# - PID namespace (sees container's process tree)
#
# WHY NOT CHROOT:
# Chroot only changes root directory - it does NOT:
# - Enter network namespace (you'd see host network)
# - Enter PID namespace (you'd see host processes)
# - Enter mount namespace (mounts would leak)
# This would BREAK the container's isolation.

CONTAINER=gentoo
CGROUP_PATH=/sys/fs/cgroup/lxc.payload.$CONTAINER/cgroup.procs

# Get container init PID
get_container_pid() {
    if [ -f "$CGROUP_PATH" ]; then
        head -1 "$CGROUP_PATH"
    else
        echo "ERROR: Container not running (cgroup not found)" >&2
        exit 1
    fi
}

PID=$(get_container_pid)

if [ -z "$PID" ]; then
    echo "ERROR: Could not find container PID" >&2
    exit 1
fi

if [ $# -eq 0 ]; then
    # Interactive shell
    exec nsenter -t "$PID" -m -u -n -p -- /bin/bash -l
else
    # Run command (use bash -c to get proper PATH)
    exec nsenter -t "$PID" -m -u -n -p -- /bin/bash -lc "$*"
fi
