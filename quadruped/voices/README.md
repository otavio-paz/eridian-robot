# Runtime Piper voices

This directory contains voice models used **on the Raspberry Pi**. It does not
contain training recordings.

For an immediately usable generic human voice, run from the repository root:

```bash
.venv/bin/python -m pip install -r requirements-rocky.txt
.venv/bin/python -m piper.download_voices \
  --data-dir quadruped/voices en_US-lessac-medium
```

That produces the pair expected by `quadruped.rocky_speech`:

```text
quadruped/voices/en_US-lessac-medium.onnx
quadruped/voices/en_US-lessac-medium.onnx.json
```

To deploy a custom, authorized voice, copy its exported pair here. The JSON
filename must be the ONNX filename plus `.json`, for example:

```text
quadruped/voices/en_US-eridian-translator-medium.onnx
quadruped/voices/en_US-eridian-translator-medium.onnx.json
```

Select it with `--model` or set `ERIDIAN_ROCKY_MODEL` to its `.onnx` path.
Model binaries are intentionally excluded from Git.

