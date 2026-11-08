"""Which language is a chat line in? (#469) A cheap local check before anything goes to DeepL:
only a line that is confidently in a language you don't read is sent, and DeepL's own
detected language has the last word (a line it calls English stays untranslated).

No library: lingua is 70-170 MB (the whole app is ~150 MB), and a guess is enough here. A
language counts by its common little words and its own letters (ñ, ç, ą, ß ...); two pieces of
evidence at least, and more than any language you read has. Latin script only: the OCR doesn't
read Cyrillic, Greek or Asian scripts at all.
"""

import re

NAMES = {
    "EN": "English", "DE": "German", "ES": "Spanish", "FR": "French", "PL": "Polish",
    "PT": "Portuguese", "IT": "Italian", "NL": "Dutch",
}  # fmt: skip
MIN_CHARS = 8  # shorter lines ("hola", "merci") aren't worth a guess; Translate is one click
EVIDENCE = 2  # words or letters of a language before it counts

# Common short words of each language. Words that are English too ("no", "me", "a", "on", "die",
# "to", "is", "we") stay out of the other lists: they prove nothing in an English chat.
_WORDS = {
    "EN": "the and you your are is was what why how who this that they them we our us my i im "
          "it its be for with not just can cant dont didnt have has get got please pls plz "
          "thanks thank good nice team play go now need guys all one he she so if do but "
          "here there come let lets yes yeah",
    "DE": "der das und ist nicht ich du wir ihr sie es ein eine einen mit auf für fur was wer "
          "wie warum bitte danke ja nein mal noch schon auch aber oder weil kann gut sehr hier "
          "jetzt alle euch mein dein macht spielt heute gerne leute geil digga alter gehts "
          "spielen zusammen",
    "ES": "el la los las que de y es en por para con una uno pero como más mas gracias hola "
          "vamos equipo bien muy todo todos nada porque qué quien quién alguien habla español "
          "espanol tanque curas soy eres estoy está esta aqui aquí jaja jajaja buenas bueno "
          "si sí nos les del al amigo amigos pasa hay",
    "FR": "le la les et est je tu il nous vous ils une des du pour avec pas mais ou où qui "
          "quoi c merci bonjour salut oui non bien joué joue allez équipe equipe très tres "
          "trop mdr ptdr ça ca sur dans fait faut encore quelqu parle français francais "
          "soins ce cette",
    "PL": "w z na nie jest się sie że ze co jak tak ja ty wy ale czy dla mnie ciebie kto "
          "gdzie dzięki dzieki za proszę prosze grajcie gramy siema cześć czesc dobrze "
          "bardzo jestem tylko już juz leczenie",
    "PT": "os que não nao sim obrigado obrigada você voce vocês voces com para uma um muito "
          "bem vamos tá ta está eu ele ela nós porque curas kkk kkkk mano pelas pelo",
    "IT": "il lo la che di è non per con una uno sono sei siamo grazie ciao bene molto tutti "
          "andiamo squadra cure perché perche cosa chi dove ragazzi bravo brava dai le",
    "NL": "de het een en niet ik jij wij zijn met voor op aan maar ook wat wie waarom "
          "bedankt dank goed heel jullie spelen hoi doei lekker",
}  # fmt: skip
WORDS = {code: frozenset(words.split()) for code, words in _WORDS.items()}
LETTERS = {"DE": "äöüß", "ES": "ñ¿¡", "FR": "çœèêëîïûâ", "PL": "ąęłśżźćń", "PT": "ãõ", "IT": "òì"}
# Chat words that are no language: never evidence.
_SLANG = (
    "gg ggs wp gl hf glhf ez xd lol lmao ty thx gj ns nt ok okay rip omg wtf uwu owo kek lul pog"
)
SLANG = frozenset(_SLANG.split())
_TOKEN = re.compile(r"[^\W\d_]+")


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in SLANG]


def scores(text: str, tokens: list[str] | None = None) -> dict[str, int]:
    """How much of each language a line shows: its words (each once: "la la la" is one), and
    2 for each of its letters."""
    lowered = text.lower()
    words = set(_tokens(text) if tokens is None else tokens)
    found = {code: sum(1 for t in words if t in known) for code, known in WORDS.items()}
    for code, letters in LETTERS.items():
        found[code] += 2 * sum(1 for ch in set(letters) if ch in lowered)
    return found


def foreign(text: str, read: set[str]) -> str | None:
    """The language a line is confidently in when it's not one you read ("ES"), else None:
    too short, chat slang, a language you read, or no clear winner."""
    tokens = _tokens(text)
    if len(text.strip()) < MIN_CHARS or len(tokens) < 2:
        return None
    found = scores(text, tokens)
    best = max(found, key=lambda code: found[code])
    if best in read or found[best] < EVIDENCE:
        return None
    if max((found[code] for code in read if code in found), default=0) >= found[best]:
        return None
    return best
