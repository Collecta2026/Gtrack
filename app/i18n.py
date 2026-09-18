"""
English / Arabic translation layer.

Design note: the English text IS the lookup key. That means a template reads
naturally — t("Shipment register") — and anything without an Arabic entry falls
back to readable English rather than an exposed key. No .po compilation step, so
the Windows install stays a plain pip install.

Locale resolution: the signed-in user's saved preference, else the session, else
English. The toggle sets both.
"""
from flask import session, has_request_context
from flask_login import current_user

LANGUAGES = {"en": "English", "ar": "العربية"}
DEFAULT_LANGUAGE = "en"
RTL_LANGUAGES = {"ar"}


# --------------------------------------------------------------------------
# Locale resolution
# --------------------------------------------------------------------------

def get_locale():
    if not has_request_context():
        return DEFAULT_LANGUAGE
    try:
        if current_user.is_authenticated and getattr(current_user, "language", None):
            if current_user.language in LANGUAGES:
                return current_user.language
    except Exception:
        pass
    lang = session.get("language")
    return lang if lang in LANGUAGES else DEFAULT_LANGUAGE


def is_rtl():
    return get_locale() in RTL_LANGUAGES


def direction():
    return "rtl" if is_rtl() else "ltr"


def t(text, **kwargs):
    """Translate a string into the active language, with optional formatting."""
    if text is None:
        return ""
    lang = get_locale()
    # Most entries use the English sentence as the key and carry only an "ar"
    # translation, so English falls straight through. A handful of entries are keyed
    # by a short symbolic name instead (because they take placeholders) and carry an
    # explicit "en" — those must resolve in English too, or the key itself leaks
    # onto the page.
    entry = TRANSLATIONS.get(str(text))
    if entry:
        out = entry.get(lang) or entry.get("en") or text
    else:
        out = text
    if kwargs:
        try:
            out = out.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return out


# Arabic month abbreviations, for the date filters.
AR_MONTHS = {
    1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو",
    7: "يوليو", 8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر",
}


def format_date(value, with_time=False):
    """Dates in Arabic use Arabic month names but Western digits, which is what
    Egyptian commercial documents actually use."""
    if not value:
        return "—"
    if get_locale() == "ar":
        day = value.strftime("%d")
        month = AR_MONTHS.get(value.month, value.strftime("%b"))
        out = f"{day} {month} {value.year}"
        if with_time and hasattr(value, "hour"):
            out += f"، {value.strftime('%H:%M')}"
        return out
    return value.strftime("%d %b %Y, %H:%M" if with_time and hasattr(value, "hour")
                          else "%d %b %Y")


# --------------------------------------------------------------------------
# Dictionary.  English key -> {"ar": "..."}
# --------------------------------------------------------------------------

def _d(pairs):
    return {en: {"ar": ar} for en, ar in pairs}


TRANSLATIONS = {}

# ---- navigation & chrome ----
TRANSLATIONS.update(_d([
    ("Dashboard", "لوحة المتابعة"),
    ("Search", "بحث"),
    ("Shipments", "الشحنات"),
    ("Shipment register", "سجل الشحنات"),
    ("Pipeline board", "لوحة المراحل"),
    ("Procurement", "المشتريات"),
    ("Purchase orders", "أوامر الشراء"),
    ("Supplier invoices", "فواتير الموردين"),
    ("Freight quotations", "عروض أسعار الشحن"),
    ("Equipment", "المعدات"),
    ("Serial register", "سجل الأرقام التسلسلية"),
    ("Allocations", "التخصيصات"),
    ("Customers", "العملاء"),
    ("Finance", "المالية"),
    ("Shipment costs", "تكاليف الشحنات"),
    ("Form 4 register", "سجل نموذج ٤"),
    ("Insight", "التقارير والتحليل"),
    ("Reports & KPIs", "التقارير ومؤشرات الأداء"),
    ("Notifications", "التنبيهات"),
    ("Help & guide", "المساعدة والدليل"),
    ("Administration", "الإدارة"),
    ("Master data", "البيانات الأساسية"),
    ("Users", "المستخدمون"),
    ("Roles", "الصلاحيات"),
    ("Notification rules", "قواعد التنبيهات"),
    ("Audit log", "سجل التدقيق"),
    ("Sign out", "تسجيل الخروج"),
    ("Sign in", "تسجيل الدخول"),
    ("Import & Equipment Tracking", "تتبع الاستيراد والمعدات"),
]))

# ---- common actions & labels ----
TRANSLATIONS.update(_d([
    ("Save", "حفظ"), ("Save changes", "حفظ التعديلات"), ("Cancel", "إلغاء"),
    ("Edit", "تعديل"), ("Add", "إضافة"), ("Update", "تحديث"), ("Filter", "تصفية"),
    ("Reset", "إعادة تعيين"), ("Export", "تصدير"), ("Download", "تنزيل"),
    ("Upload", "رفع"), ("Back", "رجوع"), ("Select…", "اختر…"), ("Any", "الكل"),
    ("All", "الكل"), ("Open", "مفتوحة"), ("Closed", "مغلقة"), ("Delayed", "متأخرة"),
    ("Total", "الإجمالي"), ("Status", "الحالة"), ("Date", "التاريخ"),
    ("Notes", "ملاحظات"), ("Note", "ملاحظة"), ("Description", "الوصف"),
    ("Reference", "المرجع"), ("Stage", "المرحلة"), ("Brand", "العلامة التجارية"),
    ("Supplier", "المورد"), ("Suppliers", "الموردون"), ("Customer", "العميل"),
    ("Route", "المسار"), ("Mode", "وسيلة الشحن"), ("ETA", "الوصول المتوقع"),
    ("ETD", "المغادرة المتوقعة"), ("Value", "القيمة"), ("Amount", "المبلغ"),
    ("Currency", "العملة"), ("Quantity", "الكمية"), ("Qty", "الكمية"),
    ("Unit", "الوحدة"), ("Model", "الموديل"), ("HS code", "الرمز الجمركي"),
    ("Serial no", "الرقم التسلسلي"), ("Serial numbers", "الأرقام التسلسلية"),
    ("Carrier", "الناقل"), ("Forwarder", "وكيل الشحن"), ("Consignee", "المرسل إليه"),
    ("Bank", "البنك"), ("Documents", "المستندات"), ("Document", "المستند"),
    ("Costs", "التكاليف"), ("Comments", "التعليقات"), ("Items", "الأصناف"),
    ("Overview", "نظرة عامة"), ("Details", "التفاصيل"), ("Type", "النوع"),
    ("Category", "الفئة"), ("Due", "تاريخ الاستحقاق"), ("Paid", "مدفوع"),
    ("Outstanding", "مستحق"), ("Overdue", "متأخر السداد"), ("Required", "مطلوب"),
    ("Pending", "قيد الانتظار"), ("Installed", "تم التركيب"), ("late", "متأخرة"),
    ("none", "لا يوجد"), ("Active", "نشط"), ("Disabled", "معطل"),
    ("Purchase order", "أمر الشراء"), ("Supplier invoice", "فاتورة المورد"),
    ("Weight", "الوزن"), ("Origin", "المنشأ"), ("Destination", "الوجهة"),
    ("Remarks", "ملاحظات"), ("Incoterm", "شرط التسليم"),
    ("Sales owner", "مسؤول الحساب"), ("Owner", "المسؤول"),
    ("Expected install", "التركيب المتوقع"), ("Warranty", "الضمان"),
    ("Warranty ends", "انتهاء الضمان"), ("active", "ساري"), ("expired", "منتهٍ"),
    ("New shipment", "شحنة جديدة"), ("New PO", "أمر شراء جديد"),
    ("List view", "عرض القائمة"), ("Board view", "عرض اللوحة"),
    ("Cost statement", "بيان التكاليف"), ("Statement", "البيان"),
    ("Back to register", "العودة إلى السجل"),
    ("Back to shipment", "العودة إلى الشحنة"),
    ("Back to dashboard", "العودة إلى لوحة المتابعة"),
    ("All POs", "كل أوامر الشراء"),
]))

# ---- the twelve stages ----
TRANSLATIONS.update(_d([
    ("PO Raised to Supplier", "صدور أمر الشراء للمورد"),
    ("Order Confirmed + Supplier Invoice", "تأكيد الطلب وفاتورة المورد"),
    ("Preparing (Quote Selected & Booked)", "التجهيز (اختيار العرض والحجز)"),
    ("Departed Origin", "المغادرة من بلد المنشأ"),
    ("In Transit", "في الطريق"),
    ("Arrived Destination", "الوصول إلى الوجهة"),
    ("Customs Filing (ACID + Form 4)", "تقديم البيان الجمركي (ACID ونموذج ٤)"),
    ("Clearance In Progress", "التخليص الجمركي جارٍ"),
    ("Cleared / Released", "تم التخليص والإفراج"),
    ("Out for Delivery", "في طريق التسليم"),
    ("Received into Warehouse", "الاستلام في المخزن"),
    ("Handed to Installation Team", "التسليم لفريق التركيب"),
    ("Cancelled", "ملغاة"),
    ("Re-exported / Returned to Supplier", "إعادة التصدير / الإرجاع للمورد"),
]))

# ---- stage owners ----
TRANSLATIONS.update(_d([
    ("Logistics", "اللوجستيات"), ("Customs", "الجمارك"), ("Warehouse", "المخزن"),
    ("Sales/Ops", "المبيعات والتشغيل"), ("Sales", "المبيعات"),
]))

# ---- roles ----
TRANSLATIONS.update(_d([
    ("CFO", "المدير المالي"),
    ("MD", "المدير العام"),
    ("Finance", "المالية"),
    ("Sales Admin", "مسؤول المبيعات"),
    ("Logistics Admin", "مسؤول اللوجستيات"),
]))

# ---- document types ----
TRANSLATIONS.update(_d([
    ("Commercial Invoice", "الفاتورة التجارية"),
    ("Packing List", "قائمة التعبئة"),
    ("Bill of Lading / AWB", "بوليصة الشحن / بوليصة الشحن الجوي"),
    ("ACID Certificate", "شهادة ACID"),
    ("Form 4 (Bank Import Registration)", "نموذج ٤ (تسجيل الاستيراد البنكي)"),
    ("Customs Declaration", "البيان الجمركي"),
    ("Certificate of Origin", "شهادة المنشأ"),
    ("Insurance Certificate", "شهادة التأمين"),
    ("Delivery Note", "إذن التسليم"),
    ("Other", "أخرى"),
]))

# ---- cost types ----
TRANSLATIONS.update(_d([
    ("Freight", "الشحن"),
    ("Customs Duty", "الرسوم الجمركية"),
    ("Clearance Fee", "رسوم التخليص"),
    ("Express Courier Fee", "رسوم الشحن السريع"),
    ("Storage / Demurrage", "التخزين والأرضيات"),
    ("Insurance", "التأمين"),
]))

# ---- statuses ----
TRANSLATIONS.update(_d([
    ("Unpaid", "غير مدفوع"), ("Partial", "مدفوع جزئياً"),
    ("In Stock", "في المخزن"), ("Allocated", "مخصص"), ("Delivered", "تم التسليم"),
    ("Draft", "مسودة"), ("Sent", "مُرسل"), ("Confirmed", "مؤكد"),
    ("Partially Shipped", "مشحون جزئياً"), ("Fulfilled", "مكتمل"),
    ("Air", "جوي"), ("Sea", "بحري"), ("Land", "بري"),
    ("FCL", "حاوية كاملة"), ("LCL", "شحنة مجمعة"), ("Express", "سريع"),
    ("Courier", "بريد سريع"), ("General", "عام"),
    ("equipment", "معدات"), ("spare part", "قطع غيار"),
    ("consumable", "مستهلكات"), ("software", "برمجيات"),
]))

# ---- dashboard ----
TRANSLATIONS.update(_d([
    ("Open shipments", "الشحنات المفتوحة"),
    ("in the pipeline now", "قيد التنفيذ حالياً"),
    ("past ETA, not arrived", "تجاوزت موعد الوصول ولم تصل"),
    ("Arriving ≤ 21 days", "تصل خلال ٢١ يوماً"),
    ("prepare customers", "تجهيز العملاء"),
    ("Machines unallocated", "معدات غير مخصصة"),
    ("no customer assigned", "لم يُحدد لها عميل"),
    ("Awaiting installation", "بانتظار التركيب"),
    ("allocated, not installed", "مخصصة ولم تُركب بعد"),
    ("Goods in transit", "البضائع في الطريق"),
    ("Unpaid costs", "تكاليف غير مدفوعة"),
    ("Open POs", "أوامر شراء مفتوحة"),
    ("past ready date", "تجاوزت موعد الجاهزية"),
    ("Pipeline", "مراحل التنفيذ"),
    ("Open board →", "فتح اللوحة ←"),
    ("Arriving soon", "تصل قريباً"),
    ("Delayed shipments", "الشحنات المتأخرة"),
    ("Stuck in stage", "متوقفة في مرحلة"),
    ("over 14 days", "أكثر من ١٤ يوماً"),
    ("Days late", "أيام التأخير"),
    ("Days", "الأيام"),
    ("Overdue purchase orders", "أوامر شراء متأخرة"),
    ("Expected ready", "الجاهزية المتوقعة"),
    ("Recent alerts", "أحدث التنبيهات"),
    ("All notifications →", "كل التنبيهات ←"),
    ("Run notification sweep", "تشغيل فحص التنبيهات"),
    ("Administrator view", "عرض مدير النظام"),
    ("declared value", "القيمة المصرح بها"),
    ("equivalent", "ما يعادل"),
    ("Nothing arriving in the next three weeks.", "لا توجد شحنات تصل خلال الأسابيع الثلاثة القادمة."),
    ("No shipments are running past their ETA.", "لا توجد شحنات تجاوزت موعد وصولها المتوقع."),
    ("Nothing has been sitting in one stage too long.", "لا توجد شحنات متوقفة في مرحلة واحدة لفترة طويلة."),
    ("No alerts yet — run a notification sweep.", "لا توجد تنبيهات بعد — شغّل فحص التنبيهات."),
]))

