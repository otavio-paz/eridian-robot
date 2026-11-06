# Translator voice training dataset

This directory is for **authorized source recordings used during training**.
It is not copied to the Raspberry Pi after a voice has been exported.

## Recording target

- Prefer **1–2 hours** of clean speech for a useful fine-tune.
- Piper's current small-fine-tune guidance is based on approximately
  **0.9–4 hours** of audio. Less than 30 minutes is useful only as an early
  experiment and will commonly produce unstable pronunciation or timbre.
- Make each WAV approximately **2–8 seconds**, with **3–5 seconds** as a useful
  average. One short sentence per file is ideal. Avoid clips longer than about
  12 seconds.
- Record mono, uncompressed PCM WAV. Use the same microphone, room, distance,
  and gain throughout. A 22,050 Hz sample rate matches the supplied Piper
  training examples; 16-bit PCM is sufficient.
- Leave a short natural margin around speech, but remove long silence, music,
  effects, other speakers, reverb, clipping, and background noise.
- Include normal English plus robot vocabulary: numbers, temperatures, left,
  right, front, rear, hip, knee, connected, disconnected, warning, stop, and
  complete.

Use only a voice you own or have explicit permission to train. Do not populate
this dataset with extracted audiobook or film dialogue.

## Required layout

Put recordings in `audio/` and make a copy of `metadata.csv.example` named
`metadata.csv`:

```text
voice_training/rocky_translator/
├── audio/
│   ├── clip0001.wav
│   ├── clip0002.wav
│   └── ...
├── metadata.csv
└── README.md
```

Each metadata line is `filename|exact transcript`, with no header:

```text
clip0001.wav|Boot test complete. All servos good.
clip0002.wav|Front left knee temperature is fifty eight degrees.
```

The transcript must match what was actually spoken, including repeated words.
Do not use the `|` character inside a transcript.

Training should run on a GPU workstation, not on the Raspberry Pi. After Piper
training and ONNX export, place only the `.onnx` and matching `.onnx.json` files
in `quadruped/voices/` on the Pi.

