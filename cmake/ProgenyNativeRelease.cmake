# Opt-in, distribution-specific compiler profile. No effect on frozen builds.
option(PROGENY_NATIVE_RELEASE "Use the validated PROGENY native release profile" OFF)

if(PROGENY_NATIVE_RELEASE)
    if(NOT CMAKE_BUILD_TYPE STREQUAL "Release")
        message(FATAL_ERROR "PROGENY_NATIVE_RELEASE requires Release")
    endif()
    if(NOT CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
        message(FATAL_ERROR "PROGENY_NATIVE_RELEASE requires GNU C++")
    endif()
    if(NOT CMAKE_CXX_COMPILER_VERSION VERSION_EQUAL "14.4.0")
        message(FATAL_ERROR "PROGENY_NATIVE_RELEASE requires GCC 14.4.0")
    endif()
    if(NOT OpenMP_CXX_FOUND)
        message(FATAL_ERROR "PROGENY_NATIVE_RELEASE requires OpenMP CXX")
    endif()
    # Target options come after CMAKE_CXX_FLAGS_RELEASE, so -O2 wins.
    # Do not use CPU-specific flags, fast-math or unvalidated LTO here.
    target_compile_options(
        progeny-directional-glocal-bounded-dp-v2 PRIVATE -O3
    )
    target_compile_options(
        progeny-directional-glocal-linear-dp-v1 PRIVATE -O2
    )
    message(STATUS "PROGENY release: GCC 14.4, bounded -O3, rolling -O2")
endif()
