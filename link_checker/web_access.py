import json
import os
import pathlib

from aiohttp import web

from . import models


async def handle(request):
    links = [
        link.json()
        for link in list(
            models.Link.select()
            .where(models.Link.response_code >= 400)
            .order_by(models.Link.parent)
        )
    ]
    return web.Response(text=json.dumps(links))


file_dir = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
static_dir = file_dir / "ui"

app = web.Application()
app.add_routes([web.get("/api/links/", handle), web.get("/{name}", handle)])
app.add_routes([web.static("/ui/", static_dir)])


def start():
    web.run_app(app)