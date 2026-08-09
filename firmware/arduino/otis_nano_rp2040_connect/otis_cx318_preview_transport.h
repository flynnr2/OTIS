#ifndef OTIS_CX318_PREVIEW_TRANSPORT_H
#define OTIS_CX318_PREVIEW_TRANSPORT_H

// Core 0 only. This is the sole formatter/serial surface for Stage 4 RPH,
// PHE, and HPR records.
void otis_cx318_preview_transport_emit_headers(void);
bool otis_cx318_preview_transport_busy(void);
void otis_cx318_preview_transport_service(void);

#endif
