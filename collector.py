# TODO(dmitry.golubkov): Write to sitemap file thread-safe.

import argparse
import asyncio
import concurrent
import datetime
import hashlib
import html
import logging
import os
import queue
import re
import subprocess
import threading
import time
import urllib
import urllib.request
import urllib.robotparser
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from multiprocessing import Pool as ThreadPool
from multiprocessing import Queue
from pathlib import Path
import signal
import sys

import pyppeteer
import requests

# Preventing 'Unverified HTTPS request is being made' warning.
import urllib3
from bs4 import BeautifulSoup
from pyppeteer import launch
from syncer import sync

import obtainers.pyppeteer

urllib3.disable_warnings()

logging.basicConfig(level=logging.INFO)
logging.getLogger("pyppeteer").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)


log = logging.getLogger(__name__)

start_url = ""

now = datetime.datetime.now()


class MyProcessPoolExecutor(ProcessPoolExecutor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._running_workers = 0

    def submit(self, *args, **kwargs):
        future = super().submit(*args, **kwargs)
        self._running_workers += 1
        future.add_done_callback(self._worker_is_done)
        return future

    def _worker_is_done(self, future):
        self._running_workers -= 1

    def get_pool_usage(self):
        return self._running_workers


class Collector:
    # Keep Future(s) of active requests.
    requests = set()

    # sitemapFile
    sitemapFile = "sitemap.xml"

    # Keep history of all visited URLs.
    history = set()
    concurrency = 1
    max_duration = 6
    useragent = ""

    def __init__(self, url):
        self.start_url = url
        self.history = set()

        # robot_txt_url = f"{self.start_url}/robots.txt"
        # log.debug("robots.txt: url = %s", robot_txt_url)
        # self.robot_txt = urllib.robotparser.RobotFileParser()
        # self.robot_txt.set_url(robot_txt_url)
        # self.robot_txt.read()

        # rrate = self.robot_txt.request_rate("*")
        # log.debug("robots.txt: requests = %s", rrate.requests)
        # log.debug("robots.txt: seconds = %s", rrate.seconds)
        # log.debug("robots.txt: crawl_delay = %s", self.robot_txt.crawl_delay("*"))

    # >>> rp.can_fetch("*", "http://www.musi-cal.com/cgi-bin/search?city=San+Francisco")
    # False
    # >>> rp.can_fetch("*", "http://www.musi-cal.com/")
    # True

    def collect(self):
        self.executor = MyProcessPoolExecutor(self.concurrency)

        # if os.path.exists(self.sitemapFile):
        #     os.remove(self.sitemapFile)

        # with open(self.sitemapFile, "a") as f:
        #     f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        #     f.write('<urlset xmlns="https://www.sitemaps.org/schemas/sitemap/0.9">\n')

        # with open(self.sitemapFile, "a") as f:
        #     f.writelines(["</urlset>"])

        # async def start(executor):
        #     return await asyncio.get_event_loop().run_in_executor(
        #         executor, obtainers.pyppeteer.get_links, self.start_url, ""
        #     )

        def shutdown():
            self.executor.shutdown()
            sys.exit()

        self._add_url(self.start_url, "")
        asyncio.get_event_loop().add_signal_handler(signal.SIGINT, shutdown)
        asyncio.get_event_loop().run_forever()

        print(f"Well done, {len(self.history)} URLs processed.")

    def _add_url(self, url, parent):
        future = asyncio.get_event_loop().run_in_executor(
            self.executor, obtainers.pyppeteer.get_links, url, parent
        )

        future.add_done_callback(self._furute_done_callback)

    def _furute_done_callback(self, future):
        # print(threading.current_thread())
        # print(future.result())
        result = future.result()

        url = result["url"]
        parent_url = result["parent_url"]
        duration = result["duration"]
        response_code = result["response_code"]
        response_reason = result["response_reason"]
        response_size = result["response_size"]
        response_content_type = result["response_content_type"]
        links = result["links"]
        process_name = result["process_name"]

        prefix_text = (
            f"{process_name}: {response_code}, {round(response_size/1024/1024, 2)}M,"
            f" {round(duration, 2)}s, {len(links)}, {self.executor.get_pool_usage()}:"
        )

        if response_code != 200:
            message = (
                f"{prefix_text} {url} <- ERROR: {response_reason}, parent: {parent_url}"
            )
        else:
            if "text/html" in response_content_type:
                # with open(self.sitemapFile, "a") as f:
                #     f.write(f"<url>\n")
                #     f.write(f"  <loc>{html.escape(url)}</loc>\n")
                #     f.write(f"  <changefreq>weekly</changefreq>\n")
                #     f.write(f"  <priority>1</priority>\n")
                #     f.write(f"</url>\n")
                message = prefix_text + f" {url}"

        print(message)

        for link in links:
            # Strip hash "http://www.address.com/something<#something>"
            link = link.split("#")[0]

            # Do not process foreign domains.
            if not link.startswith(self.start_url):
                continue

            # Skip processing already queued link.
            if link in self.history:
                continue

            self.history.add(link)
            self._add_url(link, url)

        # Remove already done request from the list.
        self.requests.remove(future)


if __name__ == "__main__":
    """
    Creates a new argument parser.
    """
    parser = argparse.ArgumentParser()
    version = "0.0.1"
    parser.add_argument("--version", "-v", action="version", version=version)
    parser.add_argument(
        "url",
        nargs=1,
        type=str,
        help="URL to the target web-site (http://example.com')",
    )
    parser.add_argument(
        "--concurrency", "-c", type=int, help="Number of concurrent requests", default=1
    )
    parser.add_argument(
        "--max_duration", "-d", type=int, help="Max response duration", default=6
    )
    parser.add_argument(
        "--useragent",
        type=str,
        help="User agent uses for requests.",
        default="User-Agent: LinkCheckerBot / 0.0.1",
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

    collector = Collector(args.url[0])
    collector.useragent = args.useragent
    collector.concurrency = args.concurrency
    collector.max_duration = args.max_duration
    collector.sitemapFile = args.sitemap
    collector.collect()
