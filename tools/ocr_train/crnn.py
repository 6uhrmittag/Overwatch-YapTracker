"""Phase 2 fallback of the OCR POC (#608): a small recognizer of our own, trained from scratch.

    fixtures/private/ocr/venv/bin/python tools/ocr_train/crnn.py                # train + export
    fixtures/private/ocr/venv/bin/python tools/ocr_train/crnn.py --export-only  # ONNX, untrained
                                                                               # or from the best

A CRNN in PyTorch with CTC: a few convolutions (48 px high, one time step per 4 px of width, in
training and in the export alike), one bidirectional GRU, softmax. It speaks RapidOCR's
recognizer dialect, so it drops in through rec_model_path / rec_keys_path with no decoder of
our own: BGR picture scaled to 48 px height, (x / 255 - 0.5) / 0.5, output [batch, steps,
classes] of probabilities, classes = blank, the lines of dict.txt, space.

Trains on labels.jsonl (silver crops) and synth.jsonl; the dev crops choose the checkpoint,
gold is never looked at. Looks for Overwatch.exe after every epoch and stops; the next run
goes on from the last epoch. Result: train/<run>/rec.onnx + dict.txt.
"""

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageFilter
from torch import nn

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402

HEIGHT = 48
MAX_WIDTH = 1280  # at 48 px height; a whole 4K chat row is ~1000
MIN_WIDTH = 320  # RapidOCR pads every crop to at least this
STRIDE = 4  # px of width per time step: narrow letters ("ll") need two steps each under CTC
EPOCHS = 40
BATCH = 64
BASE = (
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~äöüßÄÖÜ°´éèëàáâêîôûñçåÅøØ"
)


