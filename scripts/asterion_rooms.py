"""Authored Asterion 2.1 room passports. Local coordinates within each room envelope.

floor_parts defines walkable geometry. Props opt into collision independently;
art, lighting and audio never invent a second physics map.
"""

PROFILES = {
    # layout, floor, wall, accent, ambient, audio, props (kind,x,y,w,h)
    "reactor": (
        "octagonal-core",
        "reactor",
        "armored",
        "#ffbd64",
        "#3b2c30",
        "core",
        [
            ("core", 340, 185, 220, 150),
            ("capacitor", 95, 80, 90, 155),
            ("capacitor", 710, 95, 90, 145),
            ("cable", 190, 390, 195, 30),
            ("gauge", 665, 350, 90, 100),
            ("rail", 350, 400, 220, 25),
        ],
    ),
    "power": (
        "transformer-aisles",
        "industrial",
        "utility",
        "#ffd978",
        "#37332b",
        "electric",
        [
            ("transformer", 140, 80, 210, 110),
            ("transformer", 555, 325, 190, 110),
            ("switchboard", 615, 70, 155, 105),
            ("cable", 145, 350, 160, 40),
            ("battery", 385, 60, 110, 85),
            ("hazard", 390, 385, 100, 55),
        ],
    ),
    "engines": (
        "twin-turbine",
        "industrial",
        "ribbed",
        "#ff9b67",
        "#342e31",
        "turbine",
        [
            ("turbine", 100, 100, 230, 145),
            ("turbine", 565, 300, 230, 145),
            ("pipe", 610, 65, 150, 45),
            ("gauge", 365, 65, 110, 80),
            ("grate", 155, 360, 145, 55),
            ("cable", 390, 405, 110, 30),
        ],
    ),
    "cooling": (
        "coolant-elbow",
        "grating",
        "utility",
        "#83deff",
        "#243e49",
        "water",
        [
            ("tank", 110, 270, 140, 145),
            ("tank", 650, 75, 135, 155),
            ("pipe", 300, 65, 230, 45),
            ("pump", 375, 355, 140, 90),
            ("gauge", 640, 355, 85, 80),
            ("condensation", 280, 360, 60, 60),
        ],
    ),
    "maintenance": (
        "workshop-bays",
        "industrial",
        "utility",
        "#e3c582",
        "#37343a",
        "workshop",
        [
            ("workbench", 100, 90, 240, 105),
            ("robotarm", 600, 290, 160, 150),
            ("toolwall", 570, 65, 220, 70),
            ("parts", 110, 355, 150, 80),
            ("drone", 390, 70, 100, 100),
            ("locker", 345, 385, 80, 80),
        ],
    ),
    "bridge": (
        "command-bow",
        "command",
        "panoramic",
        "#89c7ff",
        "#26334c",
        "command",
        [
            ("commandtable", 340, 95, 220, 125),
            ("console", 105, 325, 160, 90),
            ("console", 635, 325, 160, 90),
            ("chair", 280, 100, 40, 65),
            ("chair", 590, 100, 40, 65),
            ("stationdisplay", 350, 385, 200, 60),
        ],
    ),
    "navigation": (
        "star-chart-wing",
        "command",
        "display",
        "#b4acff",
        "#302d4c",
        "compute",
        [
            ("starTable", 325, 90, 235, 130),
            ("computer", 120, 340, 155, 100),
            ("computer", 620, 330, 160, 100),
            ("projection", 120, 70, 135, 100),
            ("route", 350, 385, 190, 50),
            ("chair", 650, 85, 55, 65),
        ],
    ),
    "comms": (
        "signal-cells",
        "antistatic",
        "ribbed",
        "#88dce7",
        "#293b48",
        "radio",
        [
            ("radio", 120, 75, 180, 120),
            ("antenna", 620, 300, 170, 150),
            ("waveform", 555, 70, 220, 90),
            ("cable", 310, 390, 200, 30),
            ("recorder", 110, 345, 140, 90),
            ("rack", 370, 60, 110, 115),
        ],
    ),
    "security": (
        "observation-alcove",
        "command",
        "display",
        "#90b8ff",
        "#29344a",
        "surveillance",
        [
            ("monitorwall", 240, 55, 420, 100),
            ("chair", 390, 165, 60, 65),
            ("recorder", 110, 340, 150, 95),
            ("alarm", 695, 90, 60, 60),
            ("cabinet", 650, 345, 130, 80),
            ("console", 345, 385, 200, 70),
        ],
    ),
    "observatory": (
        "optical-dome",
        "observatory",
        "panoramic",
        "#c3a1ff",
        "#312d49",
        "space",
        [
            ("telescope", 315, 65, 240, 160),
            ("starTable", 150, 325, 170, 105),
            ("optics", 640, 325, 140, 120),
            ("planet", 650, 65, 100, 95),
            ("chair", 300, 365, 45, 70),
            ("route", 365, 405, 170, 35),
        ],
    ),
    "medical": (
        "treatment-suites",
        "medical",
        "clean",
        "#91f2d7",
        "#31444a",
        "medical",
        [
            ("scanner", 125, 80, 180, 150),
            ("bed", 590, 70, 160, 100),
            ("bed", 590, 335, 160, 100),
            ("medicine", 110, 350, 110, 80),
            ("lamp", 370, 70, 80, 80),
            ("cabinet", 330, 385, 160, 65),
        ],
    ),
    "laboratory": (
        "experiment-islands",
        "laboratory",
        "clean",
        "#c0d9ff",
        "#343b4a",
        "laboratory",
        [
            ("labbench", 110, 70, 215, 110),
            ("containment", 610, 305, 160, 140),
            ("microscope", 575, 70, 120, 100),
            ("reagents", 110, 350, 160, 90),
            ("centrifuge", 370, 70, 110, 110),
            ("sink", 350, 390, 155, 60),
        ],
    ),
    "biodome": (
        "garden-loop",
        "greenhouse",
        "glass",
        "#a4e59a",
        "#29483f",
        "garden",
        [
            ("garden", 320, 70, 250, 160),
            ("tree", 180, 325, 135, 115),
            ("garden", 635, 315, 155, 130),
            ("irrigation", 105, 90, 130, 85),
            ("seeds", 650, 75, 115, 90),
            ("bench", 340, 405, 210, 35),
        ],
    ),
    "oxygen": (
        "filter-manifold",
        "medical",
        "utility",
        "#87e2cf",
        "#2c4146",
        "compressor",
        [
            ("filter", 105, 75, 180, 130),
            ("tank", 625, 310, 150, 130),
            ("compressor", 580, 70, 210, 110),
            ("pipe", 310, 405, 230, 30),
            ("gauge", 110, 345, 90, 85),
            ("ventilation", 350, 70, 150, 85),
        ],
    ),
    "quarters": (
        "residential-nooks",
        "residential",
        "panoramic",
        "#edc3a2",
        "#443a45",
        "home",
        [
            ("pod", 105, 70, 205, 100),
            ("sofa", 580, 340, 200, 90),
            ("table", 360, 355, 125, 100),
            ("vending", 650, 75, 95, 125),
            ("locker", 350, 70, 120, 90),
            ("plant", 120, 365, 70, 75),
        ],
    ),
    "cargo": (
        "loading-ring",
        "cargo",
        "armored",
        "#e8b384",
        "#3d3542",
        "cargo",
        [
            ("container", 105, 75, 230, 145),
            ("forklift", 615, 300, 150, 145),
            ("crane", 590, 65, 200, 100),
            ("crate", 105, 345, 140, 95),
            ("pallet", 330, 390, 170, 50),
            ("rails", 385, 60, 110, 100),
        ],
    ),
    "storage": (
        "shelving-switchback",
        "cargo",
        "utility",
        "#d4bc9d",
        "#393740",
        "ventilation",
        [
            ("shelf", 110, 70, 235, 105),
            ("shelf", 550, 350, 235, 95),
            ("pallet", 590, 70, 170, 115),
            ("cart", 110, 335, 120, 100),
            ("rack", 370, 70, 110, 95),
            ("crate", 335, 380, 130, 70),
        ],
    ),
    "data": (
        "server-aisles",
        "antistatic",
        "ribbed",
        "#90bcff",
        "#293748",
        "servers",
        [
            ("servers", 110, 70, 230, 120),
            ("servers", 555, 335, 230, 110),
            ("servers", 555, 70, 230, 110),
            ("fan", 120, 355, 105, 90),
            ("cable", 300, 395, 180, 30),
            ("computer", 375, 65, 100, 95),
        ],
    ),
    "transit": (
        "tram-platform",
        "transit",
        "ribbed",
        "#c1a4f2",
        "#333449",
        "transit",
        [
            ("tram", 105, 65, 235, 145),
            ("schedule", 600, 65, 165, 85),
            ("luggage", 110, 355, 140, 85),
            ("barrier", 580, 360, 205, 40),
            ("rails", 360, 390, 130, 65),
            ("signal", 735, 155, 45, 60),
        ],
    ),
    "airlock": (
        "pressure-chambers",
        "grating",
        "armored",
        "#ffb2a0",
        "#41383f",
        "pressure",
        [
            ("blastgate", 610, 70, 180, 130),
            ("suit", 120, 75, 130, 135),
            ("pressure", 350, 70, 150, 90),
            ("barrier", 135, 375, 220, 40),
            ("oxygenpack", 620, 345, 95, 95),
            ("alarm", 735, 355, 50, 50),
        ],
    ),
    "nexus": (
        "asterion-hub",
        "nexus",
        "display",
        "#83e4d9",
        "#2d414c",
        "nexus",
        [
            ("meetingtable", 340, 210, 220, 100),
            ("stationdisplay", 110, 75, 140, 75),
            ("stationdisplay", 650, 75, 140, 75),
            ("bench", 125, 360, 185, 65),
            ("bench", 590, 360, 185, 65),
            ("emblem", 350, 360, 200, 100),
        ],
    ),
}


