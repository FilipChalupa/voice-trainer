import numpy as np

from trainer.transcribe import SAMPLE_RATE, cut_points, frame_rms, sentences_of


def word(text, start, end):
    return {"text": " " + text, "start": start, "end": end}


def test_sentences_split_at_punctuation_pauses_and_length():
    words = [word("Dobrý", 0.0, 0.3), word("den.", 0.3, 0.6), word("Jak", 0.8, 1.0), word("se", 1.0, 1.1), word("máte", 1.1, 1.4)]
    words += [word("dnes", 2.6, 2.9)]  # a pause of 1.2 s ends the sentence even without punctuation
    words += [word(f"slovo{i}", 4.1 + i, 4.6 + i) for i in range(30)]  # a long run without punctuation is split at pauses
    out = sentences_of(words)
    assert out[0]["text"] == "Dobrý den." and out[1]["text"] == "Jak se máte" and out[2]["text"] == "dnes"
    assert all(s["end"] - s["start"] <= 15.5 for s in out[3:]) and len(out) > 4
    assert " ".join(w["text"].strip() for w in words[6:]) == " ".join(s["text"] for s in out[3:])


def test_cut_points_land_in_the_pauses():
    sr = SAMPLE_RATE
    t = np.arange(int(4.0 * sr)) / sr
    audio = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    audio[int(1.4 * sr) : int(2.0 * sr)] = 0.0  # the real pause is 1.4–2.0 s
    audio[: int(0.3 * sr)] = 0.0
    audio[int(3.7 * sr) :] = 0.0
    # Whisper thinks the boundary is at 1.9/1.95, off by half a second
    sentences = [{"text": "A.", "start": 0.35, "end": 1.9}, {"text": "B.", "start": 1.95, "end": 3.6}]
    (s1, e1), (s2, e2) = cut_points(frame_rms(audio), sentences, 4.0)
    assert 0.0 <= s1 <= 0.3 and 1.4 <= e1 <= 2.0 and s2 == e1 and 3.65 <= e2 <= 4.0
