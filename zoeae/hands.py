"""
Hands — Tool use / action organ. Pereiopods.

The organism acts on the world. Every action passes through
the exoskeleton first — dangerous commands are blocked before
they can execute. The hands are constrained by chitin.

    hands = Hands(exo=exoskeleton)
    result = hands.reach("ls -la")       # run a shell command
    code   = hands.grasp("main.py")      # read a file
    hands.place("out.txt", "hello")      # write a file
    html   = hands.fetch("https://...")   # HTTP GET

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import os
import re
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .exoskeleton import Exoskeleton, ThreatClass


# ── DENY / ALLOW PATTERNS ──

_DEFAULT_DENY = [
    re.compile(r'(?i)\brm\s+-rf\s+/\s*$'),             # rm -rf /
    re.compile(r'(?i)\brm\s+-rf\s+/\s+'),              # rm -rf / <anything>
    re.compile(r'(?i)\brm\s+--no-preserve-root'),       # explicit root delete
    re.compile(r'(?i)\bformat\s+[a-zA-Z]:'),            # format C:
    re.compile(r'(?i)\bdel\s+/s'),                      # del /s (Windows recursive)
    re.compile(r'(?i)\bshutdown\b'),                    # shutdown
    re.compile(r'(?i)\breboot\b'),                      # reboot
    re.compile(r'(?i)\bhalt\b'),                        # halt
    re.compile(r'(?i)\binit\s+0'),                      # init 0
    re.compile(r'(?i)\bmkfs\b'),                        # mkfs
    re.compile(r'(?i)\bdd\s+.*\bof=/dev/'),             # dd to raw device
    re.compile(r'(?i)\bsudo\s+rm\b'),                   # sudo rm (any variant)
    re.compile(r'(?i)\bsudo\s+dd\b'),                   # sudo dd
    re.compile(r'(?i)\bsudo\s+mkfs\b'),                 # sudo mkfs
    re.compile(r'(?i)\bsudo\s+shutdown\b'),             # sudo shutdown
    re.compile(r'(?i)\bsudo\s+reboot\b'),               # sudo reboot
    re.compile(r'(?i)\bsudo\s+halt\b'),                 # sudo halt
    re.compile(r'(?i):(){ :\|:& };:'),                  # fork bomb
    re.compile(r'(?i)\b>\s*/dev/sd[a-z]'),              # write to raw disk
    re.compile(r'(?i)\bchmod\s+-R\s+777\s+/\s*$'),      # chmod 777 /
]


# ── ACTION RESULT ──

@dataclass
class ActionResult:
    """The outcome of any action the hands take."""
    command: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_s: float = 0.0
    safe: bool = True
    blocked_reason: str = ""

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and self.safe

    @property
    def summary(self) -> str:
        if not self.safe:
            return f"[BLOCKED] {self.blocked_reason}"
        status = "OK" if self.exit_code == 0 else f"EXIT {self.exit_code}"
        lines = self.stdout.strip().split("\n")
        preview = lines[0][:120] if lines and lines[0] else ""
        return f"[{status}] {preview}"


# ── HANDS ──

class Hands:
    """The tool-use organ. Pereiopods.

    Every action passes through the exoskeleton. Dangerous commands
    are blocked before execution. Subprocess calls have timeouts.
    File I/O is bounded. HTTP requests are scrubbed.
    """

    def __init__(self, exoskeleton: Optional[Exoskeleton] = None,
                 timeout_s: float = 30.0,
                 deny_patterns: Optional[list] = None,
                 allow_patterns: Optional[list] = None,
                 max_file_bytes: int = 50_000_000) -> None:
        self.exo = exoskeleton or Exoskeleton()
        self.timeout_s = timeout_s
        self.max_file_bytes = max_file_bytes
        self._deny = deny_patterns if deny_patterns is not None else list(_DEFAULT_DENY)
        self._allow: list[re.Pattern] = allow_patterns or []
        self._history: list[ActionResult] = []

    # ── shell execution ──

    def reach(self, command: str, timeout: Optional[float] = None,
              cwd: Optional[str] = None, env: Optional[dict] = None) -> ActionResult:
        """Run a shell command. Returns stdout, stderr, exit code.

        The command is inspected by the exoskeleton AND checked against
        the deny list before execution. Blocked commands never reach
        the shell.
        """
        t0 = time.time()

        # Check deny list first
        blocked = self._check_denied(command)
        if blocked:
            result = ActionResult(
                command=command,
                exit_code=-1,
                duration_s=time.time() - t0,
                safe=False,
                blocked_reason=blocked,
            )
            self._history.append(result)
            self.exo.record("reach_blocked", source="hands",
                            metadata={"command": command[:200], "reason": blocked})
            return result

        # Exoskeleton inspection
        inspection = self.exo.inspect(command)
        if inspection.compromised:
            threats = ", ".join(t.name for t in inspection.threats)
            result = ActionResult(
                command=command,
                exit_code=-1,
                duration_s=time.time() - t0,
                safe=False,
                blocked_reason=f"Exoskeleton blocked: {threats}",
            )
            self._history.append(result)
            return result

        # Execute
        effective_timeout = timeout if timeout is not None else self.timeout_s
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                cwd=cwd,
                env=env,
            )
            # Scrub output through exoskeleton
            stdout = self.exo.scrub(proc.stdout)
            stderr = self.exo.scrub(proc.stderr)
            result = ActionResult(
                command=command,
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode,
                duration_s=time.time() - t0,
                safe=True,
            )
        except subprocess.TimeoutExpired:
            result = ActionResult(
                command=command,
                stderr=f"Timeout after {effective_timeout}s",
                exit_code=-2,
                duration_s=time.time() - t0,
                safe=True,
                blocked_reason=f"Timeout ({effective_timeout}s)",
            )
        except Exception as e:
            result = ActionResult(
                command=command,
                stderr=str(e),
                exit_code=-3,
                duration_s=time.time() - t0,
                safe=True,
                blocked_reason=f"Error: {e}",
            )

        self._history.append(result)
        self.exo.record("reach", source="hands",
                        metadata={"command": command[:200],
                                  "exit_code": result.exit_code})
        return result

    # ── file read ──

    def grasp(self, path: str) -> str:
        """Read a file and return its contents.

        Path is validated. Exoskeleton scrubs secrets from output.
        Files larger than max_file_bytes are rejected.
        """
        p = Path(path).resolve()

        if not p.exists():
            raise FileNotFoundError(f"Cannot grasp: {p} does not exist")
        if not p.is_file():
            raise IsADirectoryError(f"Cannot grasp: {p} is not a file")
        if p.stat().st_size > self.max_file_bytes:
            raise ValueError(
                f"Cannot grasp: {p} is {p.stat().st_size} bytes "
                f"(limit {self.max_file_bytes})"
            )

        content = p.read_text(encoding="utf-8", errors="replace")
        scrubbed = self.exo.scrub(content)

        self.exo.record("grasp", source="hands",
                        metadata={"path": str(p), "size": len(content)})
        return scrubbed

    # ── file write ──

    def place(self, path: str, content: str) -> None:
        """Write content to a file.

        The content is inspected by the exoskeleton before writing.
        Parent directories are created if they don't exist.
        """
        # Inspect content
        inspection = self.exo.inspect(content)
        if inspection.compromised:
            threats = ", ".join(t.name for t in inspection.threats)
            raise PermissionError(
                f"Exoskeleton blocked write to {path}: {threats}"
            )

        p = Path(path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

        self.exo.record("place", source="hands",
                        metadata={"path": str(p), "size": len(content)})

    # ── HTTP GET ──

    def fetch(self, url: str, timeout: Optional[float] = None,
              headers: Optional[dict] = None) -> str:
        """HTTP GET. Return the response body as text.

        URL is inspected. Response is scrubbed. Timeout enforced.
        """
        # Inspect the URL
        inspection = self.exo.inspect(url)
        if inspection.compromised:
            threats = ", ".join(t.name for t in inspection.threats)
            raise PermissionError(f"Exoskeleton blocked fetch of {url}: {threats}")

        effective_timeout = timeout if timeout is not None else self.timeout_s
        req_headers = {"User-Agent": "Zoeae/0.5.0"}
        if headers:
            req_headers.update(headers)

        req = urllib.request.Request(url, headers=req_headers)

        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            self.exo.record("fetch_error", source="hands",
                            metadata={"url": url[:200], "error": str(e)})
            raise

        # Scrub the response
        body = self.exo.scrub(body)

        self.exo.record("fetch", source="hands",
                        metadata={"url": url[:200],
                                  "size": len(body),
                                  "duration_s": time.time() - t0})
        return body

    # ── deny list management ──

    def add_deny(self, pattern: str) -> None:
        """Add a regex pattern to the deny list."""
        self._deny.append(re.compile(pattern))

    def add_allow(self, pattern: str) -> None:
        """Add a regex pattern to the allow list.
        Allow patterns override deny patterns for specific commands."""
        self._allow.append(re.compile(pattern))

    def _check_denied(self, command: str) -> str:
        """Check if a command matches any deny pattern.
        Returns the reason string if denied, empty string if allowed.
        Allow patterns can override deny patterns.
        """
        # Check allow list first — explicit overrides
        for pat in self._allow:
            if pat.search(command):
                return ""

        # Check deny list
        for pat in self._deny:
            if pat.search(command):
                return f"Denied by pattern: {pat.pattern}"

        return ""

    # ── introspection ──

    @property
    def history(self) -> list[ActionResult]:
        return list(self._history)

    @property
    def last_result(self) -> Optional[ActionResult]:
        return self._history[-1] if self._history else None

    @property
    def stats(self) -> dict:
        total = len(self._history)
        blocked = sum(1 for r in self._history if not r.safe)
        failed = sum(1 for r in self._history
                     if r.safe and r.exit_code != 0)
        return {
            "total_actions": total,
            "blocked": blocked,
            "failed": failed,
            "succeeded": total - blocked - failed,
            "avg_duration_s": (
                sum(r.duration_s for r in self._history) / total
                if total else 0.0
            ),
            "deny_patterns": len(self._deny),
            "allow_patterns": len(self._allow),
        }
