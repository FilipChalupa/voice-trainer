"""The transcription import and the model check, with the heavy workers replaced by small stand-ins."""
import io
import json
import time

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from app import check, config, importer, verify
from app.main import app

client = TestClient(app)


def wav_bytes(seconds=2.0, sr=22050):
    t = np.arange(int(seconds * sr)) / sr
    audio = np.concatenate([np.zeros(sr // 4, np.float32), (0.4 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), np.zeros(sr // 4, np.float32)])
    buf = io.BytesIO()
    sf.write(buf, audio, sr, subtype="PCM_16", format="WAV")
    return buf.getvalue()


FAKE_TRANSCRIBE = '''
import json, shutil, sys
from pathlib import Path
args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
out = Path(args["--out-dir"]); (out / "clips").mkdir(exist_ok=True)
print("@@" + json.dumps({"event": "stage", "stage": "transcribing", "seconds": 2.5, "device": "cpu"}), flush=True)
print(" 50%|#####     | 1/2", end="\\r", flush=True)
clips = []
hints = (out / "hints.txt").read_text(encoding="utf-8") if (out / "hints.txt").exists() else ""
print("@@" + json.dumps({"event": "log", "message": "hints: " + hints}), flush=True)
for i, text in enumerate(["První věta z nahrávky.", "Druhá věta z nahrávky."], start=1):
    shutil.copy(args["--input"], out / "clips" / f"{i:04d}.wav")
    clips.append({"file": f"{i:04d}.wav", "text": text, "start": 0, "end": 2.5})
(out / "clips.json").write_text(json.dumps(clips, ensure_ascii=False))
print("@@" + json.dumps({"event": "done", "clips": 2, "seconds": 2.5}), flush=True)
'''


def wait_for(fn, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = fn()
        if state["status"] not in ("running", "loading", "transcribing", "cutting", "storing", "downloading"):
            return state
        time.sleep(0.1)
    raise AssertionError(f"still running: {state}")


def setup_module():
    if config.current_voice() is None:
        client.post("/api/voices", json={"name": "Worker", "owner": "Test Person", "language": "cs"})


def test_transcribe_import_stores_sentences(monkeypatch, tmp_path):
    script = tmp_path / "fake_transcribe.py"
    script.write_text(FAKE_TRANSCRIBE)
    monkeypatch.setattr(importer, "transcribe_command", lambda source, work, language: [importer.sys.executable, str(script), "--input", str(source), "--out-dir", str(work)])
    before = client.get("/api/recordings").json()["count"]
    client.put("/api/voice", json={"lexicon": {"Turris": "turis"}})
    res = client.post("/api/transcribe", files={"file": ("reading.wav", wav_bytes(), "audio/wav")}, data={"hints": "Mejzlík, TanStack"})
    assert res.status_code == 200 and res.json()["status"] in ("loading", "transcribing", "storing", "done")
    state = wait_for(lambda: client.get("/api/transcribe").json())
    assert state["status"] == "done", state
    assert state["result"]["stored"] == 2 and state["result"]["count"] == before + 2
    assert any("2 sentences" in line for line in state["log"])
    assert any("hints: Mejzlík, TanStack, Turris" in line for line in state["log"])  # typed terms + the pronunciation list
    items = client.get("/api/recordings").json()["items"]
    transcribed = [r for r in items if r["source"] == "transcribed"]
    assert sorted(r["text"] for r in transcribed) == ["Druhá věta z nahrávky.", "První věta z nahrávky."]
    assert not (config.current_voice().dir / "imports").exists()
    # unsupported file types and a second import while one runs are refused
    assert client.post("/api/transcribe", files={"file": ("x.txt", b"hi", "text/plain")}).json()["detail"]["code"] == "bad_audio"


def test_model_check_flags_the_odd_recording(monkeypatch):
    voice = config.current_voice()
    items = client.get("/api/recordings").json()["items"]
    assert len(items) >= 2
    job_dir = voice.jobs_dir / "20260101_000000_chk"
    (job_dir / "export").mkdir(parents=True)
    (job_dir / "export" / "cs_CZ-w-medium.onnx").write_bytes(b"onnx")
    (job_dir / "export" / "exports.json").write_text(json.dumps([{"variant": "last", "file": "cs_CZ-w-medium.onnx", "checkpoint": "last.ckpt", "size": 4}]))
    (job_dir / "job.json").write_text(json.dumps({"job_id": job_dir.name, "voice_id": voice.id, "slug": "w", "max_epochs": 10, "training": {}}))
    (job_dir / "result.json").write_text(json.dumps({"status": "done", "epoch": 10}))

    # no real voice: synthesis returns a tone, and the distance is large only for the take made 3 s long
    odd = items[0]["id"]
    sf.write(str(voice.recordings_dir / f"{odd}.wav"), np.zeros(22050 * 3, np.float32), 22050, subtype="PCM_16")
    monkeypatch.setattr("app.synth.load_voice", lambda path: None)
    monkeypatch.setattr("app.synth.synthesize", lambda path, text, *scales: wav_bytes(seconds=1.0))
    monkeypatch.setattr(check, "mel_distance", lambda ref, synth, sr: 0.5 if len(ref) == 22050 * 3 else 0.01)

    assert client.post(f"/api/jobs/{job_dir.name}/check").json()["status"] == "running"
    state = wait_for(lambda: client.get(f"/api/jobs/{job_dir.name}/check").json())
    assert state["status"] == "done", state
    result = state["result"]
    assert result["count"] == len(items) and result["items"][0]["id"] == odd and result["items"][0]["flagged"] is True
    assert result["flagged"] >= 1
    assert client.get(f"/api/jobs/{job_dir.name}/check/audio/{odd}").status_code == 200
    flagged = [r["id"] for r in client.get("/api/recordings").json()["items"] if "model_mismatch" in r["quality"]["issues"]]
    assert flagged == [odd]
    # once the run is gone, the verdicts no longer apply
    client.delete(f"/api/jobs/{job_dir.name}")
    assert all("model_mismatch" not in r["quality"]["issues"] for r in client.get("/api/recordings").json()["items"])
    for r in items:
        client.delete(f"/api/recordings/{r['id']}")


FAKE_VERIFY = '''
import json, sys
print(json.dumps({"event": "ready", "device": "cpu"}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    heard = "Úplně jiná věta o něčem jiném." if "jiná" in req["text"] else req["text"]
    sim = 1.0 if heard == req["text"] else 0.1
    print(json.dumps({"event": "result", "id": req["id"], "transcript": heard, "similarity": sim}, ensure_ascii=False), flush=True)
'''


def test_similarity_and_verify_endpoint(monkeypatch, tmp_path):
    from trainer.verify_worker import similarity

    assert similarity("Dobrý den, jak se máte?", "dobrý den jak se máte") == 1.0
    assert similarity("Nejvyšší teploty vystoupí na sedmnáct až dvacet stupňů.", "Nejvyšší teploty vystoupí na 17 až 20 stupňů.", "cs") >= 0.95
    assert similarity("It is twenty two degrees outside.", "It is 22 degrees outside.", "en") >= 0.95
    assert similarity("Zapni Wi-Fi v obýváku.", "Zapni wifi v obýváku.") >= 0.85
    assert similarity("Dnes tu žije přibližně dvacet tisíc obyvatel.", "Dnes tu žije přibližně 20 000 obyvatel.", "cs") >= 0.95
    assert similarity("Budík je nastavený na šest třicet ráno.", "Budík je nastavený na 6.30 ráno.", "cs") >= 0.95
    assert similarity("Zapni světlo v kuchyni na padesát procent.", "Zapni světlo v kuchyni na 50 %.", "cs") >= 0.95
    assert similarity("Dobrý den, jak se máte?", "Dobrý večer, jak se vede?") < 0.8
    script = tmp_path / "fake_verify.py"
    script.write_text(FAKE_VERIFY)
    monkeypatch.setattr(verify, "worker_command", lambda: [verify.sys.executable, str(script)])
    verify.verifier.stop()
    ok = client.post("/api/recordings", data={"text": "Věta, která sedí přesně."}, files={"file": ("a.wav", wav_bytes(), "audio/wav")}).json()
    bad = client.post("/api/recordings", data={"text": "Tohle je jiná věta."}, files={"file": ("b.wav", wav_bytes(), "audio/wav")}).json()
    assert client.post(f"/api/recordings/{ok['id']}/verify").json()["status"] == "pending"
    assert client.post(f"/api/recordings/{bad['id']}/verify").json()["status"] == "pending"
    deadline = time.time() + 90
    while time.time() < deadline:
        items = {r["id"]: r for r in client.get("/api/recordings").json()["items"]}
        if all((items[i]["verify"] or {}).get("status") in ("ok", "mismatch", "error") for i in (ok["id"], bad["id"])):
            break
        time.sleep(0.1)
    assert items[ok["id"]]["verify"]["status"] == "ok"
    assert items[bad["id"]]["verify"]["status"] == "mismatch" and "transcript_mismatch" in items[bad["id"]]["quality"]["issues"]
    # fixing the text by hand settles the verdict
    client.put(f"/api/recordings/{bad['id']}", json={"text": "Úplně jiná věta o něčem jiném."})
    items = {r["id"]: r for r in client.get("/api/recordings").json()["items"]}
    assert "transcript_mismatch" not in items[bad["id"]]["quality"]["issues"]
    assert client.get("/api/verify").json()["running"] is True
    verify.verifier.stop()
    for rid in (ok["id"], bad["id"]):
        client.delete(f"/api/recordings/{rid}")


FAKE_VERIFY_MAP = '''
import json, sys
mapping = json.load(open(sys.argv[1]))
print(json.dumps({"event": "ready", "device": "cpu"}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    heard = mapping.get(req["text"], req["text"])
    from trainer.verify_worker import similarity
    print(json.dumps({"event": "result", "id": req["id"], "transcript": heard, "similarity": similarity(req["text"], heard)}, ensure_ascii=False), flush=True)
'''


def _upload(text):
    return client.post("/api/recordings", data={"text": text}, files={"file": ("a.wav", wav_bytes(seconds=1.0), "audio/wav")}).json()


def _wait_settled(ids, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        items = client.get("/api/recordings").json()["items"]
        present = [r for r in items if r["id"] in ids]
        if all((r["verify"] or {}).get("status") in ("ok", "mismatch", "error") for r in present):
            time.sleep(0.3)  # let the reconciliation of the last verdict finish
            return client.get("/api/recordings").json()["items"]
        time.sleep(0.1)
    raise AssertionError("verification did not settle")


def test_reconcile_relabels_skipped_sentence_and_merges_split_take(monkeypatch, tmp_path):
    t1, t2, t3 = "První věta o počasí venku.", "Druhá věta o obědě v poledne.", "Třetí věta o večerním programu."
    long = "Dlouhá věta, která má dvě části, a čtenář se uprostřed nadechl."
    nxt = "Věta hned za tou dlouhou."
    # the reader skipped t1 (every take reads the next sentence), then paused inside the long sentence
    mapping = {t1: t2, t2: t3, long: "Dlouhá věta, která má dvě části,", nxt: "a čtenář se uprostřed nadechl."}
    (tmp_path / "map.json").write_text(json.dumps(mapping, ensure_ascii=False))
    script = tmp_path / "fake_verify_map.py"
    script.write_text(FAKE_VERIFY_MAP)
    monkeypatch.setattr(verify, "worker_command", lambda: [verify.sys.executable, str(script), str(tmp_path / "map.json")])
    verify.verifier.stop()
    before = {r["id"] for r in client.get("/api/recordings").json()["items"]}
    takes = [_upload(x) for x in (t1, t2, t3)]
    for tk in takes:
        time.sleep(0.02)
        client.post(f"/api/recordings/{tk['id']}/verify")
    items = _wait_settled([tk["id"] for tk in takes])
    mine = [r for r in items if r["id"] not in before]
    texts = sorted(r["text"] for r in mine)
    # t1 is no longer claimed by any take, t2 and t3 have one take each
    assert texts == sorted([t2, t3]), texts
    assert all((r["verify"] or {}).get("status") == "ok" for r in mine)

    split = [_upload(long), _upload(nxt)]
    for tk in split:
        time.sleep(0.02)
        client.post(f"/api/recordings/{tk['id']}/verify")
    items = _wait_settled([tk["id"] for tk in split])
    merged = [r for r in items if r["id"] == split[0]["id"]]
    assert merged and merged[0]["text"] == long and merged[0]["verify"]["status"] == "ok" and merged[0]["duration"] > 2.0
    assert not any(r["id"] == split[1]["id"] for r in items)
    verify.verifier.stop()
    for r in client.get("/api/recordings").json()["items"]:
        if r["id"] not in before:
            client.delete(f"/api/recordings/{r['id']}")


def test_intelligibility_test_scores_the_voice_against_the_base_voice(monkeypatch, tmp_path):
    from app import intelligibility

    if config.current_voice() is None:
        client.post("/api/voices", json={"name": "Worker", "owner": "Test Person", "language": "cs"})
    voice = config.current_voice()
    job_dir = voice.jobs_dir / "20260102_000000_int"
    (job_dir / "export").mkdir(parents=True)
    (job_dir / "export" / "cs_CZ-w-medium.onnx").write_bytes(b"onnx")
    (job_dir / "export" / "exports.json").write_text(json.dumps([{"variant": "last", "file": "cs_CZ-w-medium.onnx", "checkpoint": "last.ckpt", "size": 4}]))
    (job_dir / "job.json").write_text(json.dumps({"job_id": job_dir.name, "voice_id": voice.id, "slug": "w", "max_epochs": 10, "training": {}}))
    (job_dir / "result.json").write_text(json.dumps({"status": "done", "epoch": 10}))

    spoken = []
    monkeypatch.setattr("app.synth.synthesize", lambda path, text, *scales: spoken.append(text) or wav_bytes(seconds=1.0))
    monkeypatch.setattr("app.base.ensure_base_voice", lambda language: tmp_path / "base.onnx")
    mapping = tmp_path / "heard.json"
    mapping.write_text(json.dumps({
        "Vlk zmrzl, zhltl hrst zrn.": "Vlk zmrzl a hrst.",  # garbled
        "Martin má tip na dobrý festival.": "Martin má typ na dobrý festival.",  # the same words, said the same
        "Venku je 23,5 °C a vlhkost 45 %.": "Venku je 23,5 stupně Celsia a vlhkost 45 procent.",
    }, ensure_ascii=False))
    script = tmp_path / "fake_verify_map.py"
    script.write_text(FAKE_VERIFY_MAP)
    monkeypatch.setattr(verify, "worker_command", lambda: [verify.sys.executable, str(script), str(mapping)])
    verify.verifier.stop()

    assert client.post(f"/api/jobs/{job_dir.name}/intelligibility").json()["status"] == "running"
    state = wait_for(lambda: client.get(f"/api/jobs/{job_dir.name}/intelligibility").json())
    assert state["status"] == "done", state
    result = state["result"]
    sentences = intelligibility.SENTENCES["cs"]
    assert result["count"] == len(sentences) and result["garbled"] == 1 and result["variant"] == "last"
    worst = result["items"][0]
    assert worst["text"] == "Vlk zmrzl, zhltl hrst zrn." and worst["similarity"] < 0.9 and "zrn" in worst["missed"]
    assert all(i["similarity"] == 1.0 for i in result["items"][1:])
    assert 90 < result["score"] < 100 and 95 < result["word_accuracy"] < 100
    # the base voice read the same sentences once and is the yardstick
    assert result["baseline"] == {"score": result["score"], "word_accuracy": result["word_accuracy"], "garbled": 1}
    # the voice was given the spoken form of the text
    assert "Venku je 23 celé 5 stupně Celsia a vlhkost 45 procent." in spoken and "Martyn má typ na dobrý festyval." in spoken
    assert len(spoken) == 2 * len(sentences)
    assert client.get(f"/api/jobs/{job_dir.name}/intelligibility/audio/{worst['index']}").status_code == 200
    assert next(j for j in client.get("/api/jobs").json()["items"] if j["job_id"] == job_dir.name)["intelligibility"] == result["score"]

    # the second run reuses the yardstick
    spoken.clear()
    client.post(f"/api/jobs/{job_dir.name}/intelligibility")
    assert wait_for(lambda: client.get(f"/api/jobs/{job_dir.name}/intelligibility").json())["status"] == "done"
    assert len(spoken) == len(sentences)
    verify.verifier.stop()
    client.delete(f"/api/jobs/{job_dir.name}")
