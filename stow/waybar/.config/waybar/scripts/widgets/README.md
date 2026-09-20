# Waybar widgets

`../status_widgets.py <command>` is the stable entry point. Its explicit registry
imports only the selected module. Each widget returns a dictionary containing
`text`, plain-text `tooltip`, CSS `class`, and optionally `alt`. The loader escapes
tooltip text for Pango and writes one JSON object to stdout. Diagnostics use stderr.

Each widget owns its metric collection and presentation. Shared concerns live in
`common.py` (monitor layout and bounded commands), `formatting.py` (units),
`processes.py` (/proc snapshots), and `state.py` (locked atomic transactions).
To add a widget, implement `<name>_module(state)`, register it in the loader, and
configure its command and interval in Waybar's `config.jsonc`.

`../window_size.py` is a separate interactive controller for the
`custom/window-size` module. It captures the focused Hyprland window, opens the
fraction picker, and applies address-targeted geometry based on that window's
monitor work area. Tiled entries resize the active window/group horizontally;
the current dwindle tree may constrain the closest attainable fraction.
Floating entries opt into full-height floating geometry. `Super+Shift+R`
opens the picker centered over the active window for keyboard selection.

State is stored per widget in `~/.config/waybar/.cache/widgets/`. On first use,
relevant values are copied from the old `status-widgets.json`; that file is retained.
Hyprsunset actions and display share one transaction namespace. Interactive dialogs
may wait for user input; metric subprocesses time out after three seconds.

CPU process percentages measure tick deltas between snapshots (100% is one logical
CPU). Processes that disappear or reuse a PID are skipped. RAM process figures are
RSS and can count shared pages more than once. Network totals are interface counters,
not persisted session totals. GPU tooltips list all detected NVIDIA GPUs; the bar
continues to summarize the first GPU. Missing optional readings show `Unavailable`.

## Kubernetes status

`kubernetes.py` formats Waybar output from `~/scripts/kube-status.sh --json`. The
collector and terminal report live in the `scripts` package (`kube_status/`), not
under Waybar. Bar text summarizes ready/active pods (`P`), ready/total Deployments,
StatefulSets, and DaemonSets (`W`), and pods needing attention (`!`). Completed and
terminating pods are excluded from the pod ratio; zero-replica workloads are scaled
down and excluded from the workload ratio. Tooltips group details by namespace and
cap problem listings at ten entries per namespace. Click opens the full terminal
report in Kitty. Refresh interval is 30 seconds.

Use the terminal command directly after restowing scripts:

```sh
kube-status
kube-status --json
kube-status --namespace concoctly
```

## Per-app network usage

All network-specific source lives in `network/`: `__init__.py` provides the widget,
`apps.py` formats per-app tooltips, `collector.py` records traffic, and `setup.sh`
installs the collector and adjacent `waybar-network.service`. The repository-level
setup command below is only a convenience wrapper. The installed service runs a
root-owned copy of the collector, not the editable source in this directory.

Activate the optional collector from the repository root:

```sh
bash scripts/setup-network-usage.sh
```

This asks for sudo, installs NetHogs on Arch/CachyOS, copies the collector to a
root-owned location, and enables `waybar-network.service` at boot. Run the same
command after editing the collector to install the updated copy. Waybar itself
never runs with extra privileges and picks up the snapshot on its next refresh.

The network tooltip shows five top apps by current combined upload/download rate
and five by recorded bytes this boot. Processes with the same executable name and
UID are grouped; closed apps remain in totals. All users and system apps are
included. Traffic NetHogs cannot attribute is shown separately. Only the default
interface is captured, switching with the default route; local loopback traffic is
excluded. VPNs, containers, short-lived connections, capture loss, and NetHogs
counter resets can limit accuracy and attribution. These are approximate TCP/UDP
figures, not an exact reconciliation with interface byte counters.

Recording starts on activation, not retroactively at today's boot. The tooltip
shows that start time. Subsequent boots start the service automatically as the
network becomes available. `/run/waybar-network/usage.json` retains totals across
service restarts in the same boot, resets on reboot, and marks interruptions.
Stopped/stale collectors suppress live rates while retaining the last totals.
Only aggregate counters and executable basenames are saved, not packet contents,
destinations, or command lines.

Inspect or disable the service with:

```sh
systemctl status waybar-network.service
journalctl -u waybar-network.service -b
sudo systemctl disable --now waybar-network.service
```

Run tests from the repository root:

```sh
python3 -m unittest discover -s stow/waybar/.config/waybar/scripts/tests -v
```
