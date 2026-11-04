"""Small in-memory, per-client rate limiter for endpoints that spend LLM credits.

State is per process, so the effective limit scales with the number of workers.
That's acceptable for a single-container demo. Use Redis for a larger deployment.
"""

import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import current_app, jsonify, request

WINDOW_SECONDS = 60

_lock = threading.Lock()
_hits = defaultdict(deque)


def reset():
    with _lock:
        _hits.clear()


def _retry_after(client, limit, now):
    """Record a hit and return 0, or the seconds to wait if the client is over the limit."""
    with _lock:
        hits = _hits[client]
        while hits and now - hits[0] >= WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= limit:
            return int(WINDOW_SECONDS - (now - hits[0])) + 1
        hits.append(now)
        # Stop the table from growing without bound.
        if len(_hits) > 10000:
            for key in [k for k, v in _hits.items() if not v or now - v[-1] >= WINDOW_SECONDS]:
                del _hits[key]
        return 0


def rate_limited(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        limit = current_app.config["LLM_RATE_LIMIT_PER_MINUTE"]
        if limit > 0:
            wait = _retry_after(request.remote_addr or "unknown", limit, time.monotonic())
            if wait:
                response = jsonify(
                    {"error": f"Too many requests. Please try again in {wait} seconds."}
                )
                response.status_code = 429
                response.headers["Retry-After"] = str(wait)
                return response
        return view(*args, **kwargs)

    return wrapper
