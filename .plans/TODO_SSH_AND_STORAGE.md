# TODO: SSH Working + 100GB Storage + SELinux Enforcing

## Priority Order
1. **SSH working from external network**
2. **100GB storage for Gentoo**
3. **SELinux enforcing (not permissive)**

---

## 1. SSH Working (External Network Access)

### Current Status
- Container running with host networking
- SSH listening on port 22
- **Last test:** `ssh vince@192.168.178.130` worked

### Action Items
- [ ] Verify container is running after reboot
- [ ] Verify SSH service is started
- [ ] Test SSH from external network
- [ ] Document the working command

---

## 2. 100GB Storage for Gentoo

### Current Status
- rootfs.img: 32GB (only 27% of device)
- Device has ~120GB total, 107GB free on /data

### Action Items
- [ ] Stop container
- [ ] Create new 100GB rootfs image
- [ ] Copy existing Gentoo installation to new image
- [ ] Update container config
- [ ] Verify new storage size

### Commands
```bash
# Create new 100GB image
truncate --size 100G /data/local/tmp/gentoo-rootfs-100g.img
mkfs.ext4 /data/local/tmp/gentoo-rootfs-100g.img

# Mount both and copy
mount -o loop /data/local/tmp/gentoo-rootfs.img /mnt/old
mount -o loop /data/local/tmp/gentoo-rootfs-100g.img /mnt/new
cp -a /mnt/old/* /mnt/new/

# Replace old with new
mv /data/local/tmp/gentoo-rootfs.img /data/local/tmp/gentoo-rootfs-32g.img.bak
mv /data/local/tmp/gentoo-rootfs-100g.img /data/local/tmp/gentoo-rootfs.img
```

---

## 3. SELinux Enforcing Mode (Research Findings)

### Research Summary

**Key Finding:** Android has `neverallow` rules that block LXC operations in enforcing mode.

From Linux Containers Forum (https://discuss.linuxcontainers.org/t/lxc-containers-on-android-and-se-linux-issues/15391):

> "The container fails to start due to neverallow rules for the domain. The issue starts with permission denied for auto mounts of proc and sys."

The blocking rules in Android's SELinux:
```
# public/domain.te
neverallow { domain -init } proc:{ file dir } mounton;

# private/domain.te  
neverallow { domain -apexd -init -kernel -recovery -vold -zygote } 
    { fs_type -sdcard_type }:filesystem { mount remount relabelfrom relabelto };
```

### Solutions Found Online

| Solution | Feasibility | Notes |
|----------|-------------|-------|
| **Permissive domain** | ✅ Works | What we have now, what Lindroid uses |
| **Run from init domain** | ⚠️ Requires AOSP build | Start LXC via init.rc service |
| **Modify neverallow rules** | ⚠️ Requires AOSP rebuild | Remove/modify the blocking rules |
| **Use init_daemon_domain()** | ⚠️ Complex | Make LXC a proper Android service |

### Lindroid's Approach
From the Lindroid guide:
> "Ensure SELinux is set to permissive mode for Lindroid"

**Lindroid also uses permissive mode.** They haven't solved this either.

### The Real Solution: Init Domain

The ONLY way to run LXC with SELinux enforcing without modifying AOSP:
1. Create an init.rc service that starts LXC
2. The service runs in init domain which IS allowed to mount proc/sysfs
3. This requires an AOSP build to add the init.rc file

### Alternative: Targeted Permissive

Instead of making shell fully permissive, we can:
1. Create a dedicated `lxc_t` domain
2. Make ONLY `lxc_t` permissive (not shell)
3. This limits the security exposure

**Current Magisk rule:**
```
permissive shell  # TOO BROAD
```

**Better approach:**
```
type lxc_t domain
permissive lxc_t  # ONLY LXC is permissive
# Shell remains enforcing
```

### Action Items for SELinux
- [ ] Remove `permissive shell` from Magisk module
- [ ] Add `permissive lxc_t` instead (targeted permissive)
- [ ] Test if LXC still works with only lxc_t permissive
- [ ] If not, investigate init.rc approach for AOSP build

---

## Next Steps

1. First: Verify SSH is working now
2. Second: Create 100GB rootfs
3. Third: Fix SELinux to use targeted permissive (lxc_t only)
