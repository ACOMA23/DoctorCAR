"""Diagnostic: run pr_gui.py up to the first start click, then print UI state per second."""
import os, sys
src = open("audits/post_remediation/pr_gui.py", encoding="utf8").read()
head = src.split("ticks = []")[0]
g = {"__file__": os.path.abspath("audits/post_remediation/pr_gui.py"), "__name__": "diag"}
exec(compile(head, "pr_gui_head", "exec"), g)
w, pump, click = g["window"], g["pump"], g["click"]
print("page=", w.pages.currentIndex(), "source=", w.source_combo.currentData(), "mode=", w.mode_combo.currentData(), "family=", w.family_combo.currentData(), "start_enabled=", w.start_button.isEnabled(), "start_visible=", w.start_button.isVisible(), flush=True)
print("args=", w.source_arguments(), flush=True)
orig = w.worker.submit
def spy(c, **a):
    print("SUBMIT", c, a, "qsize", w.worker.commands.qsize(), "alive", w.worker.isRunning(), flush=True); return orig(c, **a)
w.worker.submit = spy
for nm in ("running_changed","status_changed","error","ai_changed"):
    sig = getattr(w.worker, nm, None)
    if sig is not None:
        sig.connect(lambda *a, nm=nm: print("SIG", round(__import__("time").monotonic()-T0,2), nm, str(a)[:80], flush=True))
T0=__import__("time").monotonic()
click(w.start_button)
for t in range(12):
    pump(1.0)
    print(t, "locked=", not w.source_combo.isEnabled(), "status=", w.status_label.text(), "| err=", w.error_label.isVisible(), w.error_label.text(), "| ai=", w.ai_label.text(), flush=True)
import faulthandler; faulthandler.dump_traceback(all_threads=True)
w.close(); pump(until=lambda: w.worker.isFinished(), limit=10)
