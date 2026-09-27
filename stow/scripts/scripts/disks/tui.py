"""Textual disk table and small, explicit operation dialogs."""

from __future__ import annotations

import asyncio
import difflib
import os
import shlex
from typing import TypeVar

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Select, Static, Switch

from . import client, fstab
from .fstab import read_fstab
from .system import (
    Device,
    access_status,
    discover,
    mount_options,
    shared_root_mode,
    validate_target,
)

Result = TypeVar("Result")


class Dialog(ModalScreen[Result]):
    AUTO_FOCUS = "Input, Select, Switch, Button"
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("down", "next_control", "Next control"),
        ("right", "next_control", "Next control"),
        ("up", "previous_control", "Previous control"),
        ("left", "previous_control", "Previous control"),
    ]

    def action_next_control(self) -> None:
        self.focus_next(self.AUTO_FOCUS)

    def action_previous_control(self) -> None:
        self.focus_previous(self.AUTO_FOCUS)


class DialogButton(Button):
    BINDINGS = [("enter,space", "press", "Press button")]


class Confirm(Dialog[bool]):
    def __init__(self, text: str, *, confirm: bool = True) -> None:
        super().__init__()
        self.text = text
        self.confirm = confirm

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog"):
            yield Static(self.text, markup=False)
            with Horizontal(classes="buttons"):
                if self.confirm:
                    yield DialogButton("Confirm", id="confirm", variant="primary")
                yield DialogButton("Cancel" if self.confirm else "Close", id="cancel")

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class Configure(Dialog[dict | None]):
    def __init__(self, action: str, device: Device, text: str) -> None:
        super().__init__()
        self.operation = action
        self.device = device
        self.entries = fstab.matching_entries(text, device)

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog"):
            yield Static(f"{self.operation.title()}: {self.device.path}", markup=False)
            if self.operation == "unmount":
                yield Static("Select a mount. For stacked mounts, select the top layer first.")
                yield Select(
                    [
                        (f"{m.target} · ID {m.mount_id} · {m.options}", m.mount_id)
                        for m in self.device.mounts
                    ],
                    value=self.device.mounts[-1].mount_id,
                    allow_blank=False,
                    id="mount",
                )
            else:
                if self.entries:
                    yield Static("Existing fstab entry (directory retained):")
                    yield Select(
                        [
                            (f"Line {i + 1}: {fields[1]} ({fields[3]})", i)
                            for i, fields in self.entries
                        ],
                        value=self.entries[0][0],
                        allow_blank=False,
                        id="entry",
                    )
                target = self.entries[0][1][1] if self.entries else f"/mnt/{self.device.name}"
                yield Static("Mount directory (below /mnt, /media, or /run/media):")
                yield Input(target, disabled=bool(self.entries), id="target")
                if self.operation == "boot":
                    yield Static("Mount at boot (off disables boot mounting):")
                    yield Switch(
                        value=not self.entries or not fstab.boot_enabled(self.entries[0][1]),
                        id="enabled",
                    )
                    yield Static(
                        "Boot options apply on the next mount; a mounted NTFS root may be repaired."
                    )
            with Horizontal(classes="buttons"):
                yield DialogButton("Review", id="review", variant="primary")
                yield DialogButton("Cancel", id="cancel")

    @on(Input.Submitted, "#target")
    def submit_target(self) -> None:
        self.query_one("#review", Button).press()

    @on(Select.Changed, "#entry")
    def entry_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        fields = dict(self.entries)[event.value]
        self.query_one("#target", Input).value = fields[1]
        if self.operation == "boot":
            self.query_one("#enabled", Switch).value = not fstab.boot_enabled(fields)

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "review":
            self.dismiss(None)
        elif self.operation == "unmount":
            self.dismiss({"mount_id": self.query_one("#mount", Select).value})
        else:
            self.dismiss(
                {
                    "entry": self.query_one("#entry", Select).value if self.entries else None,
                    "target": self.query_one("#target", Input).value,
                    "enabled": self.query_one("#enabled", Switch).value
                    if self.operation == "boot"
                    else False,
                }
            )

    def action_cancel(self) -> None:
        self.dismiss(None)


