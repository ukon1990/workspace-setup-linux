#!/usr/bin/env bash
# Spawn a fresh SDDM greeter on tty8 so another user can log in
# without touching this session. Safe to call from inside hyprlock
# (we don't need to launch hyprlock again — it's already running).
#
# Requires the companion polkit rule at
# /etc/polkit-1/rules.d/49-sddm-switch-user.rules so pkexec runs
# non-interactively; otherwise a polkit auth dialog will be raised
# that cannot be interacted with while hyprlock covers the screen.
set -eu

# If we were triggered from an unlocked session (Super+Shift+L),
# lock first so the current session is protected before the greeter
# grabs another VT.
if ! pgrep -x hyprlock >/dev/null; then
    hyprlock >/dev/null 2>&1 &
    sleep 0.3
fi

if command -v pkexec >/dev/null 2>&1; then
    exec pkexec systemctl start [email protected]
else
    exec sudo -n systemctl start [email protected]
fi
