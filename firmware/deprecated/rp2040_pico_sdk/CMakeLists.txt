cmake_minimum_required(VERSION 3.13)

include(pico_sdk_import.cmake)

project(otis_rp2040 C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

option(OTIS_ENABLE_RP2040_BOOT_DIAG "Emit one RP2040 boot diagnostics record at startup" OFF)

pico_sdk_init()

add_executable(otis_rp2040
    src/main.c
    src/otis_boot_diag.c
    src/otis_emit.c
    src/capture_core.c
    src/transport_core.c
    src/health.c
)

target_include_directories(otis_rp2040 PRIVATE src)
target_link_libraries(otis_rp2040 pico_stdlib)
target_compile_definitions(otis_rp2040 PRIVATE
    OTIS_ENABLE_RP2040_BOOT_DIAG=$<BOOL:${OTIS_ENABLE_RP2040_BOOT_DIAG}>
)

pico_enable_stdio_usb(otis_rp2040 1)
pico_enable_stdio_uart(otis_rp2040 0)
pico_add_extra_outputs(otis_rp2040)
