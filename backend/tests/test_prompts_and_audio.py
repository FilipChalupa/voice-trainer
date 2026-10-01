import io

import numpy as np
import soundfile as sf

from app import prompts
from app.audio import analyze, normalize_wav, trim_edges
from app.config import SAMPLE_RATE


def wav_bytes(seconds=2.0, sr=44100, amplitude=0.5, lead=0.6, tail=0.6):
    t = np.arange(int(seconds * sr)) / sr
    tone = (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    audio = np.concatenate([np.zeros(int(lead * sr), np.float32), tone, np.zeros(int(tail * sr), np.float32)])
    buf = io.BytesIO()
    sf.write(buf, audio, sr, subtype="PCM_16", format="WAV")
    return buf.getvalue()


def test_normalize_to_project_format():
    wav, duration = normalize_wav(wav_bytes(seconds=1.0, sr=44100))
    info = sf.info(io.BytesIO(wav))
    assert info.samplerate == SAMPLE_RATE and info.channels == 1 and info.subtype == "PCM_16"
    assert abs(duration - 2.2) < 0.05


def test_trim_edges_keeps_context():
    wav, _ = normalize_wav(wav_bytes(seconds=1.0, lead=1.5, tail=1.2))
    trimmed, duration = trim_edges(wav)
    assert 1.3 <= duration <= 1.5  # 1.0 s of speech + 0.2 s on both sides


def test_analyze_flags_text_mismatch_and_clipping(tmp_path):
    path = tmp_path / "a.wav"
    wav, _ = normalize_wav(wav_bytes(seconds=1.0, lead=0.3, tail=0.3))
    path.write_bytes(wav)
    ok = analyze(path, "Dobrý den všem.")
    assert ok["quality"]["issues"] == [] and len(ok["peaks"]) == 48
    mismatch = analyze(path, "Tohle je mnohem delší věta, kterou za jednu sekundu rozhodně nikdo nestihne celou přečíst nahlas.")
    assert "text_mismatch" in mismatch["quality"]["issues"]
    loud = tmp_path / "b.wav"
    wav, _ = normalize_wav(wav_bytes(seconds=1.0, amplitude=1.5, lead=0.3, tail=0.3))
    loud.write_bytes(wav)
    assert "clipping" in analyze(loud)["quality"]["issues"]
    # a recording normalised to full scale touches the limit with a sample or two and is fine
    data, sr = sf.read(str(path), dtype="float32")
    data[len(data) // 2] = 1.0
    peaked = tmp_path / "c.wav"
    sf.write(str(peaked), data, sr, subtype="PCM_16")
    assert "clipping" not in analyze(peaked)["quality"]["issues"]


def test_filter_sentences_keeps_natural_czech():
    lines = [
        "Dnes je venku opravdu krásně a svítí sluníčko.",
        "KRÁTKÉ",
        "Věta s číslem 123 do korpusu nepatří, protože se čte různě.",
        "tato věta nezačíná velkým písmenem a proto také vypadne",
        "Dnes je venku opravdu krásně a svítí sluníčko.",
        "Tahle věta nemá na konci tečku ale jinak je úplně v pořádku",
    ]
    out = prompts.filter_sentences(lines, "cs")
    assert out == ["Dnes je venku opravdu krásně a svítí sluníčko.", "Tahle věta nemá na konci tečku ale jinak je úplně v pořádku."]


def test_select_balanced_is_deterministic_and_prefers_variety():
    sentences = [f"Tohle je testovací věta číslo {w} pro výběr." for w in ("jedna", "dvě", "tři", "čtyři", "pět")] + ["Žluťoučký kůň úpěl ďábelské ódy v šeru džungle."]
    a = prompts.select_balanced(sentences, 3)
    assert a == prompts.select_balanced(sentences, 3) and len(a) == 3
    assert "Žluťoučký kůň úpěl ďábelské ódy v šeru džungle." in a


def test_split_sentences_and_prompt_ids():
    parts = prompts.split_sentences("Rozsviť v kuchyni. Jaká je teplota?\nOk\nDobrou noc všem doma!")
    assert parts == ["Rozsviť v kuchyni.", "Jaká je teplota?", "Dobrou noc všem doma!"]
    assert prompts.prompt_id("Ahoj.") == prompts.prompt_id(" Ahoj. ") and len(prompts.prompt_id("x")) == 12


def test_builtin_sets_are_usable():
    for lang, sentences in prompts.BUILTIN.items():
        assert len(sentences) >= 25 and len(set(sentences)) == len(sentences), lang


def test_inconsistent_recordings_are_flagged():
    from app.recordings import flag_inconsistent

    def item(speech_db, noise_db):
        return {"quality": {"speech_db": speech_db, "noise_db": noise_db, "issues": []}}

    items = [item(-20, -70) for _ in range(6)] + [item(-31, -70), item(-20, -45)]
    flag_inconsistent(items)
    assert [r["quality"]["issues"] for r in items[:6]] == [[]] * 6
    assert items[6]["quality"]["issues"] == ["level_mismatch"] and items[7]["quality"]["issues"] == ["noisy"]
    few = [item(-20, -70), item(-40, -40)]
    flag_inconsistent(few)  # too few recordings to know what is typical
    assert few[1]["quality"]["issues"] == []


def test_quiet_take_with_room_noise_is_not_cut_off(tmp_path):
    # a quiet reading (peak 30 %) over an audible room noise floor, with silence-ish edges of 0.4 s
    sr = 22050
    rng = np.random.default_rng(1)
    noise = (0.004 * rng.standard_normal(int(4.0 * sr))).astype(np.float32)  # about -48 dBFS
    t = np.arange(int(3.2 * sr)) / sr
    speech = (0.3 * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)
    audio = noise.copy()
    audio[int(0.4 * sr) : int(0.4 * sr) + len(speech)] += speech
    path = tmp_path / "quiet.wav"
    sf.write(str(path), audio, sr, subtype="PCM_16")
    q = analyze(path, "Krátká věta na zkoušku hlasitosti.")["quality"]
    assert "cut_start" not in q["issues"] and "cut_end" not in q["issues"]
    assert 3.0 <= q["speech_seconds"] <= 3.5


def test_misspelled_sentences_are_dropped_from_the_corpus():
    assert prompts.misspelled("Ale protože žije jen v bytě, až tolik příežitostí k pohybu nemá.", "cs") == ["příežitostí"]
    assert prompts.misspelled("Karolína vytahuje sluneční brýle a nasazuje si je.", "cs") == []
    assert prompts.misspelled("The quick brown fox jumps over the lazy dog in Springfield.", "en") == []
    assert prompts.misspelled("The quick brown fox jumpss over the lazy dog.", "en") == ["jumpss"]
    lines = ["Ale protože žije jen v bytě, až tolik příežitostí k pohybu nemá.", "Karolína vytahuje sluneční brýle a nasazuje si je na nos."]
    assert prompts.filter_sentences(lines, "cs") == [lines[1]]
    assert len(prompts.filter_sentences(lines, "cs", spell=False)) == 2


def test_quiet_pauses_fades_long_pauses_only():
    from app.audio import quiet_pauses

    sr = 22050
    rng = np.random.default_rng(2)
    noise = (0.005 * rng.standard_normal(int(5.0 * sr))).astype(np.float32)
    t = np.arange(int(1.5 * sr)) / sr
    word = (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    audio = noise.copy()
    audio[int(0.5 * sr) : int(0.5 * sr) + len(word)] += word  # 0.5-2.0 s speech
    audio[int(2.08 * sr) : int(2.08 * sr) + len(word)] += word  # a 80 ms gap: stays
    audio[int(4.3 * sr) : int(4.3 * sr) + int(0.5 * sr)] += word[: int(0.5 * sr)]  # a 0.7 s pause before it: faded
    out = quiet_pauses(audio, sr)
    rms = lambda a, b: float(np.sqrt((out[int(a * sr) : int(b * sr)] ** 2).mean()) / np.sqrt((audio[int(a * sr) : int(b * sr)] ** 2).mean()))
    assert 0.95 < rms(0.8, 1.8) < 1.05  # speech untouched
    assert 0.8 < rms(2.0, 2.08) < 1.05  # the short gap untouched
    assert rms(3.7, 4.2) < 0.2  # the long pause down by ~18 dB
    assert rms(0.0, 0.4) < 0.2  # leading silence too


def test_split_sentences_keeps_abbreviations_and_initials_together():
    text = "A teď měl koncipient dr. Mejzlík vyšetřit, které auto to bylo. Napsal to K. Čapek v r. 1929! „Poslyšte,“ řekl. Co teď?"
    assert prompts.split_sentences(text) == ["A teď měl koncipient dr. Mejzlík vyšetřit, které auto to bylo.", "Napsal to K. Čapek v r. 1929!", "„Poslyšte,“ řekl."]


def test_library_cleaning():
    from app.library import _chapter_key, strip_gutenberg, strip_wikitext

    wiki = "{{Textinfo|AUTOR=[[Autor:Karel Čapek|Karel Čapek]]}}\n== Hlava ==\n''Byla'' to [[běžná|běžná]] událost<ref>pozn.</ref>, řekl.\n"
    assert strip_wikitext(wiki).strip() == "Byla to běžná událost, řekl."
    gb = "junk\r\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\r\nFirst line\r\nsame paragraph.\r\n\r\nNext.\r\n*** END OF THE PROJECT GUTENBERG EBOOK X ***\r\nlicense"
    assert strip_gutenberg(gb).strip() == "First line same paragraph.\n\nNext."
    assert [_chapter_key(x)[0] for x in ("I", "IV", "IX", "XIV", "3", "Úvod")] == [1, 4, 9, 14, 3, 10**6]