# ---- search ----
TRANSLATIONS.update(_d([
    ("Find anything by any reference", "ابحث عن أي شيء بأي مرجع"),
    ("Search term", "كلمة البحث"),
    ("Matched on", "تطابق مع"),
    ("Machines", "المعدات"),
    ("Parties", "الأطراف"),
    ("Shipment reference", "مرجع الشحنة"),
    ("ACID number", "رقم ACID"),
    ("BL / AWB number", "رقم بوليصة الشحن"),
    ("PO number", "رقم أمر الشراء"),
    ("Serial number", "الرقم التسلسلي"),
    ("Quotation reference", "مرجع عرض السعر"),
    ("Form 4 registration", "تسجيل نموذج ٤"),
    ("Carrier / forwarder", "الناقل / وكيل الشحن"),
    ("Carriers & forwarders", "الناقلون ووكلاء الشحن"),
    ("found", "نتيجة"),
]))

# ---- shipment detail & statement ----
TRANSLATIONS.update(_d([
    ("Shipment", "الشحنة"),
    ("Dates & performance", "التواريخ والأداء"),
    ("Status timeline", "تسلسل المراحل"),
    ("Allocated customers", "العملاء المخصصون"),
    ("Items & allocation", "الأصناف والتخصيص"),
    ("Customs & Form 4", "الجمارك ونموذج ٤"),
    ("Quotations", "عروض الأسعار"),
    ("Move to next stage", "الانتقال للمرحلة التالية"),
    ("Record stage change", "تسجيل تغيير المرحلة"),
    ("Event date", "تاريخ الحدث"),
    ("Actual departure", "المغادرة الفعلية"),
    ("Actual arrival", "الوصول الفعلي"),
    ("Clearance date", "تاريخ التخليص"),
    ("Transit time", "مدة النقل"),
    ("Clearance time", "مدة التخليص"),
    ("Days in stage", "أيام في المرحلة"),
    ("Goods value", "قيمة البضاعة"),
    ("Total cost", "إجمالي التكلفة"),
    ("Shipment costs", "تكاليف الشحنة"),
    ("Landed total", "التكلفة الإجمالية حتى الوصول"),
    ("goods + all costs", "البضاعة + كل التكاليف"),
    ("Cost ratio", "نسبة التكلفة"),
    ("costs as % of goods", "التكاليف كنسبة من قيمة البضاعة"),
    ("Items in this shipment", "أصناف هذه الشحنة"),
    ("Cost trace", "تتبع التكاليف"),
    ("Landed cost by item", "التكلفة حتى الوصول لكل صنف"),
    ("Cost & contents statement", "بيان التكاليف والمحتويات"),
    ("Line value", "قيمة السطر"),
    ("Unit value", "قيمة الوحدة"),
    ("Allocated to", "مخصص لـ"),
    ("unallocated", "غير مخصص"),
    ("Payable to", "مستحق لـ"),
    ("Total shipment cost", "إجمالي تكلفة الشحنة"),
    ("Landed total (goods + costs)", "الإجمالي حتى الوصول (البضاعة + التكاليف)"),
    ("Costs apportioned", "التكاليف الموزعة"),
    ("Landed cost", "التكلفة حتى الوصول"),
    ("Per unit", "للوحدة"),
    ("Share", "النسبة"),
    ("Add item line", "إضافة سطر صنف"),
    ("Add serial numbers", "إضافة أرقام تسلسلية"),
    ("Allocate to customer", "تخصيص لعميل"),
    ("Record serials", "تسجيل الأرقام التسلسلية"),
    ("Allocate", "تخصيص"),
    ("Confirm install", "تأكيد التركيب"),
    ("Confirm installation", "تأكيد التركيب"),
    ("Installation date", "تاريخ التركيب"),
    ("Add a cost line", "إضافة بند تكلفة"),
    ("Add cost", "إضافة تكلفة"),
    ("Mark paid", "تعليم كمدفوع"),
    ("Log a quotation", "تسجيل عرض سعر"),
    ("Log quotation", "تسجيل العرض"),
    ("Select", "اختيار"),
    ("Selected", "مختار"),
    ("Upload a document", "رفع مستند"),
    ("Add to the checklist", "إضافة لقائمة المستندات"),
    ("Mark as required", "تعليم كمطلوب"),
    ("Internal comments", "تعليقات داخلية"),
    ("Add a comment", "إضافة تعليق"),
    ("Post comment", "نشر التعليق"),
    ("Held", "متوفر"),
    ("complete", "مكتمل"),
    ("Registered", "مسجل"),
    ("Exempt", "معفى"),
    ("Not recorded", "غير مسجل"),
    ("Record Form 4", "تسجيل نموذج ٤"),
    ("Registration no", "رقم التسجيل"),
    ("Registration date", "تاريخ التسجيل"),
    ("Exemption reason", "سبب الإعفاء"),
]))

# ---- equipment & allocation ----
TRANSLATIONS.update(_d([
    ("Unit", "الوحدة"),
    ("Journey", "الرحلة"),
    ("Awaiting installation", "بانتظار التركيب"),
    ("Unallocated stock", "مخزون غير مخصص"),
    ("Free qty", "الكمية المتاحة"),
    ("What each customer is waiting for", "ما ينتظره كل عميل"),
    ("Nothing outstanding for this customer.", "لا توجد مستحقات لهذا العميل."),
    ("pending", "قيد الانتظار"),
    ("installed", "تم التركيب"),
    ("next arrival", "الوصول القادم"),
    ("Condition notes", "ملاحظات الحالة"),
    ("Update unit", "تحديث الوحدة"),
    ("Not yet allocated", "لم يُخصص بعد"),
]))

# ---- reports ----
TRANSLATIONS.update(_d([
    ("Avg transit time", "متوسط مدة النقل"),
    ("Avg clearance", "متوسط مدة التخليص"),
    ("days, departure to arrival", "أيام من المغادرة إلى الوصول"),
    ("days, arrival to cleared", "أيام من الوصول إلى التخليص"),
    ("On time vs ETA", "الالتزام بموعد الوصول"),
    ("Cost per shipment", "التكلفة لكل شحنة"),
    ("Cost per kg", "التكلفة لكل كجم"),
    ("Delayed now", "متأخرة حالياً"),
    ("Docs incomplete", "مستندات ناقصة"),
    ("Total logged cost", "إجمالي التكاليف المسجلة"),
    ("Open pipeline", "المراحل المفتوحة"),
    ("Cost by category", "التكاليف حسب الفئة"),
    ("Transit time by mode", "مدة النقل حسب الوسيلة"),
    ("Busiest lanes", "أكثر المسارات ازدحاماً"),
    ("By brand", "حسب العلامة التجارية"),
    ("Supplier performance", "أداء الموردين"),
    ("Equipment by status", "المعدات حسب الحالة"),
    ("Value in transit by currency", "قيمة البضائع في الطريق حسب العملة"),
    ("Ageing — longest in stage", "الأقدم — الأطول بقاءً في مرحلة"),
    ("Document gaps", "نواقص المستندات"),
    ("Avg days", "متوسط الأيام"),
    ("Missing", "الناقص"),
    ("Lane", "المسار"),
    ("Lead time", "مدة التوريد"),
    ("Full register (Excel)", "السجل الكامل (إكسل)"),
    ("Overview", "نظرة عامة"),
    ("Pipeline & ageing", "المراحل والتقادم"),
    ("Timing & routes", "التوقيت والمسارات"),
    ("Cost breakdown", "تفصيل التكاليف"),
    ("Brands & suppliers", "العلامات التجارية والموردون"),
    ("Equipment & value", "المعدات والقيمة"),
    ("Exceptions", "الاستثناءات"),
    ("Open report", "فتح التقرير"),
    ("open", "مفتوحة"),
    ("Where open shipments sit right now, and which ones have been in stage the longest.",
     "أماكن الشحنات المفتوحة حالياً، وأيها الأطول بقاءً في مرحلته."),
    ("Transit time by mode and lane, and direct versus the fulfilment centre route.",
     "مدة النقل حسب الوسيلة والمسار، والمقارنة بين المسار المباشر ومسار مركز التنفيذ."),
    ("Logged cost by category.", "التكاليف المسجلة حسب الفئة."),
    ("Volume, value and transit performance by brand and by supplier.",
     "الحجم والقيمة وأداء النقل حسب العلامة التجارية والمورد."),
    ("Serialised equipment by status, and goods in transit by currency.",
     "المعدات المرقّمة حسب الحالة، والبضائع في الطريق حسب العملة."),
    ("Missing documents and rows with contradictory dates.",
     "المستندات الناقصة والصفوف ذات التواريخ المتناقضة."),
]))

# ---- admin & notifications ----
TRANSLATIONS.update(_d([
    ("Sent", "أُرسل"),
    ("Subject", "الموضوع"),
    ("Message", "الرسالة"),
    ("Recipient", "المستلم"),
    ("Channel", "القناة"),
    ("Add a user", "إضافة مستخدم"),
    ("Save user", "حفظ المستخدم"),
    ("Add a rule", "إضافة قاعدة"),
    ("Save rule", "حفظ القاعدة"),
    ("Last sign-in", "آخر دخول"),
    ("Name", "الاسم"),
    ("Email", "البريد الإلكتروني"),
    ("Password", "كلمة المرور"),
    ("Phone", "الهاتف"),
    ("Role", "الصلاحية"),
    ("Permissions", "الأذونات"),
    ("full access", "صلاحية كاملة"),
    ("When", "الوقت"),
    ("Action", "الإجراء"),
    ("Field", "الحقل"),
    ("Old", "القديم"),
    ("New", "الجديد"),
    ("By", "بواسطة"),
    ("Record", "السجل"),
    ("Entity", "الكيان"),
    ("Run sweep now", "تشغيل الفحص الآن"),
    ("Add a record", "إضافة سجل"),
    ("Save record", "حفظ السجل"),
    ("records →", "سجل ←"),
]))

# ---- empty states & messages ----
TRANSLATIONS.update(_d([
    ("No shipments match these filters.", "لا توجد شحنات مطابقة لهذه المرشحات."),
    ("No items recorded on this shipment.", "لا توجد أصناف مسجلة على هذه الشحنة."),
    ("No documents on the checklist yet.", "لا توجد مستندات في القائمة بعد."),
    ("No costs recorded against this shipment.", "لا توجد تكاليف مسجلة على هذه الشحنة."),
    ("No costs booked against this shipment yet.", "لم تُسجل أي تكاليف على هذه الشحنة بعد."),
    ("No quotations logged for this shipment.", "لا توجد عروض أسعار مسجلة لهذه الشحنة."),
    ("No comments on this shipment yet.", "لا توجد تعليقات على هذه الشحنة بعد."),
    ("No units match this search.", "لا توجد وحدات مطابقة لهذا البحث."),
    ("Nothing is currently awaiting installation.", "لا يوجد حالياً ما ينتظر التركيب."),
    ("No installations confirmed yet.", "لم يتم تأكيد أي عمليات تركيب بعد."),
    ("No purchase orders match this filter.", "لا توجد أوامر شراء مطابقة."),
    ("No lines on this order.", "لا توجد بنود في هذا الأمر."),
    ("No supplier invoice recorded against this PO.", "لا توجد فاتورة مورد مسجلة على أمر الشراء هذا."),
    ("No supplier invoices recorded.", "لا توجد فواتير موردين مسجلة."),
    ("No cost lines match this filter.", "لا توجد بنود تكلفة مطابقة."),
    ("No Form 4 records yet.", "لا توجد سجلات نموذج ٤ بعد."),
    ("No notifications yet — run a sweep to generate them.", "لا توجد تنبيهات بعد — شغّل الفحص لإنشائها."),
    ("No audit entries recorded yet.", "لا توجد قيود تدقيق مسجلة بعد."),
    ("No records yet.", "لا توجد سجلات بعد."),
    ("No customers assigned to you.", "لا يوجد عملاء مسندون إليك."),
    ("No shipment has been raised against this PO yet.", "لم تُنشأ أي شحنة على أمر الشراء هذا بعد."),
    ("Your role does not have access to this page.", "صلاحيتك لا تتيح الوصول إلى هذه الصفحة."),
    ("That page or record does not exist.", "هذه الصفحة أو هذا السجل غير موجود."),
    ("Something isn't available", "هناك شيء غير متاح"),
    ("Incorrect email or password.", "البريد الإلكتروني أو كلمة المرور غير صحيحة."),
    ("Please sign in to continue.", "يرجى تسجيل الدخول للمتابعة."),
]))

