-- Keep Neotest's summary readable without depending on a particular Nerd Font
-- release. Every symbol is a single display cell in supported terminals.
return {
  running_animated = { "/", "|", "\\", "-", "/", "|", "\\", "-" },
  passed = "✓",
  running = "⟳",
  failed = "✗",
  skipped = "○",
  unknown = "?",
  non_collapsible = "─",
  collapsed = "─",
  expanded = "╮",
  child_prefix = "├",
  final_child_prefix = "╰",
  child_indent = "│",
  final_child_indent = " ",
  watching = "◉",
  test = "●",
  notify = "●",
  dir = "▸",
  file = "•",
  namespace = "◆",
}
