"""Regression check: idle BZPOPMIN must outlast its five-second server timeout."""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from channels.layers import get_channel_layer


async def check():
    layer = get_channel_layer()
    channel = await layer.new_channel()
    try:
        try:
            await asyncio.wait_for(layer.receive(channel), timeout=6.5)
        except asyncio.TimeoutError:
            print(
                "PASS: idle channel survives Redis blocking-pop timeout without transport failure"
            )
    finally:
        if hasattr(layer, "close_pools"):
            await layer.close_pools()


asyncio.run(check())