# ---- remaining interface strings ----
TRANSLATIONS.update(_d([
    ("Actual", "الفعلي"),
    ("Add a line", "إضافة بند"),
    ("Add item", "إضافة صنف"),
    ("Add line", "إضافة بند"),
    ("All quotations", "كل عروض الأسعار"),
    ("Audience", "الجهة المستهدفة"),
    ("Audience role", "الصلاحية المستهدفة"),
    ("Available stage codes", "رموز المراحل المتاحة"),
    ("Avg transit", "متوسط مدة النقل"),
    ("BL / AWB", "بوليصة الشحن"),
    ("Change status", "تغيير الحالة"),
    ("Common workflows", "سير العمل المعتاد"),
    ("Complete", "مكتمل"),
    ("Cost categories", "فئات التكاليف"),
    ("Cost type", "نوع التكلفة"),
    ("Customs & bank registration (Form 4)", "الجمارك والتسجيل البنكي (نموذج ٤)"),
    ("Direction", "الاتجاه"),
    ("Docs", "المستندات"),
    ("Document and cost types", "أنواع المستندات والتكاليف"),
    ("Documents tracked", "المستندات المتتبعة"),
    ("Due / paid", "الاستحقاق / السداد"),
    ("Due date", "تاريخ الاستحقاق"),
    ("Every menu item, explained", "شرح كل عنصر في القائمة"),
    ("Every open shipment has a Form 4 record or a recorded exemption.",
     "كل شحنة مفتوحة لديها سجل نموذج ٤ أو إعفاء مسجل."),
    ("Every open shipment has its required documents.",
     "كل شحنة مفتوحة لديها مستنداتها المطلوبة."),
    ("Express carrier", "شركة الشحن السريع"),
    ("File", "الملف"),
    ("Freight: quoted vs actual", "الشحن: العرض مقابل الفعلي"),
    ("Getting started", "البداية"),
    ("Glossary", "المصطلحات"),
    ("Gross weight (kg)", "الوزن الإجمالي (كجم)"),
    ("Help & user guide", "المساعدة ودليل المستخدم"),
    ("In stage", "في المرحلة"),
    ("Invoice no", "رقم الفاتورة"),
    ("Item", "الصنف"),
    ("Items, serial numbers & allocation", "الأصناف والأرقام التسلسلية والتخصيص"),
    ("Jump to", "انتقل إلى"),
    ("Landed cost needs at least one item with a value.",
     "حساب التكلفة حتى الوصول يتطلب صنفاً واحداً على الأقل له قيمة."),
    ("Lines", "البنود"),
    ("Linked shipments", "الشحنات المرتبطة"),
    ("Meaning", "المعنى"),
    ("Model no", "رقم الموديل"),
    ("No brand data.", "لا توجد بيانات علامات تجارية."),
    ("No costs recorded.", "لا توجد تكاليف مسجلة."),
    ("No lane data yet.", "لا توجد بيانات مسارات بعد."),
    ("No quotations logged.", "لا توجد عروض أسعار مسجلة."),
    ("No serialised units.", "لا توجد وحدات بأرقام تسلسلية."),
    ("No shipment yet has both a selected quotation and an invoiced freight cost.",
     "لا توجد شحنة بعد لديها عرض سعر مختار وتكلفة شحن مفوترة معاً."),
    ("No supplier data.", "لا توجد بيانات موردين."),
    ("No units on this shipment have been allocated to a customer yet.",
     "لم تُخصص أي وحدة من هذه الشحنة لعميل بعد."),
    ("Not enough completed journeys yet.", "لا توجد رحلات مكتملة كافية بعد."),
    ("Nothing ageing.", "لا يوجد تقادم."),
    ("Nothing in transit.", "لا يوجد شيء في الطريق."),
    ("Nothing open.", "لا يوجد مفتوح."),
    ("Open shipments with no Form 4 record", "شحنات مفتوحة بدون سجل نموذج ٤"),
    ("Order", "الطلب"),
    ("Order date", "تاريخ الطلب"),
    ("Order lines", "بنود الطلب"),
    ("Ordered", "المطلوب"),
    ("PO", "أمر الشراء"),
    ("Parties & route", "الأطراف والمسار"),
    ("Payment status", "حالة السداد"),
    ("Payment terms", "شروط السداد"),
    ("Questions that come up", "أسئلة متكررة"),
    ("Quote date", "تاريخ العرض"),
    ("Quote ref", "مرجع العرض"),
    ("Quoted", "المعروض"),
    ("Quoted vs actual", "العرض مقابل الفعلي"),
    ("Reason", "السبب"),
    ("Record a supplier invoice", "تسجيل فاتورة مورد"),
    ("Record invoice", "تسجيل الفاتورة"),
    ("Ref", "المرجع"),
    ("References, dates & stage", "المراجع والتواريخ والمرحلة"),
    ("Registered & exempt", "المسجل والمعفى"),
    ("Required document", "المستند المطلوب"),
    ("Roles & permissions", "الصلاحيات والأذونات"),
    ("Rule", "القاعدة"),
    ("Sales notes", "ملاحظات المبيعات"),
    ("Serial", "الرقم التسلسلي"),
    ("Serial / item", "الرقم التسلسلي / الصنف"),
    ("Serial numbers (comma separated)", "الأرقام التسلسلية (مفصولة بفواصل)"),
    ("Service type", "نوع الخدمة"),
    ("Shipped", "المشحون"),
    ("Specific unit", "وحدة محددة"),
    ("Specification", "المواصفات"),
    ("Starting stage", "مرحلة البداية"),
    ("Template", "القالب"),
    ("Term", "المصطلح"),
    ("Test accounts", "حسابات تجريبية"),
    ("The twelve stages", "المراحل الاثنتا عشرة"),
    ("Transit", "النقل"),
    ("Transit days", "أيام النقل"),
    ("Trigger", "المُشغِّل"),
    ("Trigger type", "نوع المُشغِّل"),
    ("Trigger value", "قيمة المُشغِّل"),
    ("Unit price", "سعر الوحدة"),
    ("Uploaded", "تاريخ الرفع"),
    ("Use", "استخدام"),
    ("Valid until", "صالح حتى"),
    ("Variance", "الفرق"),
    ("Ver", "الإصدار"),
    ("Warranty (months)", "الضمان (شهور)"),
    ("What they can do", "ما يمكنهم فعله"),
    ("Who owns it", "المسؤول عنها"),
    ("Search reference, ACID, BL/AWB, PO, serial, product, customer…",
     "ابحث بالمرجع أو ACID أو بوليصة الشحن أو أمر الشراء أو الرقم التسلسلي أو المنتج أو العميل…"),
]))

# ---- help guide: section titles and labels ----
TRANSLATIONS.update(_d([
    ("What it is", "ما هي"),
    ("The tiles", "البطاقات"),
    ("What it searches", "ما الذي تبحث فيه"),
    ("Tips", "نصائح"),
    ("Filters", "المرشحات"),
    ("Reading the columns", "قراءة الأعمدة"),
    ("Exports", "التصدير"),
    ("Moving a stage", "الانتقال بين المراحل"),
    ("Export", "التصدير"),
    ("Why it matters", "لماذا هي مهمة"),
    ("Scoping", "نطاق الصلاحية"),
    ("Totals", "الإجماليات"),
    ("Gap list", "قائمة النواقص"),
    ("Timing", "التوقيتات"),
    ("Performance", "الأداء"),
    ("Cost", "التكلفة"),
    ("Exposure", "التعرض المالي"),
    ("Full register", "السجل الكامل"),
    ("Routing", "توجيه التنبيهات"),
    ("Test build", "النسخة التجريبية"),
    ("Unit history", "تاريخ الوحدة"),
    ("Currency", "العملة"),
    ("Shipment detail", "تفاصيل الشحنة"),
    ("Users, roles, rules, audit", "المستخدمون والصلاحيات والقواعد والتدقيق"),
    ("Shipment costs", "تكاليف الشحنات"),
    ("Cost & contents statement", "بيان التكاليف والمحتويات"),
]))

# ---- help guide: body text ----
TRANSLATIONS.update(_d([
    ("Your position at a glance — what is open, what is late, what is arriving, what is waiting on someone.",
     "صورة سريعة للوضع — ما هو مفتوح، وما هو متأخر، وما الذي يصل، وما ينتظر إجراءً من أحد."),
    ("Open shipments counts anything still in flight. A shipment closes when it is received into the warehouse, so the number stays meaningful. Delayed means the ETA has passed and it has not arrived. Machines unallocated counts serial-numbered units with no customer assigned.",
     "الشحنات المفتوحة تشمل كل ما هو قيد التنفيذ. تُغلق الشحنة عند استلامها في المخزن، ليبقى الرقم ذا معنى. المتأخرة تعني أن موعد الوصول المتوقع قد مضى ولم تصل. المعدات غير المخصصة هي الوحدات ذات الأرقام التسلسلية التي لم يُحدد لها عميل."),
    ("Evaluates every time-based alert rule now — ETA countdowns, delays, missing documents, overdue payments — and writes the results to the notification log. In production this runs on a schedule; the button lets you trigger it on demand.",
     "يقيّم كل قواعد التنبيه الزمنية فوراً — قرب الوصول، والتأخير، والمستندات الناقصة، والمدفوعات المتأخرة — ويسجل النتائج في سجل التنبيهات. في بيئة التشغيل يعمل وفق جدول زمني، والزر يتيح تشغيله عند الطلب."),
    ("One box that finds a shipment by any reference anyone might quote at you.",
     "خانة واحدة تجد الشحنة بأي مرجع قد يذكره لك أي شخص."),
    ("Shipment reference, ACID number, bill of lading or air waybill, purchase order number, supplier invoice number, machine serial number, product description, model, HS code, quotation reference, Form 4 registration, and customer, supplier or forwarder names.",
     "مرجع الشحنة، ورقم ACID، وبوليصة الشحن البحري أو الجوي، ورقم أمر الشراء، ورقم فاتورة المورد، والرقم التسلسلي للجهاز، ووصف المنتج، والموديل، والرمز الجمركي، ومرجع عرض السعر، وتسجيل نموذج ٤، وأسماء العملاء والموردين ووكلاء الشحن."),
    ("Partial matches work. Typing LRG finds every LargeV serial; typing part of a product name finds every shipment that carried it. Results show which reference matched, so you can tell why something appeared.",
     "البحث الجزئي يعمل. كتابة LRG تجد كل الأرقام التسلسلية لـ LargeV، وكتابة جزء من اسم المنتج تجد كل شحنة حملته. تُظهر النتائج المرجع الذي تطابق، لتعرف سبب ظهور كل نتيجة."),
    ("Every shipment in one filterable table.", "كل الشحنات في جدول واحد قابل للتصفية."),
    ("Combine status, stage, brand, supplier and mode with a free-text search. Status defaults to open for operational roles and to all for sales, who still care about a machine after it lands.",
     "يمكن الجمع بين الحالة والمرحلة والعلامة التجارية والمورد ووسيلة الشحن مع البحث النصي. الحالة الافتراضية «مفتوحة» للأدوار التشغيلية و«الكل» للمبيعات، لأنهم يتابعون الجهاز حتى بعد وصوله."),
    ("In stage shows how long it has sat where it is — amber past two weeks, red past a month. Docs shows the percentage of required documents actually held.",
     "«في المرحلة» يوضح مدة بقاء الشحنة في موضعها — برتقالي بعد أسبوعين، وأحمر بعد شهر. «المستندات» تُظهر نسبة المستندات المطلوبة المتوفرة فعلياً."),
    ("Excel, CSV and PDF buttons export exactly what your filters are showing.",
     "أزرار إكسل وCSV وPDF تصدّر ما تعرضه المرشحات الحالية بالضبط."),
    ("The same open shipments as cards across the twelve stages — the fastest way to see where the bottleneck is.",
     "نفس الشحنات المفتوحة كبطاقات موزعة على المراحل الاثنتي عشرة — أسرع طريقة لمعرفة أين الاختناق."),
    ("Shipments received into the warehouse in the last 45 days stay on the board so the warehouse and installation columns are not empty.",
     "تبقى الشحنات المستلمة في المخزن خلال آخر ٤٥ يوماً على اللوحة حتى لا يكون عمودا المخزن والتركيب فارغين."),
    ("Parties, route, references, dates and performance, plus the status timeline.",
     "الأطراف والمسار والمراجع والتواريخ والأداء، بالإضافة إلى تسلسل المراحل."),
    ("Move to next stage records the change with a date and note, writes it to the timeline, updates the matching date field, and fires any notification rule attached to that stage.",
     "«الانتقال للمرحلة التالية» يسجل التغيير بتاريخ وملاحظة، ويضيفه إلى التسلسل، ويحدّث حقل التاريخ المقابل، ويُطلق أي قاعدة تنبيه مرتبطة بتلك المرحلة."),
    ("Each product line, its serial numbers, and which customer each unit is allocated to. Add serials in bulk by separating them with commas.",
     "كل سطر منتج وأرقامه التسلسلية والعميل المخصص له كل وحدة. يمكن إضافة عدة أرقام تسلسلية دفعة واحدة بالفصل بينها بفواصل."),
    ("Upload and store the actual files. The checklist shows required versus received; re-uploading the same type bumps the version.",
     "رفع الملفات الفعلية وحفظها. تُظهر القائمة المطلوب مقابل المستلم، وإعادة رفع نفس النوع يزيد رقم الإصدار."),
    ("Every cost booked against the shipment with its own payment status.",
     "كل تكلفة مسجلة على الشحنة بحالة سداد خاصة بها."),
    ("Competing forwarder quotes. Selecting one sets the shipment's forwarder and enables the quoted-versus-actual comparison.",
     "عروض وكلاء الشحن المتنافسة. اختيار أحدها يحدد وكيل شحن الشحنة ويفعّل مقارنة العرض بالفعلي."),
    ("ACID, clearance date and the bank import registration, including recording an exemption for low-value shipments.",
     "رقم ACID وتاريخ التخليص والتسجيل البنكي للاستيراد، بما في ذلك تسجيل الإعفاء للشحنات منخفضة القيمة."),
    ("An internal thread so procurement, logistics, finance and sales leave notes against the shipment rather than in email.",
     "سلسلة تعليقات داخلية تتيح للمشتريات واللوجستيات والمالية والمبيعات تدوين ملاحظاتهم على الشحنة بدلاً من البريد الإلكتروني."),
    ("The full financial trace for one shipment on a single page — reachable from the Statement button on any shipment.",
     "التتبع المالي الكامل لشحنة واحدة في صفحة واحدة — يمكن الوصول إليه من زر «البيان» في أي شحنة."),
    ("Every line in the shipment with quantity, value, serial numbers and who each unit is allocated to.",
     "كل سطر في الشحنة مع الكمية والقيمة والأرقام التسلسلية والعميل المخصص لكل وحدة."),
    ("Every cost booked, grouped by category, showing original currency and the base-currency equivalent, who it is payable to, and whether it is paid.",
     "كل تكلفة مسجلة مجمعة حسب الفئة، مع العملة الأصلية وما يعادلها بالعملة الأساسية، والجهة المستحقة، وحالة السداد."),
    ("Shipment costs apportioned across the lines by each line's share of goods value, giving a landed cost per unit — the number you need when pricing a machine.",
     "توزيع تكاليف الشحنة على البنود بحسب نصيب كل بند من قيمة البضاعة، لتعطي تكلفة الوحدة حتى الوصول — وهو الرقم اللازم عند تسعير الجهاز."),
    ("The whole statement exports to PDF or Excel.", "يمكن تصدير البيان كاملاً إلى PDF أو إكسل."),
    ("The start of the chain — the order raised on a supplier, before any shipment exists.",
     "بداية السلسلة — الأمر الصادر للمورد قبل وجود أي شحنة."),
    ("Each line tracks ordered versus shipped versus outstanding, so a part-shipped order is visible at a glance.",
     "كل بند يتتبع المطلوب مقابل المشحون مقابل المتبقي، ليظهر الطلب المشحون جزئياً بوضوح."),
    ("Recorded against the PO and, once it exists, linked to the shipment the goods travel on.",
     "تُسجل على أمر الشراء، وتُربط بالشحنة التي تحمل البضاعة بمجرد إنشائها."),
    ("A confirmed PO past its expected ready date is flagged and alerts procurement.",
     "أمر الشراء المؤكد الذي تجاوز موعد جاهزيته المتوقع يُعلَّم ويُنبَّه قسم المشتريات."),
    ("Every quotation logged across all shipments, plus the quoted-versus-actual variance report.",
     "كل عروض الأسعار المسجلة على جميع الشحنات، مع تقرير الفرق بين العرض والفعلي."),
    ("Quotes usually arrive in USD and freight invoices often in EGP, so both sides are converted to the base currency before comparison.",
     "تصل العروض عادة بالدولار وفواتير الشحن غالباً بالجنيه المصري، لذا يُحوَّل الطرفان إلى العملة الأساسية قبل المقارنة."),
    ("Every individual machine, searchable by serial number.",
     "كل جهاز على حدة، قابل للبحث بالرقم التسلسلي."),
    ("In transit, in stock, allocated, delivered, installed.",
     "في الطريق، في المخزن، مخصص، تم التسليم، تم التركيب."),
    ("Warranty starts at installation (or warehouse receipt if no installation is recorded) and the register shows whether it is still active — this is your after-sales lookup.",
     "يبدأ الضمان عند التركيب (أو عند الاستلام في المخزن إن لم يُسجل تركيب)، ويوضح السجل ما إذا كان سارياً — وهو مرجعك لخدمة ما بعد البيع."),
    ("Opening a serial shows its whole journey: PO, shipment, route, dates, customer, sales owner and installation date.",
     "فتح الرقم التسلسلي يعرض رحلته كاملة: أمر الشراء، والشحنة، والمسار، والتواريخ، والعميل، ومسؤول الحساب، وتاريخ التركيب."),
    ("Which machine belongs to which customer, and what stage each is at.",
     "أي جهاز يخص أي عميل، وفي أي مرحلة كل منها."),
    ("Allocated but not yet confirmed installed — the sales and installation queue.",
     "مخصص ولم يُؤكد تركيبه بعد — قائمة انتظار المبيعات والتركيب."),
    ("Units with no customer assigned, so nothing sits forgotten in the warehouse.",
     "وحدات لم يُحدد لها عميل، حتى لا يبقى شيء منسياً في المخزن."),
    ("Per customer, everything they are waiting for and everything installed.",
     "لكل عميل، كل ما ينتظره وكل ما تم تركيبه."),
    ("This is the screen a sales account manager lives in: it answers \"where is my customer's machine\" without them asking logistics.",
     "هذه الشاشة التي يعمل عليها مدير حسابات المبيعات: تجيب عن سؤال «أين جهاز عميلي» دون الحاجة لسؤال اللوجستيات."),
    ("A sales user sees only their own customers. Managers see all.",
     "مستخدم المبيعات يرى عملاءه فقط، والإدارة ترى الجميع."),
    ("Every cost line across every shipment, filterable by category and payment status.",
     "كل بنود التكلفة على جميع الشحنات، قابلة للتصفية حسب الفئة وحالة السداد."),
    ("Total, unpaid, partial and overdue, all converted to the base currency.",
     "الإجمالي وغير المدفوع والمدفوع جزئياً والمتأخر، جميعها محوّلة إلى العملة الأساسية."),
    ("Bank-side import registrations and recorded exemptions.",
     "تسجيلات الاستيراد لدى البنك والإعفاءات المسجلة."),
    ("Open shipments with no Form 4 record at all, so nothing reaches customs unregistered.",
     "الشحنات المفتوحة بلا أي سجل نموذج ٤، حتى لا تصل أي شحنة إلى الجمارك غير مسجلة."),
    ("Average transit time by mode and lane, and average customs clearance time measured from arrival to release.",
     "متوسط مدة النقل حسب الوسيلة والمسار، ومتوسط مدة التخليص الجمركي محسوبة من الوصول حتى الإفراج."),
    ("On-time arrival against ETA, and supplier performance including delay frequency and lead time.",
     "الالتزام بموعد الوصول المتوقع، وأداء الموردين بما في ذلك تكرار التأخير ومدة التوريد."),
    ("Cost per shipment, cost per kilogram, and cost by category.",
     "التكلفة لكل شحنة، والتكلفة لكل كيلوجرام، والتكلفة حسب الفئة."),
    ("Value of goods in transit by currency, and the document-gap list.",
     "قيمة البضائع في الطريق حسب العملة، وقائمة نواقص المستندات."),
    ("Exports every shipment with timing and cost columns to Excel, CSV or PDF.",
     "يصدّر كل الشحنات مع أعمدة التوقيتات والتكاليف إلى إكسل أو CSV أو PDF."),
    ("Every alert the rule engine has generated, with what was sent and to whom.",
     "كل تنبيه أنشأه محرك القواعد، مع ما أُرسل ولمن."),
    ("Sales alerts go only to the account manager who owns an allocated customer on that shipment — not the whole team.",
     "تنبيهات المبيعات تصل فقط لمدير الحساب المسؤول عن عميل مخصص على تلك الشحنة — وليس للفريق كله."),
    ("Alerts are written to the log rather than emailed. Setting GTRACK_NOTIFICATIONS_LIVE=1 and adding a mail backend sends them for real.",
     "تُكتب التنبيهات في السجل بدلاً من إرسالها بالبريد. ضبط GTRACK_NOTIFICATIONS_LIVE=1 وإضافة خادم بريد يجعلها تُرسل فعلياً."),
    ("Suppliers, brands, carriers, consignee entities, customers and banks.",
     "الموردون والعلامات التجارية والناقلون وجهات الاستلام والعملاء والبنوك."),
    ("Clean master data is what makes grouping and totals trustworthy — the old spreadsheet had the same supplier under several spellings, which silently split every total.",
     "نظافة البيانات الأساسية هي ما يجعل التجميع والإجماليات موثوقة — كان الملف القديم يحتوي المورد نفسه بعدة كتابات مختلفة، ما كان يقسّم كل إجمالي دون أن يلاحظ أحد."),
    ("Create accounts and assign roles.", "إنشاء الحسابات وتحديد الصلاحيات."),
    ("What each role can see and do, as a permission list.",
     "ما يمكن لكل صلاحية رؤيته وفعله، في صورة قائمة أذونات."),
    ("Triggers, audiences, channels and message templates — editable without a code change.",
     "المُشغِّلات والجهات المستهدفة والقنوات وقوالب الرسائل — قابلة للتعديل دون تغيير البرمجة."),
    ("Every field-level change with the user who made it and when. Filter by record type and export it.",
     "كل تغيير على مستوى الحقل مع المستخدم الذي أجراه ووقته. يمكن التصفية حسب نوع السجل والتصدير."),
]))

