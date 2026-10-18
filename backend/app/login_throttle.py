"""Bound failed guesses and concurrent verification without charging successful logins."""

import hashlib
import math
import threading
import time
from collections import OrderedDict, deque

from fastapi import HTTPException

_LOGIN_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


class LoginThrottle:
    def __init__(self, window: int = 300, capacity: int = 4096):
        self.window = window
        self.capacity = max(1, capacity)
        self.entries: OrderedDict[str, deque[float]] = OrderedDict()
        # Actual accounts are bounded by administrator-created database rows,
        # rather than attacker-supplied names. Never evict their active limits.
        self.registered_entries: dict[str, deque[float]] = {}
        self.pending: dict[object, str] = {}
        self._registered_tickets: set[object] = set()
        self.lock = threading.Lock()
        self._failure_diagnostics: deque[float] = deque()

    def reset(self):
        with self.lock:
            self.entries.clear()
            self.registered_entries.clear()
            self.pending.clear()
            self._registered_tickets.clear()
            self._failure_diagnostics.clear()

    def _prune(self, now: float):
        for entries in (self.entries, self.registered_entries):
            for key in list(entries):
                history = entries[key]
                while history and history[0] <= now - self.window:
                    history.popleft()
                if not history:
                    del entries[key]

    def check(self, account: str, origin: str) -> object:
        # Peers all share loopback in this desktop app; an origin-wide persistent
        # counter lets one account block every other account. Do not trust XFF.
        # Match SQLite lower(username), used by login and its unique index.
        # Unicode casefold would merge distinct accounts such as Straße/Strasse.
        account_key = hashlib.sha256(account.strip().translate(_LOGIN_LOWER).encode()).hexdigest()
        now = time.monotonic()
        with self.lock:
            self._prune(now)
            history = self.registered_entries.get(account_key, self.entries.get(account_key, ()))
            if len(history) >= 8:
                self._reject(math.ceil(history[0] + self.window - now))
            pending_for_account = sum(key == account_key for key in self.pending.values())
            if len(self.pending) >= 40 or len(history) + pending_for_account >= 8:
                self._reject(1)
            ticket = object()
            self.pending[ticket] = account_key
            return ticket

    def mark_registered(self, ticket: object) -> None:
        """Protect a database-resolved account before password verification."""
        with self.lock:
            key = self.pending.get(ticket)
            if key is None:
                return
            self._registered_tickets.add(ticket)
            history = self.entries.pop(key, None)
            if history:
                self.registered_entries.setdefault(key, deque()).extend(history)

    @staticmethod
    def _reject(retry: int):
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Wait before trying again.",
            headers={"Retry-After": str(max(1, retry))},
        )

    def finish(self, ticket: object, *, success: bool = False, failed: bool = False):
        with self.lock:
            registered = ticket in self._registered_tickets
            self._registered_tickets.discard(ticket)
            key = self.pending.pop(ticket, None)
            if key is None:
                return
            if success:
                self.entries.pop(key, None)
                self.registered_entries.pop(key, None)
            elif failed:
                now = time.monotonic()
                self._prune(now)
                registered = registered or key in self.registered_entries
                entries = self.registered_entries if registered else self.entries
                if key not in entries:
                    # Bounded recent-account history; never turn memory pressure
                    # from unrelated guessed names into a global account lockout.
                    if not registered:
                        while len(self.entries) >= self.capacity:
                            self.entries.popitem(last=False)
                    entries[key] = deque()
                entries[key].append(now)
                if not registered:
                    self.entries.move_to_end(key)

    def allow_failure_diagnostic(self) -> bool:
        """Cap persistent anonymous failure events independently of guessed names."""
        now = time.monotonic()
        with self.lock:
            while self._failure_diagnostics and self._failure_diagnostics[0] <= now - self.window:
                self._failure_diagnostics.popleft()
            if len(self._failure_diagnostics) >= 40:
                return False
            self._failure_diagnostics.append(now)
            return True


login_throttle = LoginThrottle()
