import os
import sys
import tempfile
from pathlib import Path

# Point the app at a throw-away data directory and keep it offline before any app module is imported.
_TMP = Path(tempfile.mkdtemp(prefix="voice-test-"))
os.environ["DATA_DIR"] = str(_TMP)
os.environ["VT_OFFLINE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
