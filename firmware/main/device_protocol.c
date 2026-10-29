#include "device_protocol.h"
#include <stdio.h>
#include <string.h>
#include "driver/usb_serial_jtag.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"

static const char *TAG = "dc_protocol";
static char device[80], session[100];
static uint32_t message_sequence;
static char input[DC_MAX_LINE];
static size_t input_length;
static bool discarding;

void dc_protocol_init(const char *device_id, const char *session_id)
{
    snprintf(device, sizeof(device), "%s", device_id);
    snprintf(session, sizeof(session), "%s", session_id);
    message_sequence = 0;
    input_length = 0;
    discarding = false;
}

const char *dc_session_id(void) { return session; }

bool dc_send(const char *type, int64_t timestamp_ms, cJSON *payload)
{
    if (!payload) { ESP_LOGE(TAG, "No payload: allocation failed"); return false; }
    cJSON *root = cJSON_CreateObject();
    if (!root) { cJSON_Delete(payload); return false; }
    if (!cJSON_AddNumberToObject(root, "protocol_version", DC_PROTOCOL_VERSION) ||
        !cJSON_AddStringToObject(root, "type", type) ||
        !cJSON_AddStringToObject(root, "device_id", device) ||
        !cJSON_AddStringToObject(root, "session_id", session) ||
        !cJSON_AddNumberToObject(root, "sequence_number", message_sequence++) ||
        !cJSON_AddNumberToObject(root, "timestamp_ms", (double)timestamp_ms) ||
        !cJSON_AddStringToObject(root, "source", "DEVICE_TEST") ||
        !cJSON_AddItemToObject(root, "payload", payload)) {
        cJSON_Delete(payload);
        cJSON_Delete(root);
        return false;
    }
    char *text = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!text) return false;
    size_t size = strlen(text);
    if (size + 1 > DC_MAX_LINE) { cJSON_free(text); return false; }
    /* Heap wire buffer avoids a 4 KiB stack allocation in the main task. */
    char *wire = cJSON_malloc(size + 2);
    if (!wire) { cJSON_free(text); return false; }
    memcpy(wire, text, size);
    wire[size] = '\n';
    size_t offset = 0;
    int retries = 0;
    while (offset < size + 1 && retries++ < 4) {
        int count = usb_serial_jtag_write_bytes(wire + offset, size + 1 - offset, pdMS_TO_TICKS(20));
        if (count <= 0) break;
        offset += (size_t)count;
    }
    cJSON_free(text);
    cJSON_free(wire);
    if (offset != size + 1) {
        usb_serial_jtag_write_bytes("\n", 1, pdMS_TO_TICKS(5));
        ESP_LOGW(TAG, "USB transmit incomplete; sequence gap is observable");
        return false;
    }
    return true;
}

void dc_announce(int64_t timestamp_ms)
{
    cJSON *hello = cJSON_CreateObject();
    if (hello) {
        cJSON_AddStringToObject(hello, "firmware_version", "0.1.0-test");
        cJSON_AddBoolToObject(hello, "test_mode", true);
    }
    dc_send("HELLO", timestamp_ms, hello);
    cJSON *caps = cJSON_CreateObject();
    if (caps) {
        const char *ids[] = {"RPM", "SPEED", "COOLANT_TEMP", "ENGINE_LOAD", "THROTTLE_POS",
            "INTAKE_PRESSURE", "MAF", "INTAKE_TEMP", "SHORT_FUEL_TRIM", "LONG_FUEL_TRIM",
            "CONTROL_MODULE_VOLTAGE", "DTC"};
        cJSON *sensors = cJSON_CreateStringArray(ids, 12);
        if (!sensors || !cJSON_AddItemToObject(caps, "sensors", sensors)) {
            cJSON_Delete(sensors); cJSON_Delete(caps); return;
        }
        cJSON_AddBoolToObject(caps, "can", false);
        cJSON_AddBoolToObject(caps, "microsd", false);
        cJSON_AddBoolToObject(caps, "event_upload", false);
    }
    dc_send("CAPABILITIES", timestamp_ms, caps);
}

static void send_error(const char *code, int64_t ms)
{
    cJSON *payload = cJSON_CreateObject();
    if (payload) {
        cJSON_AddStringToObject(payload, "code", code);
        cJSON_AddStringToObject(payload, "message", "M1 test firmware accepts HELLO or ACK only");
    }
    dc_send("ERROR", ms, payload);
}

static void handle_line(int64_t ms)
{
    input[input_length] = 0;
    const char *end = NULL;
    cJSON *root = cJSON_ParseWithOpts(input, &end, true);
    cJSON *version = root ? cJSON_GetObjectItemCaseSensitive(root, "protocol_version") : NULL;
    cJSON *type = root ? cJSON_GetObjectItemCaseSensitive(root, "type") : NULL;
    if (!cJSON_IsObject(root) || !cJSON_IsNumber(version) || version->valuedouble != 1 ||
        !cJSON_IsString(type)) {
        send_error("INVALID_MESSAGE", ms);
    } else if (strcmp(type->valuestring, "HELLO") == 0) {
        dc_announce(ms);  /* no hardware state change */
    } else if (strcmp(type->valuestring, "ACK") != 0) {
        send_error("UNSUPPORTED_MESSAGE", ms);
    }
    cJSON_Delete(root);
}

void dc_poll_input(int64_t timestamp_ms)
{
    uint8_t bytes[128];
    int count = usb_serial_jtag_read_bytes(bytes, sizeof(bytes), 0);
    for (int i = 0; i < count; ++i) {
        if (bytes[i] == '\n') {
            if (discarding) send_error("OVERSIZED_MESSAGE", timestamp_ms);
            else if (input_length) handle_line(timestamp_ms);
            input_length = 0;
            discarding = false;
        } else if (!discarding) {
            if (input_length >= sizeof(input) - 1) { discarding = true; input_length = 0; }
            else input[input_length++] = (char)bytes[i];
        }
    }
}
