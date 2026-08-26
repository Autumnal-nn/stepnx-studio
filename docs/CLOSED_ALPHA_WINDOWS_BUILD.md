# Closed-alpha Windows standalone build

This procedure builds the current StepNX Studio closed-alpha package locally on Windows. It intentionally uses the repository's strict Windows gate and canonical PyInstaller spec rather than an ad-hoc command.

## Requirements

- Windows 10 or Windows 11, 64-bit;
- Python 3.11 or newer available through the `py` launcher;
- Git;
- internet access for the first dependency installation (`PySide6` and `PyInstaller`).

The project pins the GUI/build families to `PySide6>=6.7,<7` and `PyInstaller>=6.11,<7` through `pyproject.toml`.

## 1. Get the exact merge-candidate branch

From Command Prompt or PowerShell:

```powershell
git clone https://github.com/Autumnal-nn/stepnx-studio.git
cd stepnx-studio
git switch phase11
git pull --ff-only
```

For a reproducible closed-alpha build, record the commit before building:

```powershell
git rev-parse HEAD
```

The build should be produced from a clean checkout:

```powershell
git status --short
```

The command should print nothing.

## 2. Recommended isolated environment

The build script can install into the active Python environment directly, but a local virtual environment keeps the closed-alpha toolchain isolated:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

If PowerShell blocks activation for the current process:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

After activation, use `python` as the script's Python command:

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_windows_package.ps1 -Python python
```

Without a virtual environment, the equivalent canonical build is:

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_windows_package.ps1
```

The script performs all three release operations in order:

1. installs `.[gui,build]` unless `-SkipInstall` is supplied;
2. runs `tools/run_windows_test_gate.py` unless `-SkipTests` is supplied;
3. invokes PyInstaller with `packaging/stepnx-studio.spec`, validates the executable, creates the ZIP, and prints its SHA-256.

For a release candidate, **do not use `-SkipTests`**.

## 3. Strict Windows gate

The build script runs this automatically. To run it separately while diagnosing a failure:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python tools\run_windows_test_gate.py
```

The gate rejects:

- any failing test;
- fewer than the repository's minimum expected test count;
- unexpected skipped tests.

A plain green `python -m unittest` is not sufficient for the merge/release gate because Qt tests could otherwise be skipped silently.

## 4. Output

A successful build produces:

```text
dist\StepNX-Studio-Windows\
    StepNX-Studio.exe
    ...bundled runtime files...

dist\StepNX-Studio-Windows.zip
```

The distribution is intentionally **one-folder**, not a single-file PyInstaller executable. Distribute the entire `StepNX-Studio-Windows` folder or the generated ZIP; do not copy only the `.exe` out of that directory.

The build script prints the SHA-256 for:

```text
dist\StepNX-Studio-Windows.zip
```

Record that hash together with the source commit SHA for each closed-alpha drop.

## 5. Standard and patched closed-alpha executables

The ordinary build exposes these profiles:

- NXA;
- Fiesta 2;
- Prime 2.

The Step5-patched NXA profile is deliberately hidden behind the executable-name gate. To create the patched tester entry without rebuilding, copy the executable **inside the same distribution directory**:

```powershell
Copy-Item `
  .\dist\StepNX-Studio-Windows\StepNX-Studio.exe `
  .\dist\StepNX-Studio-Windows\"StepMX Studio.exe"
```

Launch:

```powershell
.\dist\StepNX-Studio-Windows\"StepMX Studio.exe"
```

The name must be exactly `StepMX Studio.exe`. Under that executable identity, `NXA-patched` replaces native NXA in the profile selector; Fiesta 2 and Prime 2 remain available.

If both launchers should be included in the closed-alpha ZIP, create the copy before making the final tester archive, then recompute the SHA-256 of that final archive. The canonical build script's ZIP contains only the standard launcher unless the script itself is changed later.

## 6. Manual smoke test before distributing

Run the packaged executable, not the editable Python checkout. At minimum verify:

1. standard `StepNX-Studio.exe` shows NXA, Fiesta 2, and Prime 2 and does not expose `NXA-patched`;
2. `StepMX Studio.exe` shows `NXA-patched`, Fiesta 2, and Prime 2;
3. open representative NXA, Fiesta 2, and Prime 2 folders/files;
4. inspect Header, Split, and Division metadata and confirm unknown/raw entries remain visible but disabled;
5. inspect a later-generation composite Header ID and confirm its field label includes the historical language slot while the full numeric ID is retained;
6. edit a disposable copy, save it, reopen it, and confirm expected round-trip behavior;
7. exercise waveform/playback with WAV, MP3, and a real uppercase `.AUD` song. Confirm `.AUD` appears in both the manual `Select audio…` picker and the `Song audio not found` prompt path without switching to `All files`, then confirm the staged AUD playback/waveform path works. The transport calls the generic ENC1/ENC2 decoder directly; NXA song coverage is primarily ENC2, but the packaged path must not depend on the legacy ENC2-only alias;
8. exercise one NX10/legacy import and one Save All workflow;
9. close/reopen the app to verify persisted local rendering preferences do not alter chart data.

Do not perform release smoke tests on irreplaceable corpus files. Use disposable copies.

## 7. Suggested closed-alpha naming

Keep the source/application version untouched until a formal release-version decision. Name the external tester artifact using the date and short commit SHA, for example:

```powershell
$sha = (git rev-parse --short=8 HEAD)
$stamp = Get-Date -Format "yyyyMMdd"
$alpha = "StepNX-Studio-ClosedAlpha-$stamp-$sha.zip"
Compress-Archive -Path .\dist\StepNX-Studio-Windows\* -DestinationPath $alpha -Force
Get-FileHash $alpha -Algorithm SHA256
```

This avoids pretending the pre-alpha package is a stable semantic version while still making every tester build traceable to an exact source state.

## 8. Merge sequence after closed-alpha validation

After the strict gate and smoke test succeed:

1. confirm `git status --short` is clean;
2. confirm the tested commit is still the head of `phase11` and Draft PR #8;
3. record the tested commit SHA and package SHA-256 in the PR or release notes;
4. mark PR #8 ready for review;
5. review the final diff;
6. merge only as a separate explicit action.

Building the closed alpha does not itself merge Phase 11.
