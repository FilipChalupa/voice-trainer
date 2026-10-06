from app import prompts
from app.config import pronounce
from trainer.spellout import spell_out
from trainer.verify_worker import similarity


def test_units_agree_with_the_number():
    assert spell_out("Je 1 °C, pak 2 °C, 5 °C a 22 °C.") == "Je 1 stupeň Celsia, pak 2 stupně Celsia, 5 stupňů Celsia a 22 stupně Celsia."
    assert spell_out("Vlhkost 45 %, baterie 82 %.") == "Vlhkost 45 procent, baterie 80 dvě procenta."
    assert spell_out("Stojí 1 250 Kč, sleva 21 Kč a 2 Kč.") == "Stojí 1250 korun, sleva 20 jedna korun a dvě koruny."
    assert spell_out("Jelo 120 km/h, váží 2 kg, spotřeba 5 kWh.") == "Jelo 120 kilometrů za hodinu, váží 2 kilogramy, spotřeba 5 kilowatthodin."
    assert spell_out("Za 25 min. denně, nebo za 1 min.") == "Za 25 minut denně, nebo za jedna minuta."


def test_decimals_are_read_as_wholes_and_parts():
    assert spell_out("Venku je 23,5 °C.") == "Venku je 23 celé 5 stupně Celsia."
    assert spell_out("Je to 1,5 km a 0,05 mm.") == "Je to jedna celá 5 kilometru a 0 celá 0 5 milimetru."
    assert spell_out("Vyrobily 12,4 kWh, tedy 2,5krát víc.") == "Vyrobily 12 celých 4 kilowatthodiny, tedy dvě celé 5krát víc."
    assert spell_out("Měří 1 000 000 částic.") == "Měří 1000000 částic."


def test_times_and_dates():
    assert spell_out("Začíná ve 14:30 a končí v 16:00.") == "Začíná ve 14 30 a končí v 16 hodin."
    assert spell_out("V 1:00, ve 2:00 a ve 22:00, odjezd v 7:05.") == "V jednu hodinu, ve dvě hodiny a ve 20 dvě hodiny, odjezd v 7 0 5."
    assert spell_out("Narodil se 3. května 1985.") == "Narodil se třetího května 1985."
    assert spell_out("Dne 1. 5. je svátek, platí do 31. 12. 2026.") == "Dne prvního května je svátek, platí do třicátého prvního prosince 2026."
    assert spell_out("Trvá to 10–15 minut.") == "Trvá to 10 až 15 minut."


def test_abbreviations_are_read_in_words():
    assert spell_out("To je např. dnes, popř. zítra, tj. brzy.") == "To je například dnes, popřípadě zítra, to jest brzy."
    assert spell_out("Koupili sýr atd. Potom šli domů.") == "Koupili sýr a tak dále. Potom šli domů."
    assert spell_out("Tzv. chytrý dům na str. 12, cca 20 lidí.") == "Takzvaný chytrý dům na straně 12, cirka 20 lidí."
    assert spell_out("Ing. Novák z firmy Dům s. r. o.") == "inženýr Novák z firmy Dům eseró."


def test_plain_text_versions_and_other_languages_stay():
    for text in ("Verze 2.5 a kapitola 3.", "Bylo jich pět.", "V roce 2024 přišlo 300 lidí.", "Atd je zkratka."):
        assert spell_out(text) == text
    assert spell_out("It is 25 % at 14:30.", "en") == "It is 25 % at 14:30."


def test_everything_goes_into_the_training_transcript_and_the_whisper_check():
    assert pronounce("Na USB je software za 2 Kč.", {}, "cs") == "Na úesbé je softvér za dvě koruny."
    assert similarity("Venku je 23,5 °C.", "Venku je 23,5 stupně Celsia.") > 0.95
    assert similarity("Přijde cca 20 lidí atd.", "Přijde cirka dvacet lidí a tak dále.") == 1.0


def test_a_date_does_not_end_the_sentence():
    assert prompts.split_sentences("Dne 1. 5. je státní svátek. Platnost končí 31. 12. 2026. Potom nic.") == ["Dne 1. 5. je státní svátek.", "Platnost končí 31. 12. 2026.", "Potom nic."]


def test_the_syllabic_mark_does_not_split_a_word_in_the_comparison():
    from trainer.verify_worker import normalize

    assert normalize("Vlk zmrzl, zhltl hrst zrn.") == ["vlk", "zmrzl", "zhltl", "hrst", "zrn"]
    assert similarity("Vlk zvlhl a zmlkl.", "vlk zvlhl a zmlkl") == 1.0


def test_numbers_in_words_for_the_reader_and_the_length_check():
    from trainer.spellout import in_words

    assert in_words("Budík zvoní v 6:45.") == "Budík zvoní v šest čtyřicet pět."
    assert in_words("Narodil se 3. května 1985.") == "Narodil se třetího května tisíc devětset osmdesát pět."
    assert in_words("Venku je 23,5 °C a 45 %.") == "Venku je dvacet tři celé pět stupně Celsia a čtyřicet pět procent."
    assert in_words("It is 25 %.", "en") == "It is twenty-five %."
