"""Interactive repository selector using curses."""

from __future__ import annotations

import curses
import sys
from dataclasses import dataclass
from typing import Any

from util import compute_delete_totals, fmt_size, load_data


@dataclass
class TuiState:
    current: int = 0
    scroll: int = 0
    selected: list[bool] | None = None
    age_filter: bool = True
    needs_full_redraw: bool = True
    prev_current: int = 0
    prev_scroll: int = 0


def format_row(
    repo: dict[str, Any],
    *,
    current_user: str,
    is_current: bool,
    is_selected: bool,
    age_filter: bool,
    age_limit_days: int,
    width: int,
) -> str:
    prefix = ">" if is_current else " "
    mark = "[x]" if is_selected else "[ ]"
    mine = " *" if repo["owner"] == current_user else ""

    if age_filter:
        body = (
            f"{prefix} {mark} {repo['full_name']:<36} {repo['artifact_count']:>3} art "
            f"{fmt_size(repo['total_size']):>8}  ({repo['old_count']} >{age_limit_days}d){mine}"
        )
    else:
        body = (
            f"{prefix} {mark} {repo['full_name']:<36} {repo['artifact_count']:>3} art "
            f"{fmt_size(repo['total_size']):>8}{mine}"
        )

    if len(body) > width:
        return body[: max(0, width - 1)]
    return body.ljust(width)


def _list_top(header_rows: int) -> int:
    return header_rows


def _visible_count(height: int, header_rows: int, footer_rows: int) -> int:
    return max(1, height - header_rows - footer_rows)


def _clamp_scroll(state: TuiState, count: int, visible: int) -> None:
    if state.current >= state.scroll + visible:
        state.scroll = state.current - visible + 1
    elif state.current < state.scroll:
        state.scroll = state.current


def _draw_header(stdscr, state: TuiState, del_count: int, del_size: int, age_limit_days: int) -> int:
    height, width = stdscr.getmaxyx()
    filter_label = (
        f"ON (>{age_limit_days} days only)" if state.age_filter else "OFF (all artifacts)"
    )

    lines = [
        "Select repositories to clear artifacts",
        "↑/↓ move  Space toggle  a all/none  t age filter  Enter confirm  q quit",
        f"Age filter: {filter_label}",
        f"Selected: {del_count} artifact(s), {fmt_size(del_size)}",
        "─" * min(width - 1, 72),
    ]

    for row, text in enumerate(lines):
        if row >= height:
            break
        stdscr.move(row, 0)
        stdscr.clrtoeol()
        stdscr.addstr(text[: max(0, width - 1)])

    return len(lines)


def _draw_footer(stdscr, start_row: int, scroll: int, end: int, count: int, visible: int) -> None:
    height, width = stdscr.getmaxyx()
    if count <= visible or start_row >= height:
        return

    text = f"Showing {scroll + 1}-{end} of {count}"
    stdscr.move(start_row, 0)
    stdscr.clrtoeol()
    stdscr.addstr(text[: max(0, width - 1)])


def _draw_row(
    stdscr,
    screen_row: int,
    repo: dict[str, Any],
    *,
    current_user: str,
    is_current: bool,
    is_selected: bool,
    age_filter: bool,
    age_limit_days: int,
) -> None:
    height, width = stdscr.getmaxyx()
    if screen_row >= height:
        return

    line = format_row(
        repo,
        current_user=current_user,
        is_current=is_current,
        is_selected=is_selected,
        age_filter=age_filter,
        age_limit_days=age_limit_days,
        width=width,
    )
    stdscr.move(screen_row, 0)
    stdscr.clrtoeol()
    stdscr.addstr(line)


def _draw_visible_list(
    stdscr,
    repos: list[dict[str, Any]],
    state: TuiState,
    current_user: str,
    header_rows: int,
    age_limit_days: int,
) -> int:
    height, width = stdscr.getmaxyx()
    visible = _visible_count(height, header_rows, footer_rows=1)
    _clamp_scroll(state, len(repos), visible)

    start = state.scroll
    end = min(start + visible, len(repos))
    list_top = _list_top(header_rows)

    for screen_row, repo_index in enumerate(range(start, end), start=list_top):
        _draw_row(
            stdscr,
            screen_row,
            repos[repo_index],
            current_user=current_user,
            is_current=repo_index == state.current,
            is_selected=state.selected[repo_index],
            age_filter=state.age_filter,
            age_limit_days=age_limit_days,
        )

    for screen_row in range(list_top + (end - start), min(list_top + visible, height - 1)):
        stdscr.move(screen_row, 0)
        stdscr.clrtoeol()

    footer_row = list_top + visible
    if footer_row < height:
        _draw_footer(stdscr, footer_row, start, end, len(repos), visible)

    return visible


