#include "test_data.h"
#include <math.h>
#include <stdbool.h>
#include "sdkconfig.h"

static bool reading(cJSON *readings, const char *id, double value, const char *unit)
{
    cJSON *r = cJSON_CreateObject();
    if (!r) return false;
    if (!cJSON_AddNumberToObject(r, "value", value) ||
        !cJSON_AddStringToObject(r, "unit", unit) ||
        !cJSON_AddStringToObject(r, "quality", "AVAILABLE")) {
        cJSON_Delete(r);
        return false;
    }
    if (!cJSON_AddItemToObject(readings, id, r)) {
        cJSON_Delete(r);
        return false;
    }
    return true;
}

cJSON *dc_test_sample(const char *session_id, uint32_t sequence, int64_t elapsed_ms)
{
    /* Cycle position affects values only. Wire timestamps and sequences never wrap per cycle. */
    double t = (double)(elapsed_ms % 155000) / 1000.0;
    double speed = 0, throttle = 4, rpm = 810;
    const char *phase = "TEST_IDLE";
    if (t < 3) { phase = "TEST_START"; rpm = 250 + t * 330; throttle = 12; }
    else if (t < 35) { phase = "TEST_WARMUP"; rpm = 1100 - (t - 3) * 8; throttle = 8; }
    else if (t < 45) { phase = "TEST_IDLE"; }
    else if (t < 60) {
        phase = "TEST_ACCELERATION"; speed = (t - 45) * 4; throttle = 48;
        rpm = 1000 + speed * 32;
    } else if (t < 105) {
        phase = "TEST_CRUISE"; speed = 60 + sin(t / 4) * 1.5; throttle = 23;
        rpm = 1000 + speed * 24;
    } else if (t < 125) {
        phase = "TEST_DECELERATION"; speed = fmax(0, 60 - (t - 105) * 3);
        throttle = 3; rpm = 810 + speed * 20;
    } else if (t >= 145) { phase = "TEST_STOPPED"; throttle = 0; rpm = 0; }
    double load = rpm > 0 ? fmin(95, throttle * 1.3 + speed * 0.12) : 0;
    double coolant = 22 + 68 * (1 - exp(-t / 35));
#if CONFIG_DOCTORCAR_TEST_THERMAL
    if (t >= 70 && t <= 130) coolant += fmin(42, fmin((t - 70) * 1.5, (130 - t) * 4));
#endif
    cJSON *sample = cJSON_CreateObject();
    cJSON *readings = cJSON_CreateObject();
    cJSON *payload = cJSON_CreateObject();
    if (!sample || !readings || !payload) goto fail;
    if (!cJSON_AddNumberToObject(sample, "sample_version", 1) ||
        !cJSON_AddStringToObject(sample, "session_id", session_id) ||
        !cJSON_AddStringToObject(sample, "source", "DEVICE_TEST") ||
        !cJSON_AddNumberToObject(sample, "sequence_number", sequence) ||
        !cJSON_AddNumberToObject(sample, "timestamp_ms", (double)elapsed_ms) ||
        !cJSON_AddStringToObject(sample, "phase", phase) ||
        !cJSON_AddStringToObject(sample, "dtc_quality", "AVAILABLE") ||
        !cJSON_AddArrayToObject(sample, "dtcs")) goto fail;
    if (!reading(readings, "RPM", rpm, "rpm") ||
        !reading(readings, "SPEED", speed, "km/h") ||
        !reading(readings, "COOLANT_TEMP", coolant, "°C") ||
        !reading(readings, "ENGINE_LOAD", load, "%") ||
        !reading(readings, "THROTTLE_POS", throttle, "%") ||
        !reading(readings, "INTAKE_PRESSURE", rpm > 0 ? 30 + load * .65 : 100, "kPa") ||
        !reading(readings, "MAF", rpm * (.002 + load * .00008), "g/s") ||
        !reading(readings, "INTAKE_TEMP", 24 + load * .08, "°C") ||
        !reading(readings, "SHORT_FUEL_TRIM", sin(t / 7) * 2, "%") ||
        !reading(readings, "LONG_FUEL_TRIM", 1.5 + sin(t / 60) * .3, "%") ||
        !reading(readings, "CONTROL_MODULE_VOLTAGE", rpm > 0 ? 13.9 + sin(t / 6) * .1 : 12.4, "V")) goto fail;
    if (!cJSON_AddItemToObject(sample, "readings", readings)) goto fail;
    readings = NULL;
    if (!cJSON_AddItemToObject(payload, "sample", sample)) goto fail;
    return payload;
fail:
    cJSON_Delete(readings);
    cJSON_Delete(sample);
    cJSON_Delete(payload);
    return NULL;
}
