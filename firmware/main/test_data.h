#pragma once
#include <stdint.h>
#include "cJSON.h"

/* Caller owns the resulting payload. No access to CAN, ADC, SD or vehicle. */
cJSON *dc_test_sample(const char *session_id, uint32_t sequence, int64_t elapsed_ms);
