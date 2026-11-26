"""Phase 2 of the OCR POC (#608): made-up chat lines for what real evenings have too little of.

    python tools/ocr_train/synth.py            # 20000 crops into fixtures/private/ocr/synth

Real data is English with a handful of names; German is ~28 lines. So: made-up names (letter
runs, digits, CamelCase, a few ä/ø/İ), German and English chat words, stretched words
("yääähi", "booooop"), the comms shapes with real hero names, drawn in open fonts close to the
chat font, in the chat's colours, over pieces of real game background (cut from the right end
of the row pictures, where no chat is). Every name and sentence here is invented.
"""

import argparse
import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402

from yaptracker import game_lists  # noqa: E402


def _words(text: str) -> list[str]:
    return text.split()


FONTS = [  # open, Arial/Helvetica-shaped like the chat font
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
COLOURS = [(255, 255, 255), (0, 255, 255), (255, 255, 110), (255, 170, 200), (255, 180, 60),
           (255, 0, 255), (120, 200, 255)]  # fmt: skip
# No name or phrase of the #118 test sets (ocr-spike, ocr-german) may be here: they measure
# this. Everyday words overlap all the same (about a third of the German set's tokens).
GERMAN = _words(
    "ich du er sie es wir ihr nicht schon mal aber ist das der die den dem ein eine einen "
    "auch noch gut ja nein bitte danke hallo jetzt wo wie warum wer was hier dann doch "
    "mit von zu auf aus bei bis nach vor oder wenn weil für über müde schön grüße süß "
    "heiß weiß groß größer spaß fuß straße möglich höher können müssen würde wäre hätte "
    "später nächste fällt läuft käse döner glühwein übrigens tschüss viel glück heiler "
    "heilen heile gegner leute jungs mädels spiel spielen runde gewonnen verloren knapp "
    "stark schwach überall öfter ärgerlich gemütlich natürlich zurück drüben außen gruß "
    "wieder gerne alles klar euch bin bist sind seid haben hat hatte war waren wird "
    "werden kann muss soll will mach mache macht geh gehe geht komm komme kommt sag sage "
    "sagt nix nichts etwas immer nie heute morgen abend nacht woche zeit lust bock geil "
    "krass mega echt wirklich leider vielleicht bestimmt genau richtig falsch links "
    "rechts oben unten hinten vorne schnell langsam zusammen allein team punkt karte held "
    "heldin schaden schild ulti bereit warte wartet hilfe hilf dir kein keine keinen mein "
    "meine dein deine unser unsere süße mäuse häuser bäume träume räume frühstück "
    "kühlschrank bürgermeister weißbier tschö servus moin nabend ne nö jo joa hm hmm "
    "achso aso okay oki supi top stabil gehts gg wp "
)
ENGLISH = _words(
    "gg wp glhf ez lol lmao nice shot ty thx np sorry my bad heal me pls group up push in "
    "fall back we got this one more who needs a hug big pizza energy tank diff dps "
    "support they have no idea what just happened i love this map can we swap wait for me "
    "dont die omg that was close wow such play much win very cozy hello there good luck "
    "have fun uwu idk tbh fr ngl brb afk im its ur u r y not ok okay yes no maybe never "
    "always again "
)
SYLLABLES = _words(
    "ka zu mi ro te la shi no bu xa qu ve dy fo gri sto ple wun der nox lux ar um el ix "
    "oo ee ww rar uw ny pa chi go bo "
)
ODD = list("äöüßÄÖÜøØéèëàáâêîôûñçåÅİıłş_")
MARKS = [":3", "<3", "xD", ":D", "^^", "T^T", ">:3", "!", "?", "...", "!!", "??", "*hug*", ";)",
         "uwu", ":)", ":(", "xd", "^_^"]  # fmt: skip
SYSTEM = ["[{n}] started playing Overwatch.", "[{n}] stopped playing Overwatch.",
          "[{n}] joined the game.", "[{n}] left the game.", "You endorsed {n}!",
          "{n} switched to {h} (was {h2}).", "[{n}] invited you to a group!"]  # fmt: skip
CALLOUTS = ["Hello!", "Thanks!", "Group up!", "I need healing!", "Fall back!", "Good work!",
            "Understood.", "You are welcome.", "I am on my way.", "Attack with me!",
            "My ultimate is charging! {p}%", "My ultimate is ready!", "I'm going in!",
            "Defend with me!", "I need help!", "Yes.", "No.", "Sorry.",
            "On cooldown for {p} seconds."]  # fmt: skip


def name(rng: random.Random) -> str:
    out = "".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 5)))
    if rng.random() < 0.3:  # the run that models shorten: "rarar", "ooo"
        i = rng.randrange(len(out))
        out = out[:i] + out[i] * rng.randint(2, 4) + out[i:]
    if rng.random() < 0.4:
        out = "".join(part.capitalize() for part in (out[: len(out) // 2], out[len(out) // 2 :]))
    elif rng.random() < 0.3:
        out = out.capitalize()
    if rng.random() < 0.15:
        out = out.upper()
    if rng.random() < 0.25:
        out += str(rng.randint(0, 99999))
    if rng.random() < 0.12:
        i = rng.randrange(len(out))
        out = out[:i] + rng.choice(ODD) + out[i + 1 :]
    return out[:16]


def stretched(rng: random.Random, word: str) -> str:
    i = rng.randrange(len(word))
    return word[:i] + word[i] * rng.randint(2, 7) + word[i + 1 :]


def sentence(rng: random.Random) -> str:
    words = GERMAN if rng.random() < 0.5 else ENGLISH
    out = [rng.choice(words) for _ in range(rng.randint(1, 7))]
    for i in range(len(out)):
        roll = rng.random()
        if roll < 0.12:
            out[i] = stretched(rng, out[i])
        elif roll < 0.30:  # German nouns and sentence starts
            out[i] = out[i].capitalize()
        elif roll < 0.33:
            out[i] = out[i].upper()
        elif roll < 0.36:
            out[i] = str(rng.randint(0, 300)) + rng.choice(["", "%", "/3", "k", "s"])
    if rng.random() < 0.3:
        out.append(rng.choice(MARKS))
    if rng.random() < 0.1:
        out[rng.randrange(len(out))] += ","
    return " ".join(out)


def line(rng: random.Random, heroes: list[str]) -> str:
    n, h, h2 = name(rng), rng.choice(heroes), rng.choice(heroes)
    roll = rng.random()
    if roll < 0.45:
        return f"[{n}]: {sentence(rng)}"
    if roll < 0.7:
        to = rng.choice(["", " to you", f" to {name(rng)} ({h2})"])
        return f"{n} ({h}){to}: {rng.choice(CALLOUTS).format(p=rng.randint(1, 99))}"
    if roll < 0.85:
        return rng.choice(SYSTEM).format(n=n, h=h, h2=h2)
    return sentence(rng)  # the second row of a wrapped message: no name in front


def backgrounds(private: Path, rng: random.Random, count: int = 400) -> list[Image.Image]:
    """Strips of game picture from the right end of whole rows, beside the chat's dark panel."""
    rows = sorted((private / "lines").rglob("*.webp"))  # sorted: the same pick every run
    out = []
    for path in rng.sample(rows, min(count * 2, len(rows))):
        image = Image.open(path).convert("RGB")
        if image.width == 1180 and len(out) < count:
            out.append(image.crop((1060, 0, 1180, image.height)))
    return out


def draw(rng: random.Random, text: str, grounds: list[Image.Image]) -> Image.Image:
    font = ImageFont.truetype(rng.choice(FONTS), rng.randint(34, 46))
    left, top, right, bottom = font.getbbox(text)
    pad_x, pad_y = rng.randint(0, 8), rng.randint(1, 7)
    size = (right - left + 2 * pad_x, bottom - top + 2 * pad_y)
    if rng.random() < 0.45:  # the dark chat panel
        ground = Image.new("RGB", size, (rng.randint(0, 25),) * 3)
    else:
        ground = rng.choice(grounds).resize(size, Image.BICUBIC)
        ground = ground.filter(ImageFilter.GaussianBlur(rng.uniform(0, 2)))
        if rng.random() < 0.6:  # the panel over the game: darker
            ground = Image.blend(ground, Image.new("RGB", size, (0, 0, 0)), rng.uniform(0.3, 0.8))
    pen = ImageDraw.Draw(ground)
    at = (pad_x - left, pad_y - top)
    pen.text((at[0] + 2, at[1] + 2), text, font=font, fill=(0, 0, 0))  # the chat's soft shadow
    edge = rng.choice([0, 0, 1, 2])  # over a bright picture the letters have a dark edge
    pen.text(at, text, font=font, fill=rng.choice(COLOURS), stroke_width=edge,
             stroke_fill=(rng.randint(0, 90),) * 3)  # fmt: skip
    if rng.random() < 0.3:
        ground = ground.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.9)))
    return ground


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("--count", type=int, default=20000)
    opts = args.parse_args()
    private, rng = common.private(), random.Random(608)
    heroes = list(game_lists.lists()["heroes"])
    common.no_game()
    grounds = backgrounds(private, rng)
    if not grounds:
        sys.exit("no 1180 px wide row pictures to cut game background from (another resolution?)")
    folder = private / "synth"
    folder.mkdir(exist_ok=True)
    with (private / "synth.jsonl").open("w", encoding="utf-8") as out:
        for n in range(opts.count):
            text = line(rng, heroes)
            draw(rng, text, grounds).save(folder / f"{n:05}.png")
            row = {"crop": f"synth/{n:05}.png", "text": text, "split": "train", "id": None,
                   "source": "synthetic"}  # fmt: skip
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{opts.count} synthetic crops")


if __name__ == "__main__":
    main()
