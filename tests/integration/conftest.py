"""Integration-test environment: relax login rate limiting so the many
logins across test cases (all from one client IP) don't trip the limiter."""

import os

os.environ.setdefault("ARK_LOGIN_MAX_PER_WINDOW", "1000")
os.environ.setdefault("ARK_LOCKOUT_THRESHOLD", "100")
