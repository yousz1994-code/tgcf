"""USERBOT Control Panel — includes Admin Bot status."""

import os
import time

import streamlit as st

from tgcf.config import read_config
from tgcf.web_ui.password import check_password
from tgcf.web_ui.utils import hide_st, switch_theme

CONFIG = read_config()

st.set_page_config(
    page_title="USERBOT Panel",
    page_icon="🤖",
    layout="wide",
)
hide_st(st)
switch_theme(st, CONFIG)

if check_password(st):
    st.markdown("## 🤖 لوحة تحكم USERBOT")
    st.caption("إدارة جلسة المستخدم التلقائية (Userbot) وبوت الإدارة")

    st.divider()

    # ── Userbot Status ────────────────────────────────────────────────────
    st.markdown("### 📡 حالة Userbot")
    try:
        from tgcf.userbot import get_status
        status = get_status()
    except Exception as ex:
        status = {"connected": False, "error": str(ex), "me": None}

    connected = status.get("connected", False)
    me = status.get("me")
    error = status.get("error")

    col1, col2 = st.columns([2, 1])

    with col1:
        if connected and me:
            st.success("🟢 متصل ويعمل")
            info_col1, info_col2 = st.columns(2)
            with info_col1:
                st.markdown(f"**الاسم:** {me.get('name', '—')}")
                st.markdown(f"**المعرف:** `{me.get('id', '—')}`")
            with info_col2:
                st.markdown(f"**اليوزرنيم:** @{me.get('username', '—')}")
                st.markdown(f"**الهاتف:** `{me.get('phone', '—')}`")
        else:
            st.error("🔴 Userbot غير متصل")
            if error:
                st.warning(f"السبب: {error}")

    with col2:
        st.markdown("### ⚙️ الإجراءات")

        if st.button("🔄 إعادة الاتصال", use_container_width=True, type="primary"):
            with st.spinner("جاري إعادة الاتصال..."):
                try:
                    from tgcf.userbot import reconnect_userbot
                    reconnect_userbot()
                    time.sleep(3)
                    st.rerun()
                except Exception as e:
                    st.error(f"خطأ: {e}")

        if st.button("🧪 اختبار الاتصال", use_container_width=True):
            with st.spinner("جاري الاختبار..."):
                try:
                    from tgcf.userbot import test_connection
                    ok, msg = test_connection()
                    if ok:
                        st.success(f"✅ {msg}")
                    else:
                        st.error(f"❌ {msg}")
                except Exception as e:
                    st.error(f"خطأ: {e}")

        if st.button("⏹ قطع الاتصال", use_container_width=True):
            with st.spinner("جاري قطع الاتصال..."):
                try:
                    from tgcf.userbot import disconnect_userbot
                    disconnect_userbot()
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"خطأ: {e}")

    st.divider()

    # ── Admin Bot Status ──────────────────────────────────────────────────
    st.markdown("### 🤖 بوت الإدارة عبر تيليغرام")
    try:
        from tgcf.bot.admin_bot import get_bot_status
        bs = get_bot_status()
        if bs.get("running"):
            bme = bs.get("me") or {}
            st.success(
                f"🟢 **بوت الإدارة يعمل** — "
                f"@{bme.get('username', '')} (ID: {bme.get('id', '')})"
            )
            st.info(
                "📱 **افتح البوت في تيليغرام وأرسل /start**\n\n"
                "**الأوامر المتاحة:**  \n"
                "`/start` — القائمة الرئيسية  \n"
                "`/help` — المساعدة  \n"
                "`/stats` — الإحصائيات  \n"
                "`/health` — فحص النظام  \n"
                "`/connections` — إدارة الروابط  \n"
                "`/reports` — تقارير التحويل  \n"
                "`/userbot` — حالة Userbot  \n"
                "`/session` — معلومات الجلسة  \n"
                "`/restart_userbot` — إعادة تشغيل Userbot  \n"
                "`/reload_connections` — إعادة تحميل الروابط  \n"
                "`/ping` — اختبار الاستجابة"
            )
        else:
            err = bs.get("error", "لم يبدأ بعد")
            st.warning(f"🟡 بوت الإدارة غير نشط — {err}")
            st.info("سيبدأ بوت الإدارة تلقائياً عند تشغيل وضع Live (صفحة 🏃 Run).")
    except Exception as e:
        st.warning(f"بوت الإدارة: {e}")

    st.divider()

    # ── Session Details ───────────────────────────────────────────────────
    st.markdown("### 🔐 بيانات الجلسة")

    has_api_id = bool(os.getenv("API_ID"))
    has_api_hash = bool(os.getenv("API_HASH"))
    has_session = bool(os.getenv("SESSION_STRING"))
    has_bot_token = bool(os.getenv("BOT_TOKEN"))
    has_admin_id = bool(os.getenv("ADMIN_ID"))

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("API_ID",         "✅" if has_api_id     else "❌")
    c2.metric("API_HASH",       "✅" if has_api_hash   else "❌")
    c3.metric("SESSION_STRING", "✅" if has_session    else "❌")
    c4.metric("BOT_TOKEN",      "✅" if has_bot_token  else "❌")
    c5.metric("ADMIN_ID",       "✅" if has_admin_id   else "❌")

    st.divider()

    # ── Update Session ────────────────────────────────────────────────────
    st.markdown("### 🔑 تحديث الجلسة")
    with st.expander("♻️ تطبيق SESSION_STRING جديد"):
        st.warning(
            "⚠️ لحفظ الجلسة بشكل دائم، يرجى تحديثها في Replit Secrets "
            "تحت اسم SESSION_STRING ثم إعادة تشغيل التطبيق."
        )
        new_session = st.text_input(
            "أدخل SESSION_STRING الجديد:", type="password", key="new_session_input"
        )
        if st.button("✅ تطبيق الجلسة الجديدة", type="primary"):
            if new_session:
                os.environ["SESSION_STRING"] = new_session
                try:
                    from tgcf.userbot import reconnect_userbot
                    reconnect_userbot()
                    time.sleep(3)
                    st.success("✅ تم تطبيق الجلسة الجديدة!")
                    st.rerun()
                except Exception as e:
                    st.error(f"خطأ: {e}")
            else:
                st.error("أدخل الجلسة أولاً")

    st.divider()

    # ── BIG BOSS Panel ────────────────────────────────────────────────────
    st.markdown("### 👑 BIG BOSS Panel")
    admin_id = os.getenv("ADMIN_ID", "—")
    st.caption(f"Admin ID: `{admin_id}`")

    bc1, bc2 = st.columns(2)

    with bc1:
        st.markdown("#### 📢 قناة الدعم")
        if st.button("📢 فتح قناة الدعم", use_container_width=True, key="support_ch"):
            st.session_state["show_support"] = not st.session_state.get("show_support", False)
        if st.session_state.get("show_support"):
            st.markdown("[📢 قناة الدعم — @shaheenys](https://t.me/shaheenys)")

    with bc2:
        st.markdown("#### 🎁 الهدية اليومية")
        if st.button("🎁 الهدية اليومية", use_container_width=True, key="daily_gift"):
            st.session_state["show_gift"] = not st.session_state.get("show_gift", False)
        if st.session_state.get("show_gift"):
            st.markdown("[🎁 الهدية اليومية — @fi1_oo](https://t.me/fi1_oo)")

    if connected and me:
        st.divider()
        st.caption("🟢 Userbot يعمل تلقائياً — Auto-refresh متاح")
