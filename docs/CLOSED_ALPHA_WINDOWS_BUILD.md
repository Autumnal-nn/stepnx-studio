# Windows standalone build

This procedure builds the current StepNX Studio Windows package with the repository's strict test gate and canonical PyInstaller spec.

## Requirements

- Windows 10 or Windows 11, 64-bit;
- Python 3.11 or newer available through the `py` launcher;
- Git;
- internet access for the first dependency installation (`PySide6` and `PyInstaller`).

The project pins the GUI/build families to `PySide6>=6.7,<7` and `PyInstaller>=6.11,<7` through `pyproject.toml`.

## 1. Get the release source

From Command Prompt or PowerShell:

```powershell
git clone https://github.com/Autumnal-nn/stepnx-studio.git
cd stepnx-studio
git switch main
git pull --ff-only
```

Record the exact source commit before building:

```powershell
git rev-parse HEAD
```

The build should be produced from a clean checkout:

```powershell
git status --short
```

The command should print nothing.

## 2. Recommended isolated environment

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

Build with:

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_windows_package.ps1 -Python python
```

Without a virtual environment:

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_windows_package.ps1
```

The script:

1. installs `.[gui,build]` unless `-SkipInstall` is supplied;
2. runs `tools/run_windows_test_gate.py` unless `-SkipTests` is supplied;
3. invokes PyInstaller with `packaging/stepnx-studio.spec`;
4. validates the executable, creates the ZIP, and prints its SHA-256.

For a release build, **do not use `-SkipTests`**.

## 3. Strict Windows gate

The build script runs this automatically. To run it separately:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python tools\run_windows_test_gate.py
```

The gate rejects failing tests, an unexpectedly low discovered-test count, and unexpected skips.

## 4. Output

A successful build produces:

```text
dist\StepNX-Studio-Windows\
    StepNX-Studio.exe
    ...bundled runtime files...

dist\StepNX-Studio-Windows.zip
```

The distribution is intentionally one-folder. Distribute the entire folder or the generated ZIP; do not copy only the executable out of its runtime directory.

## 5. Public release profile set

The standard release executable exposes the public engine-family profiles:

- NXA;
- Fiesta;
- Prime+.

Experimental or private capability gates are not part of the public release procedure.

## 6. Manual smoke test before distributing

Run the packaged executable, not the editable Python checkout. At minimum verify:

1. the standard executable exposes the expected public profiles;
2. representative NXA, Fiesta-family, and Prime+-family folders/files open correctly;
3. Header, Split, and Division metadata remain inspectable and unknown/raw entries remain preserved;
4. a disposable edit can be saved, reopened, and round-tripped as expected;
5. waveform/playback works with WAV, MP3, and a real uppercase `.AUD` song through both audio-picker paths;
6. staged `.AUD` playback uses the generic ENC1/ENC2 decoder path;
7. after the `.AUD` waveform is ready, switching audio or closing the app leaves no persistent `stepnx-audio-*` temporary directory;
8. one NX10/legacy import and one Save All workflow succeed;
9. persisted local rendering preferences survive restart without altering chart data.

Do not perform release smoke tests on irreplaceable corpus files. Use disposable copies.

## 7. Release naming

The 0.9.1 Windows artifact is published as:

```text
StepNX-Studio-0.9.1-Windows-x86_64.zip
```

Record its SHA-256 together with the source commit used for the release.