# Collision-safe union contours: all four middle door mouths remain open.
def floor_parts(layout, rect):
    shapes = {
        "octagonal-core": [(100, 0, 700, 520), (0, 100, 900, 320), (50, 50, 800, 420)],
        "transformer-aisles": [(0, 65, 900, 390), (100, 20, 700, 480)],
        "twin-turbine": [(0, 100, 900, 320), (60, 30, 780, 460)],
        "coolant-elbow": [(0, 90, 900, 340), (80, 0, 820, 300), (290, 300, 610, 220)],
        "workshop-bays": [(0, 120, 900, 280), (50, 40, 360, 440), (380, 0, 470, 520)],
        "command-bow": [(0, 140, 900, 280), (80, 65, 740, 455), (180, 20, 540, 500)],
        "star-chart-wing": [
            (0, 120, 900, 310),
            (90, 20, 540, 500),
            (580, 70, 270, 450),
        ],
        "signal-cells": [(0, 145, 900, 235), (70, 30, 350, 460), (380, 0, 450, 520)],
        "observation-alcove": [(0, 130, 900, 300), (100, 20, 700, 480)],
        "optical-dome": [(0, 150, 900, 220), (55, 75, 790, 370), (150, 20, 600, 480)],
        "treatment-suites": [
            (0, 120, 900, 290),
            (70, 0, 360, 480),
            (400, 60, 430, 460),
        ],
        "experiment-islands": [
            (0, 120, 900, 290),
            (70, 20, 360, 480),
            (390, 0, 440, 520),
        ],
        "garden-loop": [(0, 150, 900, 230), (65, 70, 770, 380), (170, 10, 560, 500)],
        "filter-manifold": [(0, 110, 900, 320), (65, 35, 770, 450), (370, 0, 160, 520)],
        "residential-nooks": [
            (0, 120, 900, 290),
            (70, 15, 290, 485),
            (320, 60, 510, 460),
        ],
        "loading-ring": [(0, 100, 900, 340), (50, 35, 800, 450)],
        "shelving-switchback": [
            (0, 130, 900, 280),
            (70, 25, 320, 475),
            (350, 65, 480, 455),
        ],
        "server-aisles": [(0, 120, 900, 280), (80, 20, 740, 480)],
        "tram-platform": [(0, 80, 900, 360), (100, 35, 700, 450), (380, 0, 140, 520)],
        "pressure-chambers": [
            (0, 150, 900, 230),
            (75, 35, 300, 450),
            (335, 60, 490, 400),
            (375, 0, 150, 520),
        ],
        "asterion-hub": [(0, 140, 900, 240), (70, 65, 760, 390), (170, 0, 560, 520)],
    }
    # North/south door stems align exactly with the existing corridor anchors.
    return [
        rect(*p)
        for p in [
            *shapes[layout],
            (360, 0, 180, 520),
            (250, 0, 400, 180),
            (250, 340, 400, 180),
        ]
    ]


