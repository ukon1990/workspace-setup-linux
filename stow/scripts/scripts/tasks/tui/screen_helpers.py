"""Shared hierarchy mounting and screen navigation."""

from __future__ import annotations

from typing import Sequence

from textual.screen import Screen
from textual.widgets.tree import TreeNode

from ..models import BackendIdentity
from .logic import HierarchyNode


def _go_back(screen: Screen) -> None:
    if len(screen.app.screen_stack) > 1:
        screen.app.pop_screen()
    else:
        screen.app.exit()


def _mount_hierarchy(
    parent: TreeNode[BackendIdentity],
    nodes: Sequence[HierarchyNode],
    *,
    expand: bool = True,
) -> None:
    for node in nodes:
        tree_node = parent.add(
            node.progress_label,
            data=node.identity,
            allow_expand=bool(node.children),
        )
        if node.children:
            _mount_hierarchy(tree_node, node.children, expand=expand)
            if expand:
                tree_node.expand()
