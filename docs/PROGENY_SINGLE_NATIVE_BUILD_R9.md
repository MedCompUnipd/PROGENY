# PROGENY — single native build location (R9)

The canonical Linux x86-64 native compiler profile is GCC 14.4.0, from the
locked Pixi environment. **All 13 CMake native tools** share one build tree:

```text
.pixi/build/progeny-native-release-gcc14.4/
```

The `pixi run build-*` tasks use a serialized incremental builder that validates
CMake's Release cache, compiler and profile. It never creates `progeny-*` build
subdirectories. The `pixi run <native-tool>` tasks execute their respective
physical binaries from the same directory. The scientific CLI executable names
remain `progeny-*` until the separately certified package rename.

A virgin installation must first complete the pinned Pixi installation and
`scripts/installation/build_progeny_native_release.sh`. This builds all 13
programs before the canonical fresh Snakemake DAG is parsed. The fresh DAG
imports upstream producer rules and **does not import every native build
rule**. As a result, an independent fresh run cannot rely on Snakemake alone
to bootstrap its native executables.

The serialized builder is for incremental development and legacy Snakemake
build targets. The clean installer deliberately rejects an existing tree;
run it only in a fresh isolated checkout. Neither script should be used in
frozen CAFA5 production.

The path changes are operational, not a change to GO donor policies, sequence
matching, DP, biological inputs or temporal classification. New path and code
fingerprints require new fresh runs. Do not resume existing publications
under a modified source tree without the normal provenance validation.

`R9_NATIVE_DIRECTORY=PASS` means only that the build directory and DAG paths
are coherent; complete scientific certification still requires cold E2E,
verified publications, serial/parallel parity and resume testing.
