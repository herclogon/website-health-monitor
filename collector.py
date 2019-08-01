import subprocess
import queue
import time

import logging
import argparse

logging.basicConfig(level=logging.DEBUG)

log = logging.getLogger(__name__)


class Collector:
    class SetQueue(queue.Queue):
        history = set()

        def _init(self, maxsize):
            self.queue = set()

        def _put(self, item):
            # Add only new items
            if item not in self.history:
                self.history.add(item)
                self.queue.add(item)

        def _get(self):
            return self.queue.pop()

        def has_in_history(self, item):
            return item in self.history

    def __init__(self, url, useragent=None):
        self.start_url = url
        self.useragent = useragent
        self.links_queue = self.SetQueue()
        self.links_queue.put(self.start_url)

    def get_links(self, url):
        # log.debug(
        #     f"Getting links from '{url}'... (q. size: {links_queue.qsize()}, full len: {len(links_queue.all_set)})"
        # )

        proc = subprocess.Popen(
            [
                "bash",
                "-c",
                f'lynx -useragent="{self.useragent}" -dump -listonly {url} | grep "{self.start_url}" | sed "s/^.*http/http/"',
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        stdout, stderr = proc.communicate()
        links = list(filter(None, stdout.decode("utf-8").split("\n")))
        return links

    def collect(self):
        while not self.links_queue.empty():
            url = self.links_queue.get()
            start = time.time()
            links = self.get_links(url)
            duration = time.time() - start
            for link in links:
                # Prevent searching inside another domain
                if link.startswith(self.start_url):
                    if not self.links_queue.has_in_history(link):
                        print(f"{url} ({round(duration, 2)}s) -> {link} ")
                        self.links_queue.put(link)


if __name__ == "__main__":
    """
    Creates a new argument parser.
    """
    parser = argparse.ArgumentParser()
    version = "0.0.1"
    parser.add_argument("--version", "-v", action="version", version=version)
    parser.add_argument(
        "--url", "-u", type=str, help="URL to the target web-site"
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

    collector = Collector(args.url, useragent=args.useragent)
    collector.collect()

    # args1 = parser.parse_args(args)

    # print(args)

