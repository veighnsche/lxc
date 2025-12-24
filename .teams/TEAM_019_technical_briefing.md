# TEAM_019: Technical Briefing Documentation

## Task
Document the comprehensive technical briefing for Android Layer and Kernel Layer developers based on investigation findings (NAND wear risks, L2 IPVLAN instability, GS101 CPU topology).

## Context
This briefing synthesizes learnings from multiple investigation teams:
- TEAM_018: ZRAM investigation
- TEAM_011: IPVLAN persistence issues
- Previous thermal and OOM investigations

## Deliverables
1. Android Layer Developer Briefing → `/home/vince/Projects/android/lxc/.docs/ANDROID_LAYER_BRIEFING.md`
2. Kernel Layer Developer Briefing → `/home/vince/Projects/android/kernel/.plans/KERNEL_LAYER_BRIEFING.md`

## Status
- [x] Team registered
- [x] Android Layer briefing created
- [x] Kernel Layer briefing created
- [x] Handoff complete

## Key Findings Documented

### Android Layer (Userspace/HAL)
| Topic | Summary |
|-------|---------|
| Network Stability | ARP sysctl tuning, wakelock management for radio sleep |
| OOM Protection | `oom_score_adj=-900`, proper cgroup placement |
| Thermal Guard | `SIGSTOP`/`SIGCONT` at 52°C/48°C thresholds |
| Storage | tmpfs for builds, noatime mounts |

### Kernel Layer
| Topic | Summary |
|-------|---------|
| CPU Scheduler | `CONFIG_UCLAMP_TASK` for GS101 heterogeneous cores |
| tmpfs | ACL/XATTR support for Portage |
| ZRAM | Must be `=y` not `=m` in GKI defconfig |
| Network | Paranoid Network GID handling for containers |

## Handoff Notes
- Both briefing documents are standalone and actionable
- Cross-references between documents are included
- Next team implementing either layer should start with respective briefing

## Team Info
- **Team ID**: TEAM_019
- **Date**: 2025-12-21
- **Focus**: Cross-layer technical documentation
- **Status**: ✅ Complete
