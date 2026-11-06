from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quadruped.rocky_speech import RockySpeaker, RockyVoiceError, prepare_translator_text


class FakeVoice:
    def __init__(self) -> None:
        self.calls = []

    def synthesize_wav(self, text, wav_file, syn_config=None) -> None:
        self.calls.append((text, syn_config))
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 16)


class RockySpeechTests(unittest.TestCase):
    def test_text_normalization_preserves_content(self) -> None:
        self.assertEqual(
            prepare_translator_text("  Servo  hot ; stop now  "),
            "Servo hot. stop now.",
        )

    def test_missing_model_has_actionable_error(self) -> None:
        speaker = RockySpeaker("missing.onnx")
        with self.assertRaisesRegex(RockyVoiceError, "Missing Piper model"):
            speaker.synthesize("Test", "unused.wav")

    def test_synthesis_uses_cached_voice_and_writes_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "voice.onnx"
            model.write_bytes(b"model-placeholder")
            Path(f"{model}.json").write_text("{}", encoding="utf-8")
            fake_voice = FakeVoice()
            loads = []

            def load_voice(path):
                loads.append(path)
                return fake_voice

            speaker = RockySpeaker(
                model,
                voice_loader=load_voice,
                synthesis_config_factory=lambda **values: values,
            )
            first = speaker.synthesize("First message", root / "first.wav")
            second = speaker.synthesize("Second message", root / "second.wav")

            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())
            self.assertEqual(loads, [model])
            self.assertEqual(fake_voice.calls[0][0], "First message.")
            self.assertEqual(fake_voice.calls[0][1]["length_scale"], 0.90)


if __name__ == "__main__":
    unittest.main()

