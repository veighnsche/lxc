#!/system/bin/sh
# ##############################################################################
# ROCKY LINUX IGNITION - FBE AWARE
# Location: /data/adb/service.d/99-rocky-boot.sh
# Permission: 0755 (chmod +x)
# ##############################################################################
#
# TEAM_022: FBE-Aware Boot Persistence for Rocky Linux container
#
# PURPOSE:
#   This Magisk service.d hook waits for Android's File-Based Encryption (FBE)
#   to be unlocked before launching the Rocky Linux container. On Pixel 6,
#   /data is encrypted until the first PIN entry, so standard init scripts
#   will fail if they fire before unlock.
#
# ARCHITECTURE:
#   1. Magisk runs this script early in boot (after data mount, before unlock)
#   2. We block in a loop until /sdcard/Android is accessible (FBE unlocked)
#   3. After unlock + grace period, we hand off to rocky-lxc.sh Boot Mode
#   4. We fork and exit immediately so Magisk service queue isn't blocked
#
# INSTALLATION (on Android host via ADB or root shell):
#   cp 99-rocky-boot.sh /data/adb/service.d/
#   chmod +x /data/adb/service.d/99-rocky-boot.sh
#   chmod +x /data/local/tmp/rocky-lxc.sh
#
# ##############################################################################

# 1. THE FBE BARRIER
# On Pixel 6, /data is encrypted until first unlock.
# We loop until the symbolic link to internal storage is active.
# This uses negligible CPU while waiting (sleep 2 between checks).
while [ ! -d "/sdcard/Android" ]; do
  sleep 2
done

# 2. THE DELAY (OPTIONAL BUT SAFE)
# Give Android networking stack 5 seconds to wake up before we contest it.
# This ensures WiFi is fully connected before rocky-lxc.sh tries to detect network.
sleep 5

# 3. THE PAYLOAD LAUNCH
# We execute rocky-lxc.sh with NO arguments to trigger the "Boot Mode" case.
# Boot Mode automatically handles:
#   - 15s settle timer
#   - Network detection
#   - Wakelocks (TEAM_021)
#   - The "Immortal Watchdog" background fork
#
# We fork (&) here so we don't block other Magisk services.
# Output redirected to /dev/null - rocky-lxc.sh has its own logging.
/data/local/tmp/rocky-lxc.sh > /dev/null 2>&1 &

exit 0
