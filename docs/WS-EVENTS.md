# WebSocket protocol v1 — implemented B/C extension

Route `/ws/rooms/{CODE}/`. First frame `{type:"auth",token:"..."}` within 10s. No token in URL. Origin must exactly match `CORS_ALLOWED_ORIGINS`. Auth success sends `auth.ok {player_id}`, `room.snapshot {room}`, then for started matches the backward-compatible private `game.started` followed by public `game.snapshot` and private `game.self`. Both versioned game DTOs include `protocol_version:1`, `game_id`, `state_version`. Ignore snapshots older than the current version. Unknown commands return `BAD_PAYLOAD`.

## Client commands

| type | Fields | Server checks |
|---|---|---|
| player.move | seq: positive safe integer, direction:{x,y} finite numbers in [-1,1] | alive, playing, increasing seq, 10/s token bucket, burst2; no trusted coordinates |
| task.begin | task_id:UUID | owner, crew, alive, playing, within85px; creates a one-use challenge/timestamp |
| task.complete | task_id:UUID, solution:number[] | same checks, minimum3s wires/sequence or8s upload; exact server challenge; once only |
| player.kill | target_player_id:UUID | impostor, both alive, target crew, ≤90px,25s cooldown,playing |
| body.report | body_id:UUID | alive,playing,unreported,≤110px |
| meeting.call | none | alive,playing,within85px of central console,once/match |
| vote.cast | target_player_id:UUID or null | alive, voting stage, target alive, one immutable vote; null is Skip |
| ping | none | renews connection lease; pong reply |

All identities come from auth, never a submitted player_id. Maximum16KiB text frames; per-connection20 commands/s plus durable movement token bucket (10/s, capacity2). Initial cooldown25s. Input expires after350ms without refresh; simulation caps delayed tick at150ms and uses20ms collision substeps. Commands do not decide elapsed movement time. Browser sends input at10Hz. Clock `run_game_worker` runs independently at10Hz and serializes on Room then Game locks. Restart recovers DB phases/timers/roles.

## Server DTOs

`game.snapshot`: `{protocol_version:1,game_id,state_version,server_time,phase,players:[{id,nickname,x,y,alive}],bodies:[{id,player_id,x,y}],tasks_completed,tasks_total,meeting,last_meeting_result,result?}`. Public DTO has **no roles, assignments, challenges, tokens or kill actor** while a game is active. `phase` is playing/meeting/finished. `meeting` is null or `{id,reporter_id,stage,deadline_at,votes_cast,alive_voters,result}`; `stage` is discussion/voting/result. Vote target totals appear only at result. Finished `result` is `{winner,reason,players_with_roles:[{id,nickname,role}]}`.

`game.self`: `{protocol_version:1,game_id,state_version,role,alive,last_move_seq,kill_available_at,emergency_used,has_voted,tasks:[{id,task_type,task_point,is_completed,started_at,challenge,x,y,seconds,point,type}]}`. Only that authenticated player receives it. Tasks are wires/sequence/upload. A begin challenge has 3 wire connector destination indices, or4 sequence indices0–3, or[] for upload. Complete requires the same index array after minimum time. Moving out of range cancels unfinished attempts; meetings invalidate them. This verifies assignment, position, duration and submitted solution; it **does not attest human interaction** or prevent a custom client automating a known challenge.

`game.started` retains Stage A shape (role/tasks owner-only). `room.snapshot` retains the unchanged public Room DTO. Additive events (with protocol_version1): `player.moved {player_id,x,y,seq}`, `player.died {player_id}`, `body.spawned {body_id,x,y}`, `task.progress {completed,total}`, `meeting.started {meeting_id}` (snapshot supplies deadlines), `vote.updated {votes_cast,alive_voters}`, `meeting.ended {ejected_player_id,counts,next_phase}`, `game.ended {winner,reason,players_with_roles}`. Events are accompanied by authoritative snapshots; consume snapshots to recover missed events. UI uses server time offset and never advances phases itself.

## Rules / explicit contract decisions

- Self-votes allowed. Tied candidates or Skip ≥ leading candidate → no ejection. Strictly greater unique candidate → ejection. All living votes may finish early; otherwise30s discussion,30s voting,5s result. No built-in chat; friends discuss over their chosen communication channel.
- Dead crew cannot do tasks, so their remaining task obligations retire from the required total. Alive crew retain3 tasks. Kill/ejection/departure re-evaluates victory. Atomic order: no impostors→crew, parity→impostor, all active tasks complete→crew. No automatic win at start.
- Explicit leave removes membership, retains historical game state and marks the player dead. Host transfers. Disconnect alone does not kill or remove membership. Finished rooms keep match history; no rematch mutates a previous game.
- Multiple tabs allowed with independent45s leases; ping every15s. Old-tab disconnect cannot clear another live lease. Clock clears expired leases. Presence is advisory, never eligibility.
- `error {code,detail}` codes: BAD_PAYLOAD, UNAUTHORIZED, FORBIDDEN, INVALID_PHASE, STALE_SEQ, RATE_LIMITED, OUT_OF_RANGE, COOLDOWN, ALREADY_DONE, TOO_EARLY, BAD_SOLUTION, SERVICE_UNAVAILABLE. Auth failures close4401, invalid JSON4400, oversize1009, service outage1013.
- Map JSON is shared byte-for-byte (`game/map.json` / `src/features/game/engine/map.json`). Version1 is1600×900,28px hitbox,150px/s. CI compares both copies; change the version and both copies together.
