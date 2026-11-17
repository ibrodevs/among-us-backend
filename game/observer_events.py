"""Protocol-v2 events are derived exclusively from an already filtered observer view."""


def changes(previous, public, previous_own, own):
    events = []
    if previous is None:
        events.extend(
            [
                {
                    "type": "map.state",
                    "map_id": public["map_id"],
                    "map_version": 2,
                    "map_mode": public["map_mode"],
                },
                {"type": "game.settings", "settings": public["settings"]},
            ]
        )
    if previous is None or previous.get("doors") != public.get("doors"):
        events.append({"type": "door.state", "doors": public["doors"]})
    old = {s["id"]: s for s in (previous or {}).get("sabotages", [])}
    current = {s["id"]: s for s in public.get("sabotages", [])}
    for key, sabotage in current.items():
        if old.get(key) != sabotage:
            events.append(
                {
                    "type": "sabotage.updated" if key in old else "sabotage.started",
                    "sabotage": sabotage,
                }
            )
    for key in old.keys() - current.keys():
        failed = (public.get("result") or {}).get("reason") == old[key][
            "kind"
        ] + "_timeout"
        events.append(
            {
                "type": "sabotage.failed" if failed else "sabotage.resolved",
                "sabotage_id": key,
            }
        )
    if previous_own is None or any(
        previous_own.get(key) != own.get(key)
        for key in ["is_in_vent", "current_vent_id", "vent_connections"]
    ):
        events.append(
            {
                "type": "vent.state",
                "is_in_vent": own["is_in_vent"],
                "current_vent_id": own["current_vent_id"],
                "connections": own["vent_connections"],
            }
        )
    if previous_own and previous_own["alive"] and not own["alive"]:
        events.append({"type": "player.ghost"})
    if previous_own and previous_own.get("ability_state") != own.get("ability_state"):
        events.append({"type": "ability.result", "ability_state": own["ability_state"]})
    previous_messages = {
        (m["id"]) for m in ((previous or {}).get("meeting") or {}).get("messages", [])
    }
    for message in (public.get("meeting") or {}).get("messages", []):
        if message["id"] not in previous_messages:
            events.append({"type": "meeting.chat.message", "message": message})
    return [
        dict(
            protocol_version=2,
            state_version=public["state_version"],
            game_id=public["game_id"],
            **event
        )
        for event in events
    ]
