"""Issue-list loading progress, including time spent waiting on a request."""

import time

from textual.widgets import Static


class LoadingPanel(Static):
    def __init__(self):
        super().__init__("", id="issue-loading-progress", markup=False)
        self.started = None
        self.operation_started = None
        self.stages = {}
        self.current = None
        self.timer = None

    def start(self, scope, backend):
        self.stop()
        self.scope = scope
        self.backend = backend
        self.started = self.operation_started = time.monotonic()
        self.stages = {}
        self.current = None
        self.timer = self.set_interval(1, self.refresh_progress)
        self.refresh_progress()

    def stop(self):
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        self.started = None
        self.update("")

    def on_unmount(self):
        self.stop()

    def advance(self, progress):
        if self.started is None:
            return
        stage = progress.stage or progress.label
        previous = self.current
        if previous is None or (previous.stage, previous.operation) != (progress.stage, progress.operation):
            self.operation_started = time.monotonic()
        self.current = progress
        self.stages[stage] = progress
        self.refresh_progress()

    def refresh_progress(self):
        if self.started is None:
            return
        now = time.monotonic()
        lines = [f"Loading {self.scope} · {int(now - self.started)}s elapsed", ""]
        for stage, progress in self.stages.items():
            suffix = f" · {progress.issue_count} loaded" if progress.issue_count is not None else ""
            if progress.completed and progress.completed_checks is not None:
                suffix += f" · {progress.completed_checks} checks completed"
            lines.append(f"{'✓' if progress.completed else '…'} {stage}{suffix}")
        progress = self.current
        if progress is not None and not progress.completed:
            if progress.completed_checks is not None:
                lines.append(f"{progress.completed_checks} checks completed")
            if progress.operation:
                lines.append(progress.operation)
            elapsed = int(now - self.operation_started)
            lines.append(f"Current operation: {elapsed}s")
            if elapsed >= 10:
                lines.append(f"Still waiting for {self.backend}…")
        if any(p.completed_checks is not None for p in self.stages.values()):
            lines.extend(["", "Related issues are checked to determine available work."])
        self.update("\n".join(lines))
