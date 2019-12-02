import json
import os
import pathlib

from aiohttp import web

from . import models
from . import config


async def handle(request):
    # Create a new connection to the db.
    # Create connection on each request is necessary cause otherwise after
    # some time `peewee` will raise the error `peewee.InterfaceError: (0, '')`.
    config.db.connect()

    try:
        links = [
            link.json()
            for link in list(
                models.Link.select()
                .where(models.Link.response_code >= 400)
                .order_by(models.Link.parent)
            )
        ]
        return web.Response(text=json.dumps(links))

    finally:
        # Close db connection after request.
        if not config.db.is_closed():
            config.db.close()


file_dir = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
static_dir = file_dir / "ui"

app = web.Application()
app.add_routes([web.get("/api/links/", handle), web.get("/{name}", handle)])
app.add_routes([web.static("/ui/", static_dir)])


def start():
    web.run_app(app)
