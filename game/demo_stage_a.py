"""Live local HTTP/WS acceptance demo; optional dependency: pip install websockets.

Run against a disposable development database. Creates four demo guests and one
started room. Tokens stay in memory and never appear in the saved evidence.
"""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from websockets.asyncio.client import connect


def assert_public(value):
    if isinstance(value, dict):
        assert not {"role", "roles", "role_map", "token", "tasks"}.intersection(value)
        for item in value.values():
            assert_public(item)
    elif isinstance(value, list):
        for item in value:
            assert_public(item)


async def run(base_url, ws_base_url=None):
    def request(method, path, *, token=None, data=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Guest " + token
        body = json.dumps(data or {}).encode() if method == "POST" else None
        req = Request(base_url + "/api/v1/" + path, data=body, headers=headers, method=method)
        try:
            response = urlopen(req, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    guests = []
    for i in range(4):
        status, guest = request("POST", "guests/", data={"nickname": f"Demo{i}"})
        assert status == 201
        guests.append(guest)
    host = guests[0]["token"]
    status, room = request("POST", "rooms/", token=host, data={"max_players": 10})
    assert status == 201
    code = room["code"]
    start_path = f"games/{code}/start/"
    no_auth, _ = request("POST", start_path)
    too_few, _ = request("POST", start_path, token=host)
    assert no_auth == 401 and too_few == 409
    for guest in guests[1:]:
        assert request("POST", "rooms/join/", token=guest["token"], data={"code": code})[0] == 200
    non_host, _ = request("POST", start_path, token=guests[1]["token"])
    assert non_host == 403

    ws_url = (ws_base_url or base_url).replace("http://", "ws://").replace("https://", "wss://") + f"/ws/rooms/{code}/"
    sockets = []
    try:
        for guest in guests:
            ws = await connect(ws_url, origin="http://localhost:3000")
            sockets.append(ws)
            await ws.send(json.dumps({"type": "auth", "token": guest["token"]}))
            auth = json.loads(await asyncio.wait_for(ws.recv(), 5))
            assert auth == {"type": "auth.ok", "player_id": guest["player_id"]}
            public = json.loads(await asyncio.wait_for(ws.recv(), 5))
            assert public["type"] == "room.snapshot"
            assert_public(public)

        started, public_room = request("POST", start_path, token=host)
        assert started == 200 and public_room["status"] == "playing"
        assert_public(public_room)
        clients = []
        for guest, ws in zip(guests, sockets):
            public = json.loads(await asyncio.wait_for(ws.recv(), 5))
            private = json.loads(await asyncio.wait_for(ws.recv(), 5))
            assert public["type"] == "room.snapshot" and public["room"]["status"] == "playing"
            assert_public(public)
            assert private["type"] == "game.started" and private["tasks"] == []
            clients.append({"nickname": guest["nickname"], "auth": "auth.ok", "own_state": private})
        assert sum(client["own_state"]["role"] == "impostor" for client in clients) == 1
        repeat, _ = request("POST", start_path, token=host)
        assert repeat == 409
        assert_public(request("GET", f"rooms/{code}/", token=host)[1])

        await sockets[0].close()
        async with connect(ws_url, origin="http://localhost:3000") as reconnected:
            await reconnected.send(json.dumps({"type": "auth", "token": host}))
            assert json.loads(await reconnected.recv())["type"] == "auth.ok"
            assert_public(json.loads(await reconnected.recv()))
            replay = json.loads(await reconnected.recv())
            assert replay == clients[0]["own_state"]

        report = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "transport": "Live HTTP and WebSocket over ASGI, PostgreSQL and Redis",
            "http": {"no_token": no_auth, "one_player": too_few, "non_host": non_host, "host_start": started, "repeat_start": repeat},
            "public_room": public_room,
            "authenticated_clients": clients,
            "reconnect_same_own_state": True,
            "public_payloads_have_no_secrets": True,
        }
        serialized = json.dumps(report)
        assert all(guest["token"] not in serialized for guest in guests)
        return report
    finally:
        for ws in sockets:
            await ws.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--ws-url", help="Optional second ASGI worker base URL to verify Redis delivery across processes")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evidence = json.dumps(asyncio.run(run(args.url.rstrip("/"), args.ws_url)), indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(evidence)
        print(f"Live stage A demo passed. Token-free evidence: {args.output}")
    else:
        print(evidence, end="")
