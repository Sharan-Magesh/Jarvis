import subprocess
import sys
import time
import platform
from typing import Literal

Action = Literal["shutdown", "restart", "sleep", "hibernate", "lock", "signout"]

def _run(cmd, shell=False):
    return subprocess.run(cmd, shell=shell, capture_output=True, text=True)

def system_action(action: Action, confirm=True, countdown=5):
    """
    Perform a system power action with optional confirmation & countdown.
    Supported: shutdown, restart, sleep, hibernate, lock, signout
    """
    if confirm:
        # simple guard; your GUI/voice layer can ask the user separately
        print(f"[SAFETY] About to {action}. Count-down: {countdown}s (Ctrl+C to cancel)")
        try:
            for i in range(countdown, 0, -1):
                print(i, end=" ", flush=True)
                time.sleep(1)
            print()
        except KeyboardInterrupt:
            print("Cancelled.")
            return {"ok": False, "msg": "Cancelled"}

    osname = platform.system().lower()

    if osname == "windows":
        if action == "shutdown":
            return _run(["shutdown", "/s", "/t", "0"])
        elif action == "restart":
            return _run(["shutdown", "/r", "/t", "0"])
        elif action == "signout":
            return _run(["shutdown", "/l"])
        elif action == "lock":
            return _run(["rundll32.exe", "user32.dll,LockWorkStation"])
        elif action == "hibernate":
            # Requires hibernation enabled: `powercfg /hibernate on`
            return _run(["shutdown", "/h"])
        elif action == "sleep":
            # More reliable via PowerShell to avoid hibernate fallback
            ps = r"""
            Add-Type -Name Powr -Namespace Win32 -MemberDefinition '
            [DllImport("Powrprof.dll", SetLastError=true)]
            public static extern bool SetSuspendState(bool hibernate, bool forceCritical, bool disableWakeEvent);
            ';
            [Win32.Powr]::SetSuspendState($false,$false,$false) | Out-Null
            """
            return _run(["powershell", "-NoProfile", "-Command", ps])
        else:
            return {"ok": False, "msg": f"Unknown action {action}"}

    elif osname == "darwin":  # macOS
        if action == "shutdown":
            # AppleScript avoids sudo; will prompt for permissions the first time
            return _run(["osascript", "-e", 'tell application "System Events" to shut down'])
        elif action == "restart":
            return _run(["osascript", "-e", 'tell application "System Events" to restart'])
        elif action == "lock":
            # Locks the screen
            return _run(["/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession", "-suspend"])
        elif action == "sleep":
            return _run(["pmset", "sleepnow"])
        elif action == "hibernate":
            # macOS “hibernation” modes are managed via pmset; most modern Macs use safe sleep.
            # This triggers deep sleep on supported configs:
            return _run(["pmset", "sleepnow"])
        elif action == "signout":
            return _run(["osascript", "-e", 'tell application "System Events" to log out'])
        else:
            return {"ok": False, "msg": f"Unknown action {action}"}

    else:  # Linux
        # May require sudo depending on policykit; configure polkit rules for passwordless if desired.
        if action == "shutdown":
            return _run(["systemctl", "poweroff"])
        elif action == "restart":
            return _run(["systemctl", "reboot"])
        elif action == "sleep":
            return _run(["systemctl", "suspend"])
        elif action == "hibernate":
            return _run(["systemctl", "hibernate"])
        elif action == "lock":
            # Try common lockers; adapt to your desktop env
            for cmd in (["loginctl", "lock-session"],
                        ["gnome-screensaver-command", "-l"],
                        ["xdg-screensaver", "lock"]):
                res = _run(cmd)
                if res.returncode == 0:
                    return res
            return {"ok": False, "msg": "No lock command worked"}
        elif action == "signout":
            # Session-specific; many DEs expose their own commands
            return _run(["loginctl", "terminate-user", str(_current_uid())])
        else:
            return {"ok": False, "msg": f"Unknown action {action}"}

def _current_uid():
    try:
        import os
        return os.getuid()
    except Exception:
        return -1
