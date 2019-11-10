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
            if href.endswith(".jpg"):
                continue
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
