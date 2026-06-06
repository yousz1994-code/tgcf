"""The module responsible for operating tgcf in live mode."""

import logging
import os
import sys
from typing import Union

from telethon import TelegramClient, events, functions, types
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

from tgcf import config, const
from tgcf import storage as st
from tgcf.bot import get_events
from tgcf.config import CONFIG, get_SESSION
from tgcf.plugins import apply_plugins, load_async_plugins
from tgcf.utils import clean_session_files, send_message


def _try_log(connection_id, con_name, source_id, dest_id, status, preview=""):
    try:
        from tgcf.db import log_message
        log_message(connection_id, con_name, source_id, dest_id, status, preview)
    except Exception as e:
        logging.debug(f"DB log skipped: {e}")


def _get_connection_id(chat_id: int):
    try:
        from tgcf.db import get_all_connections
        conns = get_all_connections()
        for c in conns:
            if c.get("source_id") == chat_id:
                return c["id"], c.get("con_name", "")
        return None, str(chat_id)
    except Exception:
        return None, str(chat_id)


async def new_message_handler(event: Union[Message, events.NewMessage]) -> None:
    """Process new incoming messages."""
    chat_id = event.chat_id

    if chat_id not in config.from_to:
        return
    logging.info(f"New message received in {chat_id}")
    message = event.message
    preview = (message.text or "")[:200] if message else ""

    event_uid = st.EventUid(event)

    length = len(st.stored)
    exceeding = length - const.KEEP_LAST_MANY
    if exceeding > 0:
        for key in st.stored:
            del st.stored[key]
            break

    dest = config.from_to.get(chat_id)

    tm = await apply_plugins(message)
    if not tm:
        return

    if event.is_reply:
        r_event = st.DummyEvent(chat_id, event.reply_to_msg_id)
        r_event_uid = st.EventUid(r_event)

    cid, con_name = _get_connection_id(chat_id)

    st.stored[event_uid] = {}
    for d in dest:
        if event.is_reply and r_event_uid in st.stored:
            tm.reply_to = st.stored.get(r_event_uid).get(d)
        try:
            fwded_msg = await send_message(d, tm)
            st.stored[event_uid].update({d: fwded_msg})
            _try_log(cid, con_name, chat_id, d, "ok", preview)
        except Exception as e:
            logging.error(f"Failed to forward to {d}: {e}")
            _try_log(cid, con_name, chat_id, d, "fail", preview)
    tm.clear()


async def edited_message_handler(event) -> None:
    """Handle message edits."""
    message = event.message
    chat_id = event.chat_id

    if chat_id not in config.from_to:
        return

    logging.info(f"Message edited in {chat_id}")
    event_uid = st.EventUid(event)
    tm = await apply_plugins(message)

    if not tm:
        return

    fwded_msgs = st.stored.get(event_uid)

    if fwded_msgs:
        for _, msg in fwded_msgs.items():
            if config.CONFIG.live.delete_on_edit == message.text:
                await msg.delete()
                await message.delete()
            else:
                await msg.edit(tm.text)
        return

    dest = config.from_to.get(chat_id)
    for d in dest:
        await send_message(d, tm)
    tm.clear()


async def deleted_message_handler(event):
    """Handle message deletes."""
    chat_id = event.chat_id
    if chat_id not in config.from_to:
        return

    logging.info(f"Message deleted in {chat_id}")
    event_uid = st.EventUid(event)
    fwded_msgs = st.stored.get(event_uid)
    if fwded_msgs:
        for _, msg in fwded_msgs.items():
            await msg.delete()
        return


ALL_EVENTS = {
    "new": (new_message_handler, events.NewMessage()),
    "edited": (edited_message_handler, events.MessageEdited()),
    "deleted": (deleted_message_handler, events.MessageDeleted()),
}


async def start_sync() -> None:
    """Start tgcf live sync."""
    # Load credentials from env vars into config
    try:
        from tgcf.config_env import load_env_into_config
        load_env_into_config()
    except Exception as e:
        logging.warning(f"config_env load: {e}")

    # Init DB
    try:
        from tgcf.db import init_db
        init_db()
    except Exception as e:
        logging.warning(f"DB init: {e}")

    # Start admin bot in background
    try:
        from tgcf.bot.admin_bot import start_admin_bot
        start_admin_bot()
        logging.info("Admin bot started in background.")
    except Exception as e:
        logging.warning(f"Admin bot start failed: {e}")

    clean_session_files()
    await load_async_plugins()

    # Re-read config after env load
    from tgcf.config import read_config
    cfg = read_config()

    SESSION = get_SESSION(cfg.login)
    client = TelegramClient(
        SESSION,
        cfg.login.API_ID,
        cfg.login.API_HASH,
        sequential_updates=cfg.live.sequential_updates,
    )
    if cfg.login.user_type == 0:
        if cfg.login.BOT_TOKEN == "":
            logging.warning("Bot token not found, but login type is set to bot.")
            sys.exit()
        await client.start(bot_token=cfg.login.BOT_TOKEN)
    else:
        await client.start()

    config.is_bot = await client.is_bot()
    logging.info(f"config.is_bot={config.is_bot}")
    command_events = get_events()

    await config.load_admins(client)

    ALL_EVENTS.update(command_events)

    for key, val in ALL_EVENTS.items():
        if cfg.live.delete_sync is False and key == "deleted":
            continue
        client.add_event_handler(*val)
        logging.info(f"Added event handler for {key}")

    if config.is_bot and const.REGISTER_COMMANDS:
        await client(
            functions.bots.SetBotCommandsRequest(
                scope=types.BotCommandScopeDefault(),
                lang_code="ar",
                commands=[
                    types.BotCommand(command=key, description=value)
                    for key, value in const.COMMANDS.items()
                ],
            )
        )

    config.from_to = await config.load_from_to(client, cfg.forwards)

    # Sync connections to DB
    try:
        from tgcf.db import sync_connections_from_config
        sync_connections_from_config(cfg.forwards)
        # Update source_id from from_to mapping
        from tgcf.db import get_all_connections, update_connection_source_id
        conns = get_all_connections()
        for c in conns:
            for sid, _ in config.from_to.items():
                if str(c.get("source_username")) in [str(f.source) for f in cfg.forwards]:
                    update_connection_source_id(c["id"], sid)
    except Exception as e:
        logging.warning(f"DB sync: {e}")

    await client.run_until_disconnected()
