#include <inttypes.h>
#include <stdio.h>
#include "device_protocol.h"
#include "test_data.h"
#include "driver/usb_serial_jtag.h"
#include "esp_err.h"
#include "esp_idf_version.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#if !CONFIG_IDF_TARGET_ESP32S3
#error "DoctorCAR M1 requires ESP32-S3"
#endif
#if ESP_IDF_VERSION < ESP_IDF_VERSION_VAL(5, 5, 0)
#error "DoctorCAR M1 targets ESP-IDF 5.5.x; older APIs have not been reviewed"
#endif
#define DOCTORCAR_REAL_CAN_ENABLED 0
#if DOCTORCAR_REAL_CAN_ENABLED
#error "Real CAN is not implemented or authorized in M1"
#endif

void app_main(void)
{
    usb_serial_jtag_driver_config_t config = {
        .tx_buffer_size = 8192, .rx_buffer_size = 4096
    };
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&config));
    uint8_t mac[6];
    ESP_ERROR_CHECK(esp_efuse_mac_get_default(mac));
    char device[80], session[100];
    snprintf(device, sizeof(device), "doctorcar-s3-%02x%02x%02x%02x%02x%02x", MAC2STR(mac));
    snprintf(session, sizeof(session), "%s-%08" PRIx32 "-%08" PRIx32,
             device, esp_random(), esp_random());
    dc_protocol_init(device, session);
    ESP_LOGI("doctorcar", "DEVICE_TEST only. USB protocol; UART console. CAN/SD disabled.");
    int64_t origin = esp_timer_get_time();
    int64_t next_sample = 0, next_hello = 0, next_heartbeat = 0;
    uint32_t sample_sequence = 0;
    while (true) {
        int64_t ms = (esp_timer_get_time() - origin) / 1000;
        /* Periodic handshake lets a host attach/reconnect without resetting the device. */
        if (ms >= next_hello) { dc_announce(ms); next_hello = ms + 5000; }
        if (ms >= next_sample) {
            dc_send("SAMPLE", ms, dc_test_sample(dc_session_id(), sample_sequence++, ms));
            next_sample = ms + 200;
        }
        if (ms >= next_heartbeat) {
            cJSON *heartbeat = cJSON_CreateObject();
            if (heartbeat) cJSON_AddNumberToObject(heartbeat, "uptime_ms", (double)ms);
            dc_send("HEARTBEAT", ms, heartbeat);
            next_heartbeat = ms + 1000;
        }
        dc_poll_input(ms);
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}
