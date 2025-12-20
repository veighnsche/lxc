# Gentoo LXC Security & Storage Assessment
## TEAM_004 - December 20, 2025

## Executive Summary

**PURPOSE:** Evaluate if current Gentoo LXC setup is suitable for storing secrets (password managers, encrypted vaults) as a portable secrets server.

---

## 🔴 CRITICAL STORAGE ISSUE

### Current Allocation
| Resource | Size | Percentage |
|----------|------|------------|
| **Total Device Storage** | ~120 GB | 100% |
| **Gentoo rootfs.img** | 32 GB | **27%** |
| **Android (remaining)** | ~88 GB | 73% |

### User Requirement
- **Gentoo should have 80%+ of storage** (Gentoo > Android)
- Current: Gentoo has only 27% - **NOT ALIGNED WITH GOALS**

### Root Cause
The rootfs image was created with a fixed 32GB size during initial deployment. This was an arbitrary choice, not aligned with the project's actual goals.

### Solution Required
1. Create a new, larger rootfs image (96GB+ recommended)
2. Or: Use a different approach - mount /data partition directly into Gentoo
3. Or: Resize existing image (complex, requires offline resize)

---

## Security Assessment for Secrets Storage

### ✅ Current Strengths

| Feature | Status | Notes |
|---------|--------|-------|
| **User Isolation** | ✅ | `vince` user with uid=1000, not root |
| **Privilege Escalation** | ✅ | `doas` configured for wheel group only |
| **SSH Access** | ✅ | Key-based authentication available |
| **Container Isolation** | ⚠️ | Host networking reduces isolation |
| **Filesystem** | ✅ | ext4 on loop device, supports encryption |

### ⚠️ Current Weaknesses

| Issue | Severity | Description |
|-------|----------|-------------|
| **SELinux Permissive** | HIGH | Shell domain is permissive for LXC to work |
| **Host Networking** | MEDIUM | Container shares Android network stack |
| **No Disk Encryption** | HIGH | rootfs.img is NOT encrypted at rest |
| **Android Root Access** | HIGH | Android root can access all container data |
| **No Secure Boot Chain** | MEDIUM | Custom kernel without verified boot |

### 🔴 Critical for Secrets Storage

#### 1. Disk Encryption Status: **NOT IMPLEMENTED**
```
Current: /data/local/tmp/gentoo-rootfs.img is UNENCRYPTED
Risk: Anyone with physical access can mount and read all data
```

#### 2. Runtime Protection: **PARTIAL**
```
- Container processes protected from Android apps: YES
- Container data protected from Android root: NO
- Container data protected if phone stolen: NO (without encryption)
```

#### 3. Network Security: **NEEDS WORK**
```
- SSH available: YES
- Firewall configured: NO
- Network isolation: NO (using host networking)
```

---

## Recommendations for Secrets Server Use Case

### Minimum Requirements for Production Secrets

1. **LUKS Encryption for rootfs**
   ```bash
   # Create encrypted container
   cryptsetup luksFormat /data/local/tmp/gentoo-rootfs.img
   cryptsetup luksOpen /data/local/tmp/gentoo-rootfs.img gentoo-crypt
   mkfs.ext4 /dev/mapper/gentoo-crypt
   ```

2. **Increase Storage to 80%+ of device**
   - Current 32GB is insufficient
   - Target: 96GB minimum

3. **Firewall Configuration**
   ```bash
   # Inside Gentoo
   emerge net-firewall/iptables
   # Only allow SSH from trusted networks
   ```

4. **Secrets Management Software**
   - Hashicorp Vault
   - Bitwarden (self-hosted)
   - pass (password-store with GPG)
   - KeePassXC

---

## Comparison: What We Have vs What We Need

| Requirement | Current | Needed | Gap |
|-------------|---------|--------|-----|
| Storage | 32GB | 96GB+ | **-64GB** |
| Encryption | None | LUKS | **MISSING** |
| Network Isolation | Host | Bridge or VPN | **PARTIAL** |
| SELinux | Permissive | Enforcing | **DEGRADED** |
| Firewall | None | iptables | **MISSING** |
| Backup Strategy | None | Encrypted backup | **MISSING** |

---

## Action Items

### Immediate (Before Storing Any Secrets)
- [ ] Resize/recreate rootfs to 96GB+
- [ ] Implement LUKS encryption
- [ ] Configure iptables firewall

