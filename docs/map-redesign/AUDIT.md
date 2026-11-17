# Asterion 2.1 audit

Base backend: 34e41d33eec31e3b8170123fe3278a4c4bae81d6 (`ai/backend-v2`). Base frontend: 243d632e92c9fb3054fbd138352b0da3ee303cd1 (`ai/frontend-v2`). Both remote heads fetched before branching. No merge/deployment authorized.

The generator uses 21 identical 900×520 bounding rectangles on a grid, two symmetric tasks, three identical upper machines, and repeated vents. The renderer draws one grid, four upper windows and sector color variations. The miniature repeats bounding rectangles. This produces identical spatial silhouettes and composition.

Dependencies: rectangle collision/LOS on Django and client; immutable legacy map v1; compact gates; task/vent/door IDs; navigation waypoints; critical panels; camera and observer filtering; live WebSocket. Redesign must regenerate both JSON files identically and preserve identifiers and legacy bytes.

Strategy: room-specific unions of floor rectangles with distinct cut corners, wings and recesses, compiled to shared collision rectangles. Keep corridor connectivity and gate identifiers. Individual typed room visual definitions describe materials, props, lights, animation and audio separately from collision. Solid props explicitly opt into shared collisions. Miniature draws the same floor parts. Cached static art plus culled dynamic animation retain the 24-chunk bound.

Risks: furniture or cut corners can block task/vent approaches and existing navigation; validate exact hitbox reachability for all interactions, spawns and sampled routes. Changed map-v2 geometry requires a coordinated frontend/backend rollout between matches; no production migration is performed. Existing v1 remains byte-identical.

Baseline: 99 backend tests, 11 frontend tests passed. Backend CI including Docker smoke passed at 34e41d3. Final v2 browser checks uncovered short test walking pulses and 10-client latency/queued movement; do not treat those unfinished checks as acceptance. Resolve under the redesign QA phase. Physical phone performance remains unverified.
