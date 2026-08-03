"""Session-wide test setup.

On Windows, asyncio's default ProactorEventLoop has known incompatibilities
with redis-py's async client under certain task-group patterns (Starlette's
BaseHTTPMiddleware in particular) - connections end up "attached to a
different loop" even within a single event loop. SelectorEventLoop doesn't
have this issue and is what the app runs under in every real deployment
(Linux containers), so this only changes local Windows test runs, not
production behavior.
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
