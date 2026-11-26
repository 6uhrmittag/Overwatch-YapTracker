"""The whole OCR POC pipeline in one command (#608), e.g. after a season patch changed the chat.

    python tools/ocr_train/run.py              # everything, from the app's data to rec.onnx
    python tools/ocr_train/run.py --from crops # go on at a step (they all resume by themselves)

Run it with the app's Python (.venv); the GPU steps start in the POC's own venv
(fixtures/private/ocr/venv: PyTorch + transformers, see vlm_reread.py). Every heavy step looks
for Overwatch.exe and stops with exit code 3; run again when the game is closed.
What needs a person once: the gold labels (gold_sheets.py, then gold/labels.json), which only
the scoring at the end uses.

Data recipe, in short: every stored line's picture -> the crops RapidOCR's detection cuts
(crops.py) -> silver labels where a local vision model reads what the app stored, or where two
models agree against it (labels.py; on the gold lines such a pair was right 21 times in 26, and
the two share a habit of correcting spelling, so those ~550 rows carry some wrong labels) ->
plus synthetic lines (synth.py) -> a small CRNN trained from scratch (crnn.py), checkpoint
chosen on the three newest training evenings -> scored on gold and on the #118 sets.

The environments, all under fixtures/private/ocr (uv, Python 3.12; ~14 GB together):
    venv         torch 2.15 (CUDA), torchvision, transformers>=5.0 (5.24), accelerate, pillow,
                 huggingface_hub, onnx, onnxscript
                 models, fetched on first use: zai-org/GLM-OCR, Qwen/Qwen3.5-4B
    venv-paddle  paddlepaddle-gpu==3.3.1 from https://www.paddlepaddle.org.cn/packages/stable/cu126/
                 + PaddleOCR/requirements.txt, paddle2onnx, onnx, onnxruntime
    venv-export  paddlepaddle==3.0.0 (CPU), paddle2onnx 2.1.0, onnx, setuptools,
                 PaddleOCR/requirements.txt (the converter can't read what 3.3 exports)
    PaddleOCR    git clone --depth 1 https://github.com/PaddlePaddle/PaddleOCR (2026-09-16)
    pretrained/latin_PP-OCRv5_mobile_rec_pretrained.pdparams from
                 https://paddle-model-ecology.bj.bcebos.com/paddlex/official_pretrained_model/

Not in this chain, because it needs its own two environments (venv-paddle to train, venv-export
for the ONNX conversion) and an hour: the fine-tuned Latin PP-OCRv5 recognizer, the more
accurate and slower one. After `labels-again` and `synth`:
    fixtures/private/ocr/venv-paddle/bin/python tools/ocr_train/train.py --run paddle
    python tools/ocr_train/bench.py ours=train/ours paddle=train/paddle
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402

HERE = Path(__file__).parent
STEPS = [  # (name, runs in the POC venv, script and arguments)
    ("inventory", False, ["inventory.py"]),
    ("crops", False, ["crops.py"]),
    ("reread", True, ["vlm_reread.py", "--model", "glm", "--set", "all"]),
    ("labels", False, ["labels.py"]),
    ("second-opinion", True, ["vlm_reread.py", "--model", "qwen", "--set", "all",
                              "--only", "readings/undecided.json"]),
    ("labels-again", False, ["labels.py"]),
    ("synth", False, ["synth.py"]),
    ("train", True, ["crnn.py"]),
    ("score", False, ["bench.py", "ours=train/ours"]),
    ("score-118", False, ["bench118.py", "ours=train/ours"]),
    ("cpu", False, ["cpu_split.py", "ours=train/ours"]),
]  # fmt: skip


def main() -> None:
    names = [name for name, _gpu, _command in STEPS]
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("--from", dest="start", choices=names, default=names[0])
    opts = args.parse_args()
    poc = common.private() / "venv" / "bin" / "python"
    for name, gpu, command in STEPS[names.index(opts.start) :]:
        print(f"\n== {name}", flush=True)
        if name == "train" and opts.start != "train":
            command = [*command, "--fresh"]  # new data: a new training; `--from train` resumes
        done = subprocess.run([poc if gpu else sys.executable, HERE / command[0], *command[1:]])
        if done.returncode:
            sys.exit(f"{name} stopped ({done.returncode}): `run.py --from {name}` goes on there")


if __name__ == "__main__":
    main()