def _redraw_changed_rows(
    stdscr,
    repos: list[dict[str, Any]],
    state: TuiState,
    current_user: str,
    header_rows: int,
    age_limit_days: int,
    visible: int,
) -> None:
    list_top = _list_top(header_rows)
    old_screen = state.prev_current - state.prev_scroll
    new_screen = state.current - state.scroll

    if state.prev_scroll == state.scroll:
        if 0 <= old_screen < visible and state.prev_current != state.current:
            _draw_row(
                stdscr,
                list_top + old_screen,
                repos[state.prev_current],
                current_user=current_user,
                is_current=False,
                is_selected=state.selected[state.prev_current],
                age_filter=state.age_filter,
                age_limit_days=age_limit_days,
            )
        if 0 <= new_screen < visible:
            _draw_row(
                stdscr,
                list_top + new_screen,
                repos[state.current],
                current_user=current_user,
                is_current=True,
                is_selected=state.selected[state.current],
                age_filter=state.age_filter,
                age_limit_days=age_limit_days,
            )
    else:
        _draw_visible_list(stdscr, repos, state, current_user, header_rows, age_limit_days)


def run(data_path: str, age_limit_days: int) -> tuple[set[str], bool] | None:
    data = load_data(data_path)
    repos = data["repos"]
    if not repos:
        print("No repositories with artifacts found. Nothing to do.")
        return None

    current_user = data["user"]
    state = TuiState(selected=[False] * len(repos))

    def _main(stdscr: curses.window) -> tuple[set[str], bool] | None:
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.nodelay(False)

        header_rows = 5
        cancelled = False
        confirmed = False

        while True:
            del_count, del_size = compute_delete_totals(data, state.selected, state.age_filter)

            if state.needs_full_redraw:
                stdscr.clear()
                header_rows = _draw_header(stdscr, state, del_count, del_size, age_limit_days)
                _draw_visible_list(
                    stdscr, repos, state, current_user, header_rows, age_limit_days
                )
                state.needs_full_redraw = False
                state.prev_current = state.current
                state.prev_scroll = state.scroll
            else:
                _draw_header(stdscr, state, del_count, del_size, age_limit_days)
                visible = _visible_count(stdscr.getmaxyx()[0], header_rows, footer_rows=1)
                _redraw_changed_rows(
                    stdscr,
                    repos,
                    state,
                    current_user,
                    header_rows,
                    age_limit_days,
                    visible,
                )

            stdscr.refresh()
            key = stdscr.getch()

            if key in (curses.KEY_UP, ord("k")):
                if state.current > 0:
                    state.prev_current = state.current
                    state.prev_scroll = state.scroll
                    state.current -= 1
            elif key in (curses.KEY_DOWN, ord("j")):
                if state.current < len(repos) - 1:
                    state.prev_current = state.current
                    state.prev_scroll = state.scroll
                    state.current += 1
            elif key == ord(" "):
                state.selected[state.current] = not state.selected[state.current]
                state.prev_current = state.current
                state.prev_scroll = state.scroll
                visible = _visible_count(stdscr.getmaxyx()[0], header_rows, footer_rows=1)
                screen_row = _list_top(header_rows) + (state.current - state.scroll)
                _draw_row(
                    stdscr,
                    screen_row,
                    repos[state.current],
                    current_user=current_user,
                    is_current=True,
                    is_selected=state.selected[state.current],
                    age_filter=state.age_filter,
                    age_limit_days=age_limit_days,
                )
            elif key in (ord("a"), ord("A")):
                if not all(state.selected):
                    state.selected = [True] * len(repos)
                else:
                    state.selected = [False] * len(repos)
                state.needs_full_redraw = True
            elif key in (ord("t"), ord("T")):
                state.age_filter = not state.age_filter
                state.needs_full_redraw = True
            elif key in (ord("\n"), ord("\r"), 10, 13):
                confirmed = True
                break
            elif key in (ord("q"), ord("Q")):
                cancelled = True
                break
            else:
                continue

            if key in (curses.KEY_UP, curses.KEY_DOWN, ord("k"), ord("j")):
                visible = _visible_count(stdscr.getmaxyx()[0], header_rows, footer_rows=1)
                if (
                    state.current < state.scroll
                    or state.current >= state.scroll + visible
                ):
                    state.needs_full_redraw = True

        if cancelled:
            return None
        if not confirmed:
            return None
        if not any(state.selected):
            return None
        selected_names = {
            repos[i]["full_name"] for i, on in enumerate(state.selected) if on
        }
        return selected_names, state.age_filter

    try:
        result = curses.wrapper(_main)
    except curses.error:
        print("Error: terminal is too small or not interactive.", file=sys.stderr)
        return None

    if result is None:
        print("Cancelled.")
        return None
    if not result[0]:
        print("No repositories selected.")
        return None
    return result
