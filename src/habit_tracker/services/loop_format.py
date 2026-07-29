"""Loop Habit Tracker file-format helpers: its fixed 20-color palette and the
color <-> index mapping used when importing/exporting its SQLite `.db` files.

Lives in services/ rather than models/ because this is Loop's own file-format
data (not a Pydantic request/response shape), and LOOP_HABIT_COLORS is the
only camelCase-adjacent identifier in the codebase for the same reason - it
mirrors Loop's own naming, not ours.
"""

LOOP_HABIT_COLORS = [
    "#D32F2F",  #  0 red
    "#E64A19",  #  1 deep orange
    "#F57C00",  #  2 orange
    "#FF8F00",  #  3 amber
    "#F9A825",  #  4 yellow
    "#AFB42B",  #  5 lime
    "#7CB342",  #  6 light green
    "#388E3C",  #  7 green
    "#00897B",  #  8 teal
    "#00ACC1",  #  9 cyan
    "#039BE5",  # 10 light blue
    "#1976D2",  # 11 blue
    "#303F9F",  # 12 indigo
    "#5E35B1",  # 13 deep purple
    "#8E24AA",  # 14 purple
    "#D81B60",  # 15 pink
    "#5D4037",  # 16 brown
    "#303030",  # 17 dark grey
    "#757575",  # 18 grey
    "#aaaaaa",  # 19 light grey
]


def map_color(color_index: int) -> str:
    """Map Loop Habit Tracker color index to hex color code."""
    if 0 <= color_index < len(LOOP_HABIT_COLORS):
        return LOOP_HABIT_COLORS[color_index]
    # Default to blue if index is out of range
    return "#1976D2"


def reverse_map_color(hex_color: str) -> int:
    """Map hex color code back to Loop Habit Tracker color index."""
    hex_upper = hex_color.upper()
    for index, color in enumerate(LOOP_HABIT_COLORS):
        if color.upper() == hex_upper:
            return index
    # Default to blue (index 11) if not found
    return 11
