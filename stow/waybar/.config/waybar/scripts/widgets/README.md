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

State is stored per widget in `~/.config/waybar/.cache/widgets/`. On first use,
relevant values are copied from the old `status-widgets.json`; that file is retained.
Hyprsunset actions and display share one transaction namespace. Interactive dialogs
may wait for user input; metric subprocesses time out after three seconds.

CPU process percentages measure tick deltas between snapshots (100% is one logical
CPU). Processes that disappear or reuse a PID are skipped. RAM process figures are
RSS and can count shared pages more than once. Network totals are interface counters,
not persisted session totals. GPU tooltips list all detected NVIDIA GPUs; the bar
continues to summarize the first GPU. Missing optional readings show `Unavailable`.

Run tests from the repository root:

```sh
python3 -m unittest discover -s stow/waybar/.config/waybar/scripts/tests -v
```