### Short-term
- [ ] Install and configure secrets manager (Vault/Bitwarden/pass)
- [ ] Set up encrypted backups
- [ ] Document recovery procedures

### Long-term
- [ ] Investigate SELinux enforcing mode compatibility
- [ ] Consider hardware security module integration
- [ ] Implement network isolation via VPN

---

---

## Research: How Others Solved This Problem

### 1. LUKS2 Encrypted Containers on Android
**Source:** https://blog.ja-ke.tech/2020/04/04/android-luks2.html

Key approach:
```bash
# Create encrypted container on Android
pkg install root-repo cryptsetup tsu
truncate --size 100G secrets.img
cryptsetup luksFormat --type luks2 secrets.img
cryptsetup open secrets.img luks
mkfs.ext4 /dev/mapper/luks
```

**Applicable to our setup:** YES - We can encrypt the Gentoo rootfs.img with LUKS

### 2. Linux Deploy (meefik)
- Popular Android app for running Linux in chroot/container
- Supports large image files on /data partition
- Users commonly create 50-100GB+ images
- **Limitation:** Uses chroot, not LXC - less isolation

### 3. Lindroid / vendor_lindroid
- Full Linux container on Android
- Uses LXC like our approach
- **Key insight:** Uses host networking, focuses on integration
- Does NOT prioritize storage allocation for Linux

### 4. postmarketOS
- Replaces Android entirely with Linux
- Full disk encryption supported
- **Most secure option** but loses Android functionality
- Not applicable if you want both Android AND Linux

### 5. Self-Hosted Secrets Managers
| Solution | Complexity | Security | Notes |
|----------|------------|----------|-------|
| **pass + GPG** | Low | High | CLI-based, GPG encryption |
| **Bitwarden (vaultwarden)** | Medium | High | Self-hosted, web UI |
| **Hashicorp Vault** | High | Very High | Enterprise-grade |
| **KeePassXC** | Low | High | Local database |

**Recommendation for our use case:** `pass` with GPG or `vaultwarden`

---

## Solution: Recreate Rootfs with Proper Allocation

### Current State
```
Device: ~120 GB total
Gentoo: 32 GB (27%) ❌ NOT ALIGNED
Android: ~88 GB (73%)
```

### Target State (Gentoo > Android)
```
Device: ~120 GB total
Gentoo: 96 GB (80%) ✅ ALIGNED
Android: ~24 GB (20%)
```

### Implementation Plan

#### Step 1: Create new 96GB encrypted rootfs
```bash
# On Android device
truncate --size 96G /data/local/tmp/gentoo-rootfs-encrypted.img
cryptsetup luksFormat --type luks2 /data/local/tmp/gentoo-rootfs-encrypted.img
cryptsetup open /data/local/tmp/gentoo-rootfs-encrypted.img gentoo-crypt
mkfs.ext4 /dev/mapper/gentoo-crypt
```

#### Step 2: Migrate existing Gentoo installation
```bash
# Mount both old and new
mount /dev/mapper/gentoo-crypt /mnt/new
mount -o loop /data/local/tmp/gentoo-rootfs.img /mnt/old
rsync -aAXv /mnt/old/ /mnt/new/
```

#### Step 3: Update container config
```
lxc.rootfs.path = dir:/data/lxc/containers/gentoo/rootfs
# (mount the encrypted image before starting container)
```

---

## Conclusion

**Current setup is NOT ready for production secrets storage.**

Critical blockers:
1. **Storage too small** (32GB vs 96GB+ needed) - **FIXABLE**
2. **No disk encryption** (data at rest is exposed) - **FIXABLE with LUKS**
3. **SELinux permissive** (reduced security guarantees) - **Acceptable tradeoff**

### Path Forward
1. ✅ Create new 96GB LUKS-encrypted rootfs image
2. ✅ Migrate existing Gentoo installation
3. ✅ Install secrets manager (vaultwarden or pass)
4. ✅ Configure firewall

**After these steps, the setup WILL be suitable for production secrets storage.**

---

## Trust Alignment Check

| Goal | Current | After Fix | Aligned? |
|------|---------|-----------|----------|
| Gentoo > Android storage | 27% | 80% | ✅ YES |
| Encrypted at rest | No | LUKS2 | ✅ YES |
| Portable secrets server | Partial | Full | ✅ YES |
| Network accessible | Yes | Yes | ✅ YES |

**The 32GB allocation was an oversight, not intentional. We can fix this.**
