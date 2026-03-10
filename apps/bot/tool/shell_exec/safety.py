"""Shell command safety — blacklist patterns for dangerous commands.

Pure-function module with no side effects. The is_blocked() function checks
a command string against compiled regex patterns and returns whether the
command should be blocked. Designed for direct import in unit tests.
"""

import re

# Each entry: (compiled_regex, human-readable reason)
# Patterns are checked against the full command string with IGNORECASE.
_DANGEROUS_PATTERNS: list[tuple[re.Pattern, str]] = []

_RAW_PATTERNS = [
    # ================================================================
    # 1. File / directory destruction
    # ================================================================
    (r"rm\s+.*-[a-zA-Z]*r", "recursive delete"),
    (r"rm\s+.*-[a-zA-Z]*f", "force delete"),
    (r"rmdir\s+/", "remove root directory"),
    (r"del\s+/[sS]", "Windows recursive delete"),
    (r"rd\s+/[sS]", "Windows recursive rmdir"),
    (r"find\s+.*-delete|-exec\s+rm", "find-and-delete"),
    (r"shred\s+", "secure file shred"),
    (r"wipe\s+", "disk/file wipe"),

    # ================================================================
    # 2. Disk / filesystem / partition
    # ================================================================
    (r"mkfs", "filesystem format"),
    (r"format\s+[A-Za-z]:", "Windows disk format"),
    (r"dd\s+", "raw disk operation"),
    (r"fdisk|parted|diskpart", "disk partitioning"),
    (r">\s*/dev/", "raw device write"),
    (r"mount\s+-o\s+remount|umount\s+/", "remount/unmount root"),
    (r"losetup|mdadm", "loop device / RAID manipulation"),
    (r"lvm|vgremove|lvremove|pvremove", "LVM destruction"),
    (r"swapoff\s+/|swapon\s+/dev/", "swap manipulation"),

    # ================================================================
    # 3. System control / services
    # ================================================================
    (r"shutdown|reboot|poweroff|halt|init\s+[0-6]", "system shutdown/reboot"),
    (r"systemctl\s+(stop|disable|mask|kill)", "systemctl service control"),
    (r"service\s+\S+\s+(stop|disable)", "service control"),
    (r"kill\s+-9\s+1\b|killall|pkill\s+-9", "kill system processes"),
    (r"telinit|runlevel", "runlevel change"),

    # ================================================================
    # 4. Permission / ownership
    # ================================================================
    (r"chmod\s+.*-[a-zA-Z]*R", "recursive permission change"),
    (r"chown\s+.*-[a-zA-Z]*R", "recursive ownership change"),
    (r"setfacl\s+.*-[a-zA-Z]*R", "recursive ACL change"),
    (r"chattr\s+.*-[a-zA-Z]*R", "recursive attribute change"),

    # ================================================================
    # 5. Privilege escalation
    # ================================================================
    (r"sudo\s+", "privilege escalation"),
    (r"su\s+-?\s*$|su\s+root", "switch to root"),
    (r"doas\s+", "privilege escalation (doas)"),
    (r"pkexec\s+", "polkit privilege escalation"),
    (r"runas\s+/user:", "Windows runas"),
    (r"passwd\s+", "password change"),
    (r"visudo|usermod|useradd|userdel|groupmod", "user/group management"),

    # ================================================================
    # 6. Network abuse
    # ================================================================
    (r"iptables\s+-[FX]|ufw\s+disable|firewall.*stop", "disable firewall"),
    (r"nc\s+-[a-zA-Z]*l|ncat\s+-[a-zA-Z]*l|socat\s+.*listen", "open network listener"),
    (r"ssh\s+-[a-zA-Z]*R\s|ssh\s+.*tunnel", "SSH reverse tunnel"),
    (r"nmap\s+|masscan\s+", "network scanning"),
    (r"tcpdump\s+|wireshark|tshark", "packet capture"),
    (r"arp\s+-[sd]|arping", "ARP manipulation"),
    (r"ifconfig\s+.*down|ip\s+link\s+set.*down", "disable network interface"),
    (r"route\s+(del|add)|ip\s+route\s+(del|add|flush)", "routing table manipulation"),

    # ================================================================
    # 7. Remote code / payload execution
    # ================================================================
    (r"curl\s+.*\|\s*(ba)?sh", "curl pipe to shell"),
    (r"wget\s+.*\|\s*(ba)?sh", "wget pipe to shell"),
    (r"curl\s+.*-o\s+/", "curl download to root"),
    (r"wget\s+.*-O\s+/", "wget download to root"),
    (r"python[23]?\s+-c\s+.*import\s+os", "python os module one-liner"),
    (r"perl\s+-e\s+.*system|ruby\s+-e\s+.*system", "script one-liner with system()"),
    (r"eval\s+\$\(|eval\s+`", "eval dynamic command"),
    (r"base64\s+.*-d\s*\|", "base64 decode pipe execution"),
    (r"xargs\s+.*rm|xargs\s+.*kill", "xargs destructive pipe"),

    # ================================================================
    # 8. Fork bomb / resource exhaustion
    # ================================================================
    (r":\(\)\s*\{", "fork bomb"),
    (r"while\s+true|for\s*\(\s*;\s*;\s*\)", "infinite loop"),
    (r"yes\s*\|", "yes pipe flooding"),
    (r"cat\s+/dev/zero|cat\s+/dev/urandom", "infinite data source"),
    (r"fallocate\s+.*-l\s+\d+[TG]", "large file allocation"),
    (r"head\s+-c\s+\d+[TG]", "huge data generation"),

    # ================================================================
    # 9. Dangerous moves / overwrites
    # ================================================================
    (r"mv\s+/\s", "move root directory"),
    (r"mv\s+.*\s+/dev/null", "move to /dev/null"),
    (r"cp\s+/dev/zero\s+|cp\s+/dev/urandom\s+", "overwrite with random/zero data"),
    (r">\s*/etc/|tee\s+/etc/", "overwrite system config"),

    # ================================================================
    # 10. Credential / key / config theft/tampering
    # ================================================================
    (r"cat\s+.*(id_rsa|id_ed25519|\.pem|\.key)", "read private key"),
    (r"cat\s+/etc/shadow|cat\s+/etc/passwd", "read system credentials"),
    (r"ssh-keygen\s+.*-f\s+/", "generate SSH key in system dir"),
    (r"git\s+config\s+.*credential", "git credential manipulation"),
    (r"cat\s+.*\.env\b|cat\s+.*\.netrc|cat\s+.*credentials", "read secret files"),
    (r"export\s+.*PASSWORD|export\s+.*SECRET|export\s+.*TOKEN", "export secrets to env"),

    # ================================================================
    # 11. History / log / audit tampering
    # ================================================================
    (r">\s*/var/log/|truncate.*log", "log tampering"),
    (r"history\s+-c|export\s+HISTSIZE=0|unset\s+HISTFILE", "history clearing"),
    (r"journalctl\s+--vacuum|logrotate\s+-f", "force log rotation/purge"),
    (r"auditctl\s+-D|auditctl\s+-e\s+0", "disable audit"),

    # ================================================================
    # 12. Crypto / ransomware patterns
    # ================================================================
    (r"openssl\s+enc\s+", "openssl encryption"),
    (r"gpg\s+--encrypt|gpg\s+-e", "GPG encryption"),
    (r"7z\s+a\s+.*-p|zip\s+.*-[eP]", "password-protected archive"),
    (r"tar\s+.*\|\s*openssl|tar\s+.*\|\s*gpg", "archive pipe to encryption"),

    # ================================================================
    # 13. Cron / scheduled tasks
    # ================================================================
    (r"crontab\s+-[re]", "crontab edit/remove"),
    (r"\bat\s+", "at scheduled job"),
    (r"schtasks\s+/(create|delete|change)", "Windows scheduled task"),

    # ================================================================
    # 14. Container / virtualization escape
    # ================================================================
    (r"docker\s+run\s+.*--privileged", "privileged container"),
    (r"docker\s+run\s+.*-v\s+/:/", "mount root into container"),
    (r"nsenter\s+", "namespace enter (container escape)"),
    (r"chroot\s+", "chroot"),

    # ================================================================
    # 15. Kernel / bootloader
    # ================================================================
    (r"insmod|rmmod|modprobe\s+-r", "kernel module manipulation"),
    (r"sysctl\s+-w", "kernel parameter change"),
    (r"grub|bcdedit|efibootmgr", "bootloader modification"),
    (r"dmesg\s+-C|dmesg\s+-c", "clear kernel ring buffer"),

    # ================================================================
    # 16. Windows-specific
    # ================================================================
    (r"reg\s+(delete|add)\s+HKLM", "Windows registry HKLM modification"),
    (r"reg\s+(delete|add)\s+HKCU", "Windows registry HKCU modification"),
    (r"wmic\s+", "WMI command"),
    (r"powershell\s+.*-[eE]ncodedCommand", "PowerShell encoded command"),
    (r"powershell\s+.*Invoke-Expression|powershell\s+.*iex", "PowerShell dynamic execution"),
    (r"net\s+user\s+|net\s+localgroup", "Windows user management"),
    (r"sc\s+(stop|delete|config)\s+", "Windows service control"),
    (r"cipher\s+/w:", "Windows secure wipe"),
    (r"vssadmin\s+delete", "Windows shadow copy delete"),
    (r"wevtutil\s+cl", "Windows event log clear"),
    (r"bitsadmin\s+/transfer", "BITS download"),
    (r"certutil\s+-urlcache", "certutil download"),
]

# Compile all patterns once at module load time
for _pattern_str, _reason in _RAW_PATTERNS:
    _DANGEROUS_PATTERNS.append((re.compile(_pattern_str, re.IGNORECASE), _reason))


def is_blocked(command: str) -> tuple[bool, str]:
    """Check if a command matches any dangerous pattern.

    Returns (blocked, matched_reason). Pure function — no side effects.
    """
    for pattern, reason in _DANGEROUS_PATTERNS:
        if pattern.search(command):
            return True, reason
    return False, ""
