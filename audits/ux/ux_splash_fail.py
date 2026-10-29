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


blocker_dir = Path(tempfile.mkdtemp(prefix="dc-ux-fail-"))
blocker = blocker_dir / "ليس مجلدا.txt"
blocker.write_text("x")
db_path = blocker / "db.sqlite3"
t0 = time.perf_counter()
proc = subprocess.Popen([python, "-B", "-m", "doctorcar", "--database", str(db_path)], stderr=subprocess.PIPE, text=True, encoding="utf-8")
frames = []
titles_seen = set()
main_seen = False
end_at = t0 + 8
while time.perf_counter() < end_at and proc.poll() is None:
    wins = windows_of(proc.pid)
    for h, title in wins:
        titles_seen.add(title)
        if title.startswith("DoctorCAR |"):
            main_seen = True
    if len(wins) >= 2 and not frames:
        time.sleep(0.8)
        for i, (h, title) in enumerate(windows_of(proc.pid)):
            name = f"{label}-fail-{i}.png"
            capture(h, out / name)
            frames.append({"title": title, "file": name})
    time.sleep(0.05)
closed = []
for h, title in windows_of(proc.pid):
    user32.PostMessageW(h, 0x0010, 0, 0)
    closed.append(title)
t1 = time.perf_counter()
while proc.poll() is None and time.perf_counter() - t1 < 10:
    time.sleep(0.05)
exit_code = proc.poll()
if exit_code is None:
    proc.kill()
result = {"label": label, "windows_titles_seen": sorted(titles_seen), "main_window_ever_visible": main_seen, "frames": frames,
          "closed": closed, "exit_code_after_closing_dialog": exit_code, "stderr_tail": (proc.stderr.read() if proc.stderr else "")[-500:]}
(out / f"{label}-fail-startup.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
print(json.dumps({k: v for k, v in result.items() if k != "stderr_tail"}, ensure_ascii=False, indent=1))
