# This is a deliberately small placeholder. For a real build, copy the
# canonical pico_sdk_import.cmake from the installed Raspberry Pi Pico SDK
# or point CMake at a system-provided one before configuring this directory.

if (NOT DEFINED PICO_SDK_PATH)
    message(FATAL_ERROR "Set PICO_SDK_PATH or replace pico_sdk_import.cmake with the Pico SDK import helper")
endif()

include(${PICO_SDK_PATH}/external/pico_sdk_import.cmake)
