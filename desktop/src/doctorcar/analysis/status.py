"""AI state vocabulary shared by Session, storage and report rendering (no ML imports)."""

ANALYZED_NORMAL = "ANALYZED_NORMAL"
ANALYZED_ANOMALOUS = "ANALYZED_ANOMALOUS"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
MODEL_NOT_LOADED = "MODEL_NOT_LOADED"
INFERENCE_FAILED = "INFERENCE_FAILED"
DISABLED = "DISABLED"
HISTORICAL = "HISTORICAL"
NO_RECENT_ANALYSIS = "NO_RECENT_ANALYSIS"
NOT_RECORDED = "NOT_RECORDED"  # events saved before AI status existed

STATES = (
    ANALYZED_NORMAL,
    ANALYZED_ANOMALOUS,
    INSUFFICIENT_DATA,
    MODEL_NOT_LOADED,
    INFERENCE_FAILED,
    DISABLED,
    HISTORICAL,
    NO_RECENT_ANALYSIS,
    NOT_RECORDED,
)

MESSAGES = {
    ANALYZED_NORMAL: (
        "حلل الذكاء الاصطناعي البيانات المتاحة ولم يكتشف شذوذًا وفق نموذجه الحالي.",
        "The AI analyzed the available data and found no anomaly under its current model.",
    ),
    ANALYZED_ANOMALOUS: (
        "اكتشف الذكاء الاصطناعي نمطًا غير معتاد في البيانات.",
        "The AI detected an unusual pattern in the data.",
    ),
    INSUFFICIENT_DATA: (
        "لم تتوفر بيانات كافية للتحليل.",
        "There was not enough data for the analysis.",
    ),
    MODEL_NOT_LOADED: (
        "تحليل الذكاء الاصطناعي غير متاح: النموذج لم يُحمّل.",
        "AI analysis is unavailable: the model was not loaded.",
    ),
    INFERENCE_FAILED: (
        "تعذر إكمال التحليل بسبب خطأ تقني.",
        "The analysis could not be completed because of a technical error.",
    ),
    DISABLED: (
        "لم يُفعَّل تحليل الذكاء الاصطناعي في هذه الجلسة.",
        "AI analysis was not enabled in this session.",
    ),
    HISTORICAL: (
        "حدث تاريخي مستورد من الجهاز؛ لم يمر بتحليل الذكاء الاصطناعي الحي.",
        "Imported device history; it did not pass through live AI analysis.",
    ),
    NO_RECENT_ANALYSIS: (
        "لم يتوفر تحليل حديث للذكاء الاصطناعي وقت الكشف.",
        "No recent AI analysis was available at the time of detection.",
    ),
    NOT_RECORDED: (
        "لم يُحلل هذا الحدث باستخدام الذكاء الاصطناعي؛ لا يوجد سجل لسبب ذلك (حدث أقدم).",
        "This event has not been analyzed by AI; no reason was recorded (older event).",
    ),
}


def message(state: str, language: str) -> str:
    return MESSAGES.get(state, MESSAGES[NOT_RECORDED])[0 if language == "ar" else 1]
