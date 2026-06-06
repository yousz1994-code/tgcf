"""Declare all global constants."""

COMMANDS = {
    "start":               "القائمة الرئيسية",
    "help":                "المساعدة وقائمة الأوامر",
    "stats":               "الإحصائيات العامة",
    "health":              "فحص صحة النظام",
    "connections":         "إدارة الروابط",
    "reports":             "تقارير التحويل",
    "userbot":             "حالة Userbot",
    "session":             "معلومات الجلسة",
    "restart_userbot":     "إعادة تشغيل Userbot",
    "reload_connections":  "إعادة تحميل الروابط",
    "ping":                "اختبار الاستجابة",
}

REGISTER_COMMANDS = True

KEEP_LAST_MANY = 10000

CONFIG_FILE_NAME = "tgcf.config.json"
CONFIG_ENV_VAR_NAME = "TGCF_CONFIG"

MONGO_DB_NAME = "tgcf-config"
MONGO_COL_NAME = "tgcf-instance-0"
