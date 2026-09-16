"""公开网页与 PDF 读取工具。"""
from io import BytesIO
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

from .base import Tool

MAX_BYTES = 2_000_000


def validate_public_url(url):
    """只允许公开 HTTP(S) 网页，避免模型访问本机、内网或带凭证的链接。"""
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("只支持不带账号密码的公开 http/https 链接")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("只支持标准网页端口")
    for result in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)):
        if not ipaddress.ip_address(result[4][0]).is_global:
            raise ValueError("不能读取本机或内网地址")
    return url


def fetch(url):
    import requests

    for _ in range(4):
        validate_public_url(url)
        with requests.get(
            url,
            timeout=(8, 20),
            allow_redirects=False,
            stream=True,
            headers={
                "User-Agent": "GoldAnalyst/0.1 (research prototype)",
                "Accept": "text/html,application/pdf",
            },
        ) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            if response.status_code in {401, 403, 429}:
                raise ValueError(
                    f"来源暂不可访问（HTTP {response.status_code}）；不绕过访问限制。可提供其他原始来源。"
                )
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_content(16384):
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise ValueError("页面超过 2 MB，本版不读取大文件")
            return bytes(data), response.headers.get("Content-Type", ""), url
    raise ValueError("网页重定向过多")


def parse_html(data, url):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "html.parser")
    title = soup.find("h1") or soup.find("title")
    title = title.get_text(" ", strip=True) if title else url
    published = ""
    meta = soup.select_one('meta[property="article:published_time"], meta[name="publishdate"]')
    if meta:
        published = meta.get("content", "")
    raw_page_text = soup.get_text(" ", strip=True)
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    body = soup.select_one(".main-text, .atc-content, .article-content, #article, article") or soup
    text = body.get_text("\n", strip=True)
    if not published:
        match = re.search(r"20\d{2}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}(?::\d{2})?", raw_page_text)
        published = match.group() if match else "未提取到，请阅读正文确认"
    tables = []
    for table in soup.find_all("table")[:6]:
        rows = [
            [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            for row in table.find_all("tr")
        ]
        tables.append([row for row in rows if row][:100])
    links = []
    for anchor in soup.find_all("a", href=True):
        target = urljoin(url, anchor["href"])
        label = anchor.get_text(" ", strip=True)
        if label and target.startswith(("https://", "http://")):
            links.append({"title": label[:180], "url": target})
    return {
        "title": title,
        "text": text[:18000],
        "published_at": published,
        "tables": tables,
        "links": links[:250],
        "truncated": len(text) > 18000,
    }


class ReadURLTool(Tool):
    name = "read_url"
    description = "阅读公开网页或 PDF，保存正文及证据编号；失败不会返回伪造资料。"
    parameters = {"url": {"type": "string"}}

    def execute(self, url):
        cached = self.context.get_cached(url)
        if cached is not None:
            return cached
        data, content_type, resolved_url = fetch(url)
        if "pdf" in content_type or data.startswith(b"%PDF"):
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(data))
            text = "\n".join(
                f"[第 {index + 1} 页]\n{page.extract_text() or ''}"
                for index, page in enumerate(reader.pages[:15])
            )[:18000]
            parsed = {
                "title": urlparse(url).path.split("/")[-1],
                "text": text,
                "tables": [],
                "published_at": "未知",
                "truncated": len(reader.pages) > 15,
                "links": [],
            }
        elif "html" in content_type or not content_type or "text/plain" in content_type:
            parsed = parse_html(data, resolved_url)
        else:
            raise ValueError("本版仅支持 HTML、文本与 PDF")
        if len(parsed["text"].strip()) < 40:
            raise ValueError("页面正文过少，可能需动态加载；不能当作完整证据")
        hostname = urlparse(resolved_url).hostname or ""
        kind = "news" if hostname == "10jqka.com.cn" or hostname.endswith(".10jqka.com.cn") else "source"
        item = self.context.add_evidence(url=resolved_url, kind=kind, **parsed)
        self.context.set_cached(url, item)
        return item
