from yaptracker import config
from yaptracker.capture.source import Region
from yaptracker.identity import Identity, same_name
from yaptracker.parser import ChatLine


def chat(speaker, target=None, kind="message"):
    return ChatLine(kind, "match", "hi", 1.0, Region(0, 0, 1, 1), speaker=speaker, target=target)


def test_names_match_despite_ocr_slips_and_battletag_numbers():
    assert same_name("NoodleBonkl", "NoodleBonk#2718")
    assert same_name("noodlebonk", "NoodleBonk")
    assert not same_name("NoodleBank", "tortillaTank")


def test_short_names_must_match_exactly():
    assert same_name("Void", "Void#1234")
    assert not same_name("Voi", "Void")
    assert not same_name("Bo", "Bob")


def test_own_and_crew_lines_are_marked():
    identity = Identity(me=("NoodleBonk#2718",), crew=("Void",))
    lines = identity.apply([chat("NoodleBonkl"), chat("Void"), chat("tortillaTank"), chat(None)])
    assert [line.role for line in lines] == ["me", "crew", None, None]


def test_comms_aimed_at_one_of_my_names_is_aimed_at_you():
    identity = Identity(me=("NoodleBonk", "OldAltName"))
    (line,) = identity.apply([chat("Void", target="OldAltName", kind="comms")])
    assert line.target == "you"


def test_identity_is_stored_in_config_not_as_players(tmp_path):
    path = tmp_path / "config.json"
    config.save_identity(["NoodleBonk#2718", "AltBonk"], ["Void"], path)
    assert config.identity(path) == Identity(me=("NoodleBonk#2718", "AltBonk"), crew=("Void",))
