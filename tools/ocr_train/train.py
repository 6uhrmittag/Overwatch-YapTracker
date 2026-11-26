"""Phase 2 of the OCR POC (#608): fine-tune the Latin PP-OCRv5 recognizer and export it to ONNX.

    fixtures/private/ocr/venv-paddle/bin/python tools/ocr_train/train.py            # train
    fixtures/private/ocr/venv-paddle/bin/python tools/ocr_train/train.py --export   # ONNX only

Recognition only, detection stays. Starts from PaddleOCR's pretrained Latin mobile recognizer
(the family of the app's LATIN_REC) and trains on the silver line crops (labels.jsonl) plus the
synthetic ones (synth.jsonl); the dev crops choose the checkpoint, gold is never looked at.
Looks for Overwatch.exe every CHECK_S seconds: when the game is there the training is stopped,
and the next run goes on from the last saved epoch. The result is train/<run>/rec.onnx plus
dict.txt, which RapidOCR loads through rec_model_path / rec_keys_path.

What differs from PaddleOCR's own recipe, because chat lines are long: texts up to MAX_TEXT
characters (theirs: 25); pictures up to WIDTH px wide at 48 px height (theirs: 320, which
squeezes a whole chat row to a third); batches of crops of similar width (`ds_width`), so a
batch is as wide as its crops; one picture height (48 px) and the backbone patched to pool in
training as it does in evaluation (see patch(), #623). RecConAug (gluing crops) is off.
"""

import argparse
import atexit
import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402

CONFIG = "configs/rec/PP-OCRv5/multi_language/latin_PP-OCRv5_mobile_rec.yml"
PRETRAINED = "pretrained/latin_PP-OCRv5_mobile_rec_pretrained"
DICT = "ppocr/utils/dict/ppocrv5_latin_dict.txt"
MAX_TEXT = 80
WIDTH = 960
BATCH = 16
EPOCHS = 10  # ~6 min each on a 4090; dev stops improving after 5
LEARNING_RATE = 1e-4  # a fine-tune: a fifth of the from-scratch rate
CHECK_S = 30


def lists(private: Path, run: Path) -> tuple[int, int]:
    """Paddle's label lists (picture<TAB>text) from our jsonl files; what can't be learned
    (a character outside the dictionary, an over-long text) is left out and counted."""
    known = set((private / "PaddleOCR" / DICT).read_text(encoding="utf-8").split("\n")) | {" "}
    rows = []
    for name in ("labels.jsonl", "synth.jsonl"):
        with (private / name).open(encoding="utf-8") as f:
            rows += [json.loads(line) for line in f]
    out, skipped = {"train": [], "dev": []}, 0
    for r in rows:
        if r["split"] not in out:
            continue
        if not r["text"] or len(r["text"]) > MAX_TEXT or not set(r["text"]) <= known:
            skipped += 1
            continue
        width, height = Image.open(private / r["crop"]).size  # for the width-sorted batches
        out[r["split"]].append(f"{r['crop']}\t{r['text']}\t{width}\t{height}\n")
    if not out["dev"]:  # the dev evenings aren't re-read yet: a first try on a slice of train
        out["dev"], out["train"] = (
            out["train"][::20],
            [line for i, line in enumerate(out["train"]) if i % 20],
        )
        print("no dev crops yet: every 20th train crop stands in")
    (run / "train.txt").write_text("".join(out["train"]), encoding="utf-8")
    dev = ["\t".join(line.split("\t")[:2]) + "\n" for line in out["dev"]]  # no sizes there
    (run / "dev.txt").write_text("".join(dev), encoding="utf-8")
    print(f"train {len(out['train'])} crops, dev {len(out['dev'])}, left out {skipped}")
    return len(out["train"]), len(out["dev"])


POOLING = "ppocr/modeling/backbones/rec_lcnetv3.py"
FIXED_STEPS = "x = F.adaptive_avg_pool2d(x, [1, 40])"
AS_EVALUATED = "x = F.avg_pool2d(x, [3, 2])  # YapTracker #623: as in evaluation"


def patch(private: Path) -> None:
    """PaddleOCR's backbone pools every training picture to 40 time steps, whatever its width;
    evaluation keeps one step per 8 px. Fine at their 320 px, fatal for a chat row (#623: 40
    steps can't spell 80 characters, the pretrained model unlearned everything in one epoch).
    Train as it evaluates; that needs 48 px height, so the sampler gets one height only."""
    path = private / "PaddleOCR" / POOLING
    text = path.read_text(encoding="utf-8")
    if FIXED_STEPS in text:
        path.write_text(text.replace(FIXED_STEPS, AS_EVALUATED), encoding="utf-8")
    elif AS_EVALUATED not in text:
        sys.exit(f"{POOLING} changed: the training-mode pooling isn't where it was (#623)")


