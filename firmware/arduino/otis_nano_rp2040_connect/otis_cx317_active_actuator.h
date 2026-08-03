#ifndef OTIS_CX317_ACTIVE_ACTUATOR_H
#define OTIS_CX317_ACTIVE_ACTUATOR_H

#include <stdint.h>

#include "otis_cx317_active_transaction.h"

// The physical actuator owner is deliberately separate from estimation and
// authority. It accepts one already-consumed transaction and returns one
// immutable acknowledgement. It has no retry or restoration entry point.
OtisCx317AppliedAck otis_cx317_active_actuator_apply_once(
    const OtisCx317ActionableRequest *request,
    const OtisCx317AcceptedRequest *accepted, uint16_t application_sequence,
    uint32_t now_s);

#endif
