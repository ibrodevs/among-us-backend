"""Compare contract copies without modifying either repository."""

from pathlib import Path
import sys

backend = Path(__file__).resolve().parents[1] / "game/map.json"
frontend = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else backend.parents[1].parent
    / "among-us-frontend/src/features/game/engine/map.json"
)
assert (
    backend.read_bytes() == frontend.read_bytes()
), "Map contracts differ; update both copies and version together"
print("Shared map contract matches byte-for-byte")
