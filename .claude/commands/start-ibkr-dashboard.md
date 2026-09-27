---
description: Start the IBKR G10 RV dashboard on port 8500
---

Start the IBKR dashboard app in this repo and confirm it's serving on port 8500.

1. Confirm `config/config.yaml` exists (copy from `config/config.example.yaml` if missing) and
   that `dashboard.port` is `8500`.
2. Launch the app with `.venv\Scripts\python -m ibkr_desk.dashboard.app` (or `uv run dashboard`; on this
   machine an AppLocker policy has blocked some executables, so the module path is the reliable one).
   Run it as a background process (e.g. `run_in_background`) since it's a long-running server,
   not a one-shot command.
   - On Windows PowerShell, make sure the real Python install directory is prepended to `$env:Path`
     before invoking `python` (the bare `python` command resolves to a non-functional Windows
     Store alias otherwise):
     ```powershell
     $pyDirs = "C:\Users\Ryuzaki\AppData\Local\Programs\Python\Python312\;C:\Users\Ryuzaki\AppData\Local\Programs\Python\Python312\Scripts\;C:\Users\Ryuzaki\AppData\Roaming\Python\Python312\Scripts\"
     $env:Path = $pyDirs + ";" + $env:Path
     cd "C:\Users\Ryuzaki\Documents\GitHub\IBKR"
     python -m ibkr_desk.dashboard.app
     ```
3. Watch the startup logs for a few seconds. The dashboard now starts even when IB Gateway/TWS is down
   or API access is disabled: the header chip and STATUS tab show IBKR as DISCONNECTED while the
   connection thread keeps retrying, and market-data subscriptions are re-established on connect.
   If IBKR stays disconnected, report that clearly (see README "IB Gateway") rather than treating
   the dashboard as broken. A `LiveAccountRefused` error means Gateway is on a non-paper account and
   `ibkr.allow_live` is false -- do not flip that flag without the user asking.
4. On successful startup, tell the user the dashboard is live at `http://127.0.0.1:8500`.
