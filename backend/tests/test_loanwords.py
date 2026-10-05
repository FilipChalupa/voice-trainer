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
    for text in ("Chata má dva byty a čtyři byty jsou volné.", "Posílám usb kabel a pc.", "Mailand, e-mailing, teamster.", "Pizzicato hraje sám.", "Ticho, nikdy, divadlo, tisk."):
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
    assert {"software", "e-mail", "jazz", "USB", "technik…"} <= words and "softwar" not in words
    assert entries("en") == []


def test_loanword_paragraphs_are_short_sentences_that_change_when_pronounced():
    loan = [p for p in paragraphs.BUILTIN["cs"] if p["id"].startswith("cizi-")]
    assert len(loan) == 5 and len(paragraphs.BUILTIN["cs"]) >= 42
    changed = 0
    for p in loan:
        sentences = prompts.split_sentences(p["text"])
        assert len(sentences) >= 10 and all(len(s) <= 110 for s in sentences)
        changed += sum(1 for s in sentences if pronounce(s, {}, "cs") != s)
    assert changed >= 45
    tricky = [p for p in paragraphs.BUILTIN["en"] if p["id"].startswith("spell-")]
    assert len(tricky) == 3 and all(len(prompts.split_sentences(p["text"])) == 10 for p in tricky)


def test_training_transcripts_are_written_the_way_they_were_said(monkeypatch):
    from app.jobs import training_lines
    from trainer import espeak_dict

    # where Piper reads with the dictionary that knows the loanwords, only the lexicon and the numbers are
    # rewritten in the text...
    monkeypatch.setattr(espeak_dict, "installed", lambda: True)
    assert training_lines([{"id": "a", "text": "Turris má e-mail za 2 Kč, vlk."}], {"Turris": "turis"}, "cs") == ["a.wav|turis má e-mail za dvě koruny, vl\u0329k."]
    assert training_lines([{"id": "c", "text": "The software works."}], {}, "en") == ["c.wav|The software works."]
    # ...anywhere else the text is respelled in full
    monkeypatch.setattr(espeak_dict, "installed", lambda: False)

    items = [{"id": "a", "text": "Přišel vám nový e-mail."}, {"id": "b", "text": "Turris | běží."}, {"id": "c", "text": "The software works."}]
    assert training_lines(items[:2], {"Turris": "turis"}, "cs") == ["a.wav|Přišel vám nový ímejl.", "b.wav|turis   běží."]
    assert training_lines(items[2:], {}, "en") == ["c.wav|The software works."]


def test_hard_ti_di_ni_and_words_without_a_vowel():
    assert respell("Martin má tip na technický festival.") == "Martyn má typ na technycký festyval."
    assert respell("Daniel a senior hrají v divizi.") == "Danyjel a senyjor hrají v dyvizi."
    # a syllabic mark after the l keeps espeak from spelling the word out
    assert respell("Vlk zvlhl a zmlkl.") == "Vl\u0329k zvl\u0329hl a zml\u0329kl."
    assert respell("PLK, krk, prst a vlka.") == "PLK, krk, prst a vlka."
