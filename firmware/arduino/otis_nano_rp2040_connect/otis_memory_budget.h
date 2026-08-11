#ifndef OTIS_MEMORY_BUDGET_H
#define OTIS_MEMORY_BUDGET_H

#include "otis_status_emit.h"

// Record an approximate live margin for the calling core. Each core owns its
// own slot; reporting occurs on the service/serial owner only.
void otis_memory_budget_note_current_core(void);
void otis_memory_budget_emit_status(OtisStatusEmitContext *status_context);

#endif
