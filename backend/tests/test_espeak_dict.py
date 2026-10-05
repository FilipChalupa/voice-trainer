"""The compiled espeak-ng dictionary: needs Piper's build tree, so it runs in the app image only."""
import shutil
import subprocess

import pytest

pytest.importorskip("piper")

from trainer import espeak_dict  # noqa: E402
from trainer.loanwords import respell  # noqa: E402


@pytest.fixture(scope="module")
def tools(tmp_path_factory):
    binary, _, data = espeak_dict.find_tools()
    root = tmp_path_factory.mktemp("espeak")
    for name in ("original", "custom"):
        shutil.copytree(data, root / name / "espeak-ng-data")
    espeak_dict.build(root / "custom" / "espeak-ng-data" / "cs_dict", {"Turris": "turis", "Wi-Fi": "vaj faj"})

    def ipa(which: str, text: str) -> str:
        out = subprocess.run([str(binary), f"--path={root / which}", "-v", "cs", "-q", "--ipa", text], capture_output=True, text=True).stdout
        return "".join(out.split()).replace("ˈ", "").replace("ˌ", "")

    return ipa


@pytest.mark.parametrize("text", [
    "Software se aktualizuje.", "Do softwaru nesahej.", "Přišel nový e-mail.", "O jazzu a jazzové hudbě.", "Martin má tip na festival.",
    "Technika a technický pokrok.", "Do Googlu to nepiš.", "Disk do USB a kabel HDMI.", "Na WC svítí světlo.", "Vlk zvlhl a zmlkl.",
    "Mám iPhone a notebook.", "Home Assistant hlásí update.", "Objednáme pizzu a croissant.", "Na display se nedívej.",
])
def test_dictionary_reads_like_the_respelling(tools, text):
    assert tools("custom", text) == tools("original", respell(text))


def test_lexicon_is_compiled_in_and_native_words_stay(tools):
    assert tools("custom", "Turris běží.") == tools("original", "turis běží.")
    assert tools("custom", "Do Turris nelez.") == tools("original", "Do turis nelez.")
    for text in ("Ticho, nikdy a divadlo.", "Chata má dva byty.", "Politika a matematika.", "Dnes je hezky, na stole leží kniha."):
        assert tools("custom", text) == tools("original", text)
    # the plain dictionary really is wrong about these
    assert tools("original", "software") != tools("custom", "software") and tools("original", "vlk") != tools("custom", "vlk")


def test_cache_key_follows_the_lexicon():
    assert espeak_dict.cache_key({}) == espeak_dict.cache_key(None) != espeak_dict.cache_key({"a": "b"})
