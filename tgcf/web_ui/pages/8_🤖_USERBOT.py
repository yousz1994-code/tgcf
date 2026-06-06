"""USERBOT Control Panel"""

import streamlit as st
import os
import time

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


def get_userbot_status():
    try:
        from tgcf.userbot import get_status
        return get_status()
    except Exception as e:
        return {"connected": False, "error": str(e), "me": None}


if check_password(st):
    st.markdown("## 🤖 لوحة تحكم USERBOT")
    st.caption("إدارة جلسة المستخدم التلقائية (Userbot)")

    st.divider()

    status = get_userbot_status()
    connected = status.get("connected", False)
    me = status.get("me")
    error = status.get("error")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("### 📡 حالة الاتصال")
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
            st.error("🔴 غير متصل")
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
                        st.success(f"✅ الاتصال يعمل: {msg}")
                    else:
                        st.error(f"❌ فشل: {msg}")
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

    st.markdown("### 🔐 بيانات الجلسة")

    has_session = bool(os.getenv("SESSION_STRING"))
    has_api_id = bool(os.getenv("API_ID"))
    has_api_hash = bool(os.getenv("API_HASH"))
    has_bot_token = bool(os.getenv("BOT_TOKEN"))
    has_admin_id = bool(os.getenv("ADMIN_ID"))

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("API_ID", "✅" if has_api_id else "❌")
    c2.metric("API_HASH", "✅" if has_api_hash else "❌")
    c3.metric("SESSION_STRING", "✅" if has_session else "❌")
    c4.metric("BOT_TOKEN", "✅" if has_bot_token else "❌")
    c5.metric("ADMIN_ID", "✅" if has_admin_id else "❌")

    st.divider()

    st.markdown("### 🔑 توليد جلسة جديدة")
    with st.expander("🔧 Generate Session String"):
        st.info("لتوليد SESSION_STRING جديد، استخدم الأداة التالية:")
        st.code("pip install tg-login && tg-login", language="bash")
        st.markdown("أو استخدم الرابط: https://replit.com/@aahnik/tg-login?v=1")
        st.markdown("**بعد الحصول على SESSION_STRING الجديد:**")
        st.markdown("1. افتح Replit Secrets")
        st.markdown("2. عدّل قيمة `SESSION_STRING`")
        st.markdown("3. اضغط زر **إعادة الاتصال** أعلاه")

    st.divider()

    st.markdown("### 🔁 تحديث الجلسة")
    with st.expander("♻️ Refresh Session"):
        st.warning("⚠️ سيؤدي هذا إلى قطع الاتصال الحالي وإعادة تهيئة الجلسة من البداية.")
        new_session = st.text_input("أدخل SESSION_STRING الجديد:", type="password", key="new_session_input")
        if st.button("✅ تطبيق الجلسة الجديدة", type="primary"):
            if new_session:
                st.warning("لحفظ الجلسة بشكل دائم، يرجى إضافتها في Replit Secrets تحت اسم SESSION_STRING")
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

    st.markdown("### 👑 BIG BOSS Panel")
    st.caption("لوحة تحكم المدير الكبير")

    admin_id = os.getenv("ADMIN_ID", "")

    bc1, bc2 = st.columns(2)

    with bc1:
        st.markdown("#### 📢 قناة الدعم")
        if st.button("📢 قناة الدعم", use_container_width=True, key="support_ch"):
            st.session_state["show_support"] = not st.session_state.get("show_support", False)
        if st.session_state.get("show_support"):
            st.markdown("[قناة الدعم — https://t.me/shaheenys](https://t.me/shaheenys)")

    with bc2:
        st.markdown("#### 🎁 الهدية اليومية")
        if st.button("🎁 الهدية اليومية", use_container_width=True, key="daily_gift"):
            st.session_state["show_gift"] = not st.session_state.get("show_gift", False)
        if st.session_state.get("show_gift"):
            st.markdown("[الهدية اليومية — https://t.me/fi1_oo](https://t.me/fi1_oo)")

    st.divider()
    st.caption(f"Admin ID: `{admin_id}`")
    if connected and me:
        st.caption("Auto-refresh: الاتصال يعمل تلقائياً")
