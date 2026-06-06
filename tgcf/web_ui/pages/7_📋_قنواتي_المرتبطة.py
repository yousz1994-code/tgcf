"""Connection Management Dashboard - قنواتي المرتبطة"""

import streamlit as st
from datetime import datetime

from tgcf.db import (
    get_all_connections,
    get_connection_by_id,
    get_recent_activity,
    set_connection_active,
    delete_connection,
    sync_connections_from_config,
    init_db,
)
from tgcf.config import read_config
from tgcf.web_ui.password import check_password
from tgcf.web_ui.utils import hide_st, switch_theme

CONFIG = read_config()

st.set_page_config(
    page_title="قنواتي المرتبطة",
    page_icon="📋",
    layout="wide",
)
hide_st(st)
switch_theme(st, CONFIG)


def fmt_dt(dt):
    if not dt:
        return "—"
    if isinstance(dt, str):
        return dt[:16]
    return dt.strftime("%Y-%m-%d %H:%M")


def health_badge(row):
    total = int(row.get("total_received") or 0)
    failed = int(row.get("total_failed") or 0)
    active = row.get("is_active", True)
    if not active:
        return "🔴 معطّل"
    if total == 0:
        return "🟡 لا توجد بيانات"
    rate = ((total - failed) / total * 100) if total > 0 else 100
    if rate >= 90:
        return "🟢 سليم"
    elif rate >= 60:
        return "🟡 تحذير"
    else:
        return "🔴 خطأ"


def success_rate(row):
    total = int(row.get("total_received") or 0)
    failed = int(row.get("total_failed") or 0)
    if total == 0:
        return "—"
    rate = (total - failed) / total * 100
    return f"{rate:.1f}%"


