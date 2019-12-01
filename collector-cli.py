import argparse

import link_checker

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

    collector = link_checker.collector.Collector(args.url[0])
    collector.useragent = args.useragent
    collector.concurrency = args.concurrency
    collector.max_duration = args.max_duration
    collector.sitemapFile = args.sitemap
    collector.obtainer = link_checker.obtainers.pyppeteer
    collector.start()
