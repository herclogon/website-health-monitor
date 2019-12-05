import asyncio
import concurrent.futures
import datetime
import logging
import multiprocessing
import os
import signal
import sys

import psutil
import urllib3

from . import config, models

logging.basicConfig(level=logging.INFO)
logging.getLogger("peewee").setLevel(logging.CRITICAL)
logging.getLogger("connectionpool").setLevel(logging.CRITICAL)
logging.getLogger("urllib3.connectionpool").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)
logging.getLogger("pyppeteer").setLevel(logging.CRITICAL)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

# Disable `InsecureRequestWarning: Unverified HTTPS request is being made.`
# log warnings.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger(__name__)


class RequestResult:
    url = ""
    parent = ""
    duration = ""
    response_code = ""
    response_reason = ""
    response_size = None
    response_content_type = ""
    links = []


class MyProcessPoolExecutor(concurrent.futures.ProcessPoolExecutor):
    """Use process pool instad of thread pool, cause `pyppeteer` can be run
    only in a main thread.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._running_workers = 0

    def submit(self, *args, **kwargs):
        future = super().submit(*args, **kwargs)
        self._running_workers += 1
        future.add_done_callback(self._worker_is_done)
        return future

    # pylint: disable=unused-argument
    def _worker_is_done(self, future):
        self._running_workers -= 1

    def get_pool_usage(self):
        return self._running_workers


def reap_process(pid, timeout=1):
    "Tries hard to terminate and ultimately kill all the children of this process."

    def on_terminate(proc):
        log.info("Process %s terminated with exit code %s.", proc, proc.returncode)

    # Collect process children.
    procs = psutil.Process(pid=pid).children()

    # Also terminate original process.
    procs.append(psutil.Process(pid=pid))

    # send SIGTERM
    for p in procs:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    gone, alive = psutil.wait_procs(procs, timeout=timeout, callback=on_terminate)
    if alive:
        # send SIGKILL
        for p in alive:
            log.info("Process {} survived SIGTERM; trying SIGKILL".format(p))
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        gone, alive = psutil.wait_procs(alive, timeout=timeout, callback=on_terminate)
        if alive:
            # give up
            for p in alive:
                log.info("Process {} survived SIGKILL; giving up".format(p))


def func_proc_result(target_func, q):
    """Push function results into queue, queue uses here for cross-process
    communication.
    """

    def wrapper(*args, **kwargs):
        try:
            result = target_func(*args, **kwargs)
            q.put(result)
        except Exception as e:
            log.debug("'target_func' call execution exception: %s", e)
            raise e

    return wrapper


def func_proc(_target_func=None, _timeout=30, *args, **kwargs):
    """Run the function in a separate process, if the function does not complete
    in timeout time - kill process with all children.
    """
    # Queue uses to get a result from the process.
    q = multiprocessing.Queue()
    try_count = 3

    while try_count > 0:
        p = multiprocessing.Process(
            target=func_proc_result(_target_func, q), args=args, kwargs=kwargs
        )
        p.start()

        p.join(timeout=_timeout)

        if p.is_alive():
            log.debug(f"Process '{p.pid}' timeout exceed, terminating...")

            # Terminate/kill process with children.
            reap_process(pid=p.pid)

            try_count -= 1
            log.info("Trying to restart the process, try count: %s", try_count)
            continue

        if not p.is_alive() and p.exitcode == 0:
            return q.get()

    raise Exception(f"Unknown process end.")


class Collector:
    # Keep Future(s) of active requests.
    requests = set()

    # sitemapFile
    sitemapFile = "sitemap.xml"

    # Keep history of all visited URLs.
    history = set()

    # How many parallel requests are possible.
    concurrency = 1

    # Max request duration, after this period will interpret result as error.
    max_duration = 6

    # Custom user agent.
    useragent = ""

    # Module with `get_links` function, collector fork a new process to call
    # the function.
    obtainer = None

    # How mach time collector will wait obtainer results, it this timeout exceed
    # collector terminates obtainer process.
    obtainer_execution_timeout = 30

    def __init__(self, url):
        self.start_url = url
        self.history = set()
        self._future_start_time = {}
        self._features = set()

    def start(self):
        # Open db connection.
        config.db.connect()

        self.executor = MyProcessPoolExecutor(self.concurrency)

        # Check broken link first.
        broken_links = list(
            models.Link.select().where(
                models.Link.response_code != 200,
                models.Link.start_url == self.start_url,
            )
        )

        broken_parent_urls = set([link.parent for link in broken_links])
        for url in broken_parent_urls:
            try:
                parent = models.Link.select().where(models.Link.url == url).get()
                parent_url = parent.parent
            except:
                continue

            self._add_url(url, parent_url)

        def shutdown():
            log.info("Shutting down...")

            # Shutting down process executor.
            self.executor.shutdown()

            # Terminate all child processes.
            reap_process(os.getpid())

            # Close db connection.
            config.db.close()

            # Exit from the application.
            sys.exit()

        async def monitor():
            while self.executor.get_pool_usage():
                await asyncio.sleep(0.5)

        # Add a `start_url` as first request.
        self._add_url(self.start_url, "")

        # Interrupt signal handler. Stop all processes and exit.
        asyncio.get_event_loop().add_signal_handler(signal.SIGINT, shutdown)

        # Wait until `executor` finished all tasks.
        asyncio.get_event_loop().run_until_complete(monitor())
        log.info("Well done, %s URLs processed.", len(self.history))

    def _add_url(self, url, parent):
        # Queue link process to execute.
        future = asyncio.get_event_loop().run_in_executor(
            self.executor,
            func_proc,
            self.obtainer.get_links,
            self.obtainer_execution_timeout,
            url,
            parent,
            self.useragent,
        )
        future.add_done_callback(self._furute_done_callback)

    def _furute_done_callback(self, future):
        if future.exception():
            log.error(future.exception())

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

        # Save link to db.
        try:
            try:
                link = models.Link.get(models.Link.url == result["url"])
            except Exception as e:
                link = models.Link(
                    start_url=self.start_url,
                    url=url,
                    parent=parent_url,
                    duration=duration,
                    size=response_size,
                    content_type=response_content_type,
                    response_code=response_code,
                    response_reason=response_reason,
                    date=datetime.datetime.now(),
                )
            link.date = datetime.datetime.now()
            link.save()

            # Delete all urls where parent is a current url.
            query = models.Link.delete().where(
                models.Link.parent == result["url"],
                models.Link.start_url == self.start_url,
            )
            query.execute()

        except Exception as e:
            log.error("%s", e)

        message = (
            f"{process_name}: {response_code}, {round(response_size/1024/1024, 2)}M,"
            f" {round(duration, 2)}s, {len(links)}, {self.executor.get_pool_usage()}, {url}"
        )

        if response_code != 200:
            message += f" <- ERROR: {response_reason}, parent: {parent_url}"

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
