<p align="center">
  <img src="./assets/project-preview.svg" alt="Long-Term Plan Widget preview" width="100%" />
</p>

<p align="center">
  <a href="./README.zh-CN.md">简体中文</a>
  ·
  <a href="https://github.com/WinTrae/long-term-plan-widget/actions/workflows/test.yml"><img src="https://github.com/WinTrae/long-term-plan-widget/actions/workflows/test.yml/badge.svg" alt="Tests" /></a>
  <img src="https://img.shields.io/badge/platform-Windows-0078D4?logo=windows11&logoColor=white" alt="Windows" />
  <img src="https://img.shields.io/badge/license-MIT-22C55E" alt="MIT license" />
</p>

# Long-Term Plan Widget

A lightweight, local-first Windows desktop planner built with Python and Tkinter. It keeps a compact plan window close at hand, stores tasks in plain JSON, and can turn Chinese speech into tasks locally with an optional Whisper model.

## Highlights

- Compact always-on-top desktop window with adjustable opacity
- Edge docking, auto-hide, and a slim reveal handle
- Create, edit, complete, reopen, and delete tasks
- Automatic due-date extraction from Chinese phrases such as “今天”, “明天”, and explicit dates
- Three visual themes, including two image-backed skins
- Local JSON storage with atomic writes and an automatic backup
- Optional offline speech recognition through `faster-whisper`
- Single-instance behavior: launching it again reveals the existing window
- No account, analytics, telemetry, or task-data upload

## Requirements

- Windows 10 or Windows 11
- Python 3.10 or newer (the standard Windows installer includes Tkinter)

The core planner uses only the Python standard library. Install the optional packages to enable image-backed themes and voice input:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run from source

```powershell
git clone https://github.com/WinTrae/long-term-plan-widget.git
cd long-term-plan-widget
py -3 .\plan_widget.pyw
```

You can also double-click `launch_plan_widget.vbs` to launch the widget without a console window. The launcher searches for `pythonw.exe` and does not contain a machine-specific path.

On first launch, the app creates `plan_data.json`. Runtime data, settings, logs, model files, and generated executables are excluded by `.gitignore`.

## Optional voice input

After installing `requirements.txt`, press and hold the microphone button, speak a Chinese task, and release it to transcribe. The first use may download the `small` Whisper model into `models/`; transcription itself runs on the local machine.

To forbid downloads and use only an already cached model:

```powershell
$env:PLAN_WIDGET_OFFLINE_ONLY = "1"
py -3 .\plan_widget.pyw
```

No speech model is bundled in this repository.

## Data format

`plan_data.example.json` documents the local data format. Copy it to `plan_data.json` if you want to start with the sample tasks:

```powershell
Copy-Item .\plan_data.example.json .\plan_data.json
```

The application writes changes atomically and keeps the previous copy in `plan_data.json.bak`.

## Tests

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
python -B -m unittest discover -s .\tests -p "test_*.py" -v
```

## Privacy notes

The public repository contains generic sample data only. Do not commit `plan_data.json`, `settings.json`, logs, screenshots of real plans, or local speech-model caches.

## License

MIT

