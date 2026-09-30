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
    assert ok["quality"]["issues"] == [] and len(ok["peaks"]) == 64
    mismatch = analyze(path, "Tohle je mnohem delší věta, kterou za jednu sekundu rozhodně nikdo nestihne celou přečíst nahlas.")
    assert "text_mismatch" in mismatch["quality"]["issues"]
    loud = tmp_path / "b.wav"
    wav, _ = normalize_wav(wav_bytes(seconds=1.0, amplitude=1.5, lead=0.3, tail=0.3))
    loud.write_bytes(wav)
    assert "clipping" in analyze(loud)["quality"]["issues"]


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
