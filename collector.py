# TODO(dmitry.golubkov): Write to sitemap file thread-safe.

import argparse
import concurrent
import logging
import queue
import re
import subprocess
import time
import hashlib

from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from multiprocessing import Queue
from pathlib import Path
import datetime
import os
import urllib
import requests

import urllib.robotparser

import asyncio
import pyppeteer

is_url_regex = re.compile(
    r"^(?:http|ftp)s?://"  # http:// or https://
    r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|"  # domain...
    r"localhost|"  # localhost...
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # ...or ip
    r"(?::\d+)?"  # optional port
    r"(?:/?|[/?]\S+)$",
    re.IGNORECASE,
)

# Preventing 'Unverified HTTPS request is being made' warning.
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings()

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("pyppeteer").setLevel(logging.ERROR)
logging.getLogger("websockets").setLevel(logging.ERROR)

log = logging.getLogger(__name__)

start_url = ""

now = datetime.datetime.now()


async def _get_links_by_pyppeteer_async(url, parent_url):
    links = set()

    start = time.time()
    page = requests.get(url, verify=False, timeout=600)
    response_code = page.status_code
    response_reason = page.reason
    response_size = len(page.content)
    duration = time.time() - start

    response_content_type = ""
    if "content-type" in page.headers:
        response_content_type = page.headers["content-type"]

    if "content-type" in page.headers and "text/html" in page.headers["content-type"]:
        # # Collect all links from the page.
        # soup = BeautifulSoup(page.text, "html.parser")
        # for link in soup.findAll("a"):
        #     href = str(link.get("href"))
        #     absolute_url = urllib.parse.urljoin(start_url, href)
        #     links.add(absolute_url)

        # Collect all resources.
        try:
            browser = await pyppeteer.launch({"headless": True})
            context = await browser.createIncognitoBrowserContext()
            py_page = await context.newPage()
            await py_page.setRequestInterception(True)

            async def request_callback(request):
                links.add(request.url)
                await request.continue_()

            py_page.on("request", request_callback)
            # Select all non-empty links.
            a_href_elems = await py_page.querySelectorAllEval(
                "a", "(nodes => nodes.map(n => n.href))"
            )

            for href in a_href_elems:
                if re.match(is_url_regex, href) is not None:
                    links.add(href)

            await browser.close()
        except pyppeteer.errors.NetworkError as error:
            response_code = 902
            response_reason = f"Browser network exception."
            log.error(error)
        except Exception as error:
            response_code = 903
            response_reason = f"Unknown exception {error}"
            log.error(error)

        if duration > 10:
            response_code = 900
            response_reason = f"Too slow response"

    result = {
        "url": url,
        "parent_url": parent_url,
        "duration": duration,
        "response_code": response_code,
        "response_reason": response_reason,
        "response_size": response_size,
        "response_content_type": response_content_type,
        "links": links,
    }
    return result


def _get_links_by_pyppeteer_io(*args, **kwargs):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return asyncio.get_event_loop().run_until_complete(
        _get_links_by_pyppeteer_async(*args, **kwargs)
    )


