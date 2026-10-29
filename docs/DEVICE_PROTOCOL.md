# DoctorCAR JSON Lines v1

العقد المستخدم فعليًا في Python موجود في `desktop/src/doctorcar/protocol/device_protocol_v1.schema.json` ومضمّن في الحزمة؛ مدخل `schemas/device_protocol_v1.schema.json` يشير إليه محليًا لتجنب عقدين متعارضين.

## التأطير والهوية والزمن

- UTF-8، كائن JSON واحد لكل سطر، LF، حد **4096 بايت شامل LF**. ترفض المفاتيح المكررة وNaN/Infinity والإصدار غير المدعوم. تتجاهل framing bytes في سطر زائد الحجم حتى LF التالي مع خطأ صريح.
- جميع الرسائل: `protocol_version=1`, `type`, `device_id`, `session_id`, `sequence_number`, `timestamp_ms`, `source`, `payload`. `event_id` مطلوب لرسائل الأحداث.
- `session_id` هوية تشغيل/boot جديدة، و`device_id` هوية المصدر. `timestamp_ms` زمن رتيب نسبي للجلسة وليس UTC. `received_at_ms` في sample زمن استقبال المضيف عند توفره، وليس وقت وقوع عطل.
- تسلسل الرسالة يشمل control/heartbeat/sample؛ تسلسل العينة داخل `payload.sample.sequence_number` مستقل لتجنب فجوات ناتجة عن heartbeat. التكرار أو التراجع في تسلسل الرسائل لا يعيد استيراد البيانات، والفجوات تعدّ وتسجل. جودة العينات تتحقق من تسلسلها وزمنها أيضًا.
- مصادر M1: `SIMULATION` للمحاكي البرمجي، `DEVICE_TEST` لبيانات اختبار من Firmware، `REPLAY` لإعادة تشغيل sample files مع provenance أصلي. لا مصدر قراءات مركبة فعلية في M1.

## الرسائل والقدرات

| النوع | payload | السلوك المنفذ |
| --- | --- | --- |
| HELLO | firmware_version, test_mode=true | إعلان test device؛ مطلوب قبل البيانات |
| CAPABILITIES | sensors, can=false, microsd=false, event_upload | حساسات مدعومة فعليًا في وضع الاختبار فقط |
| SAMPLE | sample | sample v1 بالقراءات والوحدات والجودة وDTC؛ هوية/زمن متطابقة مع الغلاف |
| HEARTBEAT | uptime_ms | حالة الجهاز؛ ليست قراءة حساس |
| EVENT_START | total_chunks, total_bytes, sha256 | بدء رفع حدث نهائي COMPLETE/PARTIAL |
| EVENT_CHUNK | index, data (Base64), sha256 | جزء مستقل التحقق |
| EVENT_END | sha256 | لا يستورد الحدث إلا بعد اكتمال كل الأجزاء والتحقق الكامل |
| ACK | ack_sequence | معروف في العقد؛ يتجاهله Firmware بأمان؛ لا يرسله تطبيق M1 تلقائيًا |
| ERROR | code, message | خطأ محدود النص؛ ظاهر للمستقبل |

`sample` يحتوي `sample_version`, `session_id`, `source`, `sequence_number`, `timestamp_ms`, `readings`. كل reading لها value رقم محدود أو null وunit وquality. DTC مصفوفة منفصلة مع `dtc_quality`؛ فراغ DTC المتاحة يختلف عن عدم دعمها. `phase` للسياق، و`freeze_frame` اختياري غير متاح من مصادر M1، و`raw` للحفاظ على الأصل. الحساسات غير المعلنة تصبح UNSUPPORTED، والمفقودة MISSING، ولا يستبدل الغياب بصفر.

## الأحداث وإعادة الاتصال

- حد الحدث **2 MiB**، حتى 4096 جزءًا، وحتى 4 تجميعات نشطة. كل جزء مفكوك لا يتجاوز 1024 بايت؛ يرسل المحاكي أجزاء 768 بايت. الحد الأدنى للحجم 1 بايت، وترقيم الأجزاء يبدأ بصفر.
- `sha256` لكل جزء وللكائن المجمع يحمي سلامة النقل من التلف؛ لا يمثل مصادقة أو ضمانًا أمنيًا لهوية الجهاز.
- تقبل إعادة الجزء بالمحتوى نفسه وبرقم رسالة جديد، وترفض المحتوى المتعارض. يجب توافر جميع الأجزاء وترتيبها وفحص الحجم والهوية والمصدر قبل الإضافة للـstream والتخزين.
- تفقد تجميعات غير مكتملة بعد 60 ثانية عند معالجة رسائل الأحداث، أو فور reset_connection. بعد إعادة الاتصال تعاد المصافحة، ثم يعاد الرفع من EVENT_START؛ لا ACK/resume جزئي آلي في M1. إعادة المحاولة الكاملة بنفس event_id لا تنشئ سجل SQLite مكررًا، والتعارض لا يكتب فوق حدث نهائي.
- لا يعيد المضيف فتح منفذ مفقود دون طلب المستخدم. Firmware يعيد HELLO/CAPABILITIES كل 5 ثوانٍ لتسهيل الالتحاق وسط التشغيل. مصدر Serial ينتظر المصافحة؛ لا يرسل طلبات أو يغيّر وضع الجهاز. إعادة تشغيل الجهاز تعطي session_id جديدة فتغلق نافذة الجلسة السابقة كجزئية دون خلط العينات.
- Firmware M1 يعلن `event_upload=false` ويولد SAMPLE/HEARTBEAT فقط مع المصافحة وERROR للأخطاء الأساسية؛ تجميع الأحداث ورفعها من الجهاز وSD مؤجل. محاكي Python ومستقبل الكمبيوتر يختبران بروتوكول الرفع الآن.
- السجلات الداخلية في UART/standard logging منفصلة عن قناة JSONL. عند رسائل تالفة أو EOF مبتور في ملف البروتوكول يتوقف المصدر بخطأ ظاهر؛ لا تدّعي الواجهة أن البيانات ما زالت حية.
