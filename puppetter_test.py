import asyncio
from pyppeteer import launch

async def request_callback(request):
    print("REQ")
    print(request.url)
    await request.continue_()


async def main():
    browser = await launch()
    page = await browser.newPage()
    await page.setRequestInterception(True)

    page.on("request", request_callback)

    # await page.tracing.start({"path": "trace.json"})
    await page.goto("https://en.wikipedia.org")
    print("DONE!")
    # await page.tracing.stop()


asyncio.get_event_loop().run_until_complete(main())
