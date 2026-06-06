---
name: userbot-session
description: Userbot connection details and auto-start behavior
---

## Account
- Username: @Y9_S4
- ID: 8511180085
- Credentials stored in Replit Secrets as SESSION_STRING, API_ID, API_HASH

## Auto-connect
`tgcf/userbot.py` starts a background asyncio thread and connects on import.
Call `get_status()` to check, `test_connection()` to verify live, `reconnect_userbot()` to force reconnect.

## Startup flow
1. `userbot.py` imported → `start_userbot()` called → background thread + `_connect()` coroutine
2. Connection uses `StringSession(SESSION_STRING)` from env
3. Status stored in module-level `_status` dict

**Why:** Telethon requires a running event loop; background thread isolates it from Streamlit's sync execution.
