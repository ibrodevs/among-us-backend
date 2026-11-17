"""Real HTTP/WS smoke test for a disposable API + clock + PostgreSQL/Redis stack.

Install the optional test client: pip install 'websockets>=15,<17'.
No guest token is printed or saved. Created memberships are cleaned up.
"""

import argparse
import asyncio
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from websockets.asyncio.client import connect


def post(base, path, body, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Guest " + token
    request = Request(
        base + path, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    with urlopen(request, timeout=15) as response:
        return json.load(response) if response.status != 204 else None


async def receive_type(socket, kind):
    for _ in range(100):
        message = json.loads(await asyncio.wait_for(socket.recv(), 5))
        if message["type"] == "error":
            raise AssertionError("WebSocket error: " + message["code"])
        if message["type"] == kind:
            return message
    raise AssertionError("Missing event: " + kind)


async def check(base):
    guests, code = [], None
    try:
        for index in range(4):
            guest = await asyncio.to_thread(
                post, base, "/api/v1/guests/", {"nickname": "ContainerQA" + str(index)}
            )
            guests.append(guest)
            if code is None:
                room = await asyncio.to_thread(
                    post, base, "/api/v1/rooms/", {"max_players": 4}, guest["token"]
                )
                code = room["code"]
            else:
                await asyncio.to_thread(
                    post, base, "/api/v1/rooms/join/", {"code": code}, guest["token"]
                )
        started = await asyncio.to_thread(
            post, base, f"/api/v1/games/{code}/start/", {}, guests[0]["token"]
        )
        assert started["status"] == "playing"
        ws_url = (
            base.replace("https://", "wss://").replace("http://", "ws://")
            + f"/ws/rooms/{code}/"
        )
        async with connect(ws_url, origin="http://localhost:3000") as socket:
            await socket.send(
                json.dumps(
                    {"type": "auth", "token": guests[0]["token"], "protocol_version": 2}
                )
            )
            await receive_type(socket, "auth.ok")
            snapshot = await receive_type(socket, "game.snapshot")
            assert all("role" not in p for p in snapshot["players"])
            assert all("role" not in p for p in snapshot.get("roster", []))
            own = await receive_type(socket, "game.self")
            assert own["role"] in ("crew", "impostor")
            before = own
            await socket.send(
                json.dumps(
                    {
                        "type": "player.move",
                        "seq": own["last_move_seq"] + 1,
                        "direction": {"x": 1, "y": 0},
                    }
                )
            )
            for _ in range(30):
                after = await receive_type(socket, "game.self")
                if after["x"] > before["x"]:
                    break
            assert 0 < after["x"] - before["x"] <= 55.1, (before["x"], after["x"])
            print(
                "PASS: real REST start, private role and server movement across API/clock containers with PostgreSQL + Redis"
            )
    finally:
        if code:
            for guest in guests:
                try:
                    await asyncio.to_thread(
                        post, base, f"/api/v1/rooms/{code}/leave/", {}, guest["token"]
                    )
                except (HTTPError, OSError):
                    pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    asyncio.run(check(parser.parse_args().url.rstrip("/")))
