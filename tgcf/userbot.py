"""Userbot manager - persistent Telethon client running in background."""

import asyncio
import logging
import os
import threading
from typing import Optional

from telethon import TelegramClient, events
from telethon.sessions import StringSession

_client: Optional[TelegramClient] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_thread: Optional[threading.Thread] = None
_status = {"connected": False, "error": None, "me": None}


def _get_credentials():
    api_id = os.getenv("API_ID", "0")
    api_hash = os.getenv("API_HASH", "")
    session_string = os.getenv("SESSION_STRING", "")
    return int(api_id), api_hash, session_string


def _run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


async def _connect():
    global _client, _status
    api_id, api_hash, session_string = _get_credentials()
    if not session_string:
        _status["error"] = "SESSION_STRING not set"
        _status["connected"] = False
        return
    try:
        _client = TelegramClient(StringSession(session_string), api_id, api_hash)
        await _client.connect()
        if not await _client.is_user_authorized():
            _status["error"] = "Session not authorized"
            _status["connected"] = False
            return
        me = await _client.get_me()
        _status["connected"] = True
        _status["error"] = None
        _status["me"] = {
            "id": me.id,
            "name": f"{me.first_name or ''} {me.last_name or ''}".strip(),
            "username": me.username or "",
            "phone": me.phone or "",
        }
        logging.info(f"Userbot connected: {_status['me']}")
    except Exception as e:
        _status["connected"] = False
        _status["error"] = str(e)
        logging.error(f"Userbot connect error: {e}")


def start_userbot():
    global _loop, _thread
    if _loop and _loop.is_running():
        return
    _loop = asyncio.new_event_loop()
    _thread = threading.Thread(target=_run_loop, args=(_loop,), daemon=True)
    _thread.start()
    asyncio.run_coroutine_threadsafe(_connect(), _loop)


def get_status():
    return dict(_status)


def get_client() -> Optional[TelegramClient]:
    return _client


def is_connected() -> bool:
    return _status.get("connected", False)


async def _disconnect():
    global _client, _status
    if _client:
        await _client.disconnect()
        _client = None
    _status["connected"] = False
    _status["me"] = None


def disconnect_userbot():
    global _loop
    if _loop and _loop.is_running() and _client:
        fut = asyncio.run_coroutine_threadsafe(_disconnect(), _loop)
        try:
            fut.result(timeout=10)
        except Exception as e:
            logging.error(f"Disconnect error: {e}")


def reconnect_userbot():
    global _loop, _status
    _status["connected"] = False
    _status["me"] = None
    if _loop and _loop.is_running():
        fut = asyncio.run_coroutine_threadsafe(_connect(), _loop)
        try:
            fut.result(timeout=15)
        except Exception as e:
            logging.error(f"Reconnect error: {e}")
    else:
        start_userbot()


async def _test_connection():
    global _client
    if not _client:
        return False, "No client"
    try:
        me = await _client.get_me()
        return True, f"{me.first_name} (@{me.username})"
    except Exception as e:
        return False, str(e)


def test_connection():
    global _loop
    if not _loop or not _loop.is_running():
        return False, "Event loop not running"
    fut = asyncio.run_coroutine_threadsafe(_test_connection(), _loop)
    try:
        return fut.result(timeout=10)
    except Exception as e:
        return False, str(e)


# Auto-start on import
start_userbot()
