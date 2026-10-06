import io
import json

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)


def wav_bytes(seconds=3.0, sr=22050, amplitude=0.4):
    t = np.arange(int(seconds * sr)) / sr
    audio = np.concatenate([np.zeros(sr // 3, np.float32), (amplitude * np.sin(2 * np.pi * 200 * t)).astype(np.float32), np.zeros(sr // 3, np.float32)])
    buf = io.BytesIO()
    sf.write(buf, audio, sr, subtype="PCM_16", format="WAV")
    return buf.getvalue()


def test_no_voice_yet():
    payload = client.get("/api/voices").json()
    assert payload["voice"] is None and payload["voices"] == [] and {lang["id"] for lang in payload["languages"]} == {"cs", "en"}
    assert client.get("/api/recordings").json()["detail"]["code"] == "no_voice"


def test_create_voice_requires_owner_and_name():
    assert client.post("/api/voices", json={"name": "", "owner": "A"}).json()["detail"]["code"] == "name_required"
    assert client.post("/api/voices", json={"name": "Filip", "owner": ""}).json()["detail"]["code"] == "owner_required"
    payload = client.post("/api/voices", json={"name": "Filip", "owner": "Filip Chalupa", "language": "cs"}).json()
    assert payload["current"] == "filip" and payload["voice"]["has_consent"] is False
    assert "Filip Chalupa" in payload["voice"]["consent_statement"]


def test_consent_gates_training_and_is_bound_to_owner():
    assert client.post("/api/train").json()["detail"]["code"] == "consent_required"
    assert client.post("/api/consent", files={"file": ("c.wav", wav_bytes(1.0), "audio/wav")}).json()["detail"]["code"] == "too_short"
    payload = client.post("/api/consent", files={"file": ("c.wav", wav_bytes(4.0), "audio/wav")}).json()
    assert payload["voice"]["has_consent"] is True and payload["voice"]["consent"]["owner"] == "Filip Chalupa"
    assert client.get("/api/consent/audio").status_code == 200
    assert client.post("/api/train").json()["detail"]["code"] == "too_little_audio"
    # changing the owner invalidates the consent
    payload = client.put("/api/voice", json={"owner": "Someone Else"}).json()
    assert payload["voice"]["has_consent"] is False
    client.put("/api/voice", json={"owner": "Filip Chalupa"})
    client.post("/api/consent", files={"file": ("c.wav", wav_bytes(4.0), "audio/wav")})


def test_prompts_recording_flow():
    prompts = client.get("/api/prompts?count=3").json()
    assert prompts["source"] == "builtin" and len(prompts["items"]) == 3
    first = prompts["items"][0]
    up = client.post("/api/recordings", data={"text": first["text"], "prompt_id": first["id"]}, files={"file": ("a.wav", wav_bytes(), "audio/wav")}).json()
    assert up["text"] == first["text"] and 3.0 <= up["duration"] <= 3.7 and len(up["peaks"]) == 48
    listing = client.get("/api/recordings").json()
    assert listing["count"] == 1 and listing["minutes"] > 0.04
    # the recorded prompt is no longer offered
    assert client.get("/api/prompts?count=3").json()["items"][0]["id"] != first["id"]
    # re-recording the same prompt replaces the earlier take
    again = client.post("/api/recordings", data={"text": first["text"], "prompt_id": first["id"]}, files={"file": ("a.wav", wav_bytes(), "audio/wav")}).json()
    ids = [r["id"] for r in client.get("/api/recordings").json()["items"]]
    assert ids == [again["id"]]
    edited = client.put(f"/api/recordings/{again['id']}", json={"text": "Opravený přepis věty."}).json()
    assert edited["text"] == "Opravený přepis věty."
    assert client.delete(f"/api/recordings/{again['id']}").json()["restorable"]
    assert client.get("/api/recordings").json()["count"] == 0
    assert client.post(f"/api/recordings/{again['id']}/restore").json()["text"] == "Opravený přepis věty."


def test_skip_and_custom_prompts():
    first = client.get("/api/prompts?count=1").json()["items"][0]
    client.post(f"/api/prompts/{first['id']}/skip")
    assert client.get("/api/prompts?count=1").json()["items"][0]["id"] != first["id"]
    assert client.post("/api/prompts/custom", json={"text": "x"}).json()["detail"]["code"] == "no_sentences"
    assert client.post("/api/prompts/custom", json={"text": "Rozsviť světlo v obýváku. Jaká je venku teplota?"}).json()["added"] == 2
    assert client.get("/api/prompts?count=1").json()["items"][0]["text"] == "Rozsviť světlo v obýváku."


def test_silent_upload_is_rejected():
    res = client.post("/api/recordings", data={"text": "Ticho."}, files={"file": ("s.wav", wav_bytes(amplitude=0.0), "audio/wav")})
    assert res.status_code == 400 and res.json()["detail"]["code"] == "silent_recording"


def test_dataset_export_is_ljspeech_zip():
    import zipfile

    client.put(f"/api/recordings/{client.get('/api/recordings').json()['items'][0]['id']}", json={"text": "Věta s | oddělovačem."})
    res = client.get("/api/dataset/export")
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    names = set(zf.namelist())
    assert {"metadata.csv", "metadata_piper.csv", "dataset.json", "README.txt", "consent.wav"} <= names
    wavs = sorted(n for n in names if n.startswith("wavs/"))
    lines = zf.read("metadata.csv").decode().splitlines()
    assert len(wavs) == len(lines) == 1
    uid, text, normalised = lines[0].split("|")
    assert f"wavs/{uid}.wav" == wavs[0] and text == normalised == "Věta s oddělovačem."
    assert zf.read("metadata_piper.csv").decode().splitlines()[0] == f"{uid}.wav|Věta s oddělovačem."
    info = json.loads(zf.read("dataset.json"))
    assert info["count"] == 1 and info["sample_rate"] == 22050 and info["consent"]["owner"] == info["owner"]
    assert sf.info(io.BytesIO(zf.read(wavs[0]))).samplerate == 22050


def test_blocks_export_joins_recordings_to_mp3():
    import zipfile

    res = client.get("/api/dataset/export/blocks")
    assert res.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    names = zf.namelist()
    mp3s = [n for n in names if n.endswith(".mp3")]
    assert len(mp3s) == 1 and "README.txt" in names and zf.read(mp3s[0])[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3")
    assert zf.read(mp3s[0].replace(".mp3", ".txt")).decode().strip() == client.get("/api/recordings").json()["items"][0]["text"]


def test_dataset_import_round_trip():
    import zipfile

    exported = client.get("/api/dataset/export").content
    before = client.get("/api/recordings").json()["count"]
    # a hand-made archive in the plain LJSpeech layout, plus a row without audio
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("wavs/take1.wav", wav_bytes())
        zf.writestr("wavs/take2.flac", wav_bytes(seconds=2.0))
        zf.writestr("metadata.csv", "take1|První importovaná věta.|První importovaná věta.\ntake2.flac|Druhá věta.\nghost|Bez zvuku.\n")
    res = client.post("/api/dataset/import", files={"file": ("d.zip", buf.getvalue(), "application/zip")}).json()
    assert res["imported"] == 2 and res["skipped"] == [{"id": "ghost", "reason": "missing_audio"}] and res["count"] == before + 2
    items = client.get("/api/recordings").json()["items"]
    assert sorted(r["text"] for r in items if r["source"] == "import") == ["Druhá věta.", "První importovaná věta."]
    # our own export imports back as well
    res = client.post("/api/dataset/import", files={"file": ("e.zip", exported, "application/zip")}).json()
    assert res["imported"] == before and res["consent_imported"] is False  # the consent exists already
    assert client.post("/api/dataset/import", files={"file": ("x.zip", b"nope", "application/zip")}).json()["detail"]["code"] == "bad_zip"
    for r in client.get("/api/recordings").json()["items"]:
        if r["source"] == "import":
            client.delete(f"/api/recordings/{r['id']}")


def test_paragraphs_queue_in_order_and_lexicon_is_applied():
    from app.config import apply_lexicon

    res = client.get("/api/paragraphs")
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert items and items[0]["sentences"] >= 5 and items[0]["recorded"] == 0
    res = client.post(f"/api/paragraphs/{items[0]['id']}/queue").json()
    assert res["added"] == res["sentences"]
    queue = client.get("/api/prompts?count=3").json()["items"]
    assert queue[0]["text"].startswith(items[0]["preview"][:20])
    assert client.post("/api/paragraphs/nope/queue").status_code == 404
    payload = client.put("/api/voice", json={"lexicon": {"Wi-Fi": "vaj faj", "HA": "há á", "": "x"}}).json()
    assert payload["voice"]["lexicon"] == {"Wi-Fi": "vaj faj", "HA": "há á"}
    assert apply_lexicon("Zapni wi-fi a HA. Haha.", payload["voice"]["lexicon"]) == "Zapni vaj faj a há á. Haha."


def test_storage_overview_and_cleanup():
    before = client.get("/api/storage").json()
    assert before["total"] > 0 and before["voices"][0]["id"] == "filip" and before["voices"][0]["recordings"] > 0
    assert before["disk_free"] > 0 and "checkpoints" in before["base"]
    # one deleted take sits in the trash; emptying it frees space
    rec = client.get("/api/recordings").json()["items"][0]
    client.delete(f"/api/recordings/{rec['id']}")
    with_trash = client.get("/api/storage").json()
    assert with_trash["reclaimable"]["trash"] > 0
    freed = client.post("/api/storage/empty-trash").json()["freed"]
    assert freed > 0 and client.get("/api/storage").json()["reclaimable"]["trash"] == 0
    assert client.post(f"/api/recordings/{rec['id']}/restore").status_code == 404
    client.post("/api/recordings", data={"text": rec["text"], "prompt_id": rec["prompt_id"] or ""}, files={"file": ("a.wav", wav_bytes(), "audio/wav")})
    assert client.post("/api/storage/clear-cache").json()["freed"] == 0


def test_redo_puts_the_sentence_first_even_when_it_is_a_custom_prompt():
    text = "Věta, kterou chci namluvit znovu a lépe."
    client.post("/api/prompts/custom", json={"text": text})  # it is a custom prompt already, like paragraphs are
    rec = client.post("/api/recordings", data={"text": text, "prompt_id": client.get("/api/prompts?count=1").json()["items"][0]["id"]}, files={"file": ("a.wav", wav_bytes(), "audio/wav")}).json()
    client.post(f"/api/prompts/{rec['prompt_id']}/skip")  # even a skipped one comes back
    res = client.post(f"/api/recordings/{rec['id']}/redo")
    assert res.status_code == 200 and res.json()["text"] == text
    assert client.get("/api/prompts?count=1").json()["items"][0]["text"] == text
    assert all(r["id"] != rec["id"] for r in client.get("/api/recordings").json()["items"])
    assert client.post(f"/api/recordings/{rec['id']}/restore").status_code == 200
    client.delete(f"/api/recordings/{rec['id']}")


def test_custom_batches_can_be_removed():
    client.post("/api/prompts/custom", json={"text": "První věta z omylem vložené knihy. Druhá věta z té samé knihy.", "source": "Kniha · Kapitola 1"})
    client.post("/api/prompts/custom", json={"text": "Tahle věta zůstává ve frontě dál.", "source": "Jiný text"})
    batches = {b["source"]: b for b in client.get("/api/prompts/custom").json()["batches"]}
    assert batches["Kniha · Kapitola 1"]["remaining"] == 2 and batches["Jiný text"]["remaining"] == 1
    assert client.delete("/api/prompts/custom", params={"source": "Kniha · Kapitola 1"}).json()["removed"] == 2
    batches = {b["source"]: b for b in client.get("/api/prompts/custom").json()["batches"]}
    assert "Kniha · Kapitola 1" not in batches and batches["Jiný text"]["remaining"] == 1
    assert client.get("/api/prompts?count=1").json()["items"][0]["text"] == "Tahle věta zůstává ve frontě dál."
    client.delete("/api/prompts/custom")
    assert client.get("/api/prompts/custom").json()["batches"] == []


def test_typo_in_the_text_is_flagged_unless_whisper_heard_the_same_word():
    from app.recordings import load_index, save_index

    rec = client.post("/api/recordings", data={"text": "Zalijte literm vývaru a vařte dvacet minut."}, files={"file": ("a.wav", wav_bytes(), "audio/wav")}).json()
    item = next(r for r in client.get("/api/recordings").json()["items"] if r["id"] == rec["id"])
    assert "spelling" in item["quality"]["issues"] and item["quality"]["unknown_words"] == ["literm"]
    assert client.get("/api/dataset").json()["issues"]["spelling"] == 1
    # an unusual word Whisper heard as written is not a typo
    voice = config.current_voice()
    index = load_index(voice)
    index[rec["id"]]["verify"] = {"status": "ok", "transcript": "Zalijte literm vývaru a vařte 20 minut.", "similarity": 1.0}
    save_index(voice, index)
    item = next(r for r in client.get("/api/recordings").json()["items"] if r["id"] == rec["id"])
    assert "spelling" not in item["quality"]["issues"]
    client.put(f"/api/recordings/{rec['id']}", json={"text": "Zalijte litrem vývaru a vařte dvacet minut."})
    client.delete(f"/api/recordings/{rec['id']}")


def test_dataset_report_and_training_params():
    report = client.get("/api/dataset").json()
    assert report["count"] == 1 and report["has_consent"] is True and report["ready"] is False
    from app.recordings import sentence_types

    kinds = sentence_types([{"text": t, "duration": 6.0} for t in ("Je doma.", "Je doma?", "Kde je?", "Pozor!", "Když přišel,", "„Kdo to byl?“")])
    assert {k: v["count"] for k, v in kinds.items()} == {"statement": 1, "question": 3, "exclamation": 1, "continuation": 1}
    assert kinds["question"]["minutes"] == 0.3 and sum(v["count"] for v in report["sentence_types"].values()) == report["count"]
    payload = client.put("/api/voice", json={"training": {"epochs": 5, "batch_size": 999, "validation_every": 10, "preview_every": 25}}).json()
    training = payload["voice"]["training"]
    assert training["epochs"] == 10 and training["batch_size"] == 64 and training["preview_every"] == 20


def test_job_summary_previews_and_exports(tmp_path):
    from app.runs import job_summary, list_exports, list_previews

    job_dir = tmp_path / "20260101_000000_abc"
    (job_dir / "previews" / "epoch_00050").mkdir(parents=True)
    (job_dir / "previews" / "epoch_00050" / "0.wav").write_bytes(b"RIFF")
    (job_dir / "previews" / "epoch_00050" / "sentences.json").write_text(json.dumps(["Ahoj."]))
    (job_dir / "export").mkdir()
    (job_dir / "export" / "cs_CZ-x-medium.onnx").write_bytes(b"onnx")
    (job_dir / "export" / "exports.json").write_text(json.dumps([{"variant": "last", "file": "cs_CZ-x-medium.onnx", "checkpoint": "last.ckpt", "size": 4}]))
    (job_dir / "checkpoints").mkdir()
    (job_dir / "checkpoints" / "last.ckpt").write_bytes(b"x")
    (job_dir / "job.json").write_text(json.dumps({"job_id": job_dir.name, "slug": "x", "max_epochs": 100, "training": {}}))
    previews = list_previews(job_dir, job_dir.name)
    assert previews[0]["epoch"] == 50 and previews[0]["items"][0]["text"] == "Ahoj."
    assert list_exports(job_dir, job_dir.name)[0]["url"].endswith("/export/cs_CZ-x-medium.onnx")
    summary = job_summary(job_dir, running_job_id=None)
    assert summary["status"] == "interrupted" and summary["resumable"] is True and summary["bundle_url"]
    assert job_summary(job_dir, running_job_id=job_dir.name)["status"] == "running"


def test_fit_command_starts_from_an_earlier_run_when_its_checkpoint_is_linked(tmp_path):
    from app.jobs import WARMSTART_FILE, manager

    job_dir = tmp_path / "20260101_000000_new"
    job_dir.mkdir()
    job = {"job_dir": str(job_dir), "slug": "x", "audio_dir": str(tmp_path), "espeak_voice": "cs", "max_epochs": 300, "base_checkpoint": "/data/base/base.ckpt",
           "training": {"batch_size": 16, "learning_rate": 0.0002, "validation_every": 10}}
    cmd = manager._fit_command(job, resume=False)
    assert cmd[cmd.index("--model.warmstart_ckpt") + 1] == "/data/base/base.ckpt"
    (job_dir / WARMSTART_FILE).write_bytes(b"ckpt")
    cmd = manager._fit_command(job, resume=False)
    assert cmd[cmd.index("--model.warmstart_ckpt") + 1] == str(job_dir / WARMSTART_FILE)
    (job_dir / "checkpoints").mkdir()
    (job_dir / "checkpoints" / "last.ckpt").write_bytes(b"x")
    cmd = manager._fit_command(job, resume=True)
    assert "--ckpt_path" in cmd and "--model.warmstart_ckpt" not in cmd
    assert client.post("/api/train", json={"from_job": "20990101_000000_nope"}).status_code in (404, 409)


def test_export_variants_and_usage_text():
    from pathlib import Path

    from app.synth import usage_text
    from trainer.export import variant_of

    assert variant_of(Path("last.ckpt")) == "last" and variant_of(Path("best_mos-epoch=40.ckpt")) == "best_mos" and variant_of(Path("best_mel-epoch=90.ckpt")) == "best_mel"
    from trainer.export import write_voice_config

    src = Path(config.DATA_DIR) / "cfg.json"
    src.write_text(json.dumps({"espeak": {"voice": "cs"}, "audio": {"sample_rate": 22050}, "num_speakers": 1}))
    out = Path(config.DATA_DIR) / "voice.onnx.json"
    write_voice_config(src, out, {"piper_language": "cs_CZ", "slug": "filip"})
    written = json.loads(out.read_text())
    assert written["language"]["code"] == "cs_CZ" and written["language"]["family"] == "cs" and written["dataset"] == "filip"
    assert written["audio"] == {"sample_rate": 22050, "quality": "medium"} and written["phoneme_map"] == {}
    text = usage_text("cs_CZ-filip-medium", {"name": "Filip", "owner": "Filip Chalupa", "consent": {"at": "2026-01-01"}})
    assert "/share/piper" in text and "cs_CZ-filip-medium.onnx.json" in text and "Filip Chalupa" in text


def test_system_and_voice_delete():
    info = client.get("/api/system").json()
    assert "gpu_available" in info and "torch_cuda" in info and info["disk_total_gb"] > 0
    other = client.post("/api/voices", json={"name": "Second", "owner": "Jane Doe", "language": "en"}).json()
    assert other["current"] == "second" and other["voice"]["language"] == "en"
    after = client.delete("/api/voices/second").json()
    assert [v["id"] for v in after["voices"]] == ["filip"] and config.current_voice().id == "filip"


def test_take_can_be_marked_for_recording_again_and_tricky_words_are_flagged():
    rec = client.post("/api/recordings", data={"text": "Na disku Flash je nový software, hm."}, files={"file": ("a.wav", wav_bytes(), "audio/wav")}).json()
    item = next(r for r in client.get("/api/recordings").json()["items"] if r["id"] == rec["id"])
    # "software" is on the built-in list, "Flash" is respelled too; only the vowel-less "hm" has no cure yet
    assert item["spoken"] == "Na disku Fleš je nový softvér, hm."
    assert "tricky_word" in item["quality"]["issues"] and item["quality"]["tricky_words"] == ["hm"]
    assert "redo" not in item["quality"]["issues"] and item["redo"] is False

    marked = client.put(f"/api/recordings/{rec['id']}", json={"redo": True}).json()
    assert marked["redo"] is True and marked["reviewed"] is False
    item = next(r for r in client.get("/api/recordings").json()["items"] if r["id"] == rec["id"])
    assert "redo" in item["quality"]["issues"]
    assert client.get("/api/dataset").json()["issues"]["redo"] >= 1
    # confirming the take as it is settles the mark; the lexicon settles the tricky word
    assert client.put(f"/api/recordings/{rec['id']}", json={"reviewed": True}).json()["redo"] is False
    client.put("/api/voice", json={"lexicon": {"hm": "hmm"}})
    item = next(r for r in client.get("/api/recordings").json()["items"] if r["id"] == rec["id"])
    assert "tricky_word" not in item["quality"]["issues"] and "redo" not in item["quality"]["issues"]
    client.put("/api/voice", json={"lexicon": {}})
    client.delete(f"/api/recordings/{rec['id']}")


def test_prompts_with_numbers_say_how_they_are_read_and_text_is_respelled_for_other_players():
    client.post("/api/prompts/custom", json={"text": "Venku je 23,5 °C a vlhkost 45 %."})
    first = client.get("/api/prompts?count=1").json()["items"][0]
    assert first["text"] == "Venku je 23,5 °C a vlhkost 45 %." and first["read_as"] == "Venku je dvacet tři celé pět stupně Celsia a vlhkost čtyřicet pět procent."
    client.post(f"/api/prompts/{first['id']}/skip")
    assert client.post("/api/pronounce", json={"text": "E-mail o 2 kg softwaru."}).json() == {"text": "Ímejl o 2 kilogramy softvéru."}


def test_sound_coverage_counts_rare_sounds_and_suggests_paragraphs():
    import pytest

    pytest.importorskip("piper")  # espeak comes with Piper: in the app image, not in the plain test environment
    from app import coverage

    counts = coverage.count_sounds(["Džbán s džusem.", "Leckdo má euro a auto."], "cs", {})
    assert counts["dž"] == 2 and counts["dz"] == 1 and counts["eu"] == 1 and counts["au"] == 1 and counts["ž"] == 0
    res = client.get("/api/dataset/coverage").json()
    assert res["available"] is True and res["low"] == 20
    assert any(i["sound"] == "dž" and i["low"] for i in res["items"])
    assert res["suggest"] and res["suggest"][0]["gain"] > 0 and "vzacne-hlasky" in [s["id"] for s in res["suggest"]]


def test_sound_coverage_without_piper_says_so(monkeypatch):
    from app import coverage

    def missing(text, voice):
        raise ImportError("piper")

    monkeypatch.setattr(coverage, "phonemes", missing)
    assert client.get("/api/dataset/coverage").json() == {"available": False, "items": [], "suggest": [], "low": 20}


def test_length_check_counts_the_words_that_are_read_not_the_digits():
    from app.audio import analyze

    # three seconds of speech for "Budík zvoní v 6:45.": eleven letters as written, thirty as said
    rec = client.post("/api/recordings", data={"text": "Budík zvoní v 6:45."}, files={"file": ("a.wav", wav_bytes(seconds=2.4), "audio/wav")}).json()
    assert "text_mismatch" not in rec["quality"]["issues"], rec["quality"]
    assert "text_mismatch" in analyze(config.current_voice().recordings_dir / f"{rec['id']}.wav", "Budík zvoní v 6:45.")["quality"]["issues"]
    client.delete(f"/api/recordings/{rec['id']}")
