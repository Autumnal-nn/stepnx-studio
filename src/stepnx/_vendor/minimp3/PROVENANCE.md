# minimp3 provenance

- Upstream: https://github.com/lieff/minimp3
- Commit: `ea99364f61c14656440e8d77e9c233ccf3124633`
- File: `minimp3.h`, copied without modification.
- SHA-256: `57e437c5c1f0e8b243885d3929c8973b5e6c778451e0100ab4251d19915cb3ad`
- License: CC0-1.0; the complete upstream dedication and public-license fallback
  are preserved in `LICENSE`. This permissive dependency does not impose a
  copyleft condition on StepNX's Apache-2.0 bridge.
- Reviewed for this integration on 2026-09-08.

StepNX uses the frame API, not the optional file/gapless API. It enables
`MINIMP3_ONLY_MP3` and `MINIMP3_NO_SIMD`, disables floating-point contraction and
fast-math, and serializes stereo PCM explicitly as signed 16-bit little-endian.
No resampling, metadata-frame removal, or gapless trimming is performed.

The dependency must be re-reviewed and the PCM golden checks rerun before
updating it. Neither libmad nor game code/assets are linked or distributed.
