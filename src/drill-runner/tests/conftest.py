import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Placeholder write paths for every test: the real list is configuration, never in this repo (ADR-004)
os.environ["ENGINEER_WRITE_PATHS"] = "src/order-service/app/example.py,src/order-service/tests/test_*.py,runbooks/*.md"
