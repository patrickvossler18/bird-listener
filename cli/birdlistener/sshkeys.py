"""A dedicated SSH key for the Pis, plus ~/.ssh/config entries, so `ssh birdpi`
works for the person and for any agent helping them, with no passphrase to
type. The public half goes onto each Pi through cloud-init at flash time.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# BIRDLISTENER_SSH_DIR lets tests (and the --dry-run docs) keep out of ~/.ssh.
SSH_DIR = Path(os.environ.get("BIRDLISTENER_SSH_DIR", Path.home() / ".ssh"))
KEY_FILE = SSH_DIR / "bird-listener_ed25519"
CONFIG_FILE = SSH_DIR / "config"
MARK_BEGIN = "# >>> bird-listener (managed by `birdlistener flash`) >>>"
MARK_END = "# <<< bird-listener <<<"


def ensure_key(key_file: Path = KEY_FILE) -> str:
    """Create the key if missing; return the public key line."""
    pub = key_file.with_suffix(key_file.suffix + ".pub")
    if not key_file.exists():
        SSH_DIR.mkdir(mode=0o700, exist_ok=True)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "bird-listener",
                        "-f", str(key_file)], check=True)
    return pub.read_text().strip()


def write_config(hosts: dict[str, str], user: str, key_file: Path = KEY_FILE) -> None:
    """hosts: alias -> hostname (e.g. {'birdpi': 'birdpi.local'})."""
    block = [MARK_BEGIN]
    for alias, hostname in hosts.items():
        block += [f"Host {alias} {hostname}",
                  f"    HostName {hostname}",
                  f"    User {user}",
                  f"    IdentityFile {key_file}",
                  "    IdentitiesOnly yes",
                  "    StrictHostKeyChecking accept-new",
                  ""]
    block.append(MARK_END)
    new_block = "\n".join(block) + "\n"

    existing = CONFIG_FILE.read_text() if CONFIG_FILE.exists() else ""
    if MARK_BEGIN in existing and MARK_END in existing:
        pre, rest = existing.split(MARK_BEGIN, 1)
        _, post = rest.split(MARK_END, 1)
        content = pre + new_block.rstrip("\n") + post
    else:
        content = existing.rstrip("\n") + ("\n\n" if existing.strip() else "") + new_block
    SSH_DIR.mkdir(mode=0o700, exist_ok=True)
    CONFIG_FILE.write_text(content)
    os.chmod(CONFIG_FILE, 0o600)


def ssh(host: str, command: str, *, timeout: float = 60, tty: bool = False,
        check: bool = False) -> subprocess.CompletedProcess:
    args = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    if tty:
        args += ["-t"]
        return subprocess.run(args + [host, command], timeout=timeout, check=check)
    return subprocess.run(args + [host, command], capture_output=True, text=True,
                          timeout=timeout, check=check)
