import hashlib
import math
import threading
import time
from collections import deque

from fastapi import HTTPException


class LoginThrottle:
    def __init__(self, window: int = 300, capacity: int = 4096):
        self.window = window
        self.capacity = capacity
        self.entries: dict[str, deque[float]] = {}
        self.lock = threading.Lock()

    def reset(self):
        with self.lock:
            self.entries.clear()

    def check(self, account: str, origin: str):
        now = time.monotonic()
        account_key = hashlib.sha256(account.strip().casefold().encode()).hexdigest()
        keys = [(f"account:{account_key}", 8), (f"origin:{origin}", 40)]
        with self.lock:
            for key in list(self.entries):
                history = self.entries[key]
                while history and history[0] <= now - self.window:
                    history.popleft()
                if not history:
                    del self.entries[key]
            retries = [
                math.ceil(self.entries[key][0] + self.window - now)
                for key, limit in keys
                if len(self.entries.get(key, ())) >= limit
            ]
            if (
                retries
                or len(self.entries) + sum(key not in self.entries for key, _ in keys)
                > self.capacity
            ):
                raise HTTPException(
                    status_code=429,
                    detail="Too many sign-in attempts. Wait before trying again.",
                    headers={"Retry-After": str(max(retries, default=self.window))},
                )
            for key, _ in keys:
                self.entries.setdefault(key, deque()).append(now)


login_throttle = LoginThrottle()