if check_password(st):
    st.markdown("## 📋 قنواتي المرتبطة")
    st.caption("لوحة إدارة الاتصالات الكاملة")

    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔄 مزامنة من الإعدادات", use_container_width=True):
            try:
                sync_connections_from_config(CONFIG.forwards)
                st.success("تمت المزامنة!")
                st.rerun()
            except Exception as e:
                st.error(f"خطأ: {e}")

    try:
        init_db()
        connections = get_all_connections()
    except Exception as e:
        st.error(f"خطأ في قاعدة البيانات: {e}")
        connections = []

    if not connections:
        st.info("لا توجد اتصالات مسجّلة. استخدم زر 'مزامنة من الإعدادات' لاستيراد اتصالاتك.")
        st.stop()

    active_conns = [c for c in connections if c.get("is_active")]
    inactive_conns = [c for c in connections if not c.get("is_active")]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("إجمالي الاتصالات", len(connections))
    m2.metric("🟢 نشط", len(active_conns))
    m3.metric("🔴 متوقف", len(inactive_conns))
    total_fwd = sum(int(c.get("total_forwarded") or 0) for c in connections)
    m4.metric("📨 رسائل محوَّلة", total_fwd)

    st.divider()

    tab_active, tab_inactive, tab_all = st.tabs([
        f"🟢 النشطة ({len(active_conns)})",
        f"🔴 المتوقفة ({len(inactive_conns)})",
        f"📋 الكل ({len(connections)})",
    ])

    def render_connections(conn_list):
        for row in conn_list:
            cid = row["id"]
            name = row.get("con_name") or f"اتصال #{cid}"
            badge = health_badge(row)
            total = int(row.get("total_received") or 0)
            forwarded = int(row.get("total_forwarded") or 0)
            failed = int(row.get("total_failed") or 0)

            with st.expander(f"{badge}  |  **{name}**  —  المصدر: `{row.get('source_username') or '—'}`"):

                info_col, stats_col = st.columns(2)

                with info_col:
                    st.markdown("#### 📌 معلومات الاتصال")
                    st.markdown(f"**الاسم:** {name}")
                    st.markdown(f"**اسم المصدر:** `{row.get('source_username') or '—'}`")
                    st.markdown(f"**معرف المصدر:** `{row.get('source_id') or '—'}`")
                    dests = row.get("dest_channels") or "—"
                    st.markdown("**القنوات الهدف:**")
                    for d in dests.split(","):
                        d = d.strip()
                        if d:
                            st.markdown(f"  • `{d}`")
                    st.markdown(f"**تاريخ الإنشاء:** {fmt_dt(row.get('created_at'))}")
                    st.markdown(f"**آخر نشاط:** {fmt_dt(row.get('last_activity'))}")
                    last_msg = row.get("last_forwarded_text") or "—"
                    st.markdown(f"**آخر رسالة:** _{last_msg[:80]}_")

                with stats_col:
                    st.markdown("#### 📊 الإحصائيات")
                    st.metric("📥 رسائل مستلمة", total)
                    st.metric("📤 رسائل محوَّلة", forwarded)
                    st.metric("❌ رسائل فاشلة", failed)
                    st.metric("✅ نسبة النجاح", success_rate(row))

                st.markdown("#### ⚡ الإجراءات")
                a1, a2, a3, a5 = st.columns(4)

                is_active = row.get("is_active", True)

                with a1:
                    if is_active:
                        if st.button("⏸ إيقاف", key=f"pause_{cid}", use_container_width=True):
                            set_connection_active(cid, False)
                            st.success("تم الإيقاف")
                            st.rerun()
                    else:
                        if st.button("▶ تشغيل", key=f"resume_{cid}", use_container_width=True):
                            set_connection_active(cid, True)
                            st.success("تم التشغيل")
                            st.rerun()

                with a2:
                    if st.button("🔄 اختبار", key=f"test_{cid}", use_container_width=True):
                        try:
                            from tgcf.userbot import is_connected
                            if is_connected():
                                st.success("✅ الاتصال يعمل")
                            else:
                                st.error("❌ الUserbot غير متصل")
                        except Exception as e:
                            st.error(f"خطأ: {e}")

                with a3:
                    if st.button("📊 تفاصيل", key=f"detail_{cid}", use_container_width=True):
                        key = f"show_detail_{cid}"
                        st.session_state[key] = not st.session_state.get(key, False)

                with a5:
                    if st.button("🗑 حذف", key=f"del_{cid}", use_container_width=True):
                        st.session_state[f"confirm_del_{cid}"] = True

                if st.session_state.get(f"confirm_del_{cid}"):
                    st.warning(f"⚠️ هل أنت متأكد من حذف **{name}**؟ لا يمكن التراجع.")
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        if st.button("✅ نعم، احذف", key=f"confirm_yes_{cid}", type="primary"):
                            delete_connection(cid)
                            st.success("تم الحذف!")
                            st.session_state[f"confirm_del_{cid}"] = False
                            st.rerun()
                    with dc2:
                        if st.button("❌ إلغاء", key=f"confirm_no_{cid}"):
                            st.session_state[f"confirm_del_{cid}"] = False
                            st.rerun()

                if st.session_state.get(f"show_detail_{cid}"):
                    st.markdown("#### 🕐 آخر 5 عمليات إعادة توجيه")
                    try:
                        logs = get_recent_activity(cid, limit=5)
                        if logs:
                            for log in logs:
                                status_icon = "✅" if log["status"] == "ok" else "❌"
                                preview = (log.get("message_preview") or "")[:60]
                                ts = fmt_dt(log.get("created_at"))
                                dest = log.get("dest_id") or "?"
                                st.markdown(f"{status_icon} `{ts}` → `{dest}` — _{preview}_")
                        else:
                            st.info("لا توجد سجلات بعد.")
                    except Exception as e:
                        st.error(f"خطأ في السجلات: {e}")

    with tab_active:
        if active_conns:
            render_connections(active_conns)
        else:
            st.info("لا توجد اتصالات نشطة.")

    with tab_inactive:
        if inactive_conns:
            render_connections(inactive_conns)
        else:
            st.info("لا توجد اتصالات متوقفة.")

    with tab_all:
        render_connections(connections)
