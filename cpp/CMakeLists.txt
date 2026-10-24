cmake_minimum_required(VERSION 3.20)

project(progeny_native_tools LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(ZLIB REQUIRED)
find_package(OpenMP REQUIRED)

add_executable(
    progeny-release-fasta-v2
    src/progeny_release_fasta_v2.cpp
)
target_link_libraries(
    progeny-release-fasta-v2
    PRIVATE ZLIB::ZLIB
)

add_executable(
    progeny-goa-normalize-v1
    src/progeny_goa_normalize_v1.cpp
)

add_executable(
    progeny-go-positive-filter-v1
    src/progeny_go_positive_filter_v1.cpp
)

add_executable(
    progeny-raw-ox-extract-v1
    src/progeny_raw_ox_extract_v1.cpp
)

add_executable(
    progeny-primary-candidate-scan-v1
    src/progeny_primary_candidate_scan_v1.cpp
)

add_executable(
    progeny-primary-candidate-scan-v2
    src/progeny_primary_candidate_scan_v2.cpp
)

add_executable(
    progeny-direct-accession-anchors-v1
    src/progeny_direct_accession_anchors_v1.cpp
)

add_executable(
    progeny-onehop-lineage-scan-v1
    src/progeny_onehop_lineage_scan_v1.cpp
)

add_executable(
    progeny-candidate-sequence-extract-v1
    src/progeny_candidate_sequence_extract_v1.cpp
)

add_executable(
    progeny-directional-glocal-full-dp-v1
    src/progeny_directional_glocal_full_dp_v1.cpp
)
target_link_libraries(
    progeny-directional-glocal-full-dp-v1
    PRIVATE OpenMP::OpenMP_CXX
)

add_executable(
    progeny-full-exact-cross-strain-v1
    src/progeny_full_exact_cross_strain_v1.cpp
)

# FIX1 canonical V2 certified bounded affine DP backend.
add_executable(
    progeny-directional-glocal-bounded-dp-v2
    src/progeny_directional_glocal_bounded_dp_v2.cpp
)
target_link_libraries(
    progeny-directional-glocal-bounded-dp-v2
    PRIVATE OpenMP::OpenMP_CXX
)

# Exact bounded-memory continuation; the frozen bounded TU is included verbatim.
add_executable(
    progeny-directional-glocal-linear-dp-v1
    src/progeny_directional_glocal_linear_dp_v1.cpp
)
target_link_libraries(
    progeny-directional-glocal-linear-dp-v1
    PRIVATE OpenMP::OpenMP_CXX
)

# Opt-in, distribution-only compiler profile; no impact on frozen runs.
include("${CMAKE_CURRENT_LIST_DIR}/../cmake/ProgenyNativeRelease.cmake")
