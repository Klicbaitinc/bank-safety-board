"""Polite HTTP. One session, retries, and a pause between successful calls."""
import os
import time

import requests

USER_AGENT = os.environ.get(
    "FDIC_USER_AGENT",
    "BankSafetySavingsBoard kennethdavis+banks@mail.grokbot.com",
).strip()

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
})


def get(url, *, params=None, headers=None, timeout=180, pause=0.5, stream=False, allow_status=()):
    last = None
    for attempt in range(6):
        if attempt:
            wait = min(60, 2 ** attempt)
            print(f"  retry {attempt} in {wait}s for {url}", flush=True)
            time.sleep(wait)
        try:
            response = SESSION.get(
                url, params=params, headers=headers, timeout=timeout, stream=stream,
            )
        except requests.RequestException as exc:
            last = exc
            continue
        if response.status_code in allow_status:
            if pause:
                time.sleep(pause)
            return response
        if response.status_code in (429, 500, 502, 503, 504):
            last = requests.HTTPError(f"{response.status_code} for {url}")
            response.close()
            continue
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            response.close()
            raise exc
        if pause:
            time.sleep(pause)
        return response
    if isinstance(last, Exception):
        raise last
    raise RuntimeError(f"request failed: {url}")
