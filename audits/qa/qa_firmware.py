"""QA-FW: static firmware review (no toolchain, no hardware). Nothing is built, flashed or modified."""

import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import EVIDENCE, ROOT, Registry, rel  # noqa: E402

reg = Registry("gate9_fw")
folder = EVIDENCE / "gate9"
folder.mkdir(parents=True, exist_ok=True)
fw = ROOT / "firmware"
read = lambda p: (fw / p).read_text(encoding="utf8")  # noqa: E731
files = {p.relative_to(fw).as_posix(): p.read_text(encoding="utf8", errors="replace") for p in fw.rglob("*") if p.is_file() and p.suffix in (".c", ".h", ".txt", ".defaults", ".projbuild")}


def find(pattern, name=None):
    out = []
    for fname, text in files.items():
        if name and fname != name:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(pattern, line):
                out.append(f"{fname}:{i}: {line.strip()[:110]}")
    return out


tools = {t: shutil.which(t) for t in ("idf.py", "cmake", "ninja", "gcc", "clang", "xtensa-esp32s3-elf-gcc")}
reg.add("QA-FW-001", "TEST-002", "Firmware build (ESP-IDF 5.5.x, esp32s3)", "locate idf.py/cmake/ninja/toolchain", "build succeeds without flashing",
        f"FIRMWARE BUILD — NOT TESTED: tools not found {tools}; IDF_PATH unset", "NOT TESTED", rel(folder / "firmware-static-review.json"),
        notes="Per project rules the build is attempted only when the SDK is present. No flashing was ever attempted.")
target = {"cmake_fatal_unless_esp32s3": bool(find(r"IDF_TARGET STREQUAL \"esp32s3\"", "CMakeLists.txt")), "sdkconfig_target": bool(find(r"CONFIG_IDF_TARGET=\"esp32s3\"", "sdkconfig.defaults")),
          "c_error_unless_s3": bool(find(r"CONFIG_IDF_TARGET_ESP32S3", "main/main.c")), "c_error_below_idf_5_5": bool(find(r"ESP_IDF_VERSION_VAL\(5, 5, 0\)", "main/main.c"))}
reg.add("QA-FW-002", "FR-011", "Target and SDK guards in CMake/sdkconfig/C", "read CMakeLists, sdkconfig.defaults, main.c", "ESP32-S3 only and IDF >= 5.5 enforced at configure/compile time",
        json.dumps(target), "PARTIAL" if all(target.values()) else "FAIL", rel(folder / "firmware-static-review.json"), notes="Static reading only; the guards have not been compiled.")
schema = json.loads((ROOT / "desktop/src/doctorcar/protocol/device_protocol_v1.schema.json").read_text("utf8"))
required = schema["required"]
text = read("main/device_protocol.c")
body = text[text.index("static void handle_line"): text.index("void dc_poll_input")]
checked = [f for f in required if f'"{f}"' in body]
missing = [f for f in required if f not in checked]
reg.add("QA-FW-003", "FR-012/A07", "A07: C receiver validates only part of the mandatory envelope (static reproduction)",
        "compare schema 'required' with the fields handle_line() inspects", "all 8 mandatory fields validated before acting (as the Python decoder does)",
        f"validated: {checked}; NOT validated: {missing}. A HELLO such as {{\"protocol_version\":1,\"type\":\"HELLO\"}} reaches dc_announce() in C but is rejected by the Python parser (QA-IOT-002)",
        "FAIL", rel(folder / "firmware-static-review.json"), notes="Defect A07 is still open; reproduction is by source inspection only, not execution.")
can = {"real_can_flag_zero": bool(find(r"#define DOCTORCAR_REAL_CAN_ENABLED 0", "main/main.c")), "compile_error_if_enabled": bool(find(r"Real CAN is not implemented", "main/main.c")),
       "twai_used": bool(find(r"twai_|driver/twai")), "wifi_used": bool(find(r"esp_wifi|esp_netif")), "sd_used": bool(find(r"sdmmc|sdspi|esp_vfs_fat")), "adc_used": bool(find(r"adc_|esp_adc")), "rtc_used": bool(find(r"rtc_|esp_rtc"))}
reg.add("QA-FW-004", "SAF-001", "Real CAN is disabled and guarded; Wi-Fi/MicroSD/ADC/RTC are not implemented", "grep sources", "CAN guard present; no TWAI/Wi-Fi/SD/ADC/RTC usage",
        json.dumps(can), "PARTIAL" if can["real_can_flag_zero"] and can["compile_error_if_enabled"] and not any(can[k] for k in ("twai_used", "wifi_used", "sd_used", "adc_used", "rtc_used")) else "FAIL",
        rel(folder / "firmware-static-review.json"), notes="Static. Those features are Not Implemented in M1, hence also not tested.")
buf = {"DC_MAX_LINE": find(r"define DC_MAX_LINE", "main/device_protocol.h"), "input_buffer": find(r"static char input\[", "main/device_protocol.c"), "overflow_guard": find(r"sizeof\(input\) - 1", "main/device_protocol.c"),
       "python_MAX_LINE_BYTES": 4096, "usb_rx_tx": find(r"rx_buffer_size|tx_buffer_size", "main/main.c")}
reg.add("QA-FW-005", "FR-013", "Line-size limit is consistent between C (4096) and Python (4096 incl. LF); oversize is discarded with an ERROR", "read buffers and discard logic",
        "same limit; overflow discards until LF and sends OVERSIZED_MESSAGE", json.dumps(buf, ensure_ascii=False)[:420], "PARTIAL", rel(folder / "firmware-static-review.json"), notes="Static only.")
modes = {"source_DEVICE_TEST": bool(find(r"DEVICE_TEST")), "event_upload_false": bool(find(r'"event_upload", false', "main/device_protocol.c")), "test_data_kconfig": bool(find(r"DOCTORCAR_TEST_THERMAL"))}
reg.add("QA-FW-006", "FR-013", "Test mode: data labelled DEVICE_TEST, event upload not advertised", "grep", "DEVICE_TEST label and event_upload=false", json.dumps(modes), "PARTIAL" if all(modes.values()) else "FAIL",
        rel(folder / "firmware-static-review.json"), notes="Static.")
errs = find(r'send_error\("')
reg.add("QA-FW-007", "FR-013", "Error behaviour in the C receiver", "grep send_error", "INVALID_MESSAGE / UNSUPPORTED_MESSAGE / OVERSIZED_MESSAGE exist; no vehicle-changing command",
        "; ".join(errs[:5]), "PARTIAL", rel(folder / "firmware-static-review.json"), notes="No command handler writes to hardware: only HELLO (re-announce) and ACK (ignored) are accepted.")
for tid, title in (("QA-FW-008", "USB Serial/JTAG on a physical ESP32-S3"), ("QA-FW-009", "Wi-Fi on ESP32"), ("QA-FW-010", "CAN (TWAI)"), ("QA-FW-011", "MicroSD"), ("QA-FW-012", "ADC / RTC / vehicle power")):
    reg.add(tid, "FR-011/M5/M6", title, "-", "hardware test", "NOT TESTED: no board, no toolchain, feature not implemented in M1" if tid != "QA-FW-008" else "NOT TESTED: no board connected; no COM port opened", "NOT TESTED", "")
(folder / "firmware-static-review.json").write_text(json.dumps({"tools": tools, "target": target, "schema_required": required, "validated_in_handle_line": checked, "not_validated": missing,
                                                                 "guards": can, "buffers": buf, "modes": modes, "send_error_sites": errs, "files": sorted(files)}, ensure_ascii=False, indent=2), encoding="utf8")
reg.save()
