import os
import signal
import subprocess
import time

import streamlit as st

from tgcf.config import CONFIG, read_config, write_config
from tgcf.config_env import load_env_into_config
from tgcf.web_ui.password import check_password
from tgcf.web_ui.utils import hide_st, switch_theme

load_env_into_config()

CONFIG = read_config()


def termination():
    st.code("process terminated!")
    try:
        os.rename("logs.txt", "old_logs.txt")
        with open("old_logs.txt", "r") as f:
            st.download_button(
                "Download last logs", data=f.read(), file_name="tgcf_logs.txt"
            )
    except FileNotFoundError:
        pass

    cfg = read_config()
    cfg.pid = 0
    write_config(cfg)
    st.button("Refresh page")


st.set_page_config(
    page_title="Run",
    page_icon="🏃",
)
hide_st(st)
switch_theme(st, CONFIG)

if check_password(st):
    # ── Admin Bot Status banner ───────────────────────────────────────────
    try:
        from tgcf.bot.admin_bot import get_bot_status, start_admin_bot
        bs = get_bot_status()
        if bs.get("running"):
            bme = bs.get("me") or {}
            st.success(
                f"🤖 بوت الإدارة يعمل — @{bme.get('username', '')} — "
                "أرسل /start في تيليغرام للوصول إلى لوحة التحكم"
            )
        else:
            # Try to start if not running
            start_admin_bot()
            time.sleep(1)
            bs2 = get_bot_status()
            if bs2.get("running"):
                st.success("🤖 تم تشغيل بوت الإدارة!")
            else:
                st.info(f"🟡 بوت الإدارة: {bs2.get('error', 'جاري البدء...')}")
    except Exception as e:
        st.warning(f"بوت الإدارة: {e}")

    with st.expander("Configure Run"):
        CONFIG.show_forwarded_from = st.checkbox(
            "Show 'Forwarded from'", value=CONFIG.show_forwarded_from
        )
        mode = st.radio("Choose mode", ["live", "past"], index=CONFIG.mode)
        if mode == "past":
            CONFIG.mode = 1
            st.warning(
                "Only User Account can be used in Past mode. Telegram does not allow bot account to go through history of a chat!"
            )
            CONFIG.past.delay = st.slider(
                "Delay in seconds", 0, 100, value=CONFIG.past.delay
            )
        else:
            CONFIG.mode = 0
            CONFIG.live.delete_sync = st.checkbox(
                "Sync when a message is deleted", value=CONFIG.live.delete_sync
            )

        if st.button("Save"):
            write_config(CONFIG)

    check = False

    if CONFIG.pid == 0:
        check = st.button("Run", type="primary")

    if CONFIG.pid != 0:
        st.warning(
            "You must click stop and then re-run tgcf to apply changes in config."
        )
        try:
            os.kill(CONFIG.pid, signal.SIGCONT)
        except Exception as err:
            st.code("The process has stopped.")
            st.code(err)
            CONFIG.pid = 0
            write_config(CONFIG)
            time.sleep(1)
            st.rerun()

        stop = st.button("Stop", type="primary")
        if stop:
            try:
                os.kill(CONFIG.pid, signal.SIGSTOP)
            except Exception as err:
                st.code(err)
                CONFIG.pid = 0
                write_config(CONFIG)
                st.button("Refresh Page")
            else:
                termination()

    if check:
        with open("logs.txt", "w") as logs:
            process = subprocess.Popen(
                ["tgcf", "--loud", mode],
                stdout=logs,
                stderr=subprocess.STDOUT,
            )
        CONFIG.pid = process.pid
        write_config(CONFIG)
        time.sleep(2)
        st.rerun()

    try:
        lines = st.slider(
            "Lines of logs to show", min_value=100, max_value=1000, step=100
        )
        temp_logs = "logs_n_lines.txt"
        os.system(f"rm -f {temp_logs}")
        with open("logs.txt", "r") as file:
            pass
        os.system(f"tail -n {lines} logs.txt >> {temp_logs}")
        with open(temp_logs, "r") as file:
            st.code(file.read())
    except FileNotFoundError:
        st.write("No present logs found")
    st.button("Load more logs")
