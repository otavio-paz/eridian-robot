"""Optional human-like translator voice using local Piper synthesis.

This module is intentionally separate from :mod:`quadruped.speech`.  The
existing eSpeak adapter remains the small, dependable fallback used by the
robot.  ``RockySpeaker`` keeps a Piper model loaded between messages so repeat
warnings do not pay the model-loading cost each time.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Callable


VOICE_DIR = Path(__file__).with_name("voices")
DEFAULT_MODEL = VOICE_DIR / "en_US-lessac-medium.onnx"
MODEL_ENVIRONMENT_VARIABLE = "ERIDIAN_ROCKY_MODEL"


class RockyVoiceError(RuntimeError):
    """Raised when the optional Piper voice cannot synthesize or play audio."""


def prepare_translator_text(message: str) -> str:
    """Normalize text without changing safety-critical meaning.

    The clipped translator character should come from how callers phrase their
    messages and from the synthesis settings.  This function deliberately does
    not paraphrase warnings, temperatures, joint names, or negation.
    """
    text = re.sub(r"\s+", " ", message).strip()
    text = re.sub(r"\s*;\s*", ". ", text)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _default_model_path() -> Path:
    configured = os.environ.get(MODEL_ENVIRONMENT_VARIABLE)
    return Path(configured).expanduser() if configured else DEFAULT_MODEL


def _load_piper_voice(model_path: Path):
    try:
        from piper import PiperVoice
    except ImportError as exc:
        raise RockyVoiceError(
            "Piper is not installed. Run: python -m pip install -r "
            "requirements-rocky.txt"
        ) from exc
    return PiperVoice.load(model_path)


def _make_synthesis_config(**settings):
    try:
        from piper.config import SynthesisConfig
    except ImportError as exc:
        raise RockyVoiceError(
            "Piper is not installed. Run: python -m pip install -r "
            "requirements-rocky.txt"
        ) from exc
    return SynthesisConfig(**settings)


class RockySpeaker:
    """Synthesize a restrained, human-like translator voice entirely locally."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        *,
        enabled: bool = True,
        length_scale: float = 0.90,
        noise_scale: float = 0.45,
        noise_w_scale: float = 0.55,
        volume: float = 0.90,
        player: str | None = None,
        voice_loader: Callable | None = None,
        synthesis_config_factory: Callable | None = None,
    ) -> None:
        self.model_path = Path(model_path) if model_path else _default_model_path()
        self.enabled = enabled
        self.length_scale = length_scale
        self.noise_scale = noise_scale
        self.noise_w_scale = noise_w_scale
        self.volume = volume
        self.player = player
        self._voice_loader = voice_loader or _load_piper_voice
        self._config_factory = synthesis_config_factory or _make_synthesis_config
        self._voice = None
        self._validate_settings()

    def _validate_settings(self) -> None:
        if not 0.5 <= self.length_scale <= 1.5:
            raise ValueError("length_scale must be in 0.5..1.5")
        if not 0 <= self.noise_scale <= 2 or not 0 <= self.noise_w_scale <= 2:
            raise ValueError("noise scales must be in 0..2")
        if not 0 < self.volume <= 2:
            raise ValueError("volume must be in 0..2")

    def _validate_model_files(self) -> None:
        config_path = Path(f"{self.model_path}.json")
        missing = [path for path in (self.model_path, config_path) if not path.is_file()]
        if missing:
            names = ", ".join(str(path) for path in missing)
            raise RockyVoiceError(
                f"Missing Piper model file(s): {names}. See quadruped/voices/README.md."
            )

    def _get_voice(self):
        if self._voice is None:
            self._validate_model_files()
            self._voice = self._voice_loader(self.model_path)
        return self._voice

    def synthesize(self, message: str, output_path: str | Path) -> Path:
        """Write one translated-voice WAV file and return its path."""
        text = prepare_translator_text(message)
        if not text:
            raise ValueError("message cannot be empty")
        voice = self._get_voice()
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        synthesis_config = self._config_factory(
            length_scale=self.length_scale,
            noise_scale=self.noise_scale,
            noise_w_scale=self.noise_w_scale,
            normalize_audio=True,
            volume=self.volume,
        )
        try:
            with wave.open(str(output), "wb") as wav_file:
                voice.synthesize_wav(
                    text,
                    wav_file,
                    syn_config=synthesis_config,
                )
        except Exception as exc:
            raise RockyVoiceError(f"Piper synthesis failed: {exc}") from exc
        return output

    def _player_command(self, wav_path: Path) -> list[str]:
        if self.player:
            return [self.player, str(wav_path)]
        if executable := shutil.which("aplay"):
            return [executable, "-q", str(wav_path)]
        if executable := shutil.which("pw-play"):
            return [executable, str(wav_path)]
        if executable := shutil.which("paplay"):
            return [executable, str(wav_path)]
        if executable := shutil.which("ffplay"):
            return [executable, "-nodisp", "-autoexit", "-loglevel", "error", str(wav_path)]
        raise RockyVoiceError("No audio player found; install alsa-utils for aplay")

    def say(self, message: str) -> None:
        """Synthesize and play a message; always mirror it to the console."""
        text = prepare_translator_text(message)
        print(f"ROCKY TRANSLATOR: {text}")
        if not self.enabled:
            return
        with tempfile.TemporaryDirectory(prefix="eridian-rocky-") as temp_dir:
            wav_path = self.synthesize(text, Path(temp_dir) / "speech.wav")
            try:
                completed = subprocess.run(
                    self._player_command(wav_path),
                    check=False,
                    timeout=60,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RockyVoiceError(f"Audio playback failed: {exc}") from exc
            if completed.returncode != 0:
                raise RockyVoiceError(
                    f"Audio player exited with status {completed.returncode}"
                )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="+", help="text to synthesize")
    parser.add_argument("--model", type=Path, default=_default_model_path())
    parser.add_argument("--output", type=Path, help="write WAV without playing it")
    parser.add_argument("--length-scale", type=float, default=0.90)
    parser.add_argument("--noise-scale", type=float, default=0.45)
    parser.add_argument("--noise-w-scale", type=float, default=0.55)
    parser.add_argument("--volume", type=float, default=0.90)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    speaker = RockySpeaker(
        args.model,
        length_scale=args.length_scale,
        noise_scale=args.noise_scale,
        noise_w_scale=args.noise_w_scale,
        volume=args.volume,
    )
    message = " ".join(args.text)
    try:
        if args.output:
            path = speaker.synthesize(message, args.output)
            print(f"Wrote {path}")
        else:
            speaker.say(message)
        return 0
    except (RockyVoiceError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