class Recognizer(nn.Module):
    def __init__(self, classes: int, width: int = 96) -> None:
        super().__init__()

        def block(cin: int, cout: int, stride: tuple[int, int]) -> nn.Sequential:
            return nn.Sequential(nn.Conv2d(cin, cout, 3, stride, 1, bias=False),
                                 nn.BatchNorm2d(cout), nn.Hardswish())  # fmt: skip

        w = width
        self.features = nn.Sequential(
            block(3, w // 4, (2, 2)),        # 24 high, width / 2
            block(w // 4, w // 2, (2, 2)),   # 12 high, width / 4
            block(w // 2, w, (2, 1)),        # 6 high
            block(w, w, (1, 1)),
            block(w, w * 2, (2, 1)),         # 3 high
            block(w * 2, w * 2, (1, 1)),
            nn.Conv2d(w * 2, w * 2, (3, 1), bias=False), nn.BatchNorm2d(w * 2), nn.Hardswish(),
        )  # fmt: skip
        self.context = nn.GRU(w * 2, w, batch_first=True, bidirectional=True)
        self.head = nn.Linear(w * 2, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.features(x).squeeze(2).transpose(1, 2)  # [batch, steps, channels]
        return self.head(self.context(x)[0])


class Export(nn.Module):
    """What RapidOCR's decoder expects: probabilities, not logits (it keeps the confidence)."""

    def __init__(self, model: Recognizer) -> None:
        super().__init__()
        self.model = model

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.model(x).softmax(-1)


def load(private: Path) -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = {"train": [], "dev": []}
    for name in ("labels.jsonl", "synth.jsonl"):
        with (private / name).open(encoding="utf-8") as f:
            for r in map(json.loads, f):
                if r["split"] in out and r["text"]:
                    out[r["split"]].append((r["crop"], r["text"]))
    return out


def picture(path: Path, rng: random.Random | None) -> np.ndarray:
    """One crop as RapidOCR feeds it; with rng, lightly disturbed (training)."""
    image = Image.open(path).convert("RGB")
    if rng:
        w, h = image.size
        dx, dy = rng.randint(0, 3), rng.randint(0, 3)  # detection boxes sit a little differently
        image = image.crop((dx, dy, w - rng.randint(0, 3), h - rng.randint(0, 3)))
        if rng.random() < 0.45:  # the same row as a 1440p screen shows it: 2/3 the size, and
            # then enlarged 2x by the app before detection (4K rows are enlarged 4/3)
            small = image.resize((max(8, round(image.width / 2)), max(8, round(image.height / 2))),
                                 Image.BILINEAR)  # fmt: skip
            image = small.resize((small.width * 2, small.height * 2), Image.BICUBIC)
        if rng.random() < 0.2:
            image = image.filter(ImageFilter.GaussianBlur(rng.uniform(0.2, 1.0)))
    width = min(MAX_WIDTH, max(STRIDE * 4, round(image.width * HEIGHT / image.height)))
    if rng:
        width = min(MAX_WIDTH, max(STRIDE * 4, round(width * rng.uniform(0.9, 1.1))))
    array = np.asarray(image.resize((width, HEIGHT), Image.BILINEAR), dtype=np.float32)
    array = array[:, :, ::-1]  # BGR, as cv2 reads it for RapidOCR
    if rng:
        array = array * rng.uniform(0.75, 1.2) + rng.uniform(-20, 20)
        if rng.random() < 0.3:
            noise = np.random.default_rng(rng.getrandbits(32))
            array = array + noise.normal(0, rng.uniform(2, 10), array.shape)
        array = array.clip(0, 255)
    return ((array / 255 - 0.5) / 0.5).transpose(2, 0, 1).astype(np.float32)


def batches(rows: list[tuple[str, str]], rng: random.Random | None) -> list[list[tuple[str, str]]]:
    """Crops of similar text length together, so a batch isn't mostly padding."""
    rows = sorted(rows, key=lambda r: len(r[1]) + (rng.random() * 6 if rng else 0))
    out = [rows[i : i + BATCH] for i in range(0, len(rows), BATCH)]
    if rng:
        rng.shuffle(out)
    return out


def tensors(private: Path, batch: list[tuple[str, str]], rng: random.Random | None):
    pictures = [picture(private / crop, rng) for crop, _text in batch]
    width = -(-max(MIN_WIDTH, *(p.shape[2] for p in pictures)) // STRIDE) * STRIDE
    x = np.zeros((len(batch), 3, HEIGHT, width), dtype=np.float32)
    for i, p in enumerate(pictures):
        x[i, :, :, : p.shape[2]] = p
    return torch.from_numpy(x), [p.shape[2] // STRIDE for p in pictures]


def decode(logits: torch.Tensor, chars: list[str]) -> list[str]:
    out = []
    for row in logits.argmax(-1).tolist():
        text, last = [], 0
        for k in row:
            if k and k != last:
                text.append(chars[k])
            last = k
        out.append("".join(text))
    return out


@torch.inference_mode()
def exact(model: Recognizer, private: Path, rows: list[tuple[str, str]], chars: list[str]) -> float:
    model.eval()
    right = 0
    for batch in batches(rows, None):
        x, _steps = tensors(private, batch, None)
        got = decode(model(x.cuda()), chars)
        right += sum(g == text for g, (_crop, text) in zip(got, batch, strict=True))
    return right / max(len(rows), 1)


def export(model: Recognizer, run: Path) -> None:
    model = Export(model).cpu().eval()
    torch.onnx.export(
        model, torch.zeros(1, 3, HEIGHT, 320), str(run / "rec.onnx"), dynamo=False,
        input_names=["x"], output_names=["probabilities"], opset_version=14,
        dynamic_axes={"x": {0: "batch", 3: "width"}, "probabilities": {0: "batch", 1: "steps"}},
    )  # fmt: skip
    print(f"{run / 'rec.onnx'}: {(run / 'rec.onnx').stat().st_size / 1e6:.1f} MB")


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("--run", default="ours", help="folder under fixtures/private/ocr/train")
    args.add_argument("--epochs", type=int, default=EPOCHS)
    args.add_argument("--width", type=int, default=96, help="channels: the size/speed knob")
    args.add_argument("--export-only", action="store_true")
    args.add_argument("--fresh", action="store_true", help="forget an earlier run in this folder")
    opts = args.parse_args()
    private = common.private()
    run = private / "train" / opts.run
    run.mkdir(parents=True, exist_ok=True)
    data = load(private)
    if not data["dev"]:  # no agreed labels on the newest evenings: a slice of train stands in
        data["dev"], data["train"] = (
            data["train"][::20],
            [row for i, row in enumerate(data["train"]) if i % 20],
        )
    state, kept = run / "last.pt", run / "dict.txt"
    if opts.fresh:
        for old in (state, kept, run / "best.pt"):
            old.unlink(missing_ok=True)
    if kept.exists():  # the alphabet belongs to the weights: a resume or export never rebuilds it
        alphabet = kept.read_text(encoding="utf-8").split("\n")
    else:
        seen = {c for _crop, text in data["train"] for c in text} - {" "}
        alphabet = list(BASE) + sorted(seen - set(BASE))
        kept.write_text("\n".join(alphabet), encoding="utf-8")
    chars = ["", *alphabet, " "]  # RapidOCR's order: blank, dict.txt, space
    index = {c: i for i, c in enumerate(chars) if c}
    model = Recognizer(len(chars), opts.width)
    if opts.export_only:
        if (run / "best.pt").exists():
            model.load_state_dict(torch.load(run / "best.pt"))
        export(model, run)
        return
    common.no_game()
    model.cuda()
    steps_per_epoch = -(-len(data["train"]) // BATCH)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    schedule = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=2e-3, total_steps=opts.epochs * steps_per_epoch, pct_start=0.1
    )
    first, best = 0, 0.0
    if state.exists():  # stopped for a game before: go on from there
        saved = torch.load(state)
        if saved.get("epochs", opts.epochs) != opts.epochs:
            sys.exit(
                f"this run was planned for {saved['epochs']} epochs: same --epochs, or --fresh"
            )
        model.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        schedule.load_state_dict(saved["schedule"])
        first, best = saved["epoch"] + 1, saved["best"]
    # Smoothed weights are the ones kept: single epochs swing between 30 % and 90 % on dev.
    smooth = torch.optim.swa_utils.AveragedModel(
        model, multi_avg_fn=torch.optim.swa_utils.get_ema_multi_avg_fn(0.999), use_buffers=True
    )
    if state.exists():
        smooth.load_state_dict(saved["smooth"])
    loss_of = nn.CTCLoss(blank=0, zero_infinity=True)
    print(f"train {len(data['train'])} crops, dev {len(data['dev'])}, {len(chars)} classes, "
          f"{sum(p.numel() for p in model.parameters()) / 1e6:.2f} M weights")  # fmt: skip
    for epoch in range(first, opts.epochs):
        rng, total = random.Random(epoch), 0.0
        model.train()
        for batch in batches(data["train"], rng):
            x, _steps = tensors(private, batch, rng)
            # Every step of the padded picture counts, not only the crop's own: RapidOCR pads
            # short crops to 320 px and decodes all of it, so padding must read as nothing.
            steps = [x.shape[3] // STRIDE] * len(batch)
            targets = [torch.tensor([index[c] for c in text if c in index], dtype=torch.long)
                       for _c, text in batch]  # fmt: skip
            log_probs = model(x.cuda()).log_softmax(-1).transpose(0, 1)
            loss = loss_of(log_probs, torch.cat(targets), torch.tensor(steps),
                           torch.tensor([len(t) for t in targets]))  # fmt: skip
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            schedule.step()
            smooth.update_parameters(model)
            total += loss.item()
        dev = exact(smooth.module, private, data["dev"], chars)
        if dev > best or not (run / "best.pt").exists():
            best = dev
            torch.save(smooth.module.state_dict(), run / "best.pt")
        saved = {"model": model.state_dict(), "optimizer": optimizer.state_dict(),
                 "schedule": schedule.state_dict(), "epoch": epoch, "best": best,
                 "epochs": opts.epochs,
                 "smooth": smooth.state_dict()}  # fmt: skip
        torch.save(saved, state)
        print(f"epoch {epoch + 1}/{opts.epochs}  loss {total / steps_per_epoch:.3f}  "
              f"dev exact {dev:.1%}  best {best:.1%}", flush=True)  # fmt: skip
        if epoch + 1 < opts.epochs:
            common.no_game(", run again to go on")
    model.load_state_dict(torch.load(run / "best.pt"))
    export(model, run)


if __name__ == "__main__":
    main()
