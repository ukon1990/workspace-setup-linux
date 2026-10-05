"""Recent-first backend picker shown before authentication or scope loading."""

from argparse import ArgumentTypeError
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from ..models import Backend


@dataclass(frozen=True)
class LauncherSelection:
    backend: Backend
    project: Optional[str] = None


class ProjectPrompt(ModalScreen[Optional[str]]):
    BINDINGS = [Binding("escape", "cancel", "Back")]
    CSS = "ProjectPrompt { align: center middle; } #project-error { color: #f28b82; height: auto; }"

    def __init__(self, validate: Callable[[str], str]):
        super().__init__()
        self.validate_project = validate

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label("Jira project")
            yield Input(placeholder="Project key, e.g. PROJ", id="project-key")
            yield Static("", id="project-error")
            yield Label("Enter to open · Esc to return")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted)
    def accept(self, event: Input.Submitted) -> None:
        try:
            project = self.validate_project(event.value.strip())
        except (ValueError, ArgumentTypeError) as error:
            self.query_one("#project-error", Static).update(str(error))
            return
        self.dismiss(project)

    def action_cancel(self) -> None:
        self.dismiss(None)


class LauncherApp(App[Optional[LauncherSelection]]):
    CSS_PATH = Path(__file__).with_name("app.tcss")
    CSS = "Screen { align: center middle; } #backend-options { height: auto; }"
    TITLE = "tasks"
    BINDINGS = [
        Binding("escape,q", "cancel", "Cancel"),
        Binding("j", "next", "Down", show=False),
        Binding("k", "previous", "Up", show=False),
    ]

    def __init__(
        self, recent: Backend, *, needs_project: bool, validate_project: Callable[[str], str]
    ):
        super().__init__()
        self.backends = [recent, Backend.JIRA if recent is Backend.GITHUB else Backend.GITHUB]
        self.needs_project = needs_project
        self.validate_project = validate_project

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="modal-box"):
            yield Label("Choose a backend")
            yield OptionList(
                *(
                    Option("GitHub" if backend is Backend.GITHUB else "Jira", id=backend.value)
                    for backend in self.backends
                ),
                id="backend-options",
            )
            yield Label("Most recent first · Enter to open")
        yield Footer()

    def on_mount(self) -> None:
        options = self.query_one(OptionList)
        options.highlighted = 0
        options.focus()

    @on(OptionList.OptionSelected)
    def pick(self, event: OptionList.OptionSelected) -> None:
        if event.option_id is None:
            return
        backend = Backend(event.option_id)
        if backend is Backend.JIRA and self.needs_project:
            self.push_screen(ProjectPrompt(self.validate_project), self.project_selected)
        else:
            self.exit(LauncherSelection(backend))

    def project_selected(self, project: Optional[str]) -> None:
        if project is not None:
            self.exit(LauncherSelection(Backend.JIRA, project))
        else:
            self.query_one(OptionList).focus()

    def action_next(self) -> None:
        self.query_one(OptionList).action_cursor_down()

    def action_previous(self) -> None:
        self.query_one(OptionList).action_cursor_up()

    def action_cancel(self) -> None:
        self.exit(None)


def pick_backend(
    recent: Backend, *, needs_project: bool, validate_project: Callable[[str], str]
) -> Optional[LauncherSelection]:
    return LauncherApp(recent, needs_project=needs_project, validate_project=validate_project).run()
