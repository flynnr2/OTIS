#ifndef OTIS_SERVICE_LATENCY_LIVE_H
#define OTIS_SERVICE_LATENCY_LIVE_H
#include "otis_service_latency.h"
// Core 1 owns stages 0..2; Core 0 owns stages 3..4. Never call across owners.
void otis_service_latency_live_note(const OtisServiceLatencySample &sample);
// Core 1 services a single immutable diagnostic mailbox; no waiting or formatting.
void otis_service_latency_live_timing_service();
// Core 0, only at a serial frame boundary, after canonical output service.
void otis_service_latency_live_output_service(uint32_t now_ms);
#endif
