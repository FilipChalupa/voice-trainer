from app.verify import lexicon_suggestions


def take(text, heard):
    return {"text": text, "verify": {"status": "mismatch", "transcript": heard}}


def test_words_whisper_keeps_hearing_differently_are_suggested():
    entries = [
        take("Router Turris stojí v chodbě.", "Router Turis stojí v chodbě."),
        take("Nový Turris má dva porty.", "Nový Turis má dva porty."),
        take("Turris zvládne i Wi-Fi.", "Turys zvládne i Wi-Fi."),
        take("Dnes je hezky.", "Dnes je hezky."),
        take("Koupil jsem rohlík.", "Koupil jsem rohlíky."),  # once is a slip, not a term
        take("Koupil jsem rohlík a mléko.", "Koupil jsem rohlík a mléko."),
        take("Koupil jsem rohlík včera.", "Koupil jsem rohlík včera."),
        take("Mně se to líbí.", "Mě se to líbí."),  # Whisper's spelling of a dictionary word
        take("Mně se to nelíbí.", "Mě se to nelíbí."),
        take("Fethead zesiluje mikrofon.", "Fathead zesiluje mikrofon."),
        take("Fethead je tichý.", "Fathead je tichý."),
    ]
    items = lexicon_suggestions(entries, {})
    assert [i["word"] for i in items] == ["Fethead", "Turris"]
    assert items[1] == {"word": "Turris", "heard": "turis", "count": 2, "takes": 3}


def test_known_lexicon_words_short_words_and_untranscribed_takes_are_left_out():
    entries = [
        take("Turris je router.", "Turis je router."),
        take("Turris je router.", "Turis je router."),
        take("Je to on.", "Je to oni."),
        take("Je to on.", "Je to oni."),
        {"text": "Bez kontroly.", "verify": None},
    ]
    assert lexicon_suggestions(entries, {"turris": "turis"}) == []
    assert lexicon_suggestions(entries, {}) == [{"word": "Turris", "heard": "turis", "count": 2, "takes": 2}]


def test_numbers_are_compared_spelled_out():
    entries = [take("Je 17 hodin.", "Je sedmnáct hodin."), take("Je 17 hodin.", "Je sedmnáct hodin.")]
    assert lexicon_suggestions(entries, {}) == []
