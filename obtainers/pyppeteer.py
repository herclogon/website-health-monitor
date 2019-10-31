import asyncio
import requests
import time
import pyppeteer
from pyppeteer import launch, errors
import re
import logging
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import threading
from multiprocessing import current_process

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("pyppeteer").setLevel(logging.ERROR)
logging.getLogger("websockets").setLevel(logging.ERROR)

log = logging.getLogger(__name__)

is_url_regex = re.compile(
    r"^(?:http|ftp)s?://"  # http:// or https://
    r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|"  # domain...
    r"localhost|"  # localhost...
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # ...or ip
    r"(?::\d+)?"  # optional port
    r"(?:/?|[/?]\S+)$",
    re.IGNORECASE,
)


class RequestResult:
    url = ""
    parent = ""
    duration = ""
    response_code = ""
    response_reason = ""
    response_size = None
    response_content_type = ""
    links = []


async def _obtain_resources(url: str, parent_url: str, user_agent: str):
    links = set()

    start = time.time()
    headers = {"User-Agent": user_agent}
    page = requests.get(url, verify=False, timeout=60, headers=headers)

    response_code = page.status_code
    response_reason = page.reason
    response_size = len(page.content)
    response_content_type = (
        page.headers["content-type"] if "content-type" in page.headers else "unknown"
    )
    duration = time.time() - start

    async def request_callback(request):
        links.add(request.url)
        await request.continue_()

    if "content-type" in page.headers and "text/html" in page.headers["content-type"]:
        try:
            browser = await pyppeteer.launch({"headless": True})
            py_page = await browser.newPage()
            py_page.on("request", request_callback)
            await py_page.setUserAgent(user_agent)
            await py_page.setRequestInterception(True)
            await py_page.goto(url)

            # Select all non-empty links.
            a_href_elems = await py_page.querySelectorAllEval(
                "a", "(nodes => nodes.map(n => n.href))"
            )

            for href in a_href_elems:
                if re.match(is_url_regex, href) is not None:
                    links.add(href)

        except pyppeteer.errors.NetworkError as error:
            response_code = 902
            response_reason = f"Browser network exception."
            log.error(error)

        except Exception as error:
            response_code = 903
            response_reason = f"Unknown exception {error}."
            log.error(error)

        finally:
            await browser.close()

        if duration > 10:
            response_code = 900
            response_reason = f"Too slow response."

    if response_content_type == "unknown":
        response_code = 904
        response_reason = f"No 'content-type' field in response header."

    result = {
        "url": url,
        "parent_url": parent_url,
        "duration": duration,
        "response_code": response_code,
        "response_reason": response_reason,
        "response_size": response_size,
        "response_content_type": response_content_type,
        "links": links,
        "process_name": current_process().name,
    }
    return result


def _get_links_by_pyppeteer_io(*args, **kwargs):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return asyncio.get_event_loop().run_until_complete(
        _obtain_resources(*args, **kwargs)
    )


def _get_links_by_pyppeteer(url, parent, user_agent):
    return _get_links_by_pyppeteer_io(url, parent, user_agent)


def get_links(*args, **kwargs) -> RequestResult:
    return _get_links_by_pyppeteer(*args, **kwargs)
