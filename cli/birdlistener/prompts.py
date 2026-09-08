"""Ask-or-flag prompting.

Every question the CLI asks can be answered by a flag. Interactive terminals
get a prompt with the default shown; non-interactive runs (an agent, a
script) must supply the flag and get a precise error naming it otherwise.
"""
from __future__ import annotations

import getpass
import os
import sys
from typing import Callable, Sequence


class MissingInput(SystemExit):
    def __init__(self, flag: str, what: str):
        super().__init__(f"error: {what} is needed; pass {flag} (not running interactively)")


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty() and not os.environ.get("BIRDLISTENER_NONINTERACTIVE")


def ask(what: str, *, flag: str, value: str | None = None, default: str | None = None,
        secret: bool = False, validate: Callable[[str], str | None] | None = None) -> str:
    """Return `value` if given, else prompt (interactive) or fail naming `flag`."""
    if value not in (None, ""):
        return str(value)
    if not interactive():
        if default not in (None, ""):
            return str(default)
        raise MissingInput(flag, what)
    while True:
        suffix = f" [{default}]" if default not in (None, "") and not secret else ""
        prompt = f"{what}{suffix}: "
        raw = getpass.getpass(prompt) if secret else input(prompt)
        raw = raw.strip()
        if not raw and default not in (None, ""):
            raw = str(default)
        if not raw:
            print("  (required)")
            continue
        if validate:
            problem = validate(raw)
            if problem:
                print(f"  {problem}")
                continue
        return raw


def confirm(question: str, *, yes: bool = False, default: bool = False) -> bool:
    if yes:
        return True
    if not interactive():
        return default
    hint = "Y/n" if default else "y/N"
    raw = input(f"{question} [{hint}] ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def choose(what: str, options: Sequence[tuple[str, str]], *, flag: str, value: str | None = None) -> str:
    """options: (key, label). Returns the key."""
    keys = [k for k, _ in options]
    if value:
        if value in keys:
            return value
        raise SystemExit(f"error: {flag} must be one of {', '.join(keys)}")
    if not interactive():
        raise MissingInput(flag, what)
    print(f"{what}:")
    for i, (k, label) in enumerate(options, 1):
        print(f"  {i}) {label}")
    while True:
        raw = input(f"choice [1-{len(options)}]: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return keys[int(raw) - 1]
        if raw in keys:
            return raw


def say(msg: str = "") -> None:
    print(msg, flush=True)


def step(msg: str) -> None:
    print(f"==> {msg}", flush=True)


def human_step(msg: str, *, yes: bool = False) -> None:
    """A step only a person can do (insert a card, plug in a mic). Waits for Enter."""
    print(f"\n>>> {msg}", flush=True)
    if interactive() and not yes:
        input("    press Enter when done ")
