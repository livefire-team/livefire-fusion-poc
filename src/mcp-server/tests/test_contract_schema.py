"""contracts/mcp-tools.schema.json is the published tool contract: it must match the code exactly."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_published_tool_schemas_match_the_code():
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "export-tool-schemas.py"), "--check"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, (out.stdout + out.stderr)[-500:] or "stale: run scripts/export-tool-schemas.py"
