# StepNX Studio 0.9.1

StepNX Studio 0.9.1 is the first public pre-1.0 desktop release of the lossless NX20 authoring environment.

## Highlights

- byte-exact NX20/NFO parsing and no-edit round-trip preservation;
- practical visual authoring with stable undo/redo, Split/Block structure editing, timing tools, selection, bulk operations, waveform display, metronome, and gameplay preview;
- engine-family authoring profiles for NXA, Fiesta, and Prime+ with unknown metadata preserved rather than normalized or discarded;
- one-way NX10 plus STF/ST2, NOT/NOT5, STX, SEE, KSF, and UCS import workflows;
- folder-level NX management, Lightmap publication support, atomic Save All, recovery snapshots, and NX/NFO mirror tooling;
- generic Andamiro `.AUD` / `.A` playback staging with ENC1 and ENC2 support, including corpus-backed recovery of mastering-profile variants;
- case-safe uppercase `.AUD` selection on Linux and Windows;
- Linux metronome playback stabilized with a dedicated Qt audio sink and transport lookahead;
- Windows staged-AUD cleanup hardened so temporary `stepnx-audio-*` directories do not persist after source release.

## Audio validation

The supplied NXA audio corpus used during development completed the decoder audit at 843/843 files: 455 ENC1 and 388 ENC2. Proprietary corpus files are not distributed with StepNX Studio.

## Importer evidence

The NX10 importer was audited against the supplied official NX2 source domain and same-path NXA successor corpus. The observed source domain is treated as frozen evidence rather than generalized beyond demonstrated behavior.

## Known limitations

StepNX Studio remains pre-1.0. Some runtime-accurate simulator details, deeper fuzzing/hardening work, accessibility/localization polish, and unresolved raw metadata fields remain on the roadmap. Unknown or unproven fields stay lossless and non-authorable instead of receiving guessed semantics.

## Downloads

- `StepNX-Studio-0.9.1-Windows-x86_64.zip`: ready-to-run Windows x86_64 one-folder bundle.
- `StepNX-Studio-0.9.1-Linux-x86_64.AppImage`: Linux x86_64 AppImage.
- `StepNX-Studio-0.9.1-Linux-x86_64.tar.gz`: unpacked-bundle fallback for Linux x86_64.
- `SHA256SUMS.txt`: SHA-256 checksums for the release artifacts.

StepNX Studio is unofficial and is not affiliated with Andamiro. Official game assets are not distributed by this project.
