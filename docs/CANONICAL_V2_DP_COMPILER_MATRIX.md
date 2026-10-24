# Canonical V2 native DP toolchain matrix (portable build gate)

This procedure builds the **frozen scientific sources** from a new checkout;
it does not consume CAFA5 outputs or require the old production checkout.
Only build tools and read-only contract inputs are used.

The runner `scripts/validation/canonical_v2_dp_toolchain_matrix.sh` accepts a
repository, a fresh build-root parent under that repository's `.pixi/build`,
and an external report directory. It creates entirely new build directories.

* `gcc12-o2`: reference comparison with the system GNU C++ compiler at
  `/usr/bin/g++`, **when available**. This profile is specific to the
  comparison server, not a required installation dependency.
* `gcc14-o2`: same Pixi toolchain at a more conservative optimization
  setting; compiles only the three DP test targets.
* `gcc14-o3`: candidate release build with the GNU C++ compiler explicitly
  selected from the independent Pixi environment. The installed compiler is
  discovered from its actual prefix rather than an assumed version number.
* Both use the frozen `cpp/CMakeLists.txt`, C++20, CMake, Ninja and OpenMP.
  Each CMake cache is new, and each compiler and its loaded `libgomp` are
  recorded. `-march=native` and `-ffast-math` are **not** used.
* The candidate compiles eleven required native tools and the additional
  full-DP reference executable **for tests only**. The GCC12 profile builds
  the bounded, rolling and full-DP reference trio.
* The frozen `tests/test_canonical_v2_linear_dp.py` differential tests are
  executed on the **new** binaries, with their compilation fixture overridden.
  The stage also compares hashes of deterministic output and metrics between
  toolchain profiles and runs a moderate pair for rudimentary timing.

The matrix is not a comprehensive performance optimization search. It is
an initial **correctness and portability gate**. Do not select a new default
optimizer merely from its timing. A clean clone outside thanos and integrated
fresh E2E plus interruption/resume tests remain separate gates.

Temporary results are retained for forensic analysis. Never copy newly built
executables into an existing CAFA5 run or `.pixi/build` of the production
checkout. Run roots must not reference compiler test binaries unless a new,
independent recipe intentionally selects and fingerprints them.

The `gcc12` comparison profile is optional on another server. The documented
release target is the Pixi toolchain, not dependence on Debian GCC 12.
