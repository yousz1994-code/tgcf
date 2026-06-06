"""Telegram Admin Bot — Primary administration interface for tgcf.

Runs a separate bot client (BOT_TOKEN) in its own thread/event-loop
alongside the userbot forwarding client.  All menus are inline-keyboard
driven; a 7-step wizard handles connection creation with full validation.
New: /broadcast (all active destinations) and /sendto (single destination).
"""

import asyncio
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from telethon import Button, TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    FloodWaitError,
    UserNotParticipantError,
    UsernameInvalidError,
    RPCError,
)
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.types import (
    Channel,
    ChannelParticipantAdmin,
    ChannelParticipantCreator,
    Chat,
    MessageMediaPhoto,
    MessageMediaDocument,
    User,
)

log = logging.getLogger("admin_bot")

# ══════════════════════════════════════════════════════════════════════════════
#  Module-level state
# ══════════════════════════════════════════════════════════════════════════════

_bot_client: Optional[TelegramClient] = None
_bot_loop: Optional[asyncio.AbstractEventLoop] = None
_bot_thread: Optional[threading.Thread] = None
_bot_status: Dict[str, Any] = {"running": False, "error": None, "me": None}

# wizard / broadcast / sendto state keyed by user_id
_wizard: Dict[int, Dict] = {}

# Wizard step groups
_WIZARD_STEPS = {"wizard_source", "wizard_dest"}
_BROADCAST_STEPS = {"broadcast_content", "broadcast_confirm"}
_SENDTO_STEPS = {"sendto_select", "sendto_content", "sendto_confirm"}
_ALL_STEPS = _WIZARD_STEPS | _BROADCAST_STEPS | _SENDTO_STEPS


# ══════════════════════════════════════════════════════════════════════════════
#  Security helpers
# ══════════════════════════════════════════════════════════════════════════════

def _get_admin_ids() -> List[int]:
    ids: List[int] = []
    raw = os.getenv("ADMIN_ID", "")
    if raw:
        try:
            ids.append(int(raw))
        except ValueError:
            pass
    try:
        from tgcf.config import ADMINS
        for a in ADMINS:
            try:
                ids.append(int(a))
            except Exception:
                pass
    except Exception:
        pass
    return list(set(ids))


