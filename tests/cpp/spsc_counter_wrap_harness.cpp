#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <type_traits>
#include "otis_firmware_host_contract.generated.h"

// Set a reachable pre-rollover state without billions of queue operations.
// No test-only mutator or alternative counter type enters the production API.
#define private public
#include "otis_spsc_queue.h"
#undef private

int main() {
  constexpr uint32_t capacity = OTIS_TELEMETRY_QUEUE_DEPTH;
  OtisSpscQueue<uint32_t, capacity> queue;
  const uint32_t origin = UINT32_MAX - 2u;
  queue.head_ = queue.tail_ = origin;
  queue.producer_slot_ = queue.consumer_slot_ = origin % capacity;
  for (uint32_t value = 0u; value < capacity; ++value)
    assert(queue.try_push(value));
  assert(queue.depth() == capacity && !queue.try_push(999u));
  for (uint32_t value = 0u; value < capacity; ++value) {
    uint32_t received = UINT32_MAX;
    assert(queue.try_pop(&received) && received == value);
    assert(queue.try_push(value + capacity));
  }
  for (uint32_t value = capacity; value < 2u * capacity; ++value) {
    uint32_t received = UINT32_MAX;
    assert(queue.try_pop(&received) && received == value);
  }
  uint32_t empty = 0u;
  assert(queue.depth() == 0u && !queue.try_pop(&empty));
  queue.reset();
  assert(queue.try_push(42u) && queue.try_pop(&empty) && empty == 42u);
  return 0;
}