# ---- help: workflows ----
TRANSLATIONS.update(_d([
    ("Following a customer's machine", "متابعة جهاز عميل"),
    ("Search the customer's name, or open Customers and find them. Each row shows the serial number, the shipment carrying it, the stage that shipment is at, the ETA and the expected installation date. When it clears customs the account manager gets an alert, which is the cue to ring the customer about scheduling.",
     "ابحث باسم العميل، أو افتح «العملاء» وابحث عنه. يعرض كل سطر الرقم التسلسلي، والشحنة التي تحمله، ومرحلتها، وموعد الوصول المتوقع، وتاريخ التركيب المتوقع. وعند التخليص الجمركي يصل تنبيه لمدير الحساب، وهو إشارة الاتصال بالعميل لتحديد الموعد."),
    ("Recording a new import from scratch", "تسجيل عملية استيراد جديدة من البداية"),
    ("Raise the purchase order on the supplier. When they confirm, record the supplier invoice against the PO. Log the freight quotations you obtain and mark the one you accept — that sets the forwarder. Create the shipment against the PO, add its item lines, then advance the stage as it moves. Capture serial numbers on arrival, allocate each unit to a customer, and confirm installation when the engineer signs off.",
     "أصدر أمر الشراء للمورد. وعند تأكيده، سجّل فاتورة المورد على أمر الشراء. سجّل عروض أسعار الشحن التي تحصل عليها وحدد العرض المقبول — وبذلك يُحدد وكيل الشحن. أنشئ الشحنة على أمر الشراء، وأضف بنود الأصناف، ثم انقلها بين المراحل مع تقدمها. سجّل الأرقام التسلسلية عند الوصول، وخصص كل وحدة لعميل، وأكّد التركيب عند اعتماد المهندس."),
    ("Chasing what a shipment actually cost", "معرفة التكلفة الفعلية لشحنة"),
    ("Open the shipment and click Statement. It lists every item, every cost booked against it with payment status, the landed total, and the landed cost per unit. Export it to PDF for the file or Excel to work on.",
     "افتح الشحنة واضغط «البيان». يعرض كل صنف، وكل تكلفة مسجلة عليها مع حالة السداد، والإجمالي حتى الوصول، وتكلفة الوحدة. يمكن تصديره إلى PDF للحفظ أو إكسل للعمل عليه."),
    ("Finding a machine you only have a serial number for", "العثور على جهاز لا تملك سوى رقمه التسلسلي"),
    ("Type the serial into Search. You get the unit, its status, the shipment that carried it, and the customer it went to — and from the unit page, its full history back to the PO.",
     "اكتب الرقم التسلسلي في البحث. ستحصل على الوحدة وحالتها والشحنة التي حملتها والعميل الذي استلمها — ومن صفحة الوحدة، تاريخها الكامل رجوعاً إلى أمر الشراء."),
    ("Checking nothing is stuck", "التأكد من عدم تعطل أي شحنة"),
    ("The dashboard's Stuck in stage panel lists anything sitting in one stage beyond two weeks. Reports & KPIs has the fuller ageing list, plus the document gaps.",
     "لوحة «متوقفة في مرحلة» تعرض كل ما بقي في مرحلة واحدة أكثر من أسبوعين. وتحتوي «التقارير ومؤشرات الأداء» على قائمة التقادم الكاملة ونواقص المستندات."),
]))

# ---- help: glossary ----
TRANSLATIONS.update(_d([
    ("ACID", "ACID"),
    ("Advance Cargo Information Declaration — the Egyptian customs registration raised through Nafeza before goods ship. Without it the cargo cannot be cleared.",
     "إقرار معلومات الشحنة المسبق — التسجيل الجمركي المصري الذي يُقدَّم عبر منصة نافذة قبل شحن البضاعة. وبدونه لا يمكن تخليص الشحنة."),
    ("Form 4", "نموذج ٤"),
    ("The bank-side import registration. Recorded per shipment against the financing bank, or marked exempt for low-value shipments below the reporting threshold.",
     "تسجيل الاستيراد لدى البنك. يُسجَّل لكل شحنة لدى البنك المموّل، أو يُعلَّم كمعفى للشحنات منخفضة القيمة تحت حد الإبلاغ."),
    ("Bill of Lading for sea freight, Air Waybill for air freight — the carrier's document of title and the reference the forwarder will quote at you.",
     "بوليصة الشحن البحري أو الجوي — سند ملكية البضاعة لدى الناقل، وهو المرجع الذي يذكره لك وكيل الشحن."),
    ("FCL / LCL", "حاوية كاملة / شحنة مجمعة"),
    ("Full Container Load, where you take a whole container, versus Less than Container Load, where your goods share one.",
     "حاوية كاملة تستأجرها بالكامل، مقابل شحنة مجمعة تتشارك فيها بضاعتك حاوية مع آخرين."),
    ("Incoterm", "شرط التسليم (إنكوترمز)"),
    ("The trade term (FOB, CIF, EXW and so on) that fixes where the supplier's responsibility ends and yours begins — and therefore which costs land on you.",
     "الشرط التجاري (فوب، سيف، تسليم المصنع وغيرها) الذي يحدد أين تنتهي مسؤولية المورد وتبدأ مسؤوليتك — وبالتالي أي التكاليف تقع عليك."),
    ("HS code", "الرمز الجمركي المنسق"),
    ("The customs tariff classification for a product, held per item line so a multi-product shipment classifies correctly.",
     "التصنيف الجمركي للمنتج، ويُحفظ لكل بند على حدة حتى تُصنَّف الشحنة متعددة المنتجات بشكل صحيح."),
    ("Landed cost", "التكلفة حتى الوصول"),
    ("Goods value plus every cost of getting them here — freight, duty, clearance, insurance. The real cost of a machine, and the basis for pricing it.",
     "قيمة البضاعة مضافاً إليها كل تكاليف إيصالها — الشحن والرسوم والتخليص والتأمين. وهي التكلفة الحقيقية للجهاز وأساس تسعيره."),
    ("Allocation", "التخصيص"),
    ("The record tying a specific machine, by serial number, to a specific customer. Deliberately separate from the shipment, because one shipment routinely carries units for several customers.",
     "السجل الذي يربط جهازاً محدداً برقمه التسلسلي بعميل محدد. وهو منفصل عن الشحنة عمداً، لأن الشحنة الواحدة تحمل عادة وحدات لعدة عملاء."),
    ("Base currency", "العملة الأساسية"),
    ("Everything is converted to EGP for totals, so mixed-currency shipments add up. Rates are set in config.py.",
     "يُحوَّل كل شيء إلى الجنيه المصري للإجماليات، حتى تتجمع الشحنات متعددة العملات بشكل صحيح. وتُضبط الأسعار في ملف config.py."),
]))

