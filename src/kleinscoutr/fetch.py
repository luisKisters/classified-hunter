import hashlib
import random
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
FRESH_TTL_DAYS = 0.05


class FetchError(RuntimeError):
    pass


class Fetch:
    def __init__(self, cache, log, jitter=(3.0, 7.0)):
        self.cache = Path(cache)
        self.log = log
        self.jitter = jitter

    def __call__(self, url, ttl_days=7, binary=False):
        self.cache.mkdir(parents=True, exist_ok=True)
        path = self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".cache")
        if path.exists() and ttl_days > 0 and time.time() - path.stat().st_mtime < ttl_days * 86400:
            data = path.read_bytes()
            return data if binary else data.decode("utf-8", errors="replace")
        req = Request(url, headers={"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9"})
        for attempt in range(3):
            try:
                with urlopen(req, timeout=30) as response:
                    data = response.read()
                path.write_bytes(data)
                time.sleep(random.uniform(*self.jitter))
                return data if binary else data.decode("utf-8", errors="replace")
            except HTTPError as e:
                # A 404 body can still contain the site's deleted-listing message.
                if e.code in (404, 410) and not binary:
                    data = e.read()
                    time.sleep(random.uniform(*self.jitter))
                    return data.decode("utf-8", errors="replace")
                self.log(f"retry {attempt + 1} {url}: {e}")
            except (URLError, TimeoutError, OSError) as e:
                self.log(f"retry {attempt + 1} {url}: {e}")
            if attempt < 2:
                time.sleep(10 + attempt * 15)
        raise FetchError(f"failed: {url}")
