#ifndef OTIS_REGULATION_ACTUATOR_H
#define OTIS_REGULATION_ACTUATOR_H

#include <stdint.h>

#include "otis_regulation_transaction.h"

// The physical actuator owner is deliberately separate from estimation and
// authority. It accepts one already-consumed transaction and returns one
// immutable acknowledgement. It has no retry or restoration entry point.
OtisRegulationAppliedAck otis_regulation_actuator_apply_once(
    const OtisRegulationActionableRequest *request,
    const OtisRegulationAcceptedRequest *accepted, uint16_t application_sequence,
    uint32_t now_s);

#endif