class Collector:
    # Keep Future(s) of active requests.
    requests = set()

    # sitemapFile
    sitemapFile = "sitemap.xml"

    # Keep history of all visited URLs.
    history = set()
    concurrency = 1
    max_duration = 6
    useragent = "User-Agent: LinkCheckerBot / 0.0.1 Check links on your website"

    def __init__(self, url):
        self.start_url = url
        self.history = set()

        robot_txt_url = f"{self.start_url}/robots.txt"
        log.debug("robots.txt: url = %s", robot_txt_url)
        self.robot_txt = urllib.robotparser.RobotFileParser()
        self.robot_txt.set_url(robot_txt_url)
        self.robot_txt.read()

        rrate = self.robot_txt.request_rate("*")
        log.debug("robots.txt: requests = %s", rrate.requests)
        log.debug("robots.txt: seconds = %s", rrate.seconds)
        log.debug("robots.txt: crawl_delay = %s", self.robot_txt.crawl_delay("*"))

    # >>> rp.can_fetch("*", "http://www.musi-cal.com/cgi-bin/search?city=San+Francisco")
    # False
    # >>> rp.can_fetch("*", "http://www.musi-cal.com/")
    # True

    def _get_links_by_soap(self, url, parent):
        """Get all 'href' links from the resource (web-page) located by URL.

        Arguments:
            url {str} -- Page download URL.
            parent {str} -- Parent page URL.

        Returns:
            [type] -- url, parent, duration, response_code, links
        """
        start = time.time()
        headers = {"User-Agent": self.useragent}
        page = requests.get(url, verify=False, timeout=60, headers=headers)
        response_code = page.status_code
        response_reason = page.reason
        response_size = len(page.content)
        response_content_type = page.headers["content-type"]
        duration = time.time() - start
        links = []

        if "text/html" in response_content_type:
            soup = BeautifulSoup(page.text, "html.parser")
            if duration > self.max_duration:
                response_code = 900
                response_reason = f"Too slow response"
        else:
            soup = BeautifulSoup("", "html.parser")

        for link in soup.findAll("a"):
            href = str(link.get("href"))
            absolute_url = urllib.parse.urljoin(self.start_url, href)
            links.append(absolute_url)

        for link in soup.findAll("img"):
            href = str(link.get("src"))
            absolute_url = urllib.parse.urljoin(self.start_url, href)
            links.append(absolute_url)

        # for link in soup.findAll("script"):
        #     href = str(link.get("src"))
        #     absolute_url = urllib.parse.urljoin(self.start_url, href)
        #     links.append(absolute_url)

        # for link in soup.findAll("link"):
        #     href = str(link.get("href"))
        #     absolute_url = urllib.parse.urljoin(self.start_url, href)
        #     links.append(absolute_url)

        return (
            url,
            parent,
            duration,
            response_code,
            response_reason,
            response_size,
            response_content_type,
            links,
        )

    def _get_links_by_pyppeteer(self, url, parent):
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_get_links_by_pyppeteer_io, url, parent)
            while not future.done():
                time.sleep(0.1)

            return future.result()

    def _get_links_by_lynx(self, url, parent):
        start = time.time()
        cmd = [
            "bash",
            "-c",
            f'lynx -useragent="{self.useragent}" -dump -listonly {url} | grep "{self.start_url}" | sed "s/^.*http/http/"',
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        stdout, _ = proc.communicate()
        duration = time.time() - start
        links = list(filter(None, stdout.decode("utf-8").split("\n")))
        return url, parent, duration, 0, links

    def collect(self):
        if os.path.exists(self.sitemapFile):
            os.remove(self.sitemapFile)

        with open(self.sitemapFile, "a") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<urlset xmlns="https://www.sitemaps.org/schemas/sitemap/0.9">\n')

        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            self.executor = executor
            future = executor.submit(self._get_links_by_pyppeteer, self.start_url, "")
            # future = executor.submit(self._get_links_by_soap, self.start_url, "")
            self.requests.add(future)
            future.add_done_callback(self._furute_done_callback)

            while len(self.requests):
                time.sleep(1)

        with open(self.sitemapFile, "a") as f:
            f.writelines(["</urlset>"])

        print(f"Well done, {len(self.history)} URLs processed.")

    def _furute_done_callback(self, future):
        class AttributeDict(dict):
            def __getattr__(self, attr):
                return self[attr]

            def __setattr__(self, attr, value):
                self[attr] = value

        page = AttributeDict(future.result(timeout=60))

        prefix_text = (
            f"{page.response_code}, {round(page.response_size/1024/1024, 2)}M,"
            f" {round(page.duration, 2)}s, {len(page.links)}, {len(self.requests)}:"
        )

        message = ""
        if page.response_code != 200:
            message = f"{prefix_text} {page.url} <- ERROR: {page.response_reason}, parent: {page.parent_url}"
        else:
            # if "text/html" in response_content_type:
            #     with open(self.sitemapFile, "a") as f:
            #         f.write(f"<url>\n")
            #         f.write(f"  <loc>{url}</loc>\n")
            #         # f.write(f"  <lastmod>{now.strftime('%Y-%m-%d')}</lastmod>\n")
            #         f.write(f"  <changefreq>weekly</changefreq>\n")
            #         f.write(f"  <priority>1</priority>\n")
            #         f.write(f"</url>\n")
            message = prefix_text + f" {page.url}"

        print(message)

        for link in page.links:
            # Do not process foreign domains.
            if not link.startswith(self.start_url):
                continue

            # Skip processing already queued link.
            if link in self.history:
                continue

            self.history.add(link)
            ex_future = self.executor.submit(
                self._get_links_by_pyppeteer, link, page.url
            )
            self.requests.add(ex_future)
            ex_future.add_done_callback(self._furute_done_callback)

        # Remove already done request from the list.
        self.requests.remove(future)


if __name__ == "__main__":
    """
    Creates a new argument parser.
    """
    parser = argparse.ArgumentParser()
    version = "0.0.1"
    parser.add_argument("--version", "-v", action="version", version=version)
    parser.add_argument("--url", "-u", type=str, help="URL to the target web-site")
    parser.add_argument(
        "--concurrency", "-c", type=int, help="Number of concurrent requests", default=1
    )
    parser.add_argument(
        "--max_duration", "-d", type=int, help="Max response duration", default=6
    )
    parser.add_argument(
        "--useragent",
        type=str,
        help="User custom user agent",
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_0) AppleWebKit/537.1 (KHTML, like Gecko) Chrome/21.0.1180.79 Safari/537.1",
    )
    parser.add_argument(
        "--sitemap",
        type=str,
        help="Generate sitemap xml-file during scan",
        default="sitemap.xml",
    )

    args = parser.parse_args()
    if not args.url:
        parser.print_help()
        exit(1)

    collector = Collector(args.url)
    collector.useragent = args.useragent
    collector.concurrency = args.concurrency
    collector.max_duration = args.max_duration
    collector.sitemapFile = args.sitemap
    collector.collect()
