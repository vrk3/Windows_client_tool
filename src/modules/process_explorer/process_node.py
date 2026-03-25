from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ProcessNode:
    pid: int
    name: str
    exe: str
    cmdline: str
    user: str
    status: str          # running | sleeping | stopped | zombie
    parent_pid: int
    children: List['ProcessNode'] = field(default_factory=list)

    # Real-time metrics
    cpu_percent: float = 0.0
    memory_rss: int = 0      # bytes
    memory_vms: int = 0
    disk_read_bps: float = 0.0
    disk_write_bps: float = 0.0
    net_send_bps: float = 0.0
    net_recv_bps: float = 0.0
    gpu_percent: float = 0.0

    # Classification (set once, stable per process lifetime)
    is_system: bool = False
    is_service: bool = False
    is_dotnet: bool = False
    is_suspended: bool = False
    integrity_level: str = "Medium"  # Low | Medium | High | System

    # VirusTotal (populated on demand)
    sha256: Optional[str] = None
    vt_score: Optional[str] = None   # e.g. "3/72"
