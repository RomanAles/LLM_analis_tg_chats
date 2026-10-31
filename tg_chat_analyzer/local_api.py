"""HTTP restricted to local inference servers, with no proxies or redirects."""
import ipaddress
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError("Перенаправления локального API запрещены")


class LocalAPI:
    def __init__(self, base_url, timeout=180):
        url = urlsplit(base_url)
        host = url.hostname or ""
        try:
            loopback = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if (url.scheme != "http" or not loopback or url.username or url.password or
                url.path not in ("", "/") or url.query or url.fragment):
            raise ValueError("Разрешён только локальный HTTP runtime на loopback-адресе")
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError("Некорректный порт runtime")
        self.base_url, self.timeout = base_url.rstrip("/"), timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path, payload=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(self.base_url + path, data=body, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                content = response.read(16 * 1024 * 1024 + 1)
            if len(content) > 16 * 1024 * 1024:
                raise ValueError("Ответ runtime превышает ограничение размера")
            result = json.loads(content)
            if not isinstance(result, dict) or result.get("error"):
                raise ValueError(f"Ошибка runtime: {str(result.get('error'))[:500] if isinstance(result, dict) else 'не объект'}")
            return result
        except HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", errors="replace")
            raise RuntimeError(f"Локальный runtime HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise RuntimeError("Локальный runtime недоступен; запустите Ollama и загрузите модель") from exc