# ---- help: intro, notes and FAQ ----
TRANSLATIONS["intro_para_1"] = {
    "en": "{app} tracks {org}'s own equipment imports from the moment a purchase order is "
          "raised on a supplier through to the machine being handed over for installation at a "
          "named customer. It is an internal system: the sales team uses it to know exactly "
          "where a customer's machine is so they can update that customer themselves. "
          "Customers never log in.",
    "ar": "يتتبع {app} عمليات استيراد المعدات الخاصة بـ {org} من لحظة إصدار أمر الشراء للمورد "
          "وحتى تسليم الجهاز للتركيب لدى عميل محدد. وهو نظام داخلي: يستخدمه فريق المبيعات "
          "لمعرفة مكان جهاز العميل بدقة حتى يتمكنوا من إبلاغ العميل بأنفسهم. "
          "العملاء لا يدخلون النظام إطلاقاً.",
}
TRANSLATIONS["intro_para_2"] = {
    "en": "Everything hangs off the shipment. A shipment carries item lines; item lines carry "
          "serial-numbered machines; machines are allocated to customers. Costs, documents, "
          "quotations, customs records and comments all attach to the shipment, and every stage "
          "change is timestamped so timings can be measured rather than guessed.",
    "ar": "كل شيء يرتبط بالشحنة. الشحنة تحمل بنود أصناف، والبنود تحمل أجهزة بأرقام تسلسلية، "
          "والأجهزة تُخصص للعملاء. وترتبط بالشحنة كذلك التكاليف والمستندات وعروض الأسعار "
          "والسجلات الجمركية والتعليقات، ويُسجَّل وقت كل تغيير في المرحلة حتى تُقاس المدد "
          "بدلاً من تقديرها.",
}
TRANSLATIONS["intro_para_3"] = {
    "en": "What you see depends on your role. If a menu item is missing, your role does not have "
          "access to it — the roles table below shows who gets what.",
    "ar": "ما تراه يعتمد على صلاحيتك. وإذا اختفى عنصر من القائمة فذلك لأن صلاحيتك لا تتيح الوصول "
          "إليه — وجدول الصلاحيات أدناه يوضح ما يحصل عليه كل دور.",
}
TRANSLATIONS["stages_note"] = {
    "en": "Three exception routes exist outside the sequence: Cancelled, Re-exported / returned "
          "to supplier, and a purchase order going to part-shipped when only some of the order "
          "travels. Allocating a machine to a customer is not a stage — it can happen at any "
          "point, from PO confirmation to warehouse receipt.",
    "ar": "توجد ثلاثة مسارات استثنائية خارج التسلسل: الإلغاء، وإعادة التصدير أو الإرجاع للمورد، "
          "وتحوّل أمر الشراء إلى مشحون جزئياً عندما يُشحن جزء من الطلب فقط. أما تخصيص الجهاز "
          "لعميل فليس مرحلة — إذ يمكن أن يحدث في أي وقت، من تأكيد أمر الشراء حتى الاستلام في المخزن.",
}
TRANSLATIONS["roles_note"] = {
    "en": "Sales scoping is enforced in the database query, not just hidden in the interface: an "
          "account manager cannot reach another manager's customer's shipment even by typing its "
          "address directly.",
    "ar": "يُطبَّق نطاق صلاحية المبيعات في استعلام قاعدة البيانات نفسها، لا بالإخفاء في الواجهة "
          "فقط: لا يستطيع مدير الحساب الوصول إلى شحنة عميل مدير آخر حتى بكتابة عنوانها مباشرة.",
}

TRANSLATIONS.update(_d([
    ("What every screen does, and how the common jobs are done",
     "ماذا تفعل كل شاشة، وكيف تُنجَز المهام المعتادة"),
    ("Every menu item", "كل عناصر القائمة"),
    ("a shipment closes at warehouse receipt; installation follows through the allocation",
     "تُغلق الشحنة عند الاستلام في المخزن، ويُتابَع التركيب من خلال التخصيص"),
    ("Why is a 2023 shipment not in 'open'?", "لماذا لا تظهر شحنة من ٢٠٢٣ ضمن «المفتوحة»؟"),
    ("A shipment closes when it is received into the warehouse — that is the end of the import job. What happens afterwards is tracked through the allocation, under Allocations and Customers.",
     "تُغلق الشحنة عند استلامها في المخزن — فهذه نهاية عملية الاستيراد. وما يحدث بعد ذلك يُتابَع من خلال التخصيص، ضمن «التخصيصات» و«العملاء»."),
    ("Why can't I see a colleague's shipments?", "لماذا لا أرى شحنات زميلي؟"),
    ("Sales accounts are scoped to their own customers. Ask an administrator if you need wider access.",
     "حسابات المبيعات مقصورة على عملائها. راجع مدير النظام إن كنت تحتاج صلاحية أوسع."),
    ("Where do notifications actually go?", "إلى أين تذهب التنبيهات فعلياً؟"),
    ("In this build they are written to the notification log rather than emailed, so you can see exactly what would have been sent. Enabling live sending is a configuration change, not a rebuild.",
     "في هذه النسخة تُكتب في سجل التنبيهات بدلاً من إرسالها بالبريد، حتى ترى بالضبط ما كان سيُرسل. وتفعيل الإرسال الفعلي مجرد تغيير في الإعدادات لا إعادة بناء."),
    ("Can I change the alert rules?", "هل يمكنني تعديل قواعد التنبيه؟"),
    ("Yes — Administration, Notification rules. Triggers, audiences, channels and the message text are all editable without touching code.",
     "نعم — من «الإدارة» ثم «قواعد التنبيهات». المُشغِّلات والجهات المستهدفة والقنوات ونص الرسالة كلها قابلة للتعديل دون المساس بالبرمجة."),
    ("Which currency are totals in?", "بأي عملة تُحسب الإجماليات؟"),
    ("Everything aggregates into the base currency so mixed-currency shipments add up. Original amounts are always shown alongside.",
     "يُجمَّع كل شيء بالعملة الأساسية حتى تتجمع الشحنات متعددة العملات بشكل صحيح. وتُعرض المبالغ الأصلية دائماً بجانبها."),
    ("Is anything I do recorded?", "هل يُسجَّل ما أقوم به؟"),
    ("Yes. Every field-level change is written to the audit log with your name and the time, which is deliberate given the governance standards this system sits under.",
     "نعم. يُكتب كل تغيير على مستوى الحقل في سجل التدقيق باسمك ووقته، وهذا مقصود نظراً لمعايير الحوكمة التي يخضع لها هذا النظام."),
]))

# ---- tile captions and small print ----
TRANSLATIONS.update(_d([
    ("Unallocated lines", "بنود غير مخصصة"),
    ("freight, duty, clearance…", "شحن، رسوم، تخليص…"),
    ("no customer yet", "لا يوجد عميل بعد"),
    ("open shipments", "شحنات مفتوحة"),
    ("past ETA", "تجاوزت موعد الوصول"),
    ("required", "مطلوب"),
    ("shipment costs apportioned by each line's share of goods value",
     "تكاليف الشحنة موزعة بحسب نصيب كل بند من قيمة البضاعة"),
    ("units with no customer assigned", "وحدات لم يُحدد لها عميل"),
]))

# ---- buttons, crumbs and remaining fragments ----
TRANSLATIONS.update(_d([
    ("All master data", "كل البيانات الأساسية"),
    ("Bank-side import registration and exemptions", "تسجيل الاستيراد لدى البنك والإعفاءات"),
    ("CSV", "CSV"), ("Excel", "إكسل"), ("PDF", "PDF"),
    ("Clean, de-duplicated reference records", "سجلات مرجعية نظيفة وخالية من التكرار"),
    ("Every change to every record — who, what and when",
     "كل تغيير على كل سجل — من ولماذا ومتى"),
    ("Off", "متوقف"), ("On", "مفعّل"),
    ("Open shipments by stage", "الشحنات المفتوحة حسب المرحلة"),
    ("Quoted versus actual freight cost", "تكلفة الشحن المعروضة مقابل الفعلية"),
    ("Raised on a supplier — the start of the shipment chain",
     "صادر لمورد — بداية سلسلة الشحن"),
    ("Triggers, audiences and message templates — configurable without a code change",
     "المُشغِّلات والجهات المستهدفة وقوالب الرسائل — قابلة للضبط دون تغيير البرمجة"),
    ("What each role can see and do", "ما يمكن لكل صلاحية رؤيته وفعله"),
    ("Which machine belongs to which customer", "أي جهاز يخص أي عميل"),
    ("freight not yet invoiced", "لم تُفوتر تكلفة الشحن بعد"),
    ("none allocated", "لا يوجد تخصيص"),
    ("overdue", "متأخر"),
]))

# ---- parameterised strings ----
TRANSLATIONS["count_lines_units"] = {
    "en": "{lines} line(s) · {units} serialised unit(s)",
    "ar": "{lines} بند · {units} وحدة بأرقام تسلسلية",
}
TRANSLATIONS["every cost booked against {ref}"] = {
    "en": "every cost booked against {ref}",
    "ar": "كل تكلفة مسجلة على {ref}",
}
TRANSLATIONS["apportioning_note"] = {
    "en": "Apportioning by value is the usual basis and the one used here. Where a shipment "
          "mixes a heavy machine with light consumables, apportioning freight by weight can be "
          "fairer — the weight is held per item, so that variant can be added if you want it.",
    "ar": "التوزيع حسب القيمة هو الأساس المعتاد وهو المستخدم هنا. وعندما تجمع الشحنة بين جهاز "
          "ثقيل ومستهلكات خفيفة، قد يكون توزيع الشحن حسب الوزن أكثر عدلاً — والوزن محفوظ لكل "
          "صنف، فيمكن إضافة هذا البديل عند الرغبة.",
}
TRANSLATIONS["{n} past ready date"] = {
    "en": "{n} past ready date", "ar": "{n} تجاوزت موعد الجاهزية",
}
TRANSLATIONS["{cur} equivalent"] = {"en": "{cur} equivalent", "ar": "ما يعادل بالـ {cur}"}
TRANSLATIONS["declared value, {cur}"] = {
    "en": "declared value, {cur}", "ar": "القيمة المصرح بها، {cur}",
}
TRANSLATIONS.update(_d([
    ("paid", "دُفع"), ("due", "يستحق"), ("of", "من"), ("outstanding", "مستحق"),
]))

# --------------------------------------------------------------------------
# Routing, the fulfilment centre, item-level detail and the banking trail.
# Added with the two-step supply route (origin → Jebel Ali free zone → Cairo).
# --------------------------------------------------------------------------
TRANSLATIONS.update(_d([
    # ---- routing & the hub ----
    ("Route type", "نوع المسار"),
    ("Routing", "المسار"),
    ("Routing & logistics", "المسار والخدمات اللوجستية"),
    ("Direct from origin", "مباشر من المنشأ"),
    ("Inbound to fulfilment centre", "وارد إلى مركز التجميع"),
    ("Re-export from fulfilment centre", "إعادة تصدير من مركز التجميع"),
    ("Internal transfer", "تحويل داخلي"),
    ("Outbound / return", "صادر / مرتجع"),
    ("Direct to Cairo, or via the Jebel Ali fulfilment centre.",
     "مباشرة إلى القاهرة، أو عبر مركز التجميع في جبل علي."),
    ("Stock leg — goods are held at the free-zone fulfilment centre until an order calls them forward.",
     "رحلة تخزين — تُحفظ البضاعة في مركز التجميع بالمنطقة الحرة حتى يطلبها أمر بيع."),
    ("Re-export leg — goods called forward from the free-zone fulfilment centre against an order.",
     "رحلة إعادة تصدير — بضاعة مطلوبة من مركز التجميع بالمنطقة الحرة مقابل أمر بيع."),
    ("From location", "من موقع"),
    ("To location", "إلى موقع"),
    ("Location", "الموقع"),
    ("Current location", "الموقع الحالي"),
    ("Unassigned location", "موقع غير محدد"),
    ("Fulfilment centre", "مركز التجميع"),
    ("Fulfilment centre stock", "مخزون مركز التجميع"),
    ("Free zone", "منطقة حرة"),
    ("free zone", "منطقة حرة"),
    ("Via fulfilment centre", "عبر مركز التجميع"),
    ("First entered on", "دخلت أول مرة على"),
    ("Goods held in the free zone, waiting to be called forward",
     "بضاعة محفوظة في المنطقة الحرة بانتظار طلبها"),
    ("Stock held", "المخزون المحفوظ"),
    ("Nothing is currently held at the fulfilment centre.",
     "لا يوجد حالياً أي مخزون في مركز التجميع."),
    ("oldest first — anything held a long time is tying up cash",
     "الأقدم أولاً — كل ما طالت مدة حفظه يجمّد سيولة"),
    ("A line counts as held once its inbound leg has landed at the fulfilment centre. "
     "When an order calls stock forward, the re-export leg links back to this line and the balance falls.",
     "يُحتسب البند محفوظاً بمجرد وصول رحلته الواردة إلى مركز التجميع. وعندما يطلب أمر بيع "
     "المخزون، ترتبط رحلة إعادة التصدير بهذا البند وينقص الرصيد."),
    ("Inbound leg", "الرحلة الواردة"),
    ("Qty in", "الكمية الواردة"),
    ("Called forward", "المطلوب منها"),
    ("Balance held", "الرصيد المحفوظ"),
    ("Days held", "أيام الحفظ"),
    ("Arrived", "تاريخ الوصول"),
    ("units held", "وحدة محفوظة"),
    ("line(s)", "بند/بنود"),
    ("record(s)", "سجل/سجلات"),
    ("banking record(s)", "سجل/سجلات بنكية"),

    # ---- parties ----
    ("Exporter", "المصدّر"),
    ("Exporter / shipper", "المصدّر / الشاحن"),
    ("Who ships the goods — may differ from the manufacturer.",
     "من يشحن البضاعة — قد يختلف عن المُصنّع."),
    ("Internal entity", "كيان داخلي"),
    ("(internal)", "(داخلي)"),
    ("Manufacturer / brand owner", "مُصنّع / مالك العلامة"),
    ("Trading supplier", "مورد تجاري"),
    ("Internal SGE entity", "كيان داخلي تابع للشركة"),
    ("Freight agent", "وكيل شحن"),
    ("Origin supplier", "المورد الأصلي"),
    ("Origin suppliers on this shipment", "الموردون الأصليون في هذه الشحنة"),
    ("Consolidated from {n} origin suppliers", "مجمّعة من {n} موردين أصليين"),
    ("consolidated", "مجمّعة"),
    ("Same as shipment", "نفس الشحنة"),
    ("Customs broker", "مخلّص جمركي"),
    ("Customs brokers", "المخلّصون الجمركيون"),
    ("Broker", "المخلّص"),
    ("Licence no", "رقم الترخيص"),

    # ---- shipment header ----
    ("Document type", "نوع المستند"),
    ("Master", "أصلية (ماستر)"),
    ("House", "فرعية (هاوس)"),
    ("Payment terms", "شروط الدفع"),
    ("Advance", "دفع مقدم"),
    ("Cash against documents", "نقداً مقابل المستندات"),
    ("Letter of credit", "اعتماد مستندي"),
    ("Open account", "حساب مفتوح"),
    ("Chargeable weight", "الوزن القابل للاحتساب"),
    ("Chargeable weight (kg)", "الوزن القابل للاحتساب (كجم)"),
    ("Measurement", "الحجم"),
    ("Measurement (CBM)", "الحجم (متر مكعب)"),
    ("Cut-off date", "موعد الإقفال"),
    ("Cut-off missed", "فات موعد الإقفال"),
    ("cut-off", "الإقفال"),
    ("Pickup address", "عنوان الاستلام"),
    ("Customs note", "ملاحظة جمركية"),
    ("e.g. under USD 2,000 exemption, temporary admission",
     "مثال: إعفاء أقل من ٢٠٠٠ دولار، إدخال مؤقت"),

    # ---- item lines ----
    ("Spare part", "قطعة غيار"),
    ("Consumable", "مستهلكات"),
    ("Software licence", "رخصة برمجيات"),
    ("Declared / invoice value", "القيمة المصرح بها / الفاتورة"),
    ("Actual value", "القيمة الفعلية"),
    ("Declared vs actual", "المصرح به مقابل الفعلي"),
    ("Supplier invoice no", "رقم فاتورة المورد"),
    ("Invoice", "فاتورة"),
    ("Invoice date", "تاريخ الفاتورة"),
    ("Net weight (kg)", "الوزن الصافي (كجم)"),
    ("Net", "صافي"),
    ("Gross", "إجمالي"),
    ("Dimensions", "الأبعاد"),

    # ---- asset movements ----
    ("Received", "تم الاستلام"),
    ("Transferred", "تم التحويل"),
    ("Re-exported", "أعيد تصديره"),
    ("Returned", "مرتجع"),
    ("This unit has travelled on {n} shipment legs.",
     "انتقلت هذه الوحدة عبر {n} رحلات شحن."),

    # ---- costs ----
    ("Paid by", "جهة الدفع"),
    ("Company", "الشركة"),
    ("Ocean / Air Freight", "شحن بحري / جوي"),
    ("Ex-Works Charges", "مصاريف تسليم المصنع"),
    ("Delivery Order", "إذن تسليم"),
    ("Terminal Handling (THC)", "مناولة بالميناء"),
    ("Customs Fees", "رسوم جمركية"),
    ("Customs Broker Fees", "أتعاب التخليص الجمركي"),
    ("Fumigation", "تبخير"),
    ("Inspection Fees", "رسوم الفحص"),
    ("Repacking", "إعادة تغليف"),
    ("Relabelling", "إعادة ترقيم"),
    ("Earlier leg", "الرحلة السابقة"),
    ("Earlier leg costs", "تكاليف الرحلة السابقة"),
    ("Earlier leg costs are carried forward from", "تكاليف الرحلة السابقة مرحّلة من"),
    ("carried from the fulfilment centre leg", "مرحّلة من رحلة مركز التجميع"),
    ("True landed total", "إجمالي التكلفة الحقيقية"),
    ("including every leg", "شاملاً كل الرحلات"),
    ("via", "عبر"),

    # ---- banking ----
    ("Add a banking record", "إضافة سجل بنكي"),
    ("Save banking record", "حفظ السجل البنكي"),
    ("No banking record on this shipment yet.", "لا يوجد سجل بنكي على هذه الشحنة بعد."),
    ("Advance payment ref", "مرجع الدفعة المقدمة"),
    ("SWIFT", "سويفت"),
    ("SWIFT reference 1", "مرجع سويفت ١"),
    ("SWIFT reference 2", "مرجع سويفت ٢"),
    ("Transfer date", "تاريخ التحويل"),
    ("In progress", "قيد التنفيذ"),
    ("Yes — exempt", "نعم — معفاة"),
    ("e.g. value below the USD 2,000 threshold", "مثال: القيمة أقل من حد ٢٠٠٠ دولار"),

    # ---- master data screens ----
    ("Suppliers & trading parties", "الموردون والأطراف التجارية"),
    ("Locations & facilities", "المواقع والمنشآت"),
    ("Brands & product lines", "العلامات وخطوط المنتجات"),
    ("Consignee entities", "جهات الاستلام"),
    ("Banks", "البنوك"),
    ("Party type", "نوع الطرف"),
    ("Office", "مكتب"),
    ("Port / airport", "ميناء / مطار"),
    ("Freight forwarder", "وكيل شحن"),
    ("Express courier", "بريد سريع"),
    ("Shipping line", "خط ملاحي"),
    ("Airline", "شركة طيران"),
    ("Account no", "رقم الحساب"),
    ("Address", "العنوان"),
    ("Branch", "الفرع"),
    ("Brand lines", "خطوط العلامات"),
    ("City", "المدينة"),
    ("Contact", "جهة الاتصال"),
    ("Country", "الدولة"),
    ("Install site", "موقع التركيب"),
    ("Lead time (days)", "مدة التوريد (أيام)"),

    # ---- generic ----
    ("Yes", "نعم"),
    ("No", "لا"),
    ("Any", "الكل"),
]))

