cmake_minimum_required(VERSION 3.13)

include(pico_sdk_import.cmake)

project(otis_rp2040 C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(otis_rp2040
    src/main.c
    src/otis_emit.c
    src/capture_core.c
    src/transport_core.c
    src/health.c
)

target_include_directories(otis_rp2040 PRIVATE src)
target_link_libraries(otis_rp2040 pico_stdlib)

pico_enable_stdio_usb(otis_rp2040 1)
pico_enable_stdio_uart(otis_rp2040 0)
pico_add_extra_outputs(otis_rp2040)
