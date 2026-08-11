#include "otis_memory_budget.h"

#include <Arduino.h>
#include <RP2040Support.h>
#include <pico/platform.h>
#include <stdint.h>

#include "otis_config.h"
#include "otis_protocol.h"

namespace {

struct OtisMemoryBudgetState {
  volatile uint32_t minimum_free_stack_bytes[2];
  volatile bool core_observed[2];
  uint32_t minimum_free_heap_bytes;
  bool heap_observed;
};

OtisMemoryBudgetState memory_budget = {{0xffffffffu, 0xffffffffu},
                                       {false, false}, 0xffffffffu, false};

void emit_u32(OtisStatusEmitContext *context, const char *key,
              uint32_t value, const char *severity, uint32_t flags) {
  otis_status_emit_u32(context, "memory_budget", key, value, severity, flags);
}

void emit_bool(OtisStatusEmitContext *context, const char *key, bool value,
               const char *severity, uint32_t flags) {
  otis_status_emit(context, "memory_budget", key,
                   value ? "true" : "false", severity, flags);
}

}  // namespace

void otis_memory_budget_note_current_core(void) {
  const uint32_t core = get_core_num();
  if (core > 1u) return;
  const int free_stack = rp2040.getFreeStack();
  if (free_stack >= 0) {
    const uint32_t observed = static_cast<uint32_t>(free_stack);
    const uint32_t previous =
        __atomic_load_n(&memory_budget.minimum_free_stack_bytes[core],
                        __ATOMIC_RELAXED);
    if (observed < previous) {
      __atomic_store_n(&memory_budget.minimum_free_stack_bytes[core], observed,
                       __ATOMIC_RELAXED);
    }
    __atomic_store_n(&memory_budget.core_observed[core], true,
                     __ATOMIC_RELEASE);
  }
  if (core == 0u) {
    const int free_heap = rp2040.getFreeHeap();
    if (free_heap >= 0) {
      const uint32_t observed = static_cast<uint32_t>(free_heap);
      if (!memory_budget.heap_observed ||
          observed < memory_budget.minimum_free_heap_bytes) {
        memory_budget.minimum_free_heap_bytes = observed;
      }
      memory_budget.heap_observed = true;
    }
  }
}

void otis_memory_budget_emit_status(OtisStatusEmitContext *status_context) {
  if (status_context == nullptr) return;
  otis_memory_budget_note_current_core();
  const bool core0_observed =
      __atomic_load_n(&memory_budget.core_observed[0], __ATOMIC_ACQUIRE);
  const bool core1_observed =
      __atomic_load_n(&memory_budget.core_observed[1], __ATOMIC_ACQUIRE);
  const uint32_t core0_free = __atomic_load_n(
      &memory_budget.minimum_free_stack_bytes[0], __ATOMIC_RELAXED);
  const uint32_t core1_free = __atomic_load_n(
      &memory_budget.minimum_free_stack_bytes[1], __ATOMIC_RELAXED);
  const bool core0_ok =
      core0_observed && core0_free >= OTIS_MINIMUM_FREE_STACK_BYTES;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  const bool core1_required = true;
#else
  const bool core1_required = false;
#endif
  const bool core1_ok =
      !core1_required ||
      (core1_observed && core1_free >= OTIS_MINIMUM_FREE_STACK_BYTES);
  const bool heap_ok = memory_budget.heap_observed &&
                       memory_budget.minimum_free_heap_bytes >=
                           OTIS_MINIMUM_FREE_HEAP_BYTES;
  const bool valid = core0_ok && core1_ok && heap_ok;
  const char *severity = valid ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR;
  const uint32_t flags = valid ? OTIS_FLAG_PROFILE_ASSUMPTION
                               : OTIS_FLAG_SOURCE_HEALTH_SUSPECT;

  emit_bool(status_context, "valid", valid, severity, flags);
  emit_u32(status_context, "minimum_free_stack_budget_bytes",
           OTIS_MINIMUM_FREE_STACK_BYTES, OTIS_SEVERITY_INFO,
           OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_u32(status_context, "minimum_free_heap_budget_bytes",
           OTIS_MINIMUM_FREE_HEAP_BYTES, OTIS_SEVERITY_INFO,
           OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_bool(status_context, "core0_observed", core0_observed,
            core0_observed ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
            core0_observed ? OTIS_FLAG_NONE
                           : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  if (core0_observed) {
    emit_u32(status_context, "core0_minimum_free_stack_bytes", core0_free,
             core0_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
             core0_ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  }
  emit_bool(status_context, "core1_required", core1_required,
            OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_bool(status_context, "core1_observed", core1_observed,
            core1_required && !core1_observed ? OTIS_SEVERITY_ERROR
                                              : OTIS_SEVERITY_INFO,
            core1_required && !core1_observed
                ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                : OTIS_FLAG_NONE);
  if (core1_observed) {
    emit_u32(status_context, "core1_minimum_free_stack_bytes", core1_free,
             core1_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
             core1_ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  }
  emit_u32(status_context, "minimum_free_heap_bytes",
           memory_budget.minimum_free_heap_bytes,
           heap_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
           heap_ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  otis_status_emit(status_context, "memory_budget", "measurement_scope",
                   "live_observed_minimum_approximation",
                   OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
}
