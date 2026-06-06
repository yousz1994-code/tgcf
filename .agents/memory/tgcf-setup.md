---
name: tgcf-project-setup
description: Key constraints for this tgcf Streamlit project to avoid regressions
---

## Streamlit Version: 1.25.0

**NOT supported (will crash):**
- `st.container(border=True)` — use plain `st.container()` or `st.expander()`
- `st.page_link()` — not available in 1.25
- `st.link_button()` — not available in 1.25

**Supported:**
- `st.rerun()` — works in 1.25
- `st.experimental_rerun()` — also works but deprecated

## Credential loading
Credentials live in Replit Secrets (API_ID, API_HASH, SESSION_STRING, BOT_TOKEN, ADMIN_ID).
`tgcf/config_env.py:load_env_into_config()` syncs them to `tgcf.config.json` on call.
Must be called before `read_config()` in any page that needs credentials.

## utils.py fix
Removed `from run import package_dir` (broken import). Now uses `_get_package_dir()` helper internally.

**Why:** `run` module not in sys.path when Streamlit runs pages directly.

## Admin Bot Session — CRITICAL
The admin bot MUST use `StringSession()` (in-memory), NOT a file-based session string like "tgcf_admin_bot".
File-based sessions cause "database is locked" when Streamlit and tgcf live both try to open the same SQLite file.

**Why:** Multiple processes/threads cannot share the same SQLite session file safely.
**How to apply:** Always `TelegramClient(StringSession(), api_id, api_hash)` for bots started in background threads.

## Auto-start admin bot
`0_👋_Hello.py` calls `start_admin_bot()` on first Streamlit load so the bot is available without running tgcf live mode.
`live.py:start_sync()` also calls `start_admin_bot()` so it also runs in live forwarding mode.
