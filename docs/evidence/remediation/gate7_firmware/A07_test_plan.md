# DEF-008 / A07 — خطة اختبار Patch الـFirmware (غير منفذة)

الحالة: **PATCH PROPOSED — NOT BUILT — NOT VERIFIED.** لم يُعدَّل `firmware/` في هذه المهمة (لا ESP-IDF ولا مترجم C ولا لوحة).

1. بناء `idf.py build` بعد تطبيق `A07_envelope_validation.patch` (يتطلب ESP-IDF؛ NOT TESTED الآن).
2. اختبار host للمحلل: استخراج `envelope_is_valid` مع cJSON إلى اختبار وحدة على الحاسوب، بالحالات: HELLO كاملة ← تُقبل؛ غياب كل حقل من الحقول الثمانية على حدة ← INVALID_MESSAGE؛ `sequence_number` سالب/عشري/نصي ← INVALID_MESSAGE؛ `payload` غير كائن ← INVALID_MESSAGE؛ `protocol_version=2` ← INVALID_MESSAGE؛ ACK ناقص ← INVALID_MESSAGE.
3. على اللوحة (بعد إذن صريح): إرسال HELLO ناقص عبر USB Serial والتأكد من رد ERROR/INVALID_MESSAGE وعدم إرسال CAPABILITIES.
4. اختبار توافق: `HELLO` الصادر من `doctorcar.protocol.messages` (المضيف) يجب أن يظل مقبولًا.
