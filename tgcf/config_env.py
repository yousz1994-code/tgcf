"""Load credentials from environment variables into the config on startup."""

import os
import logging
from tgcf.config import read_config, write_config


def load_env_into_config():
    """If env vars are set, write them into tgcf.config.json automatically."""
    api_id_str = os.getenv("API_ID", "")
    api_hash = os.getenv("API_HASH", "")
    session_string = os.getenv("SESSION_STRING", "")
    bot_token = os.getenv("BOT_TOKEN", "")
    admin_id = os.getenv("ADMIN_ID", "")

    if not any([api_id_str, api_hash, session_string, bot_token]):
        return

    try:
        cfg = read_config()
        changed = False

        if api_id_str and int(api_id_str) != cfg.login.API_ID:
            cfg.login.API_ID = int(api_id_str)
            changed = True

        if api_hash and api_hash != cfg.login.API_HASH:
            cfg.login.API_HASH = api_hash
            changed = True

        if session_string and session_string != cfg.login.SESSION_STRING:
            cfg.login.SESSION_STRING = session_string
            cfg.login.user_type = 1  # userbot
            changed = True

        if bot_token and bot_token != cfg.login.BOT_TOKEN:
            cfg.login.BOT_TOKEN = bot_token
            changed = True

        if admin_id and admin_id not in [str(a) for a in cfg.admins]:
            cfg.admins.append(int(admin_id))
            changed = True

        if changed:
            write_config(cfg)
            logging.info("Config updated from environment variables.")

    except Exception as e:
        logging.warning(f"load_env_into_config error: {e}")


# Run on import
load_env_into_config()
