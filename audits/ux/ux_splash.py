"""DC-UX-001: launch the real application as a separate process and observe startup from outside.

Usage: ux_splash.py <python.exe> <out_dir> [label]
Measures (Windows, win32 API only): time until the splash window is visible, the sequence of splash frames
(captured with PrintWindow, i.e. the windows' own rendering), time until the main window is visible, and clean exit.
The database path contains Arabic letters and spaces. No product code is imported here.
"""

import ctypes
import json
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

python, out = sys.argv[1], Path(sys.argv[2])
label = sys.argv[3] if len(sys.argv) > 3 else "source"
out.mkdir(parents=True, exist_ok=True)
user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
user32.FindWindowW.restype = wintypes.HWND
user32.IsWindowVisible.argtypes = [wintypes.HWND]
EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class PE32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


def process_tree(root_pid: int) -> set[int]:
    """The venv python.exe is a launcher that starts the real interpreter as a child: include descendants."""
    snap = ctypes.windll.kernel32.CreateToolhelp32Snapshot(2, 0)
    entry = PE32()
    entry.dwSize = ctypes.sizeof(PE32)
    parents = {}
    ok = ctypes.windll.kernel32.Process32FirstW(snap, ctypes.byref(entry))
    while ok:
        parents[entry.th32ProcessID] = entry.th32ParentProcessID
        ok = ctypes.windll.kernel32.Process32NextW(snap, ctypes.byref(entry))
    ctypes.windll.kernel32.CloseHandle(snap)
    tree = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in tree and pid not in tree:
                tree.add(pid)
                changed = True
    return tree


def windows_of(pid: int) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    tree = process_tree(pid)

    def cb(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in tree and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return found


def capture(hwnd: int, path: Path) -> tuple[int, int]:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, 2)

    class BIH(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("w", wintypes.LONG), ("h", wintypes.LONG), ("planes", wintypes.WORD),
                    ("bits", wintypes.WORD), ("comp", wintypes.DWORD), ("img", wintypes.DWORD), ("xp", wintypes.LONG),
                    ("yp", wintypes.LONG), ("used", wintypes.DWORD), ("imp", wintypes.DWORD)]

    info = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buffer = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buffer, ctypes.byref(info), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, hdc)
    from PySide6.QtGui import QImage

    QImage(buffer.raw, w, h, QImage.Format.Format_ARGB32).save(str(path))
    return w, h


root = Path(tempfile.mkdtemp(prefix="dc-ux-splash-")) / "مجلد تجربة" / "قاعدة بيانات.sqlite3"
root.parent.mkdir(parents=True)
t0 = time.perf_counter()
proc = subprocess.Popen([python, "-B", "-m", "doctorcar", "--database", str(root)], stderr=subprocess.PIPE, text=True, encoding="utf-8")
seen_splash = main_seen = None
frames: list[dict] = []
main_hwnd = 0
last_frame = 0.0
while time.perf_counter() - t0 < 40 and proc.poll() is None:
    now = time.perf_counter() - t0
    wins = windows_of(proc.pid)
    splash = [h for h, title in wins if title == "DoctorCAR"]
    main = [h for h, title in wins if title.startswith("DoctorCAR |")]
    if splash and seen_splash is None:
        seen_splash = now
    if splash and now - last_frame > 0.12 and len(frames) < 12:
        name = f"{label}-splash-{len(frames):02d}.png"
        w, h = capture(splash[0], out / name)
        frames.append({"t_s": round(now, 3), "file": name, "size": [w, h]})
        last_frame = now
    if main and main_seen is None:
        main_seen = now
        main_hwnd = main[0]
        time.sleep(1.2)  # let the first paint complete
        capture(main_hwnd, out / f"{label}-main-first.png")
        break
    time.sleep(0.01)
splash_after_main = bool([h for h, title in windows_of(proc.pid) if title == "DoctorCAR"])
main_windows = len([1 for _, title in windows_of(proc.pid) if title.startswith("DoctorCAR |")])
exited = None
if main_hwnd:
    user32.PostMessageW(main_hwnd, 0x0010, 0, 0)  # WM_CLOSE
    t1 = time.perf_counter()
    while proc.poll() is None and time.perf_counter() - t1 < 15:
        time.sleep(0.05)
    exited = proc.poll()
if proc.poll() is None:
    proc.kill()
err = proc.stderr.read() if proc.stderr else ""
result = {
    "label": label,
    "python": python,
    "database_path": str(root),
    "splash_visible_after_s": round(seen_splash, 3) if seen_splash is not None else None,
    "main_visible_after_s": round(main_seen, 3) if main_seen is not None else None,
    "splash_frames": frames,
    "splash_still_visible_after_main": splash_after_main,
    "main_windows": main_windows,
    "exit_code_after_close": exited,
    "database_created": root.exists(),
    "stderr_tail": err[-600:],
}
(out / f"{label}-startup.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
print(json.dumps({k: v for k, v in result.items() if k not in ("splash_frames", "stderr_tail")}, ensure_ascii=False, indent=1))
print("frames:", len(frames))
