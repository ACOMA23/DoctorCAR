#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "cJSON.h"

#define DC_PROTOCOL_VERSION 1
#define DC_MAX_LINE 4096

void dc_protocol_init(const char *device_id, const char *session_id);
const char *dc_session_id(void);
/* send consumes payload, including on failure */
bool dc_send(const char *type, int64_t timestamp_ms, cJSON *payload);
void dc_announce(int64_t timestamp_ms);
void dc_poll_input(int64_t timestamp_ms);
