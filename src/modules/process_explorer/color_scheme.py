from __future__ import annotations
from PyQt6.QtGui import QColor
from modules.process_explorer.process_node import ProcessNode


class ProcessColor:
    SYSTEM    = QColor(173, 216, 230)   # light blue
    SERVICE   = QColor(255, 182, 193)   # pink
    DOTNET    = QColor(255, 255, 153)   # yellow
    GPU       = QColor(216, 191, 216)   # light purple
    SUSPENDED = QColor(200, 200, 200)   # grey
    DEFAULT   = QColor(0, 0, 0, 0)      # transparent = default palette


def get_row_color(node: ProcessNode) -> QColor:
    """Return background QColor for a process row. Priority: suspended > system > service > dotnet > gpu > default."""
    if node.is_suspended:
        return ProcessColor.SUSPENDED
    if node.is_system:
        return ProcessColor.SYSTEM
    if node.is_service:
        return ProcessColor.SERVICE
    if node.is_dotnet:
        return ProcessColor.DOTNET
    if node.gpu_percent > 0.5:
        return ProcessColor.GPU
    return ProcessColor.DEFAULT
