import io

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from app import config, processing
from app.audio import apply_processing, eq_gain, processing_active
from app.main import app

client = TestClient(app)
SR = 22050


def tone(freqs, seconds=2.0, amplitude=0.2):
    t = np.arange(int(seconds * SR)) / SR
    return sum(amplitude * np.sin(2 * np.pi * f * t) for f in freqs).astype(np.float32)


def level(audio, freq):
    spectrum = np.abs(np.fft.rfft(audio))
    return 20 * np.log10(spectrum[int(round(freq * audio.shape[0] / SR))])


def test_settings_are_kept_inside_their_limits():
    assert config.clean_processing(None) == config.DEFAULT_PROCESSING
    assert config.clean_processing({"highpass_hz": 20, "bass_db": -40, "bass_hz": "x", "treble_db": 99, "treble_hz": 3000}) == {"highpass_hz": 40, "bass_db": -12, "bass_hz": 250, "treble_db": 9, "treble_hz": 3000}
    assert not processing_active(config.DEFAULT_PROCESSING) and processing_active({"bass_db": -3})


def test_gain_curve_of_each_control():
    db = lambda p, f: 20 * np.log10(eq_gain(np.array([f]), config.clean_processing(p))[0])
    assert db({"highpass_hz": 80}, 40) < -20 and abs(db({"highpass_hz": 80}, 80) + 3) < 0.2 and db({"highpass_hz": 80}, 300) > -0.1
    assert abs(db({"bass_db": -6}, 30) + 6) < 0.3 and abs(db({"bass_db": -6, "bass_hz": 250}, 250) + 2) < 0.6 and db({"bass_db": -6}, 2000) > -0.2
    assert abs(db({"treble_db": 4}, 11000) - 4) < 0.6 and db({"treble_db": 4}, 300) < 0.1


def test_take_keeps_its_length_and_speech_band_while_the_bass_goes_down():
    audio = tone([60, 150, 1000])
    out = apply_processing(audio, SR, config.clean_processing({"highpass_hz": 90, "bass_db": -6}))
    assert out.shape == audio.shape and out.dtype == np.float32
    assert level(audio, 60) - level(out, 60) > 12 and 3 < level(audio, 150) - level(out, 150) < 9 and abs(level(audio, 1000) - level(out, 1000)) < 0.7
    assert apply_processing(audio, SR, config.DEFAULT_PROCESSING) is audio
    boosted = apply_processing(tone([6000], amplitude=0.6), SR, config.clean_processing({"treble_db": 9}))
    assert np.max(np.abs(boosted)) <= 0.99 + 1e-6


def test_suggestion_brings_a_boomy_voice_to_a_neutral_balance():
    freqs = np.fft.rfftfreq(processing.N_FFT, 1.0 / SR)
    power = np.where(freqs < 250, 4.0, 1.0) * np.where(freqs < 40, 0.0, 1.0) / np.maximum(freqs, 40)
    before = processing.band_levels(freqs, power)
    suggested = processing.suggest(freqs, power)
    after = processing.band_levels(freqs, power * eq_gain(freqs, suggested) ** 2)
    assert suggested["highpass_hz"] == 80 and suggested["bass_db"] < -2
    assert before["bass"] - before["mid"] > 2 and abs((after["bass"] - after["mid"]) - processing.NEUTRAL_BASS_DB) < 0.6
    flat = processing.suggest(freqs, np.where(freqs < 250, 0.2, 1.0) / np.maximum(freqs, 40))
    assert flat["bass_db"] == 0


def test_api_saves_the_settings_analyses_and_previews_a_take(tmp_path):
    if client.get("/api/voices").json()["voice"] is None:
        client.post("/api/voices", json={"name": "Proc", "owner": "Test Person", "language": "cs"})
    buf = io.BytesIO()
    speech = tone([120, 200, 800, 2500], seconds=3.0, amplitude=0.1)
    sf.write(buf, np.concatenate([np.zeros(SR // 3, np.float32), speech, np.zeros(SR // 3, np.float32)]), SR, subtype="PCM_16", format="WAV")
    rec = client.post("/api/recordings", data={"text": "Zkouška úpravy zvuku pro učení."}, files={"file": ("a.wav", buf.getvalue(), "audio/wav")}).json()
    payload = client.put("/api/voice", json={"processing": {"highpass_hz": 80, "bass_db": -4, "treble_db": 50}}).json()
    assert payload["voice"]["processing"] == {"highpass_hz": 80, "bass_db": -4, "bass_hz": 250, "treble_db": 9, "treble_hz": 4000}
    assert payload["processing_limits"]["bass_db"] == [-12, 6]

    res = client.post("/api/processing/analysis", json={"processing": {"bass_db": -6}}).json()
    assert res["available"] and [b["band"] for b in res["bands"]] == ["sub", "bass", "mid", "presence", "air"]
    bass = next(b for b in res["bands"] if b["band"] == "bass")
    assert bass["after_db"] < bass["before_db"] - 2 and len(res["curve"]) > 30 and set(res["suggested"]) == set(config.DEFAULT_PROCESSING)

    original, _ = sf.read(io.BytesIO(client.get(rec["url"]).content), dtype="float32")
    preview = client.post("/api/processing/preview", json={"recording_id": rec["id"], "processing": {"highpass_hz": 150}})
    assert preview.status_code == 200 and preview.headers["content-type"] == "audio/wav"
    processed, _ = sf.read(io.BytesIO(preview.content), dtype="float32")
    assert processed.shape == original.shape and np.sqrt(np.mean(processed**2)) < np.sqrt(np.mean(original**2))
    assert client.post("/api/processing/preview", json={"recording_id": "nope"}).status_code == 404

    # the copies for training carry the correction, the take itself does not change
    from app.jobs import prepare_training_audio
    from app.voices import require_voice

    voice = require_voice()
    prepare_training_audio(voice, [rec], tmp_path, quiet=False, processing=config.clean_processing({"highpass_hz": 150}))
    copy, _ = sf.read(str(tmp_path / f"{rec['id']}.wav"), dtype="float32")
    assert np.allclose(copy, processed, atol=2e-4)
    again, _ = sf.read(io.BytesIO(client.get(rec["url"]).content), dtype="float32")
    assert np.array_equal(again, original)
    client.put("/api/voice", json={"processing": config.DEFAULT_PROCESSING})
    client.delete(f"/api/recordings/{rec['id']}")
