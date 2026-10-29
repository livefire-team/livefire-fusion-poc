import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

# Unit tests never talk to Azure: no telemetry exporter, and a local file as the secret source.
os.environ.pop("APPLICATIONINSIGHTS_CONNECTION_STRING", None)
os.environ.setdefault("SECRET_SOURCE", f"file:{APP_DIR.parent / 'tests' / 'unused-secret'}")
