# StepNX Studio 0.9.2a

## 0.9.2 hotfix

- FIX: Very short long notes now follow the native draw order instead of collapsing at an overly large screen-space threshold. Tails remain visible as soon as they extend beyond the head, while fully overlapping terminals still read as a normal arrow.
- FIX: Long-note shafts remain suppressed while the terminals overlap, preventing the body from showing through transparent areas of the head artwork.
- FIX: Header 1100 now supports the same high-word localization / language variant addressing used by Header 1103.
- FIX: Header 20 is now exposed correctly in the Prime profile with the same later-generation `.V` resource semantics used by Fiesta. The distinct NXA Header 20 behavior is unchanged.
