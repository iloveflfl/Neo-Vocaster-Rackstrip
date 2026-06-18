# Neo Vocaster RackStrip

A slim vertical control strip for **Focusrite Vocaster Hub / Vocaster Two**.

Neo Vocaster RackStrip keeps the original Vocaster Hub running in the background as the real device-control backend, then provides a cleaner side-monitor-friendly rack panel UI on top of it.

It was built for a workflow where the app stays docked to the left edge of a secondary monitor.

> Not affiliated with Focusrite. Focusrite, Vocaster, and related names are trademarks of their respective owners.

---

## What it does

- Uses the installed **Vocaster Hub** as a hidden backend.
- Controls Vocaster Hub through Windows UI Automation.
- Provides a narrow rack-style UI for a side monitor.
- Adds smart remap toggles:
  - **Host mic knob → AUX level**
  - **Guest mic knob → Bluetooth level**
- Uses gamma mapping for smoother visual fader behavior.
- Supports a custom EXE icon and running taskbar/window icon.
- Builds into a portable one-file EXE.

---

## Current supported controls

The app relies on the UIA control order exposed by the current Vocaster Hub UI:

| Index | Control |
|---:|---|
| 0 | Host mic level |
| 1 | Guest mic level |
| 4 | AUX level |
| 5 | Bluetooth level |

The original Hub also exposes other mix controls, but this RackStrip UI intentionally keeps only the controls that make sense in a narrow vertical panel.

---

## Requirements

- Windows 10/11
- Focusrite Vocaster Hub installed
- Focusrite Vocaster driver installed
- Vocaster Two connected
- Python 3.10+ for development/building
- GitHub CLI only if you want to use the included publishing script

The final built EXE does **not** include Focusrite software or drivers. The target PC must already have Vocaster Hub and the Focusrite driver installed.

---

## Quick run from source

Open PowerShell in this folder:

```powershell
.\run_rackstrip.bat
```

The batch file installs Python requirements and runs:

```powershell
py neo_vocaster_rackstrip.py
```

---

## Build portable EXE

Open PowerShell in this folder:

```powershell
.\build_exe.bat
```

Build output:

```text
dist\NeoVocasterRackStrip_v8.exe
```

This is a one-file portable EXE. You can copy that EXE by itself to another PC, but that PC still needs the official Focusrite Vocaster Hub/driver installed.

---


## Notes

This project does not patch, modify, or redistribute the original Vocaster Hub. It simply automates the installed local Vocaster Hub UI.

Headphone side knobs on the Vocaster Two do not appear to be exposed as normal UIA slider/range controls in Vocaster Hub, so they are not remapped in this app.
