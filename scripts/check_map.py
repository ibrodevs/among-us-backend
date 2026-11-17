"""Compare both versioned contracts without modifying either repository."""
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
frontend=Path(sys.argv[1]) if len(sys.argv)>1 else root.parent/'among-us-frontend/src/features/game/engine/map.json'
for backend,client in [(root/'game/map.json',frontend),(root/'game/maps/asterion.json',frontend.with_name('asterion.json'))]:
    assert backend.read_bytes()==client.read_bytes(), f'Map contracts differ: {backend.name}'
    print(f'{backend.name}: byte-identical')
assert (root/'game/map.json').read_bytes()==(root/'game/maps/v1.json').read_bytes(), 'Legacy map changed'
