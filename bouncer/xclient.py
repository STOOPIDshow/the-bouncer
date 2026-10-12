"""Read-only X API v2 client. GET only; OAuth 1.0a user context from env vars."""
import base64, hashlib, hmac, json, os, secrets, time, urllib.parse, urllib.request, urllib.error

API = "https://api.x.com"
# Only these path shapes may be called. Anything else is refused.
ALLOWED_PATHS = (
    "/2/users/by/username/",   # user lookup (by handle)
    "/2/users/",               # /2/users/{id}/followers|following|mentions|tweets
)
ALLOWED_SUFFIXES = ("/followers", "/following", "/mentions", "/tweets")
ENV_KEYS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")


class ReadOnlyViolation(RuntimeError):
    pass


def guard(method, path):
    if method.upper() != "GET":
        raise ReadOnlyViolation(f"The Bouncer is read-only; refused {method} {path}")
    if path.startswith("/2/users/by/username/"):
        return
    if path.startswith("/2/users/") and path.endswith(ALLOWED_SUFFIXES) and path.count("/") == 4:
        return
    raise ReadOnlyViolation(f"Endpoint not on the read-only allowlist: {path}")


def _pct(s):
    return urllib.parse.quote(str(s), safe="~-._")


def oauth1_header(method, url, params, creds, nonce=None, ts=None):
    o = {
        "oauth_consumer_key": creds["X_API_KEY"],
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(ts or int(time.time())),
        "oauth_token": creds["X_ACCESS_TOKEN"],
        "oauth_version": "1.0",
    }
    allp = {**params, **o}
    pstr = "&".join(f"{k}={v}" for k, v in sorted((_pct(k), _pct(v)) for k, v in allp.items()))
    base = "&".join([method.upper(), _pct(url), _pct(pstr)])
    key = f"{_pct(creds['X_API_SECRET'])}&{_pct(creds['X_ACCESS_TOKEN_SECRET'])}"
    o["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(o.items()))


def load_creds():
    missing = [k for k in ENV_KEYS if not os.environ.get(k)]
    if missing:
        raise SystemExit("Missing env vars: " + ", ".join(missing) + " (see README.md, or run: python3 -m bouncer setup)")
    return {k: os.environ[k] for k in ENV_KEYS}


class XClient:
    def __init__(self, creds=None, transport=None, sleep=time.sleep, max_retries=6):
        self.transport = transport  # callable(path, params) -> (status, headers, body_dict) for tests
        self.creds = creds if (creds or transport) else load_creds()
        self.sleep = sleep
        self.max_retries = max_retries
        self.resources = 0  # billable items returned

    def _http(self, path, params):
        url = API + path
        q = urllib.parse.urlencode(params)
        req = urllib.request.Request(url + ("?" + q if q else ""), method="GET")
        req.add_header("Authorization", oauth1_header("GET", url, params, self.creds))
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, dict(r.headers), json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                body = json.loads(body)
            except Exception:
                body = {"raw": body.decode(errors="replace")}
            return e.code, dict(e.headers), body

    def get(self, path, params=None, method="GET"):
        guard(method, path)
        params = {k: v for k, v in (params or {}).items() if v is not None}
        for attempt in range(self.max_retries + 1):
            status, headers, body = (self.transport or self._http)(path, params)
            if status == 429 or status >= 500:
                if attempt == self.max_retries:
                    break
                reset = headers.get("x-rate-limit-reset") or headers.get("X-Rate-Limit-Reset")
                wait = max(1, int(reset) - int(time.time()) + 1) if reset and status == 429 else min(900, 2 ** attempt * 5)
                print(f"  HTTP {status}; backing off {wait}s (attempt {attempt + 1})")
                self.sleep(min(wait, 900))
                continue
            if status != 200:
                raise RuntimeError(f"X API {status} on {path}: {body}")
            data = body.get("data")
            if isinstance(data, list):
                self.resources += len(data)
            elif data:
                self.resources += 1
            return body
        raise RuntimeError(f"X API still failing (last HTTP {status}, body {body}) after {self.max_retries} retries on {path}")

    def paginate(self, path, params, token_param="pagination_token"):
        params = dict(params)
        out, includes = [], {}
        while True:
            body = self.get(path, params)
            out.extend(body.get("data") or [])
            for k, v in (body.get("includes") or {}).items():
                includes.setdefault(k, []).extend(v)
            nt = (body.get("meta") or {}).get("next_token")
            if not nt:
                return out, includes
            params[token_param] = nt
