# Protocol v2 and privacy

Authenticate with `{type:"auth",token,protocol_version:2}`. Guest identity is resolved server-side; clients cannot select a different player. V1 matches keep their original protocol. A v1 socket opening a v2 match receives UPGRADE_REQUIRED and closes with 4406.

`game.snapshot` is an authenticated observer view, never a broadcast world dump. It contains map/version/mode, immutable settings, own and currently visible appearances, visible bodies, public door state, active sabotage panels/deadlines, nearby visual effects, progress and the observer's meeting channel. `roster` provides nicknames/colors for meetings but has no live coordinates, alive flags or roles. During play, other players use opaque appearance IDs. Kill commands resolve these aliases inside the locked game transaction; mimic epochs rotate them to avoid identity correlation. Meeting and finished views can use roster identities; final results reveal roles after game completion.

`game.self` contains only the socket owner's role, position, tasks/challenges, cooldowns, tunnel node/connections, abilities, repair challenge and authorized terminal output. Comms preserves database assignments while suppressing their transmission and terminal output. Cameras apply radius, occlusion and disguise and omit players in tunnels. Admin gives counts only. Vitals delays corpse status five seconds.

The Redis room-group notification contains only protocol version and state version. Every consumer reloads and filters for its authenticated observer, and skips versions already sent. No tunnel destination, task challenge, hidden role or killer identity crosses the public room bus.

Observer events (`map.state`, `game.settings`, `door.state`, sabotage events, `vent.state`, `ability.result`, `player.ghost`, `meeting.chat.message`) are derived from already filtered snapshot transitions. Tunnel state and ability results are private. Chat events use only that observer's living/ghost channel. `task.challenge` and `task.verified` are sent directly to the actor. All v2 events include game ID and state version. Snapshots remain the reconnect source of truth.

Client command envelopes and observer event discriminators are described in `game/protocol-v2.schema.json`. Frontend command/state unions live in `src/features/game/network/types.ts` in the paired repository. Clients discard stale snapshot versions. Unknown or invalid commands, role/distance/phase/cooldown failures, malformed numbers and replayed task completions are rejected server-side.

Movement sends directions, never accepted coordinates. The durable 10 Hz clock normalizes and substeps movement against the shared map and currently closed doors. Stop input cannot be starved by movement tokens; it cannot advance position or bypass the frame-rate/traffic limits.

Report resolves active reactor/oxygen incidents. It preserves lights/comms faults. Opening a meeting exits vents, stops movement/observations and invalidates unfinished task attempts. A critical deadline is checked before an attempted late repair. Dead crew retain task obligations when ghost tasks are enabled; voluntary departures retire their tasks while preserving final roster history.
