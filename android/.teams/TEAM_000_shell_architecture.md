# TEAM 000 — Shell Architecture & Nested Shell Solutions

**Created:** 2024-12-16
**Status:** In Progress
**Focus:** Solve adb shell su -c quoting/escaping pain

---

## Problem Statement

Three shell layers exist:
1. **Host shell** (Linux bash) — runs adb commands
2. **Android shell** (`adb shell su -c '...'`) — complex quoting, no proper PTY
3. **Alpine shell** (inside LXC container) — shell-in-shell-in-shell via lxc-attach

Current `adb_shell_su()` in `lib/common.sh`:
```bash
adb_shell_su() {
    adb_cmd shell su -c "$1"
}
```

This breaks on:
- Commands with quotes
- Commands with special characters ($, `, \, etc.)
- Multi-line commands
- Commands with spaces in arguments

---

## Research Findings

### Pattern 1: printf %q escaping
Bash's `printf %q` escapes strings for shell reuse:
```bash
cmd='echo "hello world"'
escaped=$(printf %q "$cmd")
adb shell su -c "$escaped"
```
**Pros:** Works for single commands, built into bash
**Cons:** Only works if remote shell is also bash-compatible

### Pattern 2: Heredoc via stdin
Push script content via stdin instead of command line:
```bash
adb shell su -c sh <<'EOF'
echo "no quoting issues"
complex_command --with="args"
EOF
```
**Pros:** No quoting issues, multi-line support
**Cons:** May not work with all su implementations

### Pattern 3: Push script, then execute
```bash
# Push script to temp file
adb push script.sh /data/local/tmp/script.sh
# Execute it
adb shell su -c 'sh /data/local/tmp/script.sh'
```
**Pros:** Completely avoids quoting, full script capabilities
**Cons:** Extra round-trip, temp file management

### Pattern 4: Base64 encoding
```bash
cmd='echo "complex $command"'
encoded=$(echo "$cmd" | base64)
adb shell su -c "echo $encoded | base64 -d | sh"
```
**Pros:** Works for any content
**Cons:** Requires base64 on device, overhead

### Pattern 5: Dedicated escape function
Build a proper escape function that handles all cases:
```bash
shell_escape() {
    printf '%s\n' "$1" | sed "s/'/'\\\\''/g; 1s/^/'/; \$s/\$/'/"
}
```

---

## Proposals

See PROPOSALS section below.

---

## Progress Log

- [x] Created team infrastructure
- [x] Researched nested shell best practices
- [x] Analyzed existing code patterns
- [x] Created clean.sh script for host + device cleanup
- [ ] Draft proposals
- [ ] Get user feedback
- [ ] Implement chosen solution

---