# --------------------------------------------------------------------------
# Help & guide — the sections added with routing, the fulfilment centre,
# item-level detail, the banking trail and the stock view.
# --------------------------------------------------------------------------
TRANSLATIONS.update(_d([
    ("Combine status, stage, brand, supplier, mode and route type with a free-text search. "
     "Status defaults to open for operational roles and to all for sales, who still care about "
     "a machine after it lands.",
     "يمكنك الجمع بين الحالة والمرحلة والعلامة والمورد ووسيلة الشحن ونوع المسار مع بحث نصي حر. "
     "تكون الحالة الافتراضية «مفتوحة» للأدوار التشغيلية و«الكل» للمبيعات، لأنهم يتابعون الجهاز "
     "حتى بعد وصوله."),
    ("Direct means origin straight to Cairo. Inbound to fulfilment centre is a stock leg into the "
     "Jebel Ali free zone. Re-export from fulfilment centre is stock called forward from there "
     "against an order. Filtering on route type separates the two halves of a two-step supply route.",
     "«مباشر» تعني من المنشأ إلى القاهرة رأساً. و«وارد إلى مركز التجميع» رحلة تخزين إلى المنطقة "
     "الحرة بجبل علي. و«إعادة تصدير من مركز التجميع» مخزون يُطلب من هناك مقابل أمر بيع. والتصفية "
     "حسب نوع المسار تفصل شطري المسار ذي الخطوتين."),
    ("The route type and the leg it represents, the from and to locations, the customs broker, "
     "the document type (master or house bill), payment terms, chargeable weight, measurement and "
     "the cargo cut-off. A missed cut-off — the date has passed and the shipment has not departed "
     "— is flagged in red.",
     "نوع المسار والرحلة التي يمثلها، وموقعا الانطلاق والوصول، والمخلّص الجمركي، ونوع المستند "
     "(بوليصة أصلية أو فرعية)، وشروط الدفع، والوزن القابل للاحتساب، والحجم، وموعد إقفال الشحن. "
     "ويُعلَّم بالأحمر تجاوز موعد الإقفال — أي مرور التاريخ دون مغادرة الشحنة."),
    ("Exporter versus supplier", "المصدّر مقابل المورد"),
    ("The supplier is who made or sold the goods; the exporter is who actually shipped them. On a "
     "re-export leg out of the fulfilment centre the exporter is our own entity, while the original "
     "manufacturers stay on the item lines. When more than one origin supplier is present the "
     "shipment is marked consolidated.",
     "المورد هو من صنع البضاعة أو باعها، أما المصدّر فهو من شحنها فعلياً. وفي رحلة إعادة التصدير "
     "من مركز التجميع يكون المصدّر كياننا نحن، بينما يبقى المصنّعون الأصليون على بنود الأصناف. "
     "وعند وجود أكثر من مورد أصلي تُوسم الشحنة بأنها مجمّعة."),
    ("Item detail", "تفاصيل الصنف"),
    ("Each line carries its own origin supplier, brand, category, supplier invoice number and date, "
     "net and gross weight and dimensions — so a consolidated shipment still says which manufacturer "
     "each box came from. Declared and actual values are held separately and the difference is shown, "
     "which matters when the customs declaration and the commercial reality differ.",
     "يحمل كل بند المورد الأصلي الخاص به والعلامة والتصنيف ورقم فاتورة المورد وتاريخها والوزن "
     "الصافي والإجمالي والأبعاد — فتظل الشحنة المجمّعة قادرة على بيان مصدر كل طرد. وتُحفظ القيمة "
     "المصرح بها والقيمة الفعلية كل على حدة مع بيان الفارق، وهو أمر مهم عند اختلاف الإقرار الجمركي "
     "عن الواقع التجاري."),
    ("Hub trail", "مسار مركز التجميع"),
    ("A line that came forward from the fulfilment centre is marked Via fulfilment centre and links "
     "back to the inbound leg it first arrived on, so you can follow a machine all the way to its origin.",
     "يُوسم البند القادم من مركز التجميع بعبارة «عبر مركز التجميع» ويرتبط بالرحلة الواردة التي وصل "
     "عليها أول مرة، فيمكنك تتبع الجهاز حتى منشئه."),
    ("Every cost booked against the shipment with its own payment status, and who paid it — us, the "
     "forwarder, or the supplier — so costs advanced on our behalf and later recharged are not "
     "confused with what we settled directly.",
     "كل تكلفة مقيدة على الشحنة بحالة سدادها، ومَن دفعها — نحن أم وكيل الشحن أم المورد — حتى لا "
     "تختلط المبالغ التي دُفعت نيابة عنا وأُعيد تحميلها لاحقاً بما سددناه مباشرة."),
    ("ACID, bill type, clearance date, the customs broker handling it, and the bank import "
     "registrations. A shipment part-paid in advance and part against documents produces more than "
     "one banking record, so these accumulate rather than overwrite: each carries its own advance "
     "payment reference, two SWIFT references, amount, currency and transfer date. Low-value "
     "shipments are recorded as exempt with the reason.",
     "رقم الأسيد ونوع البوليصة وتاريخ الإفراج والمخلّص الجمركي المسؤول والتسجيلات البنكية "
     "للاستيراد. والشحنة المدفوعة جزئياً مقدماً وجزئياً مقابل المستندات تُنتج أكثر من سجل بنكي، "
     "ولذلك تتراكم هذه السجلات بدل أن يحل أحدها محل الآخر: لكل سجل مرجع دفعته المقدمة ومرجعا سويفت "
     "والمبلغ والعملة وتاريخ التحويل. أما الشحنات منخفضة القيمة فتُسجل معفاة مع بيان السبب."),
    ("When a line came forward from the fulfilment centre, the cost of the inbound leg that first "
     "brought it into the free zone is carried forward and added, giving a true landed total. "
     "Costing the re-export leg on its own would understate what the machine actually cost to land "
     "in Cairo.",
     "عندما يأتي البند من مركز التجميع، تُرحَّل تكلفة الرحلة الواردة التي أدخلته أول مرة إلى "
     "المنطقة الحرة وتُضاف، فينتج إجمالي تكلفة حقيقي. فاحتساب رحلة إعادة التصدير وحدها يقلل من "
     "التكلفة الفعلية لوصول الجهاز إلى القاهرة."),
    ("What is currently sitting in the Jebel Ali free zone, waiting to be called forward against an order.",
     "ما هو موجود حالياً في المنطقة الحرة بجبل علي بانتظار طلبه مقابل أمر بيع."),
    ("How a balance is worked out", "كيف يُحتسب الرصيد"),
    ("A line counts as held once its inbound leg has landed. When an order calls stock forward, the "
     "re-export leg links back to that line and the balance falls. A part-called line shows what is left.",
     "يُحتسب البند محفوظاً بمجرد وصول رحلته الواردة. وعندما يطلب أمر بيع المخزون، ترتبط رحلة إعادة "
     "التصدير بذلك البند وينقص الرصيد. والبند المطلوب جزئياً يعرض المتبقي منه."),
    ("Sorted oldest first, amber past three months and red past six — anything sitting a long time "
     "is tying up cash in the free zone.",
     "مرتَّب من الأقدم، بلون كهرماني بعد ثلاثة أشهر وأحمر بعد ستة — فكل ما طال بقاؤه يجمّد سيولة "
     "في المنطقة الحرة."),
    ("Who can see it", "من يمكنه الاطلاع عليه"),
    ("Management, procurement, logistics and finance. Sales users do not see stock positions.",
     "الإدارة والمشتريات والخدمات اللوجستية والمالية. ولا يرى مستخدمو المبيعات أرصدة المخزون."),
    ("Suppliers and trading parties, locations and facilities, customs brokers, brands, carriers, "
     "consignee entities, customers and banks. Each record can be edited in place from its row.",
     "الموردون والأطراف التجارية، والمواقع والمنشآت، والمخلّصون الجمركيون، والعلامات، وشركات "
     "الشحن، وجهات الاستلام، والعملاء، والبنوك. ويمكن تعديل كل سجل من صفه مباشرة."),
    ("Suppliers are typed as manufacturer, trading supplier, internal entity or freight agent. "
     "Typing our own entities as internal is what lets the system tell an intercompany movement "
     "from a third-party purchase.",
     "يُصنَّف الموردون إلى مُصنّع أو مورد تجاري أو كيان داخلي أو وكيل شحن. وتصنيف كياناتنا على "
     "أنها داخلية هو ما يمكّن النظام من التمييز بين حركة بين الشركات وشراء من طرف ثالث."),
    ("Locations", "المواقع"),
    ("Our own facilities — the Jebel Ali fulfilment centre, the Cairo warehouse — as distinct from "
     "a customer site. Marking one as a free zone is what drives the fulfilment centre stock view.",
     "منشآتنا نحن — مركز التجميع بجبل علي ومستودع القاهرة — تمييزاً لها عن موقع العميل. وتحديد "
     "الموقع كمنطقة حرة هو ما يغذي شاشة مخزون مركز التجميع."),
    ("Bringing stock in through the fulfilment centre", "إدخال المخزون عبر مركز التجميع"),
    ("Create the inbound leg with route type Inbound to fulfilment centre and the to location set "
     "to Jebel Ali, and record its item lines with their origin suppliers. The goods then appear on "
     "Fulfilment centre stock. When a customer orders, create a second shipment with route type "
     "Re-export from fulfilment centre, from Jebel Ali to Cairo, and record its item lines against "
     "the stock they draw on — the balance falls and the machine's journey stays in one place. If "
     "the re-export carries goods from several original manufacturers, it is marked consolidated "
     "and each line keeps its own supplier.",
     "أنشئ الرحلة الواردة بنوع مسار «وارد إلى مركز التجميع» وموقع وصول جبل علي، وسجّل بنود أصنافها "
     "مع مورديها الأصليين. عندئذ تظهر البضاعة في شاشة مخزون مركز التجميع. وعند طلب العميل، أنشئ "
     "شحنة ثانية بنوع مسار «إعادة تصدير من مركز التجميع» من جبل علي إلى القاهرة، وسجّل بنودها "
     "مقابل المخزون الذي تسحب منه — فينقص الرصيد وتبقى رحلة الجهاز في مكان واحد. وإذا حملت إعادة "
     "التصدير بضائع من عدة مصنّعين أصليين، تُوسم بأنها مجمّعة ويحتفظ كل بند بمورده."),
    ("Working out what a re-exported machine really cost", "احتساب التكلفة الحقيقية لجهاز أُعيد تصديره"),
    ("Open the re-export leg and click Statement. Alongside its own costs you will see Earlier leg "
     "costs — the share of the inbound leg's freight, duty and handling that belongs to those units "
     "— and a true landed total including every leg. The earlier legs it draws on are named and "
     "linked underneath.",
     "افتح رحلة إعادة التصدير واضغط «كشف التكلفة». ستجد إلى جانب تكاليفها «تكاليف الرحلة السابقة» "
     "— أي نصيب تلك الوحدات من شحن الرحلة الواردة ورسومها ومناولتها — مع إجمالي تكلفة حقيقي شامل "
     "لكل الرحلات. والرحلات السابقة المعتمد عليها مذكورة ومرتبطة بالأسفل."),
    ("Recording a payment trail against a shipment", "تسجيل مسار السداد على الشحنة"),
    ("Open the shipment, go to Customs & Form 4 and add a banking record for each transfer: the "
     "advance payment reference, the SWIFT references the bank will quote back at you, the amount "
     "and the transfer date. Add a second record when the balance is paid against documents. "
     "Low-value shipments are recorded as exempt with the reason instead.",
     "افتح الشحنة وانتقل إلى «الجمارك ونموذج ٤» وأضف سجلاً بنكياً لكل تحويل: مرجع الدفعة المقدمة، "
     "ومراجع سويفت التي سيذكرها لك البنك، والمبلغ، وتاريخ التحويل. وأضف سجلاً ثانياً عند سداد "
     "الرصيد مقابل المستندات. أما الشحنات منخفضة القيمة فتُسجل معفاة مع بيان السبب."),
    ("Our own facility in the Jebel Ali free zone. Goods can be shipped there from the origin "
     "supplier and held, then re-exported into Egypt when an order calls them forward — an "
     "alternative to shipping direct from origin into Cairo.",
     "منشأتنا في المنطقة الحرة بجبل علي. يمكن شحن البضاعة إليها من المورد الأصلي وحفظها، ثم "
     "إعادة تصديرها إلى مصر عند طلبها مقابل أمر بيع — بديلاً عن الشحن المباشر من المنشأ إلى القاهرة."),
    ("Which leg of the supply route a shipment represents: direct from origin, inbound to the "
     "fulfilment centre, re-export from the fulfilment centre, an internal transfer, or outbound.",
     "أي جزء من مسار التوريد تمثله الشحنة: مباشر من المنشأ، أو وارد إلى مركز التجميع، أو إعادة "
     "تصدير منه، أو تحويل داخلي، أو صادر."),
    ("Who ships the goods, as opposed to who made or sold them. On a re-export leg the exporter is "
     "our own entity while the manufacturers stay on the item lines.",
     "من يشحن البضاعة، تمييزاً عمّن صنعها أو باعها. وفي رحلة إعادة التصدير يكون المصدّر كياننا نحن "
     "بينما يبقى المصنّعون على بنود الأصناف."),
    ("Consolidated shipment", "شحنة مجمّعة"),
    ("One shipment carrying goods from more than one original supplier — routine on a re-export leg "
     "out of the fulfilment centre.",
     "شحنة واحدة تحمل بضائع من أكثر من مورد أصلي — وهو أمر معتاد في رحلة إعادة التصدير من مركز التجميع."),
    ("Master / house bill", "البوليصة الأصلية / الفرعية"),
    ("A master bill is issued by the carrier to the consolidator; a house bill is issued by the "
     "consolidator to us. Which one you hold decides who releases the cargo.",
     "البوليصة الأصلية يصدرها الناقل للمجمِّع، والفرعية يصدرها المجمِّع لنا. وأيهما بحوزتك يحدد "
     "من يفرج عن البضاعة."),
    ("The greater of actual weight and volumetric weight — what air freight is actually billed on.",
     "الأكبر بين الوزن الفعلي والوزن الحجمي — وهو ما يُحتسب عليه الشحن الجوي فعلياً."),
    ("Cargo cut-off", "موعد إقفال الشحن"),
    ("The last moment cargo can be delivered to the terminal for a given sailing or flight. "
     "Missing it means the next departure.",
     "آخر موعد لتسليم البضاعة للمحطة لرحلة بحرية أو جوية معينة. وتجاوزه يعني الانتظار للرحلة التالية."),
    ("Who settled a cost — us, the forwarder, or the supplier. Costs a forwarder advances and later "
     "recharges are tracked separately from what we paid direct.",
     "من سدد التكلفة — نحن أم وكيل الشحن أم المورد. والمبالغ التي يدفعها وكيل الشحن ويعيد تحميلها "
     "لاحقاً تُتابَع منفصلة عما سددناه مباشرة."),
]))

