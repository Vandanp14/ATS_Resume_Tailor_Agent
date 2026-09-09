"""Single-owner access policy and bounded, revocable browser sessions."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlsplit


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=131072,
        r=8,
        p=1,
        maxmem=256 * 1024 * 1024,
        dklen=32,
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


@dataclass(frozen=True)
class AccessSettings:
    public_origin: str = ""
    password_digest: str = ""

    def __post_init__(self) -> None:
        if self.public_origin:
            parsed = urlsplit(self.public_origin)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise RuntimeError(
                    "PUBLIC_ORIGIN must be an HTTPS origin without a trailing slash."
                )
            if not self.password_digest:
                raise RuntimeError("APP_PASSWORD_HASH is required for hosted access.")
        if self.password_digest:
            try:
                algorithm, salt, digest = self.password_digest.split("$")
                assert algorithm == "scrypt" and len(bytes.fromhex(salt)) == 16
                assert len(bytes.fromhex(digest)) == 32
            except (ValueError, AssertionError) as exc:
                raise RuntimeError(
                    "APP_PASSWORD_HASH must be generated with the access helper."
                ) from exc

    @property
    def cookie_name(self) -> str:
        return "__Host-resume-session" if self.public_origin else "resume-session"

    def host_allowed(self, host: str) -> bool:
        if self.public_origin:
            return host.lower() == urlsplit(self.public_origin).netloc.lower()
        try:
            return urlsplit(f"http://{host}").hostname in {
                "127.0.0.1",
                "localhost",
                "::1",
            }
        except ValueError:
            return False

    def origin_allowed(self, origin: str | None, host: str) -> bool:
        if self.public_origin:
            return origin == self.public_origin
        return origin is None or origin == f"http://{host}"


class Sessions:
    lifetime = 1800

    def __init__(self, settings: AccessSettings):
        self.settings = settings
        self.tokens: dict[str, float] = {}
        self.attempts: deque[float] = deque()

    def allowed_attempt(self) -> bool:
        now = time.monotonic()
        while self.attempts and self.attempts[0] <= now - 60:
            self.attempts.popleft()
        if len(self.attempts) >= 5:
            return False
        self.attempts.append(now)
        return True

    def verify(self, password: str) -> bool:
        if not self.settings.password_digest:
            return False
        salt = bytes.fromhex(self.settings.password_digest.split("$")[1])
        return secrets.compare_digest(
            password_hash(password, salt), self.settings.password_digest
        )

    def valid(self, token: str) -> bool:
        return self.tokens.get(token, 0) > time.monotonic()

    def issue(self) -> str:
        now = time.monotonic()
        self.tokens = {
            key: expiry for key, expiry in self.tokens.items() if expiry > now
        }
        if len(self.tokens) >= 20:
            self.tokens.pop(next(iter(self.tokens)))
        token = secrets.token_urlsafe(32)
        self.tokens[token] = now + self.lifetime
        return token


if __name__ == "__main__":
    from getpass import getpass

    password = getpass("New workspace password (at least 16 characters): ")
    if len(password) < 16 or password != getpass("Confirm password: "):
        raise SystemExit("Passwords must match and contain at least 16 characters.")
    print(password_hash(password))
