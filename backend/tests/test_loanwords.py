from app import paragraphs, prompts
from app.config import pronounce
from trainer.loanwords import entries, listed, respell
from trainer.verify_worker import similarity


def test_loanwords_are_respelled_with_their_endings_and_capital():
    assert respell("Software i softwaru, e-mailem přišel update o jazzovém víkendu.") == "Softvér i softvéru, ímejlem přišel apdejt o džezovém víkendu."
    assert respell("Pizzu z pizzerie a croissant.") == "Picu z picerie a kroasán."
    assert respell("Disk do USB, kabel HDMI.") == "Disk do úesbé, kabel hádéemí."
    assert respell("Home Assistantu se daří, je to fair play.") == "Houm asistentu se daří, je to fér plej."


def test_similar_czech_words_and_other_languages_are_left_alone():
    for text in ("Chata má dva byty a čtyři byty jsou volné.", "Posílám usb kabel a pc.", "Mailand, e-mailing, teamster.", "Pizzicato hraje sám."):
        assert respell(text) == text
    assert respell("The software update came by e-mail.", "en") == "The software update came by e-mail."


def test_lexicon_wins_over_the_builtin_list():
    assert pronounce("Software a jazz.", {}, "cs") == "Softvér a džez."
    assert pronounce("Software a jazz.", {"jazz": "jaz"}, "cs") == "Softvér a jaz."
    # word -> the same word switches the built-in respelling off
    assert pronounce("Software a jazz.", {"software": "software"}, "cs") == "software a džez."
    assert pronounce("Turris má software.", {"Turris": "turis"}, "cs") == "turis má softvér."


def test_whisper_check_compares_the_spoken_forms():
    assert similarity("V sobotu jdeme na jazzový koncert.", "V sobotu jdeme na džezový koncert.") == 1.0
    assert similarity("Přišel vám nový e-mail.", "Přišel vám nový ímejl.") == 1.0


def test_listed_words_are_not_typos_and_the_list_is_shown():
    assert listed("deadline") and listed("happy") and listed("softwaru") and not listed("rohlík")
    words = {e["word"] for e in entries("cs")}
    assert {"software", "e-mail", "jazz", "USB"} <= words and "softwar" not in words
    assert entries("en") == []


def test_loanword_paragraphs_are_short_sentences_that_change_when_pronounced():
    loan = [p for p in paragraphs.BUILTIN["cs"] if p["id"].startswith("cizi-")]
    assert len(loan) == 5
    changed = 0
    for p in loan:
        sentences = prompts.split_sentences(p["text"])
        assert len(sentences) >= 10 and all(len(s) <= 110 for s in sentences)
        changed += sum(1 for s in sentences if pronounce(s, {}, "cs") != s)
    assert changed >= 45
    tricky = [p for p in paragraphs.BUILTIN["en"] if p["id"].startswith("spell-")]
    assert len(tricky) == 3 and all(len(prompts.split_sentences(p["text"])) == 10 for p in tricky)


def test_training_transcripts_are_written_the_way_they_were_said():
    from app.jobs import training_lines

    items = [{"id": "a", "text": "Přišel vám nový e-mail."}, {"id": "b", "text": "Turris | běží."}, {"id": "c", "text": "The software works."}]
    assert training_lines(items[:2], {"Turris": "turis"}, "cs") == ["a.wav|Přišel vám nový ímejl.", "b.wav|turis   běží."]
    assert training_lines(items[2:], {}, "en") == ["c.wav|The software works."]