def config(private: Path, run: Path, epochs: int, steps_per_epoch: int) -> Path:
    with (private / "PaddleOCR" / CONFIG).open(encoding="utf-8") as f:
        c = yaml.safe_load(f)
    g = c["Global"]
    g.update(epoch_num=epochs, save_model_dir=str(run), save_epoch_step=1000, distributed=False,
             pretrained_model=str(private / PRETRAINED), print_batch_step=20,
             eval_batch_step=[0, steps_per_epoch], character_dict_path=DICT,
             d2s_train_image_shape=[3, 48, WIDTH])  # fmt: skip
    c["Optimizer"]["lr"].update(learning_rate=LEARNING_RATE, warmup_epoch=1)
    c["Architecture"]["Head"]["head_list"][1]["NRTRHead"]["max_text_length"] = MAX_TEXT
    train, dev = c["Train"], c["Eval"]
    train["dataset"].update(data_dir=str(private), label_file_list=[str(run / "train.txt")])
    dev["dataset"].update(data_dir=str(private), label_file_list=[str(run / "dev.txt")])
    train["dataset"]["transforms"] = [
        step for step in train["dataset"]["transforms"] if "RecConAug" not in step
    ]
    train["dataset"].pop("ext_op_transform_idx", None)
    train["dataset"]["ds_width"] = True
    for step in train["dataset"]["transforms"] + dev["dataset"]["transforms"]:
        for name, options in step.items():
            if options and "max_text_length" in options and name != "KeepKeys":
                options["max_text_length"] = MAX_TEXT
            if name == "RecResizeImg":
                options["image_shape"] = [3, 48, WIDTH]
    train["sampler"].update(scales=[[320, 48]], first_bs=BATCH, max_w=WIDTH)
    train["loader"].update(batch_size_per_card=BATCH, num_workers=4)
    dev["loader"].update(num_workers=2)
    path = run / "config.yml"
    path.write_text(yaml.safe_dump(c, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def train(private: Path, run: Path, cfg: Path) -> None:
    command = [sys.executable, "tools/train.py", "-c", str(cfg)]
    if (run / "latest.pdparams").exists():  # stopped for a game before: go on from there
        command += ["-o", f"Global.checkpoints={run / 'latest'}"]
    with (run / "train.log").open("a", encoding="utf-8") as log:
        # Its own process group: stopping this wrapper must stop the training and its loader
        # workers too. A trial once lived on for an hour and shared the GPU with every later run.
        job = subprocess.Popen(command, cwd=private / "PaddleOCR", stdout=log,
                               stderr=subprocess.STDOUT, start_new_session=True)  # fmt: skip

        def stop(*_signal) -> None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(job.pid, signal.SIGTERM)

        atexit.register(stop)
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
        while job.poll() is None:
            time.sleep(CHECK_S)
            if job.poll() is None and common.game_running():
                stop()
                job.wait()
                print("Overwatch is running: training stopped, run again to go on")
                sys.exit(common.GAME_EXIT)
    if job.returncode:
        sys.exit(f"training failed ({job.returncode}): see {run / 'train.log'}")


def export(private: Path, run: Path, cfg: Path) -> None:
    """Best dev checkpoint -> Paddle inference model -> ONNX. In the export venv: the converter
    doesn't know the operators PaddlePaddle 3.3 writes (linear_v2, shape64), 3.0 writes old ones."""
    python = private / "venv-export" / "bin" / "python"
    out = run / "inference"
    shutil.rmtree(out, ignore_errors=True)
    steps = (
        ([python, "tools/export_model.py", "-c", str(cfg), "-o", "Global.use_gpu=false",
          f"Global.pretrained_model={run / 'best_accuracy'}", f"Global.save_inference_dir={out}"],
         private / "PaddleOCR"),
        ([private / "venv-export" / "bin" / "paddle2onnx", "--model_dir", out,
          "--model_filename", "inference.json", "--params_filename", "inference.pdiparams",
          "--save_file", run / "rec.onnx", "--opset_version", "14"], None),
    )  # fmt: skip
    for command, cwd in steps:
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        if done.returncode:
            sys.exit(f"export failed:\n{done.stdout[-2000:]}\n{done.stderr[-2000:]}")
    # 57 MB: PaddlePaddle 3.0's export keeps the training-only head in the file (3.3's is 8 MB
    # but can't be converted). Removing unused weights by name didn't shrink it; slimming the
    # graph properly is for the ship issue (#624).
    shutil.copy(private / "PaddleOCR" / DICT, run / "dict.txt")
    print(f"{run / 'rec.onnx'}: {(run / 'rec.onnx').stat().st_size / 1e6:.1f} MB")


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("--run", default="run1", help="folder under fixtures/private/ocr/train")
    args.add_argument("--epochs", type=int, default=EPOCHS)
    args.add_argument("--export", action="store_true", help="only export the best checkpoint")
    opts = args.parse_args()
    private = common.private()
    run = private / "train" / opts.run
    run.mkdir(parents=True, exist_ok=True)
    common.no_game()
    patch(private)
    n_train, _ = lists(private, run)
    cfg = config(private, run, opts.epochs, max(1, n_train // BATCH))
    if not opts.export:
        train(private, run, cfg)
    export(private, run, cfg)


if __name__ == "__main__":
    main()
