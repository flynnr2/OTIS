#ifndef OTIS_PHASE_PREVIEW_TRANSPORT_H
#define OTIS_PHASE_PREVIEW_TRANSPORT_H

// Core 0 only. This is the sole formatter/serial surface for RPH, PHE, and
// HPR preview records.
void otis_phase_preview_transport_emit_headers(void);
bool otis_phase_preview_transport_busy(void);
bool otis_phase_preview_transport_frame_active(void);
bool otis_phase_preview_transport_abandon_active_frame(void);
void otis_phase_preview_transport_service(void);

#endif
