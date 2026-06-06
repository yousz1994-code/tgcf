import os
import streamlit as st

from tgcf.web_ui.utils import hide_st, switch_theme
from tgcf.config import read_config

CONFIG = read_config()

# Auto-start admin bot on app load
try:
    from tgcf.bot.admin_bot import start_admin_bot, get_bot_status
    if not get_bot_status().get("running"):
        start_admin_bot()
except Exception:
    pass

st.set_page_config(
    page_title="Hello",
    page_icon="👋",
    layout="wide",
)
hide_st(st)
switch_theme(st, CONFIG)

st.write("# Welcome to tgcf 👋")

html = """
<p align="center">
<img src = "https://user-images.githubusercontent.com/66209958/115183360-3fa4d500-a0f9-11eb-9c0f-c5ed03a9ae17.png" alt = "tgcf logo"  width=120>
</p>
"""
st.components.v1.html(html, width=None, height=None, scrolling=False)

# ── Userbot status banner ───────────────────────────────────────────────────
try:
    from tgcf.userbot import get_status
    ub = get_status()
    if ub.get("connected") and ub.get("me"):
        me = ub["me"]
        st.success(f"🟢 Userbot متصل: **{me.get('name','')}** (@{me.get('username','')})")
    else:
        err = ub.get("error", "غير متصل")
        st.error(f"🔴 Userbot غير متصل — {err}")
except Exception as e:
    st.warning(f"Userbot: {e}")

st.divider()

# ── Quick Action Buttons ────────────────────────────────────────────────────
st.markdown("### 🎛️ لوحة التحكم السريعة")
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown("**📢 قناة الدعم**")
    if st.button("📢 قناة الدعم", use_container_width=True, key="btn_support"):
        st.session_state["show_support"] = not st.session_state.get("show_support", False)
    if st.session_state.get("show_support", False):
        st.markdown("[🔗 قناة الدعم](https://t.me/shaheenys)")

with col2:
    st.markdown("**🎁 الهدية اليومية**")
    if st.button("🎁 الهدية اليومية", use_container_width=True, key="btn_gift"):
        st.session_state["show_gift"] = not st.session_state.get("show_gift", False)
    if st.session_state.get("show_gift", False):
        st.markdown("[🔗 الهدية اليومية](https://t.me/fi1_oo)")

with col3:
    st.markdown("**📋 قنواتي المرتبطة**")
    st.info("📋 اذهب إلى الصفحة من القائمة الجانبية")

with col4:
    st.markdown("**🤖 USERBOT Panel**")
    st.info("🤖 اذهب إلى الصفحة من القائمة الجانبية")

st.divider()

# ── Global Stats ────────────────────────────────────────────────────────────
st.markdown("### 📊 الإحصائيات العامة")
try:
    from tgcf.db import get_global_stats, get_today_stats, get_all_connections, init_db
    init_db()
    gs = get_global_stats()
    ts = get_today_stats()
    conns = get_all_connections()

    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("🔗 الاتصالات", len(conns))
    s2.metric("📨 إجمالي الرسائل", int(gs.get("total_messages") or 0))
    s3.metric("✅ محوَّل", int(gs.get("total_forwarded") or 0))
    s4.metric("📅 اليوم", int(ts.get("total_messages") or 0))
    total = int(gs.get("total_messages") or 0)
    fwd = int(gs.get("total_forwarded") or 0)
    rate = f"{fwd/total*100:.1f}%" if total > 0 else "—"
    s5.metric("📈 نسبة النجاح", rate)
except Exception as e:
    st.info(f"الإحصائيات غير متاحة: {e}")

st.divider()

with st.expander("ℹ️ Features"):
    st.markdown("""
tgcf is the ultimate tool to automate custom telegram message forwarding.

- Forward messages as "forwarded" or send a copy from source to destination chats.
- Supports **live** mode (real-time) and **past** mode (history).
- Login with a bot or userbot account.
- Custom plugins: filter, format, replace, watermark, OCR, captions.
- Full connection dashboard with real statistics.
    """)

st.warning("Please press Save after changing any config.")
