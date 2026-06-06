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
