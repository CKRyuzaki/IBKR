---
description: Start the IBKR G10 RV dashboard on port 8500
---

Start the IBKR dashboard app in this repo and confirm it's serving on port 8500.

1. Confirm `config/config.yaml` exists (copy from `config/config.example.yaml` if missing) and
   that `dashboard.port` is `8500`.
2. Launch the app with `python -m ibkr_dashboard.app` (prefer `poetry run dashboard` only if
   `poetry` is confirmed runnable in this environment -- on this machine Poetry's executable is
   blocked by an AppLocker policy, so `python -m ibkr_dashboard.app` is the reliable path).
   Run it as a background process (e.g. `run_in_background`) since it's a long-running server,
   not a one-shot command.
   - On Windows PowerShell, make sure the real Python install directory is prepended to `$env:Path`
     before invoking `python` (the bare `python` command resolves to a non-functional Windows
     Store alias otherwise):
     ```powershell
     $pyDirs = "C:\Users\Ryuzaki\AppData\Local\Programs\Python\Python312\;C:\Users\Ryuzaki\AppData\Local\Programs\Python\Python312\Scripts\;C:\Users\Ryuzaki\AppData\Roaming\Python\Python312\Scripts\"
     $env:Path = $pyDirs + ";" + $env:Path
     cd "C:\Users\Ryuzaki\Documents\GitHub\IBKR"
     python -m ibkr_dashboard.app
     ```
3. Watch the startup logs for a few seconds: if IB Gateway/TWS isn't running or API access isn't
   enabled, `IBConnectionManager.start()` will raise a `TimeoutError` after ~20s (this is
   expected/clean failure, not a bug -- see README "Install & configure IB Gateway"). Report
   this clearly to the user rather than treating it as a crash to silently retry.
4. On successful startup, tell the user the dashboard is live at `http://127.0.0.1:8500`.
