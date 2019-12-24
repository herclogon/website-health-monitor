import html
import json
import os
import pathlib

from aiohttp import web

from . import config, models


def generate_sitemap(links):
    output = '<?xml version="1.0" encoding="UTF-8"?>'
    output += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    output += "@URLS@"
    output += "</urlset>"

    sitemap_urls = ""
    for link in links:
        sitemap_urls += (
            f"<url>"
            f"<loc>{html.escape(link['url'])}</loc>"
            f"<lastmod>{link['date']}</lastmod>"
            f"</url>"
        )
    output = output.replace("@URLS@", sitemap_urls)
    return output


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


async def sitemap(request):
    start_url = request.rel_url.query["start_url"]

    excludes = []
    for key, val in request.rel_url.query.items():
        if key == "exclude":
            excludes += [val]

    # Create a new connection to the db.
    # Create connection on each request is necessary cause otherwise after
    # some time `peewee` will raise the error `peewee.InterfaceError: (0, '')`.
    config.db.connect()

    try:
        links = [
            link.json()
            for link in list(
                models.Link.select().where(
                    (models.Link.start_url == start_url)
                    & (models.Link.content_type.startswith("text/html"))
                    & (models.Link.response_code == 200)
                )
            )
        ]

        # Remove excluded urls.
        def exclude_filter(link):
            for exclude in excludes:
                if link.url.startswith(exclude):
                    return False
            return True

        links = list(filter(exclude_filter, links))
        return web.Response(text=generate_sitemap(links), content_type="text/xml")

    finally:
        # Close db connection after request.
        if not config.db.is_closed():
            config.db.close()


file_dir = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
static_dir = file_dir / "ui"

app = web.Application()
app.add_routes([web.get("/api/links/", handle), web.get("/{name}", handle)])
app.add_routes([web.get("/api/sitemap/", sitemap), web.get("/", sitemap)])
app.add_routes([web.static("/ui/", static_dir)])


def start():
    web.run_app(app)