class DisksApp(App[None]):
    TITLE = "disks"
    CSS = """
    DataTable { height: 1fr; }
    #details-pane { height: 8; padding: 1 2; border-top: solid $accent; }
    #details { height: auto; }
    #status { height: auto; max-height: 4; padding: 0 2; }
    ModalScreen { align: center middle; background: $background 70%; }
    .dialog { width: 90%; max-width: 110; height: auto; max-height: 90%;
              padding: 1 2; border: thick $accent; background: $surface; }
    .dialog Static { height: auto; margin-bottom: 1; }
    .buttons { height: auto; margin-top: 1; }
    .buttons Button { margin-right: 2; }
    """
    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("m", "mount_disk", "Mount"),
        ("u", "unmount_disk", "Unmount"),
        ("b", "boot_disk", "Boot setup"),
        ("j", "down", "Down"),
        ("k", "up", "Up"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.devices: list[Device] = []
        self.fstab_text = ""
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(cursor_type="row", id="disks")
        with VerticalScroll(id="details-pane"):
            yield Static("Loading disks…", id="details", markup=False)
        yield Static(
            "Run as your user. System disks are view-only; operations prompt for sudo.",
            id="status",
            markup=False,
        )
        yield Footer()

    def on_mount(self) -> None:
        for label, width in (
            ("Device", 20),
            ("Label", 14),
            ("Size", 6),
            ("Filesystem", 10),
            ("Mount locations", 24),
            ("Mode", 5),
            ("Boot", 4),
            ("Status", 14),
        ):
            self.query_one(DataTable).add_column(label, width=width)
        self.refresh_disks()

    def selected(self) -> Device | None:
        table = self.query_one(DataTable)
        if table.row_count:
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            return next((d for d in self.devices if d.path == key), None)
        return None

    async def load_disks(self) -> None:
        previous = self.selected()
        self.devices = await asyncio.to_thread(discover)
        self.fstab_text = await asyncio.to_thread(read_fstab)
        fstab.entries(self.fstab_text)
        table = self.query_one(DataTable)
        table.clear()
        for device in self.devices:
            if device.kind == "loop" or device.name.startswith("zram"):
                continue
            entries = fstab.matching_entries(self.fstab_text, device)
            boot = ", ".join("on" if fstab.boot_enabled(f) else "off" for _, f in entries) or "—"
            mode = (
                ", ".join("ro" if "ro" in m.options.split(",") else "rw" for m in device.mounts)
                or "—"
            )
            values = [
                device.path,
                device.label,
                device.size,
                device.fstype or device.kind,
                ", ".join(m.target for m in device.mounts) or "—",
                mode,
                boot,
                device.reason or "Ready",
            ]
            table.add_row(*(Text(value) for value in values), key=device.path)
        if previous and previous.path in [key.value for key in table.rows]:
            table.move_cursor(row=table.get_row_index(previous.path))
        self.show_details()

    @work(exclusive=True, group="refresh")
    async def refresh_disks(self) -> None:
        if self.busy:
            return
        self.busy = True
        try:
            await self.load_disks()
        except (OSError, RuntimeError, ValueError) as error:
            self.query_one("#status", Static).update(f"Discovery failed: {error}")
            self.query_one(DataTable).clear()
        finally:
            self.busy = False

    @on(DataTable.RowHighlighted)
    def show_details(self) -> None:
        device = self.selected()
        if device:
            lines = [
                f"{device.path} · UUID: {device.uuid or 'none'} · {device.reason or 'Data filesystem'}"
            ]
            for m in device.mounts:
                mode = "read-only" if "ro" in m.options.split(",") else "read/write"
                lines.append(
                    f"{m.target} · ID {m.mount_id} · mount {mode} · "
                    f"your access: {access_status(m.target)}\n  {m.options}"
                )
            if not device.mounts:
                lines.append(f"Default mount: /mnt/{device.name}")
            self.query_one("#details", Static).update("\n".join(lines))

    def action_refresh(self) -> None:
        if not self.busy:
            self.refresh_disks()

    def action_down(self) -> None:
        self.query_one(DataTable).action_cursor_down()

    def action_up(self) -> None:
        self.query_one(DataTable).action_cursor_up()

    def action_mount_disk(self) -> None:
        self.manage("mount")

    def action_unmount_disk(self) -> None:
        self.manage("unmount")

    def action_boot_disk(self) -> None:
        self.manage("boot")

    def action_quit(self) -> None:
        if not self.busy:
            self.exit()

    @work(group="operations")
    async def manage(self, action: str) -> None:
        if self.busy:
            return
        device = self.selected()
        if not device:
            return
        self.busy = True
        try:
            if device.reason:
                raise ValueError(device.reason)
            if action == "mount" and device.mounts:
                raise ValueError(
                    "Already mounted. Unmount existing layers first to change permissions."
                )
            if action == "unmount" and not device.mounts:
                raise ValueError("This partition is not mounted.")
            settings = await self.push_screen_wait(Configure(action, device, self.fstab_text))
            if settings is None:
                return
            request = {
                "action": action,
                "device": device.identity,
                "fstab_digest": fstab.digest(self.fstab_text),
                **settings,
            }
            if action == "boot":
                candidate = fstab.propose(
                    self.fstab_text,
                    device,
                    self.devices,
                    target=settings["target"],
                    index=settings["entry"],
                    enabled=settings["enabled"],
                    uid=os.getuid(),
                    gid=os.getgid(),
                )
                request["candidate_digest"] = fstab.digest(candidate)
                preview = (
                    "".join(
                        difflib.unified_diff(
                            self.fstab_text.splitlines(keepends=True),
                            candidate.splitlines(keepends=True),
                            fromfile="/etc/fstab (current)",
                            tofile="/etc/fstab (proposed)",
                        )
                    )
                    or "No fstab changes needed."
                )
                preview += "\nA backup is required before saving. Current mounts will not be remounted."
                matching = [m for m in device.mounts if m.target == settings["target"]]
                if settings["enabled"] and device.driver == "ntfs3":
                    if matching:
                        request["repair_root"] = True
                        mode = shared_root_mode(settings["target"])
                        preview += (
                            f"\nNTFS root mode: {mode:o}. If mounted read/write and needed, "
                            "set root mode to 777 for all local users."
                        )
                    else:
                        preview += (
                            "\nNTFS root permissions can be checked by mounting through disks."
                        )
            elif action == "mount":
                validate_target(settings["target"], self.devices, mounting=True)
                old = fstab.entry_for(self.fstab_text, device, settings["entry"])
                options = mount_options(device, os.getuid(), os.getgid(), old[3] if old else "")
                preview = shlex.join(
                    [
                        "mount",
                        "-t",
                        device.driver,
                        "-o",
                        ",".join(options),
                        "--",
                        device.path,
                        settings["target"],
                    ]
                )
                if device.driver == "ntfs3":
                    request["repair_root"] = True
                    preview += (
                        "\nIf the mounted NTFS root lacks shared access, "
                        "set its mode to 777. Existing files and subfolders are unchanged."
                    )
                if device.driver in {"ext4", "xfs", "btrfs"}:
                    preview += "\nExisting Unix ownership and permissions will be preserved."
            else:
                mount = next(m for m in device.mounts if m.mount_id == settings["mount_id"])
                preview = f"Unmount one layer at {mount.target} (ID {mount.mount_id})."
            if not await self.push_screen_wait(
                Confirm(preview + "\n\nSudo may request your password.")
            ):
                return
            failure: BaseException | None = None
            with self.suspend():
                try:
                    result = await asyncio.to_thread(client.execute, request)
                except BaseException as error:
                    failure = error
            if failure is not None:
                raise failure
            try:
                await self.load_disks()
            except (OSError, RuntimeError, ValueError) as error:
                result += f"\nRefresh failed: {error}. Press r to retry."
            if action == "mount":
                result += f"\nYour access: {access_status(settings['target'])}"
            self.query_one("#status", Static).update(result)
            await self.push_screen_wait(Confirm(result, confirm=False))
        except (OSError, RuntimeError, ValueError) as error:
            self.query_one("#status", Static).update(str(error))
            await self.push_screen_wait(Confirm(str(error), confirm=False))
        finally:
            self.busy = False
