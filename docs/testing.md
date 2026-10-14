# Testing

All scene tests operate on copies. Never point an output path at a production rig.

## Unit tests

From the repository root with Python 3.10+ and pytest:

```powershell
python -m pytest tests/unit -q -p no:cacheprovider
```

## Maya integration tests

Set the supplied AS rig path and make the package plus pytest visible to Maya's Python:

```powershell
$env:PYTHONPATH="$PWD\src;C:\path\to\pytest\site-packages"
$env:ASMB_AS_RIG="C:\path\to\Belato01_rig_v01_w01.mb"
$env:ASMB_STUDIO_RIG="C:\path\to\TeamExtra01_rig_v01.mb"
$env:QT_QPA_PLATFORM="offscreen"
python tests/maya/run_test_suite.py `
  --mayapy "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe"
```

The runner intentionally starts a fresh Maya process for each test file. Maya standalone and
third-party plug-ins can crash during repeated initialize/uninitialize cycles when the complete
suite shares one process. The tests open the supplied files read-only, create temporary scenes,
and never save over the inputs.

## Supplied-rig acceptance

```powershell
$env:PYTHONPATH="$PWD\src"
& "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" tests/maya/run_acceptance.py `
  --as-rig "C:\path\to\Belato01_rig_v01_w01.mb" `
  --studio-rig "C:\path\to\TeamExtra01_rig_v01.mb" `
  --output "$PWD\outputs\acceptance"
```

The ignored output directory receives:

- `acceptance.json` with pass/fail status, validation metrics, and source hashes;
- an animated copy of the studio rig used as source;
- an AS work-mode bake result for manual playback review.

Acceptance passes only when both workflow scenarios validate and SHA-256 hashes prove both supplied source files are unchanged. Missing renderer or grooming plugins may print Maya load warnings; those warnings are not treated as body-retarget failures.
