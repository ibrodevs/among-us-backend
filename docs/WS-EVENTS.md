# Stage A WebSocket events

Compatible with [frontend API-CONTRACT.md](https://github.com/ibrodevs/among-us-frontend/blob/main/docs/API-CONTRACT.md). This document describes the implemented stage A subset; commands for stages B/C remain `NOT_IMPLEMENTED`.

## Connection and authentication

Connect to `/ws/rooms/ABC234/` and send a JSON text frame within 10 seconds:

```json
{"type":"auth","token":"<signed guest token>"}
```

The token belongs in this frame, never the URL. The server validates its signature, 24-hour lifetime and current room membership before subscribing to either group. Authentication cannot change identities within an existing connection.

The server replies in this order:

```json
{"type":"auth.ok","player_id":"c2a3f506-65ee-4d65-8564-769f1a394372"}
{"type":"room.snapshot","room":{"id":"cd17c1f3-519c-44a3-85ec-dc7778ecc67a","code":"ABC234","status":"playing","min_players":4,"max_players":10,"host_player_id":"c2a3f506-65ee-4d65-8564-769f1a394372","players":[{"id":"c2a3f506-65ee-4d65-8564-769f1a394372","nickname":"Player0","is_host":true,"is_connected":true}],"created_at":"2026-11-12T06:00:00Z"}}
```

The example abbreviates `players` to one entry; the actual snapshot contains every member. `room` is the existing `RoomSerializer` DTO, unchanged, without roles, tokens or assignments.

If this member already has a match state, a private `game.started` follows immediately. A member waiting in the lobby receives it after a successful host start.

## Private start and reconnect

Only the authenticated owner receives this message:

```json
{"type":"game.started","game_id":"56483341-a306-4c55-99c9-85c805680741","room_code":"ABC234","started_at":"2026-11-12T06:01:00+00:00","state_version":1,"role":"crew","tasks":[]}
```

Another connection receives its own role, potentially `impostor`. Names do not determine roles. Stage A creates no assignments, so `tasks` starts empty; the schema and owner-filtered serializer are ready for later assignments.

Reconnect to the same route with the same valid token. The server reads the existing DB state and replays `auth.ok`, the current public room and the same private `game.started`; it never rerolls roles. Subscribe-before-read also covers a start racing with authentication. A start event can be delivered more than once during this race: clients should replace their state using `(game_id, state_version)` rather than append assignments.

```ts
type OwnTask = {
  id: string;
  task_type: string;
  task_point: string;
  is_completed: boolean;
};

type GameStarted = {
  type: "game.started";
  game_id: string;
  room_code: string;
  started_at: string; // ISO 8601 UTC
  state_version: number;
  role: "crew" | "impostor";
  tasks: OwnTask[];
};
```

## Delivery and privacy

- `room_<CODE>` receives only `{"type":"room.snapshot","room":<public Room DTO>}` after the start transaction commits.
- `game_<CODE>_player_<UUID>` is a private group joined only after membership authentication. All authenticated tabs belonging to that player may receive the same own state.
- The private channel-layer notification is only `{"type":"game.started"}`. Its handler checks membership again and loads the role and assignments for the connection's authenticated player. No role map, token or caller-provided player identity is used.
- The public handler also checks membership and serializes the current public room before sending. An unauthenticated connection joins neither group.
- A disconnect preserves the roster, match, role and coordinates. The existing `is_connected` boolean is advisory presence, not match eligibility or an authoritative connection count.

Notifications run with `transaction.on_commit`. A DB failure rolls back the room, match and player states together and returns safe REST `503` detail. A Redis failure after commit leaves a valid match; reconnect recovers its state once Redis is available. No durable event queue is introduced in stage A.

## Other messages and errors

```json
{"type":"ping"}
{"type":"pong"}
{"type":"error","code":"UNAUTHORIZED","detail":"Invalid guest or room"}
```

| Condition | Error code | Close code |
| --- | --- | --- |
| Missing/invalid/expired token, missing room, non-member, membership removed | `UNAUTHORIZED` | `4401` |
| No auth within 10 seconds or first message is not auth | `UNAUTHORIZED` | `4401` |
| Second auth after success | `ALREADY_AUTHENTICATED` | Connection remains open |
| Invalid JSON or binary frame | `BAD_PAYLOAD` | `4400` |
| Text frame larger than 16 KiB | `BAD_PAYLOAD` | `1009` |
| Invalid JSON object/type after auth | `BAD_PAYLOAD` | Connection remains open |
| DB or channel-layer unavailable during auth/event handling | `SERVICE_UNAVAILABLE` | `1013` (retry later) |
| Unknown or stage B/C command | `NOT_IMPLEMENTED` | Connection remains open |

Movement, kill, report, task completion, meetings, voting, public game simulation snapshots and timers are outside stage A. No win evaluation runs at start.
