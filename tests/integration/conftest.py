"""Integration-test environment: relax login rate limiting so the many
logins across test cases (all from one client IP) don't trip the limiter,
and allow the insecure default secret_key/bootstrap password that the
startup guard otherwise refuses."""

import os

os.environ.setdefault("ARK_LOGIN_MAX_PER_WINDOW", "1000")
os.environ.setdefault("ARK_LOCKOUT_THRESHOLD", "100")
os.environ.setdefault("ARK_ALLOW_INSECURE", "true")
os.environ.setdefault("ARK_EGRESS_ALLOW_FILE_SOURCES", "true")