def apply_room_definitions(rooms, rect):
    extras = {
        "medical": [("partition", 490, 65, 22, 120), ("partition", 490, 335, 22, 110)],
        "quarters": [("partition", 285, 65, 20, 115), ("partition", 545, 340, 20, 120)],
        "airlock": [("partition", 300, 95, 24, 100), ("partition", 300, 335, 24, 100)],
        "maintenance": [("partition", 520, 325, 22, 130)],
    }
    decor = []
    for room in rooms:
        rid = room["id"]
        layout, material, wall, accent, ambient, audio, props = PROFILES[rid]
        b = room["bounds"]
        room["floor_parts"] = [
            {**p, "x": p["x"] + b["x"], "y": p["y"] + b["y"]}
            for p in floor_parts(layout, rect)
        ]
        parts = room["floor_parts"]
        xs = sorted({v for p in parts for v in [p["x"], p["x"] + p["width"]]})
        ys = sorted({v for p in parts for v in [p["y"], p["y"] + p["height"]]})
        inside = lambda x, y: any(
            p["x"] < x < p["x"] + p["width"] and p["y"] < y < p["y"] + p["height"]
            for p in parts
        )
        outline = []
        for x in xs:
            for y0, y1 in zip(ys, ys[1:]):
                if inside(x - 0.1, (y0 + y1) / 2) != inside(x + 0.1, (y0 + y1) / 2):
                    outline.append([x, y0, x, y1])
        for y in ys:
            for x0, x1 in zip(xs, xs[1:]):
                if inside((x0 + x1) / 2, y - 0.1) != inside((x0 + x1) / 2, y + 0.1):
                    outline.append([x0, y, x1, y])
        room["outline"] = outline
        room["visual"] = {
            "layoutId": layout,
            "floorMaterial": material,
            "wallMaterial": wall,
            "accentColor": accent,
            "ambientLight": ambient,
            "visualTheme": rid,
            "audioProfile": audio,
            "landmark": props[0][0],
            "windows": rid in ["bridge", "observatory", "quarters", "airlock"],
            "lightSources": [
                {"x": b["x"] + 130, "y": b["y"] + 255, "radius": 150},
                {"x": b["x"] + 770, "y": b["y"] + 255, "radius": 170},
            ],
            "animatedObjects": [rid + "-prop0", rid + "-prop1"],
        }
        for i, (kind, x, y, w, h) in enumerate([*props, *extras.get(rid, [])]):
            decor.append(
                dict(
                    id=f"{rid}-prop{i}",
                    kind=kind,
                    room_id=rid,
                    bounds=rect(b["x"] + x, b["y"] + y, w, h),
                    solid=kind
                    not in [
                        "cable",
                        "hazard",
                        "grate",
                        "condensation",
                        "route",
                        "irrigation",
                        "rails",
                        "emblem",
                        "signal",
                        "alarm",
                        "lamp",
                    ],
                    landmark=i == 0,
                )
            )
    return decor
