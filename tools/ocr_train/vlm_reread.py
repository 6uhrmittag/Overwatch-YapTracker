"""Phase 1 of the OCR POC (#608): a local vision model re-reads the line pictures on the GPU.

    fixtures/private/ocr/venv/bin/python tools/ocr_train/vlm_reread.py --model qwen --set gold
    ... --set all        # every picture (silver labels); stops and resumes by itself

Runs in the POC's own venv (PyTorch + transformers), never the app's. Local only: the models
are downloaded once from Hugging Face, no picture or text leaves the PC. Checks for
Overwatch.exe before the model loads and every CHECK_EVERY pictures; when the game is there it
stops (exit code 3) and the next run goes on where it stopped (readings/<model>.jsonl).
"""

import argparse
import json
import sys
import time
from pathlib import Path

import torch
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402

EXACT = (
    "Transcribe the text in this image exactly, character by character, including brackets, "
    "punctuation and umlauts. It is video game chat: names and slang are spelled unusually, "
    "do not correct anything. Ignore icons. Output only the text, on one line."
)
MODELS = {  # name: (Hugging Face repo, prompt)
    "paddle": ("PaddlePaddle/PaddleOCR-VL-1.6", "OCR:"),
    "glm": ("zai-org/GLM-OCR", "Text Recognition:"),
    "qwen": ("Qwen/Qwen3.5-4B", EXACT),
}
UPSCALE = 2  # a 45 px row is below every model's smallest picture: enlarge it ourselves
CHECK_EVERY = 20  # pictures between two looks for Overwatch.exe
GAME_EXIT = 3


class Reader:
    def __init__(self, name: str) -> None:
        import transformers

        repo, self.prompt = MODELS[name]
        self.thinking = {"enable_thinking": False} if name == "qwen" else {}
        self.processor = transformers.AutoProcessor.from_pretrained(repo)
        loader = getattr(transformers, "AutoModelForMultimodalLM", None)
        if name != "qwen" or loader is None:
            loader = transformers.AutoModelForImageTextToText
        self.model = loader.from_pretrained(repo, dtype=torch.bfloat16).to("cuda").eval()

    @torch.inference_mode()
    def read(self, picture: Path) -> str:
        image = Image.open(picture).convert("RGB")
        image = image.resize((image.width * UPSCALE, image.height * UPSCALE), Image.LANCZOS)
        messages = [{"role": "user", "content": [
            {"type": "image", "image": image}, {"type": "text", "text": self.prompt}]}]  # fmt: skip
        inputs = self.processor.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=True, return_dict=True,
            return_tensors="pt", **self.thinking,
        ).to(self.model.device)  # fmt: skip
        out = self.model.generate(**inputs, max_new_tokens=160, do_sample=False)
        text = self.processor.decode(out[0][inputs["input_ids"].shape[-1] :],
                                     skip_special_tokens=True)  # fmt: skip
        return " ".join(text.split())


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("--model", choices=MODELS, required=True)
    args.add_argument("--set", choices=("gold", "all"), default="gold")
    args.add_argument("--limit", type=int, help="stop after this many pictures (a first try)")
    opts = args.parse_args()
    private = common.private()
    with (private / "dataset.jsonl").open(encoding="utf-8") as f:
        data = [json.loads(line) for line in f]
    if opts.set == "gold":
        gold = set(json.loads((private / "gold" / "sample.json").read_text()))
        data = [r for r in data if r["id"] in gold]
    out_path = private / "readings" / f"{opts.model}.jsonl"
    out_path.parent.mkdir(exist_ok=True)
    done = set()
    if out_path.exists():
        with out_path.open(encoding="utf-8") as f:
            done = {json.loads(line)["id"] for line in f}
    todo = [r for r in data if r["id"] not in done][: opts.limit]
    if not todo:
        sys.exit(f"nothing to do: {len(done)} readings in {out_path.name}")
    if common.game_running():
        sys.exit(GAME_EXIT)
    reader = Reader(opts.model)
    seconds = []
    with out_path.open("a", encoding="utf-8") as out:
        for n, r in enumerate(todo):
            if n % CHECK_EVERY == 0 and n and common.game_running():
                print(f"Overwatch is running: stopped after {n} of {len(todo)}")
                sys.exit(GAME_EXIT)
            start = time.perf_counter()
            row = reader.read(private / r["picture"])
            seconds.append(time.perf_counter() - start)
            out.write(json.dumps({"id": r["id"], "row": row, "s": round(seconds[-1], 3)},
                                 ensure_ascii=False) + "\n")  # fmt: skip
            out.flush()
    rest = sorted(seconds[1:]) or seconds  # the first read warms the GPU up
    print(f"{opts.model}: {len(todo)} pictures, median {rest[len(rest) // 2]:.2f} s per line, "
          f"{torch.cuda.max_memory_allocated() / 2**30:.1f} GB VRAM")  # fmt: skip


if __name__ == "__main__":
    main()