TRANSLATIONS.update(_d([
    ("Held at the fulfilment centre", "محفوظ في مركز التجميع"),
    ("Past the cargo cut-off", "تجاوزت موعد إقفال الشحن"),
    ("cut-off passed and still not departed", "مرّ موعد الإقفال ولم تغادر بعد"),
    ("not departed past the cargo cut-off", "لم تغادر رغم تجاوز موعد الإقفال"),
]))
TRANSLATIONS["oldest {n} days"] = {"en": "oldest {n} days", "ar": "الأقدم {n} يوماً"}

TRANSLATIONS.update(_d([
    ("Direct versus the fulfilment centre route", "المسار المباشر مقابل المسار عبر مركز التجميع"),
    ("hub legs", "رحلة عبر مركز التجميع"),
    ("consolidated shipments", "شحنة مجمّعة"),
    ("Costs as % of goods", "التكاليف كنسبة من قيمة البضاعة"),
    ("Cost per kg", "التكلفة لكل كجم"),
    ("Avg transit", "متوسط العبور"),
    ("Avg clearance", "متوسط التخليص"),
    ("No routing data yet.", "لا توجد بيانات مسارات بعد."),
    ("The two-step route through the free zone buys flexibility but pays freight, handling and "
     "clearance twice. Comparing cost as a share of goods value, and cost per kilogram, is what "
     "shows whether it is earning its keep.",
     "المسار ذو الخطوتين عبر المنطقة الحرة يمنح مرونة لكنه يدفع الشحن والمناولة والتخليص مرتين. "
     "ومقارنة التكلفة كنسبة من قيمة البضاعة، والتكلفة لكل كيلوجرام، هي ما يبيّن ما إذا كان يستحق "
     "تكلفته."),
]))

TRANSLATIONS.update(_d([
    ("Date anomalies", "تناقضات في التواريخ"),
    ("dates that cannot both be true — excluded from the timing averages",
     "تواريخ لا يمكن أن تصح معاً — مستبعدة من متوسطات التوقيت"),
    ("Problem", "المشكلة"),
    ("check the dates", "راجع التواريخ"),
    ("No contradictory dates recorded.", "لا توجد تواريخ متناقضة مسجلة."),
    ("Arrival is recorded before departure", "تاريخ الوصول مسجل قبل تاريخ المغادرة"),
    ("Customs release is recorded before arrival", "تاريخ الإفراج الجمركي مسجل قبل الوصول"),
    ("Warehouse receipt is recorded before customs release",
     "تاريخ الاستلام بالمستودع مسجل قبل الإفراج الجمركي"),
    ("ETA is earlier than ETD", "تاريخ الوصول المتوقع أسبق من تاريخ المغادرة المتوقع"),
    ("Transit and clearance times are shown as unknown until these are corrected.",
     "تُعرض مدتا العبور والتخليص كغير معروفتين حتى يتم تصحيح ذلك."),
    ("These rows came across from the spreadsheet with contradictory dates. Their transit and "
     "clearance times are treated as unknown rather than counted as negative, so the averages "
     "above stay honest. Correcting the dates on the shipment removes it from this list.",
     "وردت هذه السجلات من ملف الإكسل بتواريخ متناقضة. وتُعامَل مدتا العبور والتخليص فيها كغير "
     "معروفتين بدل احتسابها بالسالب، فتبقى المتوسطات أعلاه صادقة. وتصحيح التواريخ على الشحنة "
     "يزيلها من هذه القائمة."),
]))

# ---- admin: users, roles, authorisation matrix, FX rates ----
TRANSLATIONS.update(_d([
    ("Admin", "الإدارة"),
    ("Users, roles, the authorisation matrix and FX rates",
     "المستخدمون والأدوار ومصفوفة الصلاحيات وأسعار الصرف"),
    ("accounts, each assigned a role", "حساب، لكل منها دور محدد"),
    ("add more at any time", "يمكن إضافة المزيد في أي وقت"),
    ("what each role can access", "ما يمكن لكل دور الوصول إليه"),
    ("currencies, indicative unless set", "عملة، أسعارها إرشادية ما لم تُحدَّد"),
    ("Create accounts and assign each one a role.", "أنشئ الحسابات وحدد لكل منها دوراً."),
    ("Manage users", "إدارة المستخدمين"),
    ("Manage roles", "إدارة الأدوار"),
    ("Separate from the role list itself — exactly what each role can see and do, "
     "permission by permission.",
     "مصفوفة منفصلة عن قائمة الأدوار نفسها — تحدد بدقة ما يمكن لكل دور رؤيته والقيام به، "
     "صلاحية بصلاحية."),
    ("Open matrix", "فتح المصفوفة"),
    ("The exchange rates used to convert every cost line into EGP. Indicative until an admin sets one.",
     "أسعار الصرف المستخدمة لتحويل كل بند تكلفة إلى الجنيه المصري. تبقى إرشادية حتى يحددها أحد المسؤولين."),
    ("Manage FX rates", "إدارة أسعار الصرف"),
    ("Triggers, audiences, channels and message templates.", "المحفزات والجمهور والقنوات وقوالب الرسائل."),
    ("Manage notification rules", "إدارة قواعد الإشعارات"),
    ("Every field-level change, filterable and exportable.", "كل تغيير على مستوى الحقل، قابل للتصفية والتصدير."),
    ("View audit log", "عرض سجل التدقيق"),

    ("The role matrix — add more at any time; set what each one can access on the Authorisation matrix",
     "مصفوفة الأدوار — أضف المزيد في أي وقت؛ وحدد صلاحيات كل دور من مصفوفة الصلاحيات"),
    ("Authorisation matrix", "مصفوفة الصلاحيات"),
    ("Access", "الصلاحيات"),
    ("full access", "صلاحية كاملة"),
    ("permissions", "صلاحية"),
    ("edit", "تعديل"),
    ("edit access", "تعديل الصلاحيات"),
    ("Add a role", "إضافة دور"),
    ("Role name", "اسم الدور"),
    ("Code", "الرمز"),
    ("derived from the name if left blank", "يُشتق من الاسم إن تُرك فارغاً"),
    ("New roles start with no access. Grant permissions straight after on the Authorisation matrix.",
     "تبدأ الأدوار الجديدة بلا صلاحيات. امنحها الصلاحيات مباشرة من مصفوفة الصلاحيات."),
    ("Add role", "إضافة الدور"),
    ("A role name is required.", "اسم الدور مطلوب."),
    ("Role saved. Set what it can access on the Authorisation matrix.",
     "تم حفظ الدور. حدد صلاحياته من مصفوفة الصلاحيات."),
    ("Save", "حفظ"),

    ("What each role can see and do — separate from the role list itself",
     "ما يمكن لكل دور رؤيته والقيام به — بمعزل عن قائمة الأدوار نفسها"),
    ("Roles", "الأدوار"),
    ("Permission", "الصلاحية"),
    ("Full access", "صلاحية كاملة"),
    ("always", "دائماً"),
    ("Tick \"Full access\" to give a role everything, including permissions added later. "
     "The CFO role always has full access and manages this matrix.",
     "فعّل \"صلاحية كاملة\" لمنح الدور كل شيء، بما في ذلك الصلاحيات التي تُضاف لاحقاً. "
     "يملك دور المدير المالي دائماً صلاحية كاملة وهو من يدير هذه المصفوفة."),
    ("Save authorisation matrix", "حفظ مصفوفة الصلاحيات"),
    ("Authorisation matrix updated.", "تم تحديث مصفوفة الصلاحيات."),

    ("View all shipments", "عرض جميع الشحنات"),
    ("View own customers' shipments only", "عرض شحنات عملائهم فقط"),
    ("View reports & KPIs", "عرض التقارير ومؤشرات الأداء"),
    ("Export reports", "تصدير التقارير"),
    ("Edit master data", "تعديل البيانات الأساسية"),
    ("Edit purchase orders", "تعديل أوامر الشراء"),
    ("Edit supplier invoices", "تعديل فواتير الموردين"),
    ("Edit shipments", "تعديل الشحنات"),
    ("Advance shipment stage", "تحريك مرحلة الشحنة"),
    ("Edit freight quotations", "تعديل عروض أسعار الشحن"),
    ("Edit documents", "تعديل المستندات"),
    ("Edit cost lines", "تعديل بنود التكلفة"),
    ("Edit Form 4 / bank registration", "تعديل نموذج 4 / التسجيل البنكي"),
    ("Edit serials / assets", "تعديل الأرقام التسلسلية / الأصول"),
    ("Edit customer allocations", "تعديل تخصيصات العملاء"),
    ("Add comments", "إضافة تعليقات"),

    ("FX rates", "أسعار الصرف"),
    ("Used to convert every cost line into the base currency (EGP)",
     "تُستخدم لتحويل كل بند تكلفة إلى العملة الأساسية (الجنيه المصري)"),
    ("Currency", "العملة"),
    ("Rate to EGP", "السعر مقابل الجنيه المصري"),
    ("As of", "اعتباراً من"),
    ("Source", "المصدر"),
    ("admin-set", "محدد من الإدارة"),
    ("indicative default", "افتراضي إرشادي"),
    ("history", "السجل"),
    ("Set a rate", "تحديد سعر"),
    ("Saving adds a new dated rate; the most recent one for a currency is what the system uses. "
     "EGP is always 1.",
     "الحفظ يضيف سعراً جديداً بتاريخ محدد؛ والنظام يستخدم أحدث سعر لكل عملة. "
     "الجنيه المصري يساوي دائماً 1."),
    ("Save rate", "حفظ السعر"),
    ("Currency and rate are both required.", "العملة والسعر مطلوبان معاً."),
    ("FX rate saved.", "تم حفظ سعر الصرف."),

    ("User saved.", "تم حفظ المستخدم."),
    ("Notification rule saved.", "تم حفظ قاعدة الإشعار."),
]))

