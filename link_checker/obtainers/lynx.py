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