def is_admin(user_id: int) -> bool:
    """Return True iff user_id is an authorised administrator."""
    return user_id in _get_admin_ids()


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fmt_num(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return "0"


# ══════════════════════════════════════════════════════════════════════════════
#  Inline keyboards
# ══════════════════════════════════════════════════════════════════════════════

def _kb_main():
    return [
        [Button.inline("🔗 إدارة الروابط",    b"menu:connections"),
         Button.inline("📋 قنواتي المرتبطة", b"menu:my_connections")],
        [Button.inline("🤖 USERBOT",            b"menu:userbot"),
         Button.inline("📊 الإحصائيات",        b"menu:stats")],
        [Button.inline("📈 التقارير",           b"menu:reports"),
         Button.inline("🔄 إدارة الجلسة",      b"menu:session")],
        [Button.inline("📢 بث رسالة",           b"menu:broadcast"),
         Button.inline("🎯 إرسال مستهدف",      b"menu:sendto")],
        [Button.inline("⚙️ الإعدادات",          b"menu:settings"),
         Button.inline("👑 𝐁𝐈𝐆 𝐁𝐎𝐒𝐒",        b"menu:bigboss")],
        [Button.url("📢 قناة الدعم", "https://t.me/shaheenys"),
         Button.url("🎁 الهدية اليومية",  "https://t.me/fi1_oo")],
    ]


def _kb_connections():
    return [
        [Button.inline("➕ إنشاء ربط",   b"wizard:start"),
         Button.inline("📋 عرض الروابط", b"conn:list")],
        [Button.inline("🔄 مزامنة",       b"conn:sync"),
         Button.inline("◀️ رجوع",         b"menu:main")],
    ]


def _kb_conn_list(connections):
    rows = []
    for c in connections[:8]:
        cid = c["id"]
        name = (c.get("con_name") or c.get("source_username") or f"#{cid}")[:22]
        status = "🟢" if c.get("is_active") else "🔴"
        rows.append([Button.inline(f"{status} {name}", f"conn:detail:{cid}".encode())])
    rows.append([Button.inline("◀️ رجوع", b"menu:connections")])
    return rows


def _kb_conn_detail(cid: int, is_active: bool):
    return [
        [Button.inline("📊 تفاصيل",    f"conn:stats:{cid}".encode()),
         Button.inline("🔄 اختبار",    f"conn:test:{cid}".encode())],
        [Button.inline("⏸ إيقاف" if is_active else "▶️ تشغيل",
                       f"conn:pause:{cid}".encode() if is_active else f"conn:resume:{cid}".encode()),
         Button.inline("🗑 حذف",       f"conn:delete:{cid}".encode())],
        [Button.inline("◀️ رجوع",      b"conn:list")],
    ]


def _kb_confirm_delete(cid: int):
    return [
        [Button.inline("✅ تأكيد الحذف",  f"conn:delete_confirm:{cid}".encode()),
         Button.inline("❌ إلغاء",         f"conn:detail:{cid}".encode())],
    ]


def _kb_userbot():
    return [
        [Button.inline("🔄 إعادة الاتصال",  b"ub:reconnect"),
         Button.inline("📊 الحالة",          b"ub:status")],
        [Button.inline("🧪 اختبار الاتصال",  b"ub:test"),
         Button.inline("◀️ رجوع",            b"menu:main")],
    ]


def _kb_session():
    return [
        [Button.inline("📋 معلومات الجلسة", b"sess:info"),
         Button.inline("🔄 إعادة تحميل",    b"sess:reload")],
        [Button.inline("◀️ رجوع",            b"menu:main")],
    ]


def _kb_back_main():
    return [[Button.inline("◀️ رجوع للقائمة الرئيسية", b"menu:main")]]


def _kb_wizard_cancel():
    return [[Button.inline("❌ إلغاء المعالج", b"wizard:cancel")]]


def _kb_broadcast_confirm():
    return [
        [Button.inline("✅ إرسال للجميع",  b"bc:confirm"),
         Button.inline("❌ إلغاء",          b"bc:cancel")],
    ]


def _kb_sendto_confirm():
    return [
        [Button.inline("✅ إرسال",   b"st:confirm"),
         Button.inline("❌ إلغاء",   b"st:cancel")],
    ]


def _kb_sendto_select(destinations: List[Tuple]):
    """destinations: list of (dest_id, display_name)"""
    rows = []
    for i, (did, dname) in enumerate(destinations[:10]):
        label = f"📥 {dname}"[:30]
        rows.append([Button.inline(label, f"st:sel:{i}".encode())])
    rows.append([Button.inline("❌ إلغاء", b"st:cancel")])
    return rows


# ══════════════════════════════════════════════════════════════════════════════
#  Stats / reports helpers
# ══════════════════════════════════════════════════════════════════════════════

def _get_stats_text() -> str:
    try:
        from tgcf.db import get_global_stats, get_today_stats, get_all_connections
        gs = get_global_stats() or {}
        ts = get_today_stats() or {}
        conns = get_all_connections()
        active = sum(1 for c in conns if c.get("is_active"))
        total_m = int(gs.get("total_messages") or 0)
        total_f = int(gs.get("total_forwarded") or 0)
        total_fail = int(gs.get("total_failed") or 0)
        today_m = int(ts.get("total_messages") or 0)
        today_f = int(ts.get("total_forwarded") or 0)
        rate = f"{total_f / total_m * 100:.1f}%" if total_m > 0 else "—"
        return (
            f"📊 **الإحصائيات العامة**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔗 الروابط الإجمالية: `{len(conns)}`\n"
            f"🟢 الروابط النشطة:   `{active}`\n"
            f"📨 إجمالي الرسائل:   `{_fmt_num(total_m)}`\n"
            f"✅ تم التحويل:        `{_fmt_num(total_f)}`\n"
            f"❌ فشل:               `{_fmt_num(total_fail)}`\n"
            f"📅 اليوم (رسائل):    `{_fmt_num(today_m)}`\n"
            f"📅 اليوم (محوَّل):    `{_fmt_num(today_f)}`\n"
            f"📈 نسبة النجاح:       `{rate}`\n"
            f"🕐 {_now_str()}"
        )
    except Exception as e:
        return f"❌ خطأ في الإحصائيات: {e}"


def _get_connections_report() -> str:
    try:
        from tgcf.db import get_all_connections
        conns = get_all_connections()
        if not conns:
            return "📋 لا توجد روابط محفوظة."
        lines = ["📋 **قنواتي المرتبطة**\n━━━━━━━━━━━━━━━━━━"]
        for c in conns:
            name = c.get("con_name") or c.get("source_username") or f"#{c['id']}"
            status = "🟢" if c.get("is_active") else "🔴"
            src = c.get("source_username", "—")
            dest = c.get("dest_channels", "—")
            recv = int(c.get("total_received") or 0)
            fwd = int(c.get("total_forwarded") or 0)
            fail = int(c.get("total_failed") or 0)
            rate = f"{fwd / recv * 100:.0f}%" if recv > 0 else "—"
            last = c.get("last_activity")
            last_str = last.strftime("%m/%d %H:%M") if last else "—"
            lines.append(
                f"\n{status} **{name}**\n"
                f"  📤 من: `{src}`\n"
                f"  📥 إلى: `{dest}`\n"
                f"  📨 استُقبل: `{recv}` | ✅ حُوِّل: `{fwd}` | ❌ فشل: `{fail}`\n"
                f"  📈 نجاح: `{rate}` | 🕐 آخر نشاط: `{last_str}`"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"❌ خطأ: {e}"


def _get_userbot_text() -> str:
    try:
        from tgcf.userbot import get_status, test_connection
        s = get_status()
        if s.get("connected") and s.get("me"):
            me = s["me"]
            ok, msg = test_connection()
            test_str = f"✅ {msg}" if ok else f"❌ {msg}"
            return (
                f"🤖 **USERBOT Status**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🟢 متصل\n"
                f"👤 الاسم: `{me.get('name', '')}`\n"
                f"🔷 المعرف: @{me.get('username', '')}\n"
                f"🆔 ID: `{me.get('id', '')}`\n"
                f"📞 الهاتف: `{me.get('phone', '***')}`\n"
                f"🧪 اختبار الاتصال: {test_str}\n"
                f"🕐 {_now_str()}"
            )
        else:
            err = s.get("error", "غير متصل")
            return f"🔴 **Userbot غير متصل**\n\nالخطأ: `{err}`"
    except Exception as e:
        return f"❌ خطأ Userbot: {e}"


def _get_session_text() -> str:
    try:
        api_id = os.getenv("API_ID", "—")
        bot_token_set = "✅" if os.getenv("BOT_TOKEN") else "❌"
        session_set = "✅" if os.getenv("SESSION_STRING") else "❌"
        admin_id = os.getenv("ADMIN_ID", "—")
        from tgcf.userbot import get_status
        s = get_status()
        me = s.get("me") or {}
        return (
            f"🔄 **معلومات الجلسة**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🆔 API_ID: `{api_id}`\n"
            f"🔑 SESSION_STRING: {session_set}\n"
            f"🤖 BOT_TOKEN: {bot_token_set}\n"
            f"👑 ADMIN_ID: `{admin_id}`\n"
            f"👤 Userbot: `{me.get('name', '—')}` (@{me.get('username', '—')})\n"
            f"🔗 Userbot ID: `{me.get('id', '—')}`\n"
            f"🟢 الحالة: {'متصل' if s.get('connected') else '🔴 منقطع'}\n"
            f"🕐 {_now_str()}"
        )
    except Exception as e:
        return f"❌ خطأ: {e}"


def _get_health_text() -> str:
    checks = []
    try:
        from tgcf.db import init_db, get_global_stats
        init_db()
        get_global_stats()
        checks.append("✅ قاعدة البيانات")
    except Exception as e:
        checks.append(f"❌ قاعدة البيانات: {e}")
    try:
        from tgcf.userbot import get_status
        s = get_status()
        if s.get("connected"):
            checks.append("✅ Userbot متصل")
        else:
            checks.append(f"❌ Userbot: {s.get('error')}")
    except Exception as e:
        checks.append(f"❌ Userbot: {e}")
    try:
        from tgcf.config import read_config
        cfg = read_config()
        checks.append(f"✅ الإعدادات (API_ID={cfg.login.API_ID})")
    except Exception as e:
        checks.append(f"❌ الإعدادات: {e}")
    checks.append("✅ بوت الإدارة يعمل" if _bot_status.get("running") else "❌ بوت الإدارة متوقف")
    result = "\n".join(checks)
    score = result.count("✅")
    total = len(checks)
    return (
        f"🏥 **فحص النظام** — درجة الصحة: `{score}/{total}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{result}\n\n🕐 {_now_str()}"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Wizard / state machine helpers
# ══════════════════════════════════════════════════════════════════════════════

def _wiz_set(uid: int, step: str, **data):
    existing = _wizard.get(uid, {})
    existing.update({"step": step, "ts": time.time(), **data})
    _wizard[uid] = existing


def _wiz_get(uid: int) -> Dict:
    return _wizard.get(uid, {})


def _wiz_clear(uid: int):
    _wizard.pop(uid, None)


def _in_wizard(uid: int) -> bool:
    s = _wizard.get(uid, {})
    if not s:
        return False
    if time.time() - s.get("ts", 0) > 600:
        _wiz_clear(uid)
        return False
    return bool(s.get("step"))


def _in_flow(uid: int) -> bool:
    """True if user is in any active flow (wizard, broadcast, sendto)."""
    return _in_wizard(uid)


# ══════════════════════════════════════════════════════════════════════════════
#  Entity resolution helpers
# ══════════════════════════════════════════════════════════════════════════════

async def _resolve_entity(client: TelegramClient, target):
    """Resolve a Telegram entity. Returns (entity, id, title)."""
    try:
        entity = await client.get_entity(target)
        if isinstance(entity, (Channel, Chat)):
            return entity, entity.id, getattr(entity, "title", str(target))
        elif isinstance(entity, User):
            name = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
            return entity, entity.id, name
        return entity, getattr(entity, "id", 0), str(target)
    except (ChannelPrivateError, UserNotParticipantError):
        raise ValueError(f"❌ لا يمكن الوصول إلى `{target}` — القناة/المجموعة خاصة أو الحساب غير مشترك")
    except UsernameInvalidError:
        raise ValueError(f"❌ معرف غير صالح: `{target}`")
    except Exception as e:
        raise ValueError(f"❌ خطأ في حل المعرف `{target}`: {e}")


async def _check_userbot_access(source) -> Tuple[bool, str]:
    """Check userbot can access and read source channel."""
    try:
        from tgcf.userbot import get_client, is_connected
        if not is_connected():
            return False, "Userbot غير متصل"
        client = get_client()
        if not client:
            return False, "لا يوجد عميل Userbot"
        entity, eid, title = await _resolve_entity(client, source)
        await client.get_messages(entity, limit=1)
        return True, f"✅ وصول Userbot مؤكد إلى `{title}` (ID: {eid})"
    except ValueError as e:
        return False, str(e)
    except Exception as e:
        return False, f"❌ خطأ Userbot: {e}"


async def _check_bot_access(bot_client: TelegramClient, dest) -> Tuple[bool, str]:
    """Check bot is admin in destination channel."""
    try:
        entity, eid, title = await _resolve_entity(bot_client, dest)
        if not isinstance(entity, (Channel, Chat)):
            return False, f"❌ `{dest}` ليس قناة أو مجموعة"
        try:
            me = await bot_client.get_me()
            part = await bot_client(GetParticipantRequest(entity, me))
            participant = part.participant
            if isinstance(participant, (ChannelParticipantAdmin, ChannelParticipantCreator)):
                return True, f"✅ البوت مشرف في `{title}` (ID: {eid})"
            return False, f"❌ البوت ليس مشرفاً في `{title}` — أضفه كمشرف مع صلاحية إرسال الرسائل"
        except Exception as e:
            return False, f"❌ البوت لا يملك وصولاً إلى `{title}`: {e}"
    except ValueError as e:
        return False, str(e)
    except Exception as e:
        return False, f"❌ خطأ بوت: {e}"


# ══════════════════════════════════════════════════════════════════════════════
#  Broadcast / SendTo helpers
# ══════════════════════════════════════════════════════════════════════════════

def _get_active_destinations() -> List[Tuple[str, str]]:
    """Return list of (dest_id_str, display_name) from all active connections."""
    try:
        from tgcf.db import get_all_connections
        conns = get_all_connections()
        seen = set()
        result = []
        for c in conns:
            if not c.get("is_active"):
                continue
            dest_str = c.get("dest_channels", "")
            conn_name = c.get("con_name", "")
            for d in dest_str.split(","):
                d = d.strip()
                if d and d not in seen:
                    seen.add(d)
                    display = conn_name or d
                    result.append((d, display[:28]))
        return result
    except Exception as e:
        log.error(f"get_active_destinations error: {e}")
        return []


def _detect_media_type(message) -> str:
    """Return 'text', 'photo', 'video', or 'document'."""
    if message.photo:
        return "photo"
    if message.video or (message.document and message.document.mime_type
                         and "video" in message.document.mime_type):
        return "video"
    if message.document:
        return "document"
    return "text"


async def _send_content_to_dest(
    bot_client: TelegramClient,
    dest,
    media_type: str,
    text: str,
    caption: str,
    pending_msg,
) -> Tuple[bool, str]:
    """Send the stored content to a single destination. Returns (ok, error)."""
    try:
        if media_type == "text":
            await bot_client.send_message(dest, text, parse_mode="html")
        else:
            file_data = await bot_client.download_media(pending_msg, file=bytes)
            if not file_data:
                return False, "فشل تحميل الوسائط"
            await bot_client.send_file(
                dest,
                file=file_data,
                caption=caption or "",
                parse_mode="html",
            )
        return True, ""
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 1)
        try:
            if media_type == "text":
                await bot_client.send_message(dest, text, parse_mode="html")
            else:
                file_data = await bot_client.download_media(pending_msg, file=bytes)
                await bot_client.send_file(dest, file=file_data, caption=caption or "", parse_mode="html")
            return True, ""
        except Exception as e2:
            return False, str(e2)
    except Exception as e:
        return False, str(e)


async def _do_broadcast(bot_client: TelegramClient, pending: Dict) -> str:
    """Execute broadcast to all active destinations. Returns report string."""
    destinations = _get_active_destinations()
    if not destinations:
        return "❌ لا توجد وجهات نشطة للبث."

    media_type = pending.get("media_type", "text")
    text = pending.get("text", "")
    caption = pending.get("caption", "")
    pending_msg = pending.get("pending_msg")

    ok_list: List[str] = []
    fail_list: List[str] = []

    for dest_id, dest_name in destinations:
        ok, err = await _send_content_to_dest(
            bot_client, dest_id, media_type, text, caption, pending_msg
        )
        if ok:
            ok_list.append(dest_name)
            try:
                from tgcf.db import log_message
                log_message(None, "broadcast", 0, 0, "ok", f"Broadcast → {dest_name}")
            except Exception:
                pass
        else:
            fail_list.append(f"• `{dest_name}`: {err}")
            try:
                from tgcf.db import log_message
                log_message(None, "broadcast", 0, 0, "fail", f"Broadcast FAIL → {dest_name}: {err}")
            except Exception:
                pass
        await asyncio.sleep(0.3)

    report = (
        f"📊 **نتيجة البث**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ نجح: `{len(ok_list)}`\n"
        f"❌ فشل: `{len(fail_list)}`\n"
        f"📊 الإجمالي: `{len(destinations)}`\n"
    )
    if fail_list:
        report += "\n📋 **الوجهات الفاشلة:**\n" + "\n".join(fail_list)
    return report


async def _do_sendto(bot_client: TelegramClient, pending: Dict) -> str:
    """Execute sendto for the selected destination. Returns report string."""
    dest_id = pending.get("selected_dest", "")
    dest_name = pending.get("selected_dest_name", str(dest_id))
    media_type = pending.get("media_type", "text")
    text = pending.get("text", "")
    caption = pending.get("caption", "")
    pending_msg = pending.get("pending_msg")

    ok, err = await _send_content_to_dest(
        bot_client, dest_id, media_type, text, caption, pending_msg
    )
    if ok:
        try:
            from tgcf.db import log_message
            log_message(None, "sendto", 0, 0, "ok", f"SendTo → {dest_name}")
        except Exception:
            pass
        return (
            f"✅ **تم الإرسال بنجاح**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎯 الوجهة: `{dest_name}`\n"
            f"📨 نوع الرسالة: `{media_type}`\n"
            f"🕐 {_now_str()}"
        )
    else:
        try:
            from tgcf.db import log_message
            log_message(None, "sendto", 0, 0, "fail", f"SendTo FAIL → {dest_name}: {err}")
        except Exception:
            pass
        return (
            f"❌ **فشل الإرسال**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎯 الوجهة: `{dest_name}`\n"
            f"⚠️ الخطأ: `{err}`\n"
            f"🕐 {_now_str()}"
        )


async def _store_pending_content(event, step_name: str, uid: int, extra: Dict = None):
    """Parse incoming message, store in wizard state for step_name, return preview text."""
    msg = event.message
    media_type = _detect_media_type(msg)
    text = (msg.text or msg.message or "").strip()
    caption = (msg.message or "").strip() if media_type != "text" else ""

    update = {
        "pending_msg": msg,
        "media_type": media_type,
        "text": text,
        "caption": caption,
    }
    if extra:
        update.update(extra)
    _wiz_set(uid, step_name, **update)

    type_labels = {
        "text": "📝 نص",
        "photo": "🖼 صورة",
        "video": "🎥 فيديو",
        "document": "📄 مستند",
    }
    preview_text = (
        f"👁 **معاينة المحتوى**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📌 النوع: {type_labels.get(media_type, media_type)}\n"
    )
    if media_type == "text":
        preview_text += f"💬 النص:\n```\n{text[:300]}\n```\n"
    else:
        if caption:
            preview_text += f"💬 التعليق:\n```\n{caption[:200]}\n```\n"
        else:
            preview_text += "💬 بدون تعليق\n"
    return preview_text


# ══════════════════════════════════════════════════════════════════════════════
#  Connection wizard step handler
# ══════════════════════════════════════════════════════════════════════════════

async def _run_wizard_step(event, bot_client: TelegramClient):
    """Handle wizard / broadcast / sendto state machines for a user."""
    uid = event.sender_id
    state = _wiz_get(uid)
    step = state.get("step", "")
    text = (event.message.text or "").strip()

    if text.lower() in ("/cancel", "إلغاء", "cancel"):
        _wiz_clear(uid)
        await event.respond("❌ تم الإلغاء.", buttons=_kb_main())
        return

    # ── Broadcast: collecting content ─────────────────────────────────────
    if step == "broadcast_content":
        preview_text = await _store_pending_content(event, "broadcast_confirm", uid)
        await event.respond(
            f"{preview_text}\n"
            f"📢 سيتم إرسال هذه الرسالة إلى **جميع الوجهات النشطة**.\n"
            f"هل تريد المتابعة؟",
            buttons=_kb_broadcast_confirm()
        )
        return

    # ── SendTo: collecting content ──────────────────────────────────────
    if step == "sendto_content":
        selected_dest = state.get("selected_dest", "")
        selected_name = state.get("selected_dest_name", "")
        preview_text = await _store_pending_content(
            event, "sendto_confirm", uid,
            extra={"selected_dest": selected_dest, "selected_dest_name": selected_name}
        )
        await event.respond(
            f"{preview_text}\n"
            f"🎯 الوجهة المختارة: `{selected_name}`\n"
            f"هل تريد المتابعة؟",
            buttons=_kb_sendto_confirm()
        )
        return

    # ── Connection wizard: Step 1 — got source ────────────────────────────
    if step == "wizard_source":
        await event.respond("⏳ جاري التحقق من المصدر...")
        ok, msg = await _check_userbot_access(text)
        if not ok:
            await event.respond(
                f"❌ **فشل التحقق من المصدر**\n{msg}\n\nأرسل معرف/رابط المصدر مجدداً أو /cancel",
                buttons=_kb_wizard_cancel()
            )
            return
        _wiz_set(uid, "wizard_dest", source=text, source_check=msg)
        await event.respond(
            f"✅ **المصدر صالح**\n{msg}\n\n"
            f"**الخطوة 2/7 — الهدف**\n"
            f"أرسل معرف أو يوزرنيم قناة الهدف (يجب أن يكون البوت مشرفاً فيها):",
            buttons=_kb_wizard_cancel()
        )
        return

    # ── Connection wizard: Step 2 — got dest ─────────────────────────────
    if step == "wizard_dest":
        source = state.get("source")
        await event.respond("⏳ جاري التحقق من الهدف والصلاحيات...")

        ub_ok, ub_msg = await _check_userbot_access(source)
        bot_ok, bot_msg = await _check_bot_access(bot_client, text)

        src_check = state.get("source_check", ub_msg)
        report_lines = [
            "📋 **تقرير التحقق**\n━━━━━━━━━━━━━━━━━━",
            f"{'✅' if ub_ok else '❌'} المصدر: {src_check}",
            f"{'✅' if bot_ok else '❌'} الهدف: {bot_msg}",
            f"{'✅' if ub_ok else '❌'} وصول Userbot: {'مؤكد' if ub_ok else 'فشل'}",
            f"{'✅' if bot_ok else '❌'} صلاحية البوت: {'مؤكدة' if bot_ok else 'فشلت'}",
        ]
        all_ok = ub_ok and bot_ok

        if not all_ok:
            report_lines.append("\n❌ **الاتصال لم يُحفظ** — الرجاء إصلاح المشاكل أعلاه وحاول مجدداً.")
            _wiz_clear(uid)
            await event.respond("\n".join(report_lines), buttons=_kb_main())
            return

        report_lines.append("✅ **اختبار الاتصال: ناجح**")
        report_lines.append("\n✅ **جميع الفحوصات نجحت — جاري حفظ الاتصال...**")

        try:
            from tgcf.config import read_config, write_config, Forward
            from tgcf.db import upsert_connection, init_db
            init_db()
            cfg = read_config()

            from tgcf.userbot import get_client as ub_get_client
            ub_client = ub_get_client()

            src_entity, src_id, src_title = await _resolve_entity(ub_client, source)
            dest_entity, dest_id, dest_title = await _resolve_entity(ub_client, text)

            con_name = f"{src_title[:20]}_to_{dest_title[:20]}"

            new_fwd = Forward(con_name=con_name, source=src_id, dest=[dest_id], use_this=True)
            cfg.forwards = [f for f in cfg.forwards if str(f.source) != str(src_id)]
            cfg.forwards.append(new_fwd)
            write_config(cfg)

            cid = upsert_connection(con_name, source, src_id, str(dest_id), True)

            try:
                from tgcf import config as tgcf_config
                if hasattr(tgcf_config, "from_to"):
                    if src_id not in tgcf_config.from_to:
                        tgcf_config.from_to[src_id] = [dest_id]
            except Exception:
                pass

            report_lines.append(f"\n💾 **تم الحفظ بنجاح!**")
            report_lines.append(f"🔗 اسم الربط: `{con_name}`")
            report_lines.append(f"🆔 معرف الربط: `{cid}`")

        except Exception as e:
            report_lines.append(f"\n❌ خطأ في الحفظ: {e}")

        _wiz_clear(uid)
        await event.respond("\n".join(report_lines), buttons=_kb_main())


# ══════════════════════════════════════════════════════════════════════════════
#  Command handlers
# ══════════════════════════════════════════════════════════════════════════════

async def _require_admin(event) -> bool:
    if not is_admin(event.sender_id):
        await event.respond("🚫 غير مصرح لك باستخدام هذا الأمر.")
        raise events.StopPropagation
    return True


async def cmd_start(event):
    if not is_admin(event.sender_id):
        await event.respond("🚫 غير مصرح.")
        raise events.StopPropagation
    await event.respond(
        "👋 **مرحباً بك في لوحة تحكم tgcf!**\n\n"
        "🔄 منصة التحويل الهجينة — مُدارة بالكامل عبر تيليغرام\n\n"
        "اختر من القائمة أدناه:",
        buttons=_kb_main()
    )
    raise events.StopPropagation


async def cmd_help(event):
    if not is_admin(event.sender_id):
        raise events.StopPropagation
    text = (
        "📖 **الأوامر المتاحة**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "/start — القائمة الرئيسية\n"
        "/help — هذه المساعدة\n"
        "/stats — الإحصائيات\n"
        "/health — فحص النظام\n"
        "/connections — الروابط\n"
        "/reports — التقارير\n"
        "/userbot — حالة Userbot\n"
        "/session — معلومات الجلسة\n"
        "/broadcast — بث رسالة لجميع الوجهات\n"
        "/sendto — إرسال لوجهة محددة\n"
        "/restart_userbot — إعادة تشغيل Userbot\n"
        "/reload_connections — إعادة تحميل الروابط\n"
        "/ping — اختبار الاستجابة\n\n"
        "**جميع الأوامر محمية — للمديرين المصرح لهم فقط.**"
    )
    await event.respond(text, buttons=_kb_back_main())
    raise events.StopPropagation


async def cmd_stats(event):
    if not is_admin(event.sender_id):
        raise events.StopPropagation
    await event.respond(_get_stats_text(), buttons=_kb_back_main())
    raise events.StopPropagation


async def cmd_health(event):
    if not is_admin(event.sender_id):
        raise events.StopPropagation
    await event.respond(_get_health_text(), buttons=_kb_back_main())
    raise events.StopPropagation


async def cmd_connections(event):
    if not is_admin(event.sender_id):
        raise events.StopPropagation
    await event.respond("🔗 **إدارة الروابط**\nاختر إجراءً:", buttons=_kb_connections())
    raise events.StopPropagation


async def cmd_reports(event):
    if not is_admin(event.sender_id):
        raise events.StopPropagation
    await event.respond(_get_connections_report(), buttons=_kb_back_main())
    raise events.StopPropagation


async def cmd_userbot(event):
    if not is_admin(event.sender_id):
        raise events.StopPropagation
    await event.respond(_get_userbot_text(), buttons=_kb_userbot())
    raise events.StopPropagation


async def cmd_session(event):
    if not is_admin(event.sender_id):
        raise events.StopPropagation
    await event.respond(_get_session_text(), buttons=_kb_session())
    raise events.StopPropagation


async def cmd_broadcast(event):
    if not is_admin(event.sender_id):
        raise events.StopPropagation
    uid = event.sender_id

    dests = _get_active_destinations()
    if not dests:
        await event.respond(
            "❌ **لا توجد وجهات نشطة**\n\n"
            "يرجى إضافة روابط نشطة أولاً عبر `/connections`.",
            buttons=_kb_back_main()
        )
        raise events.StopPropagation

    dest_list = "\n".join(f"  • `{name}`" for _, name in dests[:10])
    if len(dests) > 10:
        dest_list += f"\n  _...و{len(dests)-10} وجهات أخرى_"

    _wiz_set(uid, "broadcast_content")
    await event.respond(
        f"📢 **بث رسالة**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"الوجهات النشطة ({len(dests)}):\n{dest_list}\n\n"
        f"**أرسل المحتوى الذي تريد بثّه:**\n"
        f"• نص (مع دعم HTML و Markdown)\n"
        f"• صورة (مع تعليق اختياري)\n"
        f"• فيديو (مع تعليق اختياري)\n"
        f"• مستند (مع تعليق اختياري)\n\n"
        f"أرسل /cancel للإلغاء.",
        buttons=_kb_wizard_cancel()
    )
    raise events.StopPropagation


async def cmd_sendto(event):
    if not is_admin(event.sender_id):
        raise events.StopPropagation
    uid = event.sender_id

    dests = _get_active_destinations()
    if not dests:
        await event.respond(
            "❌ **لا توجد وجهات نشطة**\n\n"
            "يرجى إضافة روابط نشطة أولاً عبر `/connections`.",
            buttons=_kb_back_main()
        )
        raise events.StopPropagation

    _wiz_set(uid, "sendto_select", destinations=dests)
    await event.respond(
        f"🎯 **إرسال مستهدف**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"اختر الوجهة ({len(dests)} متاحة):",
        buttons=_kb_sendto_select(dests)
    )
    raise events.StopPropagation


async def cmd_restart_userbot(event):
    if not is_admin(event.sender_id):
        raise events.StopPropagation
    await event.respond("🔄 جاري إعادة تشغيل Userbot...")
    try:
        from tgcf.userbot import reconnect_userbot
        reconnect_userbot()
        await event.respond("✅ تم إعادة تشغيل Userbot بنجاح.", buttons=_kb_back_main())
    except Exception as e:
        await event.respond(f"❌ خطأ: {e}", buttons=_kb_back_main())
    raise events.StopPropagation


async def cmd_reload_connections(event):
    if not is_admin(event.sender_id):
        raise events.StopPropagation
    await event.respond("🔄 جاري إعادة تحميل الروابط...")
    try:
        from tgcf.config import read_config
        from tgcf.db import sync_connections_from_config
        cfg = read_config()
        sync_connections_from_config(cfg.forwards)
        await event.respond(
            f"✅ تم مزامنة `{len(cfg.forwards)}` ربط/ربطات.", buttons=_kb_back_main()
        )
    except Exception as e:
        await event.respond(f"❌ خطأ: {e}", buttons=_kb_back_main())
    raise events.StopPropagation


async def cmd_ping(event):
    if not is_admin(event.sender_id):
        raise events.StopPropagation
    t0 = time.time()
    msg = await event.respond("🏓 Pong!")
    elapsed = (time.time() - t0) * 1000
    await msg.edit(f"🏓 Pong! `{elapsed:.0f}ms`")
    raise events.StopPropagation


# ══════════════════════════════════════════════════════════════════════════════
#  Message handler (wizard + broadcast + sendto + fallback)
# ══════════════════════════════════════════════════════════════════════════════

async def _make_message_handler(bot_client: TelegramClient):
    async def _handler(event):
        if not is_admin(event.sender_id):
            return
        uid = event.sender_id
        text = (event.message.text or "").strip()

        if text.startswith("/"):
            return

        if _in_flow(uid):
            await _run_wizard_step(event, bot_client)
        else:
            await event.respond("👈 استخدم /start للوصول إلى القائمة الرئيسية.", buttons=_kb_main())

    return _handler


# ══════════════════════════════════════════════════════════════════════════════
#  Callback handler
# ══════════════════════════════════════════════════════════════════════════════

async def _make_callback_handler(bot_client: TelegramClient):
    async def _handler(event):
        uid = event.sender_id
        if not is_admin(uid):
            await event.answer("🚫 غير مصرح.", alert=True)
            return

        data = event.data.decode("utf-8", errors="ignore")
        parts = data.split(":")
        action = parts[0]
        sub = parts[1] if len(parts) > 1 else ""
        param = parts[2] if len(parts) > 2 else ""

        # ── menu navigation ───────────────────────────────────────────────
        if action == "menu":
            if sub == "main":
                await event.edit("👑 **القائمة الرئيسية**\nاختر من الخيارات أدناه:", buttons=_kb_main())
            elif sub == "connections":
                await event.edit("🔗 **إدارة الروابط**:", buttons=_kb_connections())
            elif sub == "my_connections":
                text = _get_connections_report()
                try:
                    from tgcf.db import get_all_connections
                    conns = get_all_connections()
                    await event.edit(text, buttons=_kb_conn_list(conns))
                except Exception:
                    await event.edit(text, buttons=_kb_back_main())
            elif sub == "userbot":
                await event.edit(_get_userbot_text(), buttons=_kb_userbot())
            elif sub == "stats":
                await event.edit(_get_stats_text(), buttons=_kb_back_main())
            elif sub == "reports":
                await event.edit(_get_connections_report(), buttons=_kb_back_main())
            elif sub == "session":
                await event.edit(_get_session_text(), buttons=_kb_session())
            elif sub == "settings":
                await event.edit(
                    "⚙️ **الإعدادات**\n\nلتعديل الإعدادات استخدم لوحة Streamlit الإدارية.",
                    buttons=_kb_back_main()
                )
            elif sub == "bigboss":
                await event.edit(
                    "👑 **𝐁𝐈𝐆 𝐁𝐎𝐒𝐒 Panel**\n\n"
                    f"🔗 [قناة الدعم](https://t.me/shaheenys)\n"
                    f"🎁 [الهدية اليومية](https://t.me/fi1_oo)\n\n"
                    f"{_get_health_text()}",
                    buttons=_kb_back_main()
                )
            elif sub == "broadcast":
                # Start broadcast flow from menu button
                dests = _get_active_destinations()
                if not dests:
                    await event.edit(
                        "❌ لا توجد وجهات نشطة. أضف روابط أولاً.",
                        buttons=_kb_back_main()
                    )
                else:
                    dest_list = "\n".join(f"  • `{name}`" for _, name in dests[:10])
                    _wiz_set(uid, "broadcast_content")
                    await event.answer()
                    await event.respond(
                        f"📢 **بث رسالة**\n━━━━━━━━━━━━━━━━━━\n"
                        f"الوجهات النشطة ({len(dests)}):\n{dest_list}\n\n"
                        f"**أرسل المحتوى الذي تريد بثّه:**\n"
                        f"أرسل /cancel للإلغاء.",
                        buttons=_kb_wizard_cancel()
                    )
                    return
            elif sub == "sendto":
                dests = _get_active_destinations()
                if not dests:
                    await event.edit(
                        "❌ لا توجد وجهات نشطة. أضف روابط أولاً.",
                        buttons=_kb_back_main()
                    )
                else:
                    _wiz_set(uid, "sendto_select", destinations=dests)
                    await event.edit(
                        f"🎯 **إرسال مستهدف**\n━━━━━━━━━━━━━━━━━━\n"
                        f"اختر الوجهة ({len(dests)} متاحة):",
                        buttons=_kb_sendto_select(dests)
                    )
                    return
            await event.answer()

        # ── wizard ────────────────────────────────────────────────────────
        elif action == "wizard":
            if sub == "start":
                _wiz_set(uid, "wizard_source")
                await event.answer()
                await event.respond(
                    "🔮 **معالج إنشاء الربط — الخطوة 1/7**\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                    "**أرسل معرف أو يوزرنيم قناة/مجموعة المصدر:**\n"
                    "• يوزرنيم: `@mychannel`\n"
                    "• معرف: `-1001234567890`\n\n"
                    "📌 يجب أن يكون Userbot مشتركاً في المصدر.",
                    buttons=_kb_wizard_cancel()
                )
            elif sub == "cancel":
                _wiz_clear(uid)
                await event.edit("❌ تم إلغاء المعالج.", buttons=_kb_main())
                await event.answer()

        # ── broadcast confirm / cancel ────────────────────────────────────
        elif action == "bc":
            state = _wiz_get(uid)
            if state.get("step") != "broadcast_confirm":
                await event.answer("⚠️ انتهت جلسة البث. استخدم /broadcast من جديد.", alert=True)
                return
            if sub == "cancel":
                _wiz_clear(uid)
                await event.edit("❌ تم إلغاء البث.", buttons=_kb_main())
                await event.answer()
            elif sub == "confirm":
                await event.answer("📢 جاري البث...")
                await event.edit("⏳ **جاري إرسال الرسالة للجميع...**\nيرجى الانتظار.")
                pending = dict(state)
                _wiz_clear(uid)
                report = await _do_broadcast(bot_client, pending)
                await event.edit(report, buttons=_kb_back_main())

        # ── sendto: select destination ────────────────────────────────────
        elif action == "st":
            if sub == "cancel":
                _wiz_clear(uid)
                await event.edit("❌ تم الإلغاء.", buttons=_kb_main())
                await event.answer()

            elif sub == "sel" and param:
                state = _wiz_get(uid)
                destinations = state.get("destinations", [])
                try:
                    idx = int(param)
                    dest_id, dest_name = destinations[idx]
                except (IndexError, ValueError):
                    await event.answer("❌ وجهة غير صالحة.", alert=True)
                    return
                _wiz_set(uid, "sendto_content",
                         selected_dest=dest_id, selected_dest_name=dest_name)
                await event.answer()
                await event.edit(
                    f"🎯 **الوجهة المختارة:** `{dest_name}`\n\n"
                    f"**أرسل المحتوى الذي تريد إرساله:**\n"
                    f"• نص، صورة، فيديو، أو مستند\n\n"
                    f"أرسل /cancel للإلغاء.",
                    buttons=_kb_wizard_cancel()
                )

            elif sub == "confirm":
                state = _wiz_get(uid)
                if state.get("step") != "sendto_confirm":
                    await event.answer("⚠️ انتهت الجلسة. استخدم /sendto من جديد.", alert=True)
                    return
                await event.answer("🎯 جاري الإرسال...")
                await event.edit("⏳ **جاري الإرسال...**")
                pending = dict(state)
                _wiz_clear(uid)
                report = await _do_sendto(bot_client, pending)
                await event.edit(report, buttons=_kb_back_main())

        # ── connection actions ────────────────────────────────────────────
        elif action == "conn":
            if sub == "list":
                try:
                    from tgcf.db import get_all_connections
                    conns = get_all_connections()
                    if not conns:
                        await event.edit("📋 لا توجد روابط.", buttons=_kb_connections())
                    else:
                        await event.edit(
                            f"📋 **روابطك** ({len(conns)} ربط):",
                            buttons=_kb_conn_list(conns)
                        )
                except Exception as e:
                    await event.edit(f"❌ خطأ: {e}", buttons=_kb_back_main())
                await event.answer()

            elif sub == "detail" and param:
                try:
                    from tgcf.db import get_connection_by_id
                    c = get_connection_by_id(int(param))
                    if not c:
                        await event.edit("❌ الربط غير موجود.", buttons=_kb_back_main())
                        await event.answer()
                        return
                    name = c.get("con_name") or f"#{c['id']}"
                    status = "🟢 نشط" if c.get("is_active") else "🔴 متوقف"
                    recv = int(c.get("total_received") or 0)
                    fwd = int(c.get("total_forwarded") or 0)
                    fail = int(c.get("total_failed") or 0)
                    rate = f"{fwd / recv * 100:.0f}%" if recv > 0 else "—"
                    last = c.get("last_activity")
                    last_str = last.strftime("%Y-%m-%d %H:%M") if last else "—"
                    text = (
                        f"📊 **{name}**\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"🔗 المصدر: `{c.get('source_username', '—')}`\n"
                        f"🆔 Source ID: `{c.get('source_id', '—')}`\n"
                        f"📥 الهدف: `{c.get('dest_channels', '—')}`\n"
                        f"⚡ الحالة: {status}\n"
                        f"🕐 آخر نشاط: `{last_str}`\n"
                        f"📨 استُقبل: `{recv}` | ✅ حُوِّل: `{fwd}` | ❌ فشل: `{fail}`\n"
                        f"📈 نسبة النجاح: `{rate}`\n"
                        f"📝 آخر رسالة: `{str(c.get('last_forwarded_text', '—'))[:80]}`"
                    )
                    await event.edit(text, buttons=_kb_conn_detail(int(param), bool(c.get("is_active"))))
                except Exception as e:
                    await event.edit(f"❌ خطأ: {e}", buttons=_kb_back_main())
                await event.answer()

            elif sub == "stats" and param:
                try:
                    from tgcf.db import get_recent_activity, get_connection_by_id
                    cid = int(param)
                    c = get_connection_by_id(cid)
                    logs = get_recent_activity(cid, 5)
                    name = (c.get("con_name") or f"#{cid}") if c else f"#{cid}"
                    lines = [f"📊 **آخر 5 سجلات — {name}**\n━━━━━━━━━━━━━━━━━━"]
                    for lg in logs:
                        s = "✅" if lg.get("status") == "ok" else "❌"
                        t = lg.get("created_at")
                        ts = t.strftime("%m/%d %H:%M") if t else "—"
                        prev = str(lg.get("message_preview") or "")[:50]
                        lines.append(f"{s} `{ts}` → `{prev}`")
                    if not logs:
                        lines.append("لا توجد سجلات.")
                    await event.edit(
                        "\n".join(lines),
                        buttons=[[Button.inline("◀️ رجوع", f"conn:detail:{param}".encode())]]
                    )
                except Exception as e:
                    await event.edit(f"❌ خطأ: {e}", buttons=_kb_back_main())
                await event.answer()

            elif sub == "test" and param:
                await event.answer("🔄 جاري الاختبار...")
                try:
                    from tgcf.db import get_connection_by_id
                    from tgcf.userbot import test_connection
                    cid = int(param)
                    c = get_connection_by_id(cid)
                    name = c.get("con_name") if c else f"#{cid}"
                    src = (c.get("source_username") or str(c.get("source_id"))) if c else "?"
                    ub_ok, ub_msg = await _check_userbot_access(src)
                    ub_conn_ok, ub_conn_msg = test_connection()
                    result = (
                        f"🧪 **اختبار الربط: {name}**\n"
                        f"{'✅' if ub_ok else '❌'} وصول Userbot: {ub_msg}\n"
                        f"{'✅' if ub_conn_ok else '❌'} اتصال Userbot: {ub_conn_msg}"
                    )
                    await event.edit(result, buttons=[[Button.inline("◀️ رجوع", f"conn:detail:{param}".encode())]])
                except Exception as e:
                    await event.edit(f"❌ خطأ في الاختبار: {e}", buttons=_kb_back_main())

            elif sub == "pause" and param:
                try:
                    from tgcf.db import set_connection_active
                    set_connection_active(int(param), False)
                    await event.edit(f"⏸ تم إيقاف الربط #{param}.", buttons=_kb_conn_detail(int(param), False))
                except Exception as e:
                    await event.edit(f"❌ خطأ: {e}", buttons=_kb_back_main())
                await event.answer("⏸ تم الإيقاف")

            elif sub == "resume" and param:
                try:
                    from tgcf.db import set_connection_active
                    set_connection_active(int(param), True)
                    await event.edit(f"▶️ تم تشغيل الربط #{param}.", buttons=_kb_conn_detail(int(param), True))
                except Exception as e:
                    await event.edit(f"❌ خطأ: {e}", buttons=_kb_back_main())
                await event.answer("▶️ تم التشغيل")

            elif sub == "delete" and param:
                await event.edit(
                    f"⚠️ **هل أنت متأكد من حذف الربط #{param}؟**\nهذا الإجراء لا يمكن التراجع عنه!",
                    buttons=_kb_confirm_delete(int(param))
                )
                await event.answer()

            elif sub == "delete_confirm" and param:
                try:
                    from tgcf.db import delete_connection, get_connection_by_id
                    from tgcf.config import read_config, write_config
                    cid = int(param)
                    c = get_connection_by_id(cid)
                    src_id = c.get("source_id") if c else None
                    delete_connection(cid)
                    if src_id:
                        cfg = read_config()
                        cfg.forwards = [f for f in cfg.forwards if int(f.source) != int(src_id)]
                        write_config(cfg)
                    await event.edit(f"🗑 تم حذف الربط #{param} بنجاح.", buttons=_kb_connections())
                except Exception as e:
                    await event.edit(f"❌ خطأ في الحذف: {e}", buttons=_kb_back_main())
                await event.answer("🗑 تم الحذف")

            elif sub == "sync":
                try:
                    from tgcf.config import read_config
                    from tgcf.db import sync_connections_from_config
                    cfg = read_config()
                    sync_connections_from_config(cfg.forwards)
                    await event.edit(
                        f"✅ تمت مزامنة `{len(cfg.forwards)}` ربط من الإعدادات.",
                        buttons=_kb_connections()
                    )
                except Exception as e:
                    await event.edit(f"❌ خطأ في المزامنة: {e}", buttons=_kb_back_main())
                await event.answer()

        # ── userbot actions ───────────────────────────────────────────────
        elif action == "ub":
            if sub == "status":
                await event.edit(_get_userbot_text(), buttons=_kb_userbot())
            elif sub == "reconnect":
                await event.answer("🔄 جاري إعادة الاتصال...")
                try:
                    from tgcf.userbot import reconnect_userbot
                    reconnect_userbot()
                    await event.edit(_get_userbot_text(), buttons=_kb_userbot())
                except Exception as e:
                    await event.edit(f"❌ خطأ: {e}", buttons=_kb_userbot())
            elif sub == "test":
                await event.answer("🧪 جاري الاختبار...")
                try:
                    from tgcf.userbot import test_connection
                    ok, msg = test_connection()
                    icon = "✅" if ok else "❌"
                    await event.edit(f"{icon} نتيجة الاختبار:\n`{msg}`", buttons=_kb_userbot())
                except Exception as e:
                    await event.edit(f"❌ خطأ: {e}", buttons=_kb_userbot())
            await event.answer()

        # ── session actions ───────────────────────────────────────────────
        elif action == "sess":
            if sub == "info":
                await event.edit(_get_session_text(), buttons=_kb_session())
            elif sub == "reload":
                await event.answer("🔄 جاري إعادة تحميل...")
                try:
                    from tgcf.config_env import load_env_into_config
                    load_env_into_config()
                    from tgcf.userbot import reconnect_userbot
                    reconnect_userbot()
                    await event.edit("✅ تمت إعادة تحميل الإعدادات وإعادة الاتصال.", buttons=_kb_session())
                except Exception as e:
                    await event.edit(f"❌ خطأ: {e}", buttons=_kb_session())
            await event.answer()

        else:
            await event.answer()

    return _handler


# ══════════════════════════════════════════════════════════════════════════════
#  Bot startup / shutdown
# ══════════════════════════════════════════════════════════════════════════════

async def _run_bot():
    global _bot_client, _bot_status

    bot_token = os.getenv("BOT_TOKEN", "")
    api_id_str = os.getenv("API_ID", "0")
    api_hash = os.getenv("API_HASH", "")

    if not bot_token or not api_id_str or not api_hash:
        _bot_status["error"] = "BOT_TOKEN / API_ID / API_HASH not set"
        log.error("Admin bot cannot start: missing credentials")
        return

    api_id = int(api_id_str)

    try:
        _bot_client = TelegramClient(StringSession(), api_id, api_hash)
        await _bot_client.start(bot_token=bot_token)
        me = await _bot_client.get_me()
        _bot_status["running"] = True
        _bot_status["error"] = None
        _bot_status["me"] = {
            "id": me.id,
            "username": me.username or "",
            "name": me.first_name or "",
        }
        log.info(f"Admin bot started: @{me.username}")

        # Register command handlers (in order — specific before generic)
        _bot_client.add_event_handler(cmd_start,              events.NewMessage(pattern=r"(?i)/start"))
        _bot_client.add_event_handler(cmd_help,               events.NewMessage(pattern=r"(?i)/help"))
        _bot_client.add_event_handler(cmd_stats,              events.NewMessage(pattern=r"(?i)/stats"))
        _bot_client.add_event_handler(cmd_health,             events.NewMessage(pattern=r"(?i)/health"))
        _bot_client.add_event_handler(cmd_connections,        events.NewMessage(pattern=r"(?i)/connections"))
        _bot_client.add_event_handler(cmd_reports,            events.NewMessage(pattern=r"(?i)/reports"))
        _bot_client.add_event_handler(cmd_userbot,            events.NewMessage(pattern=r"(?i)/userbot"))
        _bot_client.add_event_handler(cmd_session,            events.NewMessage(pattern=r"(?i)/session"))
        _bot_client.add_event_handler(cmd_broadcast,          events.NewMessage(pattern=r"(?i)/broadcast"))
        _bot_client.add_event_handler(cmd_sendto,             events.NewMessage(pattern=r"(?i)/sendto"))
        _bot_client.add_event_handler(cmd_restart_userbot,    events.NewMessage(pattern=r"(?i)/restart_userbot"))
        _bot_client.add_event_handler(cmd_reload_connections, events.NewMessage(pattern=r"(?i)/reload_connections"))
        _bot_client.add_event_handler(cmd_ping,               events.NewMessage(pattern=r"(?i)/ping"))

        msg_handler = await _make_message_handler(_bot_client)
        cb_handler  = await _make_callback_handler(_bot_client)

        _bot_client.add_event_handler(msg_handler, events.NewMessage())
        _bot_client.add_event_handler(cb_handler,  events.CallbackQuery())

        log.info("Admin bot — all handlers registered, running...")
        await _bot_client.run_until_disconnected()

    except Exception as e:
        _bot_status["running"] = False
        _bot_status["error"] = str(e)
        log.error(f"Admin bot error: {e}")


def _thread_target(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_run_bot())


def start_admin_bot():
    """Start the admin bot in a background thread. Safe to call multiple times."""
    global _bot_loop, _bot_thread
    if _bot_status.get("running"):
        return
    _bot_loop = asyncio.new_event_loop()
    _bot_thread = threading.Thread(
        target=_thread_target,
        args=(_bot_loop,),
        daemon=True,
        name="admin-bot-thread",
    )
    _bot_thread.start()
    log.info("Admin bot thread started.")


def stop_admin_bot():
    """Gracefully stop the admin bot."""
    global _bot_client, _bot_loop, _bot_status
    _bot_status["running"] = False
    if _bot_client and _bot_loop and _bot_loop.is_running():
        asyncio.run_coroutine_threadsafe(_bot_client.disconnect(), _bot_loop)
    log.info("Admin bot stopped.")


def get_bot_status() -> Dict[str, Any]:
    return dict(_bot_status)