# ---- role descriptions (Admin -> Roles) ----
TRANSLATIONS.update(_d([
    ("Full access; manages users, roles, the authorisation matrix, FX rates and all master data.",
     "صلاحية كاملة؛ يدير المستخدمين والأدوار ومصفوفة الصلاحيات وأسعار الصرف وجميع البيانات الأساسية."),
    ("Raises and manages purchase orders and supplier invoices; creates and manages shipments, "
     "quotations and bookings; updates transit and customs milestones; confirms warehouse receipt "
     "and triggers installation handover; maintains the supplier and logistics master data.",
     "يُصدر ويدير أوامر الشراء وفواتير الموردين؛ وينشئ ويدير الشحنات وعروض الأسعار والحجوزات؛ "
     "ويحدّث مراحل العبور والجمارك؛ ويؤكد استلام المستودع ويبدأ تسليم التركيب؛ ويحافظ على "
     "البيانات الأساسية للموردين واللوجستيات."),
    ("Manages cost lines, payment status, bank registration and financial reports.",
     "يدير بنود التكلفة وحالة السداد والتسجيل البنكي والتقارير المالية."),
    ("Read-only view of shipments and allocations for their own customers; receives milestone "
     "alerts; can add customer-facing comments.",
     "عرض للقراءة فقط لشحنات وتخصيصات عملائهم؛ يتلقى تنبيهات المراحل؛ ويمكنه إضافة تعليقات "
     "موجهة للعملاء."),
    ("Department oversight — sees and manages allocations across every customer, not just "
     "their own; receives milestone alerts; runs and exports sales reports.",
     "إشراف على القسم — يرى ويدير التخصيصات عبر جميع العملاء، وليس عملاءه فقط؛ يتلقى تنبيهات "
     "المراحل؛ ويُعدّ تقارير المبيعات ويصدّرها."),
    ("Full read access and dashboards across all shipments; exportable reports.",
     "صلاحية قراءة كاملة ولوحات معلومات عبر جميع الشحنات؛ وتقارير قابلة للتصدير."),

    ("Admin: users, roles, authorisation, FX rates, audit",
     "الإدارة: المستخدمون والأدوار والصلاحيات وأسعار الصرف والتدقيق"),
    ("The role matrix — CFO, MD, Finance, Sales, Sales Admin and Logistics Admin "
     "out of the box, matching the company's actual positions. The CFO can add more "
     "at any time from Admin -> Roles.",
     "مصفوفة الأدوار — تضم افتراضياً المدير المالي والمدير العام والمالية والمبيعات ومسؤول "
     "المبيعات ومسؤول اللوجستيات، بما يطابق مسميات الشركة الفعلية. ويمكن للمدير المالي إضافة "
     "المزيد في أي وقت من الإدارة -> الأدوار."),
    ("The role matrix — currently CFO, MD, Finance, Sales, Sales Admin and Logistics Admin. "
     "Add more whenever the business needs a new one.",
     "مصفوفة الأدوار — تضم حالياً المدير المالي والمدير العام والمالية والمبيعات ومسؤول "
     "المبيعات ومسؤول اللوجستيات. أضف المزيد كلما احتاج العمل إلى دور جديد."),
    ("Separate from the role list itself — a permission-by-permission "
     "grid of exactly what each role can see and do. New roles start "
     "with no access until this is set.",
     "مصفوفة منفصلة عن قائمة الأدوار نفسها — جدول يحدد بدقة، صلاحية بصلاحية، ما يمكن لكل دور "
     "رؤيته والقيام به. تبدأ الأدوار الجديدة بلا صلاحيات حتى يتم تحديدها."),
    ("The exchange rates used to convert every cost line into EGP. Indicative "
     "defaults until an admin sets one from Admin -> FX rates; each save is dated, "
     "and the most recent rate for a currency is what the system uses.",
     "أسعار الصرف المستخدمة لتحويل كل بند تكلفة إلى الجنيه المصري. تبقى قيماً إرشادية "
     "حتى يحددها أحد المسؤولين من الإدارة -> أسعار الصرف؛ وكل حفظ يُسجَّل بتاريخ، "
     "والنظام يستخدم أحدث سعر لكل عملة."),
]))

# ---- admin: user edit (Admin -> Users) ----
TRANSLATIONS.update(_d([
    ("New password", "كلمة مرور جديدة"),
    ("leave blank to keep the current one", "اتركه فارغاً للإبقاء على كلمة المرور الحالية"),
]))

# ---- admin: delete a user (Admin -> Users) ----
TRANSLATIONS.update(_d([
    ("This is your own account — sign in as someone else to delete it.",
     "هذا حسابك الخاص — سجّل الدخول بحساب آخر لحذفه."),
    ("Has activity on record, so it can't be deleted — set Active to No above instead.",
     "له نشاط مسجَّل، لذا لا يمكن حذفه — عطّل الحساب بدلاً من ذلك عبر تعيين \"نشط\" إلى \"لا\" أعلاه."),
    ("Delete {name}? This can't be undone.", "هل تريد حذف {name}؟ لا يمكن التراجع عن هذا الإجراء."),
    ("Delete user", "حذف المستخدم"),
    ("You can't delete your own account while signed in as it.",
     "لا يمكنك حذف حسابك الخاص أثناء تسجيل الدخول به."),
    ("Can't delete the last user with full access — "
     "create another admin account first, or deactivate this one instead.",
     "لا يمكن حذف آخر مستخدم يملك صلاحية كاملة — أنشئ حساب إدارة آخر أولاً، أو عطّل هذا الحساب بدلاً من حذفه."),
    ("This user has activity on record (shipments, comments, notifications or "
     "similar) — deleting them would break that history. Set them to Inactive "
     "instead: edit the account and switch Active to No.",
     "لهذا المستخدم نشاط مسجَّل (شحنات أو تعليقات أو إشعارات أو ما شابه) — حذفه سيؤدي إلى فقدان "
     "هذا السجل. عطّله بدلاً من ذلك: افتح الحساب للتعديل وغيّر \"نشط\" إلى \"لا\"."),
    ("User deleted.", "تم حذف المستخدم."),
]))

# ---- admin: temporary password / reset password (Admin -> Users) ----
TRANSLATIONS.update(_d([
    ("Reset password", "إعادة تعيين كلمة المرور"),
    ("Reset {name}'s password? A new temporary one will be generated for you to share with them.",
     "هل تريد إعادة تعيين كلمة مرور {name}؟ سيتم توليد كلمة مرور مؤقتة جديدة لتسليمها له."),
    ("Temporary password — not yet set their own",
     "كلمة مرور مؤقتة — لم يحدد بعد كلمة مرور خاصة به"),
    ("Password (optional)", "كلمة المرور (اختياري)"),
    ("leave blank to auto-generate a temporary one", "اتركه فارغاً لتوليد كلمة مرور مؤقتة تلقائياً"),
    ("Whatever password is set here is temporary — the new account will be asked to choose its "
     "own the moment it first signs in.",
     "أي كلمة مرور تُحدَّد هنا مؤقتة — سيُطلب من الحساب الجديد اختيار كلمة مرور خاصة به فور أول "
     "تسجيل دخول."),
    ("User saved. Temporary password: {password} — share it with them; they'll be asked to set "
     "their own the moment they sign in.",
     "تم حفظ المستخدم. كلمة المرور المؤقتة: {password} — سلّمها له؛ سيُطلب منه تحديد كلمة مرور "
     "خاصة به فور تسجيل الدخول."),
    ("Temporary password for {name}: {password} — share it with them; they'll be asked to set "
     "their own the moment they sign in.",
     "كلمة المرور المؤقتة لـ {name}: {password} — سلّمها له؛ سيُطلب منه تحديد كلمة مرور خاصة به "
     "فور تسجيل الدخول."),
    ("That current password is incorrect.", "كلمة المرور الحالية غير صحيحة."),
    ("The new password must be at least 6 characters.",
     "يجب أن تتكون كلمة المرور الجديدة من 6 أحرف على الأقل."),
    ("The new password and its confirmation don't match.",
     "كلمة المرور الجديدة وتأكيدها غير متطابقين."),
    ("Password set — you're all set.", "تم تعيين كلمة المرور — كل شيء جاهز الآن."),
    ("Set your password", "تعيين كلمة المرور"),
    ("You're signed in with a temporary password — choose your own to continue.",
     "أنت مسجَّل الدخول بكلمة مرور مؤقتة — اختر كلمة مرور خاصة بك للمتابعة."),
    ("Current (temporary) password", "كلمة المرور الحالية (المؤقتة)"),
    ("Confirm new password", "تأكيد كلمة المرور الجديدة"),
    ("Set password", "تعيين كلمة المرور"),
]))

# ---- freight quotations: cost-element breakdown ----
TRANSLATIONS.update(_d([
    ("Air / sea freight", "الشحن الجوي / البحري"),
    ("Export customs clearance", "التخليص الجمركي للتصدير"),
    ("X-ray / scanning", "الفحص بالأشعة السينية"),
    ("Origin handling", "مناولة في بلد المنشأ"),
    ("Documentation fee", "رسوم المستندات"),
    ("Log a received quote", "تسجيل عرض سعر مستلم"),
    ("Back to quotations", "العودة إلى عروض الأسعار"),
    ("Received quote", "عرض السعر المستلم"),
    ("Shipment", "الشحنة"),
    ("Cost elements", "عناصر التكلفة"),
    ("Cost elements — fill in whichever the forwarder itemised; they add up to the quoted "
     "total automatically.",
     "عناصر التكلفة — أدخل ما حدده الوكيل الملاحي منها؛ ستُجمع تلقائياً لتكوين إجمالي العرض."),
    ("Break the forwarder's price down to what it's actually made of — fill in whichever "
     "elements they itemised. They add up to the quoted total automatically.",
     "قسّم سعر الوكيل الملاحي إلى العناصر التي يتكون منها فعلياً — أدخل ما حدده منها. ستُجمع "
     "تلقائياً لتكوين إجمالي العرض."),
    ("Total (only if not itemised above)", "الإجمالي (فقط إن لم تُحدَّد العناصر أعلاه)"),
    ("Open the full quotation entry screen", "فتح شاشة إدخال عروض الأسعار الكاملة"),
]))

# ---- landed cost build-up (per shipment) ----
TRANSLATIONS.update(_d([
    ("Landed cost build-up", "تفصيل تكلفة الوصول"),
    ("Full statement (per item)", "الكشف الكامل (لكل صنف)"),
    ("Back to shipment", "العودة إلى الشحنة"),
    ("From goods value to total cost of the machine", "من قيمة البضاعة إلى إجمالي تكلفة الجهاز"),
    ("Every figure here is in", "كل الأرقام هنا بعملة"),
    ("Goods value (from invoice)", "قيمة البضاعة (من الفاتورة)"),
    ("Total landed cost", "إجمالي تكلفة الوصول"),
    ("Earlier leg costs carried forward", "تكاليف مرحلة سابقة مرحّلة"),
    ("True landed total (including earlier legs)",
     "إجمالي التكلفة الفعلي (شاملاً المراحل السابقة)"),
    ("Shipping is priced from the winning quote", "تكلفة الشحن مأخوذة من عرض السعر الفائز"),
    ("selected forwarder", "الوكيل الملاحي المختار"),
    ("quote ref", "مرجع العرض"),
    ("Freight actually booked so far", "تكلفة الشحن المسجَّلة فعلياً حتى الآن"),
    ("vs quote", "مقارنة بالعرض"),
    ("No freight cost booked against this shipment yet — the build-up above uses actual "
     "booked costs, so shipping shows as zero until one is.",
     "لم تُسجَّل بعد أي تكلفة شحن لهذه الشحنة — يعتمد التفصيل أعلاه على التكاليف المسجَّلة فعلياً، "
     "لذا يظهر الشحن صفراً حتى تُسجَّل تكلفة."),
    ("No quotation has been selected for this shipment yet — log one from the Quotations tab, "
     "or the full quotation entry screen, so shipping cost can be tracked against what was "
     "actually quoted.",
     "لم يُحدَّد بعد عرض سعر لهذه الشحنة — سجّل عرضاً من تبويب عروض الأسعار، أو من شاشة إدخال "
     "عروض الأسعار الكاملة، حتى يمكن متابعة تكلفة الشحن مقارنة بما عُرض فعلياً."),
    ("Per machine / item", "لكل جهاز / صنف"),
    ("Apportioned costs", "التكاليف الموزَّعة"),
    ("Landed cost per unit", "تكلفة الوصول لكل وحدة"),
    ("Costs are apportioned across items by each item's share of total goods value. For "
     "serial numbers and allocations per item, use the full statement.",
     "تُوزَّع التكاليف على الأصناف حسب حصة كل صنف من إجمالي قيمة البضاعة. للاطلاع على الأرقام "
     "التسلسلية والتخصيصات لكل صنف، استخدم الكشف الكامل."),
    ("No item lines recorded yet.", "لا توجد بنود أصناف مسجَّلة بعد."),
    ("Shipping (freight)", "الشحن (النقل)"),
    ("Customs & clearance", "الجمارك والتخليص"),
    ("Bank charges", "مصاريف بنكية"),
    ("Last-mile delivery", "التوصيل للميل الأخير"),
    ("Other costs", "تكاليف أخرى"),
    ("Bank Charges", "مصاريف بنكية"),
    ("Last-Mile Delivery", "التوصيل للميل الأخير"),
]))

# ---- financial analysis report ----
TRANSLATIONS.update(_d([
    ("Financial analysis", "التحليل المالي"),
    ("Total landed value", "إجمالي القيمة الواصلة"),
    ("Every shipment, every cost element", "كل شحنة، وكل عنصر تكلفة"),
    ("figures in", "الأرقام بعملة"),
    ("shipments", "شحنات"),
    ("No shipments in scope.", "لا توجد شحنات ضمن النطاق."),
    ("Click a shipment to open its full Landed cost build-up. Every figure here is pulled "
     "live from the cost lines, supplier invoices and freight quotations logged against "
     "each shipment — nothing is entered here directly.",
     "اضغط على شحنة لفتح تفصيل تكلفة الوصول الكامل الخاص بها. كل رقم هنا مأخوذ مباشرة من "
     "بنود التكاليف وفواتير الموردين وعروض أسعار الشحن المسجَّلة على كل شحنة — لا يتم إدخال "
     "أي شيء هنا مباشرة."),
]))
