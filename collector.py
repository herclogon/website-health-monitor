import argparse
import concurrent
import logging
import queue
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Queue
from pathlib import Path

import requests

# Preventing 'Unverified HTTPS request is being made' warning.
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings()


logging.basicConfig(level=logging.INFO)

log = logging.getLogger(__name__)


class Collector:
    requests = {}
    history = set()

    def __init__(self, url, useragent=None, concurrency=1):
        self.start_url = url
        self.history = set()
        self.useragent = useragent
        self.concurrency = concurrency

    def get_links(self, url, parent):
        """Get all 'href' links from the resource (web-page) located by URL.
        
        Arguments:
            url {str} -- Page download URL.
            parent {str} -- Pagent page URL.
        
        Returns:
            [type] -- url, parent, duration, response_code, links
        """
        start = time.time()
        page = requests.get(url, verify=False, timeout=10)
        response_code = page.status_code
        response_reason = page.reason
        duration = time.time() - start
        links = []
        
        try:
            soup = BeautifulSoup(page.text, "html.parser")
        except TypeError:
            # Work-around to prevent fail.
            log.error(f"HTML parser can't data from '{url}'")
            soup = BeautifulSoup("", "html.parser")
        
        for link in soup.findAll("a"):
            href = str(link.get("href"))
            if href.startswith("/"):
                links.append(self.start_url + href)
            if href.startswith(self.start_url):
                links.append(href)
        return url, parent, duration, response_code, links, response_reason

    def get_links_by_lynx(self, url, parent):
        start = time.time()
        cmd = [
            "bash",
            "-c",
            f'lynx -useragent="{self.useragent}" -dump -listonly {url} | grep "{self.start_url}" | sed "s/^.*http/http/"',
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        stdout, stderr = proc.communicate()
        duration = time.time() - start
        links = list(filter(None, stdout.decode("utf-8").split("\n")))
        return url, parent, duration, 0, links

    def collect(self):
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            future = executor.submit(self.get_links, self.start_url, "")
            self.requests[future] = self.start_url

            while len(self.requests):
                for future in list(self.requests):
                    if not future.done():
                        continue

                    done_url = self.requests[future]
                    del self.requests[future]
                    url, parent, duration, response_code, links, response_reason = future.result(
                        timeout=1
                    )

                    prefix_text = f"{response_code}, {round(duration, 2)}s, {len(links)}, {len(self.requests)}:"
                    if response_code != 200:
                        message = prefix_text + f" {done_url} <- ERROR: {response_reason}, parent: {parent}"
                    else:
                        message = prefix_text + f" {done_url}"
                    print(message)

                    for link in links:
                        if (
                            # Prevent searching inside another domain and already
                            # visited links.
                            link.startswith(self.start_url)
                            and link not in self.history
                        ):
                            self.history.add(link)
                            future = executor.submit(self.get_links, link, url)
                            self.requests[future] = link
                time.sleep(0.1)


if __name__ == "__main__":
    """
    Creates a new argument parser.
    """
    parser = argparse.ArgumentParser()
    version = "0.0.1"
    parser.add_argument("--version", "-v", action="version", version=version)
    parser.add_argument("--url", "-u", type=str, help="URL to the target web-site")
    parser.add_argument(
        "--concurrency", "-c", type=int, help="Number of cuncurrent requests", default=1
    )
    parser.add_argument(
        "--useragent",
        type=str,
        help="user custom user agent",
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_0) AppleWebKit/537.1 (KHTML, like Gecko) Chrome/21.0.1180.79 Safari/537.1",
    )

    args = parser.parse_args()
    if not args.url:
        parser.print_help()
        exit(1)

    collector = Collector(
        args.url, useragent=args.useragent, concurrency=args.concurrency
    )
    collector.collect()

    # args1 = parser.parse_args(args)

    # print(args)
