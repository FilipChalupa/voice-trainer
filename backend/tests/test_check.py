import numpy as np
import pytest

librosa = pytest.importorskip("librosa")

from app.check import mel_distance  # noqa: E402


def tone(freq, seconds=1.0, sr=22050):
    t = np.arange(int(seconds * sr)) / sr
    return (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_mel_distance_is_small_for_the_same_content_and_larger_otherwise():
    same = mel_distance(tone(220), tone(220, seconds=1.3), 22050)  # the same sound, a different tempo
    other = mel_distance(tone(220), tone(1800), 22050)
    assert same < 0.05 and other > same * 5
