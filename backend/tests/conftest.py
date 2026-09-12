"""Keep tests independent from a developer's local .env or database service."""

import os


# This is set before pytest imports the application modules and overrides .env values.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_aivoa.db"
