#ifndef OTIS_SPSC_QUEUE_H
#define OTIS_SPSC_QUEUE_H

#include <stddef.h>
#include <stdint.h>
#include <type_traits>

// Fixed-capacity, allocation-free single-producer/single-consumer queue.
//
// The producer owns tail and the consumer owns head.  Release/acquire ordering
// makes the by-value message immutable to the consumer once published.  This
// deliberately does not expose a reference to queue storage: estimator and
// controller state can therefore never be shared through this transport.
template <typename Message, size_t Capacity>
class OtisSpscQueue {
 public:
  static_assert(Capacity > 0u, "SPSC queue capacity must be non-zero");
  static_assert(std::is_trivially_copyable<Message>::value,
                "cross-core messages must be trivially copyable values");

  OtisSpscQueue() : head_(0u), tail_(0u), high_water_(0u),
                    producer_slot_(0u), consumer_slot_(0u) {}

  void reset() {
    __atomic_store_n(&head_, 0u, __ATOMIC_RELAXED);
    __atomic_store_n(&tail_, 0u, __ATOMIC_RELAXED);
    __atomic_store_n(&high_water_, 0u, __ATOMIC_RELAXED);
    producer_slot_ = consumer_slot_ = 0u;
  }

  bool try_push(const Message &message) {
    return try_push_with_precommit(message, [](Message &) {});
  }

  // The bounded callback sees only the producer-owned, already copied slot.
  // It runs after successful capacity admission, immediately before release.
  // A clock sampled here precedes publication; it is not a publication latch.
  template <typename Precommit>
  bool try_push_with_precommit(const Message &message, Precommit precommit) {
    const uint32_t tail = __atomic_load_n(&tail_, __ATOMIC_RELAXED);
    const uint32_t head = __atomic_load_n(&head_, __ATOMIC_ACQUIRE);
    const uint32_t depth = tail - head;
    if (depth >= Capacity) return false;

    slots_[producer_slot_] = message;
    precommit(slots_[producer_slot_]);
    if (++producer_slot_ == Capacity) producer_slot_ = 0u;
    __atomic_store_n(&tail_, tail + 1u, __ATOMIC_RELEASE);
    update_high_water(depth + 1u);
    return true;
  }

  bool try_pop(Message *message) {
    if (message == nullptr) return false;
    const uint32_t head = __atomic_load_n(&head_, __ATOMIC_RELAXED);
    const uint32_t tail = __atomic_load_n(&tail_, __ATOMIC_ACQUIRE);
    if (head == tail) return false;

    *message = slots_[consumer_slot_];
    if (++consumer_slot_ == Capacity) consumer_slot_ = 0u;
    __atomic_store_n(&head_, head + 1u, __ATOMIC_RELEASE);
    return true;
  }

  uint32_t depth() const {
    const uint32_t tail = __atomic_load_n(&tail_, __ATOMIC_ACQUIRE);
    const uint32_t head = __atomic_load_n(&head_, __ATOMIC_ACQUIRE);
    return tail - head;
  }

  uint32_t high_water() const {
    return __atomic_load_n(&high_water_, __ATOMIC_ACQUIRE);
  }

  static constexpr size_t capacity() { return Capacity; }

 private:
  void update_high_water(uint32_t candidate) {
    uint32_t observed = __atomic_load_n(&high_water_, __ATOMIC_RELAXED);
    while (candidate > observed &&
           !__atomic_compare_exchange_n(&high_water_, &observed, candidate,
                                        false, __ATOMIC_RELAXED,
                                        __ATOMIC_RELAXED)) {
    }
  }

  Message slots_[Capacity];
  alignas(4) uint32_t head_;
  alignas(4) uint32_t tail_;
  alignas(4) uint32_t high_water_;
  // These positions have one owner each. Published counters wrap modulo2^32
  // for depth arithmetic; that wrap is not a slot wrap when Capacity is not
  // a power of two. Deriving a slot from counter % Capacity would then reuse
  // occupied storage and lose unread evidence.
  uint32_t producer_slot_;
  uint32_t consumer_slot_;
};

#endif
