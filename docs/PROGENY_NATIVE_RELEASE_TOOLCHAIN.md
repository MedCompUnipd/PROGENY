# Native release compiler profile (candidate for full E2E certification)

Frozen scientific source commit: `e5abd2590c6fb43f105922309977cda61a8445b1`.
The independent DP build/stress matrices validated GCC 14.4.0 (Pixi), C++20,
OpenMP and cross-profile scientific equivalence on the tested cases.

The installation path **does not** consume binaries, caches, manifests, or
execution status from historical runs or CAFA5. A clean Linux x86-64 clone
must install Pixi from the pinned lockfile and build the native programs.

Candidate release configuration (opt-in using `PROGENY_NATIVE_RELEASE=ON`):

- GNU C++ 14.4.0 from the locked Pixi environment.
- CMake Release (`-O3 -DNDEBUG`) for ordinary native tools.
- Bounded affine DP V2: `-O3`.
- Rolling memory DP V1: `-O2` **after** the standard Release flags.
- C++20, OpenMP; no LTO, `-march=native`, `-Ofast`, or `-ffast-math`.

The profile is deliberately OFF for legacy or frozen builds. Source-level
algorithm and data-contract files are unchanged. Use the new build script,
`scripts/installation/build_progeny_native_release.sh`, in a clean clone.
It refuses to reuse an existing build tree. It checks version and compiler,
then creates a new `.pixi/build/progeny-native-release-gcc14.4` directory.

This build is **not** a full scientific certification. An independent clean
clone must subsequently pass native differential tests and a full synthetic
fresh pipeline, interrupted-run/resume, and final verification. Default flags
are candidates for release installation pending those end-to-end checks.
