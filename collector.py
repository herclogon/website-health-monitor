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
from syncer import sync
import datetime
import os

import requests

import asyncio
import pyppeteer
from pyppeteer import launch

# Preventing 'Unverified HTTPS request is being made' warning.
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings()

logging.basicConfig(level=logging.INFO)
logging.getLogger("pyppeteer").setLevel(logging.CRITICAL)

log = logging.getLogger(__name__)

start_url = ""

now = datetime.datetime.now()


async def _get_links_by_pyppeteer_async(url, parent):
    links = set()

    start = time.time()
    page = requests.get(url, verify=False, timeout=60)
    response_code = page.status_code
    response_reason = page.reason
    response_size = len(page.content)
    duration = time.time() - start

    async def request_callback(request):
        links.add(request.url)
        await request.continue_()

    if "content-type" in page.headers and "text/html" in page.headers["content-type"]:
        # Collect all links from the page.
        soup = BeautifulSoup(page.text, "html.parser")
        for link in soup.findAll("a"):
            href = str(link.get("href"))
            if href.startswith("/"):
                links.add(start_url + href)
            if href.startswith(start_url):
                links.add(href)

        # # Collect all resources.
        # try:
        #     browser = await launch({"headless": False})
        #     page = await browser.newPage()
        #     await page.setRequestInterception(True)
        #     page.on("request", request_callback)
        #     await page.goto(url)
        #     await page.screenshot({"path": f"pic.jpg"})
        #     await browser.close()
        # except pyppeteer.errors.NetworkError as err:
        #     response_code = 902
        #     response_reason = f"Browser network exception"

        if duration > 2:
            response_code = 900
            response_reason = f"Too slow response"

    result = (
        url,
        parent,
        duration,
        response_code,
        response_reason,
        response_size,
        list(links),
    )
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
    max_duration = 2
    useragent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_0) AppleWebKit/537.1 (KHTML, like Gecko) Chrome/21.0.1180.79 Safari/537.1"

    def __init__(self, url):
        self.start_url = url
        self.history = set()

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
            if href.startswith("/"):
                links.append(self.start_url + href)
            if href.startswith(self.start_url):
                links.append(href)
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
            future = executor.submit(self._get_links_by_soap, self.start_url, "")
            self.requests.add(future)
            future.add_done_callback(self._furute_done_callback)

            while len(self.requests):
                time.sleep(1)

        with open(self.sitemapFile) as f:
            f.writelines(["</urlset>"])

        print(f"Well done, {len(self.history)} URLs processed.")

    def _furute_done_callback(self, future):
        (
            url,
            parent,
            duration,
            response_code,
            response_reason,
            response_size,
            response_content_type,
            links,
        ) = future.result(timeout=60)

        prefix_text = (
            f"{response_code}, {round(response_size/1024/1024, 2)}M,"
            f" {round(duration, 2)}s, {len(links)}, {len(self.requests)}:"
        )

        if response_code != 200:
            message = (
                f"{prefix_text} {url} <- ERROR: {response_reason}, parent: {parent}"
            )
        else:
            if "text/html" in response_content_type:
                with open(self.sitemapFile, "a") as f:
                    f.write(f"<url>\n")
                    f.write(f"  <loc>{url}</loc>\n")
                    # f.write(f"  <lastmod>{now.strftime('%Y-%m-%d')}</lastmod>\n")
                    f.write(f"  <changefreq>weekly</changefreq>\n")
                    f.write(f"  <priority>1</priority>\n")
                    f.write(f"</url>\n")
            message = prefix_text + f" {url}"

        print(message)

        for link in links:
            # Do not process foreign domains.
            if not link.startswith(self.start_url):
                continue

            # Skip processing already queued link.
            if link in self.history:
                continue

            self.history.add(link)
            ex_future = self.executor.submit(self._get_links_by_soap, link, url)
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
        "--max_duration", "-d", type=int, help="Max response duration", default=2
    )
    parser.add_argument(
        "--useragent",
        type=str,
        help="user custom user agent",
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_0) AppleWebKit/537.1 (KHTML, like Gecko) Chrome/21.0.1180.79 Safari/537.1",
    )
    parser.add_argument(
        "--sitemap",
        type=str,
        help="renerate sitemap xml file during scan",
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
