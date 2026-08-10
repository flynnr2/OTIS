#ifndef OTIS_PPS_COUNT_BOUNDARY_RING_H
#define OTIS_PPS_COUNT_BOUNDARY_RING_H

#include <stdint.h>

#include "otis_pps_count_boundary.h"

void otis_pps_count_boundary_ring_reset(void);
bool otis_pps_count_boundary_ring_push_from_isr(
    const OtisPpsCountBoundaryObservation &observation);
bool otis_pps_count_boundary_ring_pop(
    OtisPpsCountBoundaryObservation *observation);
bool otis_pps_count_boundary_ring_peek(
    OtisPpsCountBoundaryObservation *observation);
uint32_t otis_pps_count_boundary_ring_dropped_count(void);
uint8_t otis_pps_count_boundary_ring_depth(void);
uint8_t otis_pps_count_boundary_ring_capacity(void);

#endif
