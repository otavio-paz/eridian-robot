"""Small text-to-speech adapter for Raspberry Pi OS."""

from __future__ import annotations

import shutil
import subprocess


class Speaker:
    """Speak with espeak-ng/espeak; always mirror the message to the console."""

    def __init__(self, enabled: bool = True) -> None:
        self.executable = (
            shutil.which("espeak-ng") or shutil.which("espeak") if enabled else None
        )

    def say(self, message: str) -> None:
        print(f"SPEAKER: {message}")
        if not self.executable:
            return
        try:
            subprocess.run(
                [self.executable, "-s", "155", message],
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"WARNING: text-to-speech failed: {exc}")

