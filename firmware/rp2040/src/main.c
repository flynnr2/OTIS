#include "otis_protocol.h"
#include "otis_records.h"

#include "pico/stdlib.h"

int main(void) {
    stdio_init_all();
    sleep_ms(1500);

    otis_emit_csv_headers();
    otis_emit_health(1u, 1600000000ull, OTIS_DOMAIN_RP2040_TIMER0,
                     "system", "boot", "true", OTIS_SEVERITY_INFO,
                     OTIS_FLAG_PROFILE_ASSUMPTION);
    otis_emit_raw_event(OTIS_RECORD_EVT, 1000u, OTIS_CHANNEL_GENERIC_EVENT,
                        OTIS_EDGE_RISING, 1600001234ull,
                        OTIS_DOMAIN_RP2040_TIMER0, OTIS_FLAG_NONE);
    otis_emit_raw_event(OTIS_RECORD_EVT, 1001u, OTIS_CHANNEL_GENERIC_EVENT,
                        OTIS_EDGE_FALLING, 1600001872ull,
                        OTIS_DOMAIN_RP2040_TIMER0, OTIS_FLAG_NONE);
    otis_emit_raw_event(OTIS_RECORD_REF, 1002u, OTIS_CHANNEL_PPS_REFERENCE,
                        OTIS_EDGE_RISING, 1616000000ull,
                        OTIS_DOMAIN_RP2040_TIMER0, OTIS_FLAG_NONE);
    otis_emit_count_observation(1u, OTIS_CHANNEL_OSC_OBSERVATION,
                                1600000000ull, 1616000000ull,
                                OTIS_DOMAIN_RP2040_TIMER0, 16000000ull,
                                OTIS_EDGE_RISING, OTIS_DOMAIN_H0_TCXO_16MHZ,
                                OTIS_FLAG_NONE);

    while (true) {
        tight_loop_contents();
    }
}
