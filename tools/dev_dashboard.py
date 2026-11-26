"""Save a dashboard config to a storage-mode dashboard on ha-dev.

Usage: HA_TOKEN=... python tools/dev_dashboard.py WS_URL URL_PATH TITLE CONFIG.yaml

Creates the dashboard when it doesn't exist, then replaces its config. It
also warns about custom cards that have no frontend resource.
"""

import asyncio
import itertools
import json
import os
import re
import sys

import websockets
from ruamel.yaml import YAML


class Client:
    """A minimal Home Assistant WebSocket API client."""

    def __init__(self, ws: websockets.ClientConnection) -> None:
        self.ws = ws
        self.ids = itertools.count(1)

    async def call(self, message_type: str, **data: object) -> object:
        msg_id = next(self.ids)
        await self.ws.send(json.dumps({"id": msg_id, "type": message_type, **data}))
        while True:
            reply = json.loads(await self.ws.recv())
            if reply.get("id") == msg_id:
                break
        if not reply["success"]:
            raise RuntimeError(f"{message_type}: {reply['error']['message']}")
        return reply["result"]


async def save(ws_url: str, url_path: str, title: str, text: str) -> None:
    config = YAML(typ="safe").load(text)
    async with websockets.connect(ws_url, max_size=None) as ws:
        await ws.recv()  # auth_required
        await ws.send(
            json.dumps({"type": "auth", "access_token": os.environ["HA_TOKEN"]})
        )
        if json.loads(await ws.recv())["type"] != "auth_ok":
            raise SystemExit("Authentication failed")
        client = Client(ws)

        dashboards = await client.call("lovelace/dashboards/list")
        if not any(d["url_path"] == url_path for d in dashboards):
            await client.call(
                "lovelace/dashboards/create",
                url_path=url_path,
                title=title,
                icon="mdi:cash-clock",
                mode="storage",
                show_in_sidebar=True,
                require_admin=False,
            )
            print(f"Created dashboard /{url_path}")
        await client.call("lovelace/config/save", url_path=url_path, config=config)
        print(f"Saved the dashboard to /{url_path}")

        resources = " ".join(r["url"] for r in await client.call("lovelace/resources"))
        cards = set(re.findall(r"type: custom:([a-z0-9-]+)", text))
        for card in sorted(cards):
            if card not in resources:
                print(f"Warning: no frontend resource for custom:{card}")


def main() -> None:
    ws_url, url_path, title, config_path = sys.argv[1:5]
    with open(config_path) as f:
        text = f.read()
    asyncio.run(save(ws_url, url_path, title, text))


if __name__ == "__main__":
    main()
