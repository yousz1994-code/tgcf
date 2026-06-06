"""Reports Panel - لوحة التقارير"""

import streamlit as st
from datetime import datetime, timedelta

from tgcf.db import get_all_connections, get_global_stats, get_today_stats, get_recent_activity, init_db
from tgcf.config import read_config
from tgcf.web_ui.password import check_password
from tgcf.web_ui.utils import hide_st, switch_theme

CONFIG = read_config()

st.set_page_config(
    page_title="التقارير",
    page_icon="📊",
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


if check_password(st):
    st.markdown("## 📊 لوحة التقارير والإحصائيات")
    st.caption("إحصائيات حية من قاعدة البيانات فقط")

    if st.button("🔄 تحديث البيانات", use_container_width=False):
        st.rerun()

    try:
        init_db()
        global_stats = get_global_stats()
        today_stats = get_today_stats()
        connections = get_all_connections()
    except Exception as e:
        st.error(f"خطأ في قاعدة البيانات: {e}")
        st.stop()

    st.markdown("### 📈 إحصائيات إجمالية")
    g1, g2, g3, g4 = st.columns(4)
    total_msg = int(global_stats.get("total_messages") or 0)
    total_fwd = int(global_stats.get("total_forwarded") or 0)
    total_fail = int(global_stats.get("total_failed") or 0)
    total_rate = f"{(total_fwd/total_msg*100):.1f}%" if total_msg > 0 else "—"

    g1.metric("📨 إجمالي الرسائل", total_msg)
    g2.metric("✅ محوَّلة بنجاح", total_fwd)
    g3.metric("❌ فاشلة", total_fail)
    g4.metric("📊 نسبة النجاح الكلية", total_rate)

    st.divider()

    st.markdown("### 📅 إحصائيات اليوم")
    t1, t2, t3 = st.columns(3)
    today_msg = int(today_stats.get("total_messages") or 0)
    today_fwd = int(today_stats.get("total_forwarded") or 0)
    today_fail = int(today_stats.get("total_failed") or 0)

    t1.metric("📨 رسائل اليوم", today_msg)
    t2.metric("✅ محوَّلة اليوم", today_fwd)
    t3.metric("❌ فاشلة اليوم", today_fail)

    st.divider()

    st.markdown("### 🔗 إحصائيات الاتصالات")

    if not connections:
        st.info("لا توجد اتصالات مسجّلة بعد.")
    else:
        for row in connections:
            cid = row["id"]
            name = row.get("con_name") or f"اتصال #{cid}"
            total = int(row.get("total_received") or 0)
            forwarded = int(row.get("total_forwarded") or 0)
            failed = int(row.get("total_failed") or 0)
            rate = f"{(forwarded/total*100):.1f}%" if total > 0 else "—"
            active = row.get("is_active", True)
            status_icon = "🟢" if active else "🔴"

            with st.expander(f"{status_icon} **{name}** — محوَّل: {forwarded} | فاشل: {failed} | نسبة: {rate}"):
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("📥 مستلم", total)
                r2.metric("📤 محوَّل", forwarded)
                r3.metric("❌ فاشل", failed)
                r4.metric("✅ نسبة", rate)

                st.markdown(f"**المصدر:** `{row.get('source_username') or '—'}`  |  **آخر نشاط:** {fmt_dt(row.get('last_activity'))}")

                st.markdown("**آخر 5 عمليات:**")
                try:
                    logs = get_recent_activity(cid, limit=5)
                    if logs:
                        rows_data = []
                        for log in logs:
                            icon = "✅" if log["status"] == "ok" else "❌"
                            rows_data.append({
                                "الحالة": icon,
                                "الوقت": fmt_dt(log.get("created_at")),
                                "الوجهة": str(log.get("dest_id") or "?"),
                                "الرسالة": (log.get("message_preview") or "")[:50],
                            })
                        st.table(rows_data)
                    else:
                        st.info("لا توجد سجلات بعد.")
                except Exception as e:
                    st.error(f"خطأ: {e}")

    st.divider()

    st.markdown("### 🔧 أدوات قاعدة البيانات")
    with st.expander("🗄️ حالة قاعدة البيانات"):
        try:
            import os, psycopg2
            conn = psycopg2.connect(os.getenv("DATABASE_URL"))
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM connections")
            c_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM message_logs")
            m_count = cur.fetchone()[0]
            conn.close()
            st.success("✅ قاعدة البيانات متصلة وتعمل")
            st.markdown(f"- عدد الاتصالات: **{c_count}**")
            st.markdown(f"- عدد السجلات: **{m_count}**")
        except Exception as e:
            st.error(f"❌ خطأ: {e}")
