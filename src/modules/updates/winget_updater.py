import subprocess
import re
from dataclasses import dataclass
from typing import List, Callable, Optional


@dataclass
class AppUpdate:
    name: str
    winget_id: str
    installed_version: str
    available_version: str
    source: str


def _run_winget(args: List[str], output_cb: Optional[Callable[[str], None]] = None) -> str:
    """Run winget, stream output via output_cb, return full output."""
    try:
        proc = subprocess.Popen(
            ["winget"] + args,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        lines = []
        for line in proc.stdout:
            line = line.rstrip()
            lines.append(line)
            if output_cb:
                output_cb(line)
        proc.wait()
        return "\n".join(lines)
    except FileNotFoundError:
        msg = "winget not found. Please install App Installer from the Microsoft Store."
        if output_cb:
            output_cb(msg)
        return msg
    except Exception as e:
        msg = f"Error running winget: {e}"
        if output_cb:
            output_cb(msg)
        return msg


def fetch_updates() -> List[AppUpdate]:
    """Run winget upgrade --include-unknown, parse and return list of updates."""
    output = _run_winget(["upgrade", "--include-unknown"])
    return _parse_upgrade_output(output)


def _parse_upgrade_output(output: str) -> List[AppUpdate]:
    """Parse winget upgrade output table into AppUpdate list."""
    updates = []
    lines = output.splitlines()

    # Find the header line (contains "Name" and "Id" and "Version" etc.)
    header_idx = -1
    for i, line in enumerate(lines):
        if "Name" in line and "Id" in line and "Version" in line:
            header_idx = i
            break

    if header_idx < 0:
        return updates

    # Find separator line (dashes)
    sep_idx = -1
    for i in range(header_idx + 1, min(header_idx + 3, len(lines))):
        if lines[i].strip().startswith("-"):
            sep_idx = i
            break

    if sep_idx < 0:
        return updates

    # Determine column positions from header
    header = lines[header_idx]
    # Typical columns: Name, Id, Version, Available, Source
    col_name = header.index("Name") if "Name" in header else 0
    col_id = header.index("Id") if "Id" in header else 30
    col_ver = header.index("Version") if "Version" in header else 60
    col_avail = header.index("Available") if "Available" in header else 80
    col_source = header.index("Source") if "Source" in header else 100

    for line in lines[sep_idx + 1:]:
        if not line.strip() or line.strip().startswith("-"):
            continue
        # Skip summary lines
        if "upgrades available" in line.lower():
            continue

        def _extract(start: int, end: int) -> str:
            if start >= len(line):
                return ""
            return line[start:end].strip() if end <= len(line) else line[start:].strip()

        name = _extract(col_name, col_id)
        winget_id = _extract(col_id, col_ver)
        installed = _extract(col_ver, col_avail)
        available = _extract(col_avail, col_source)
        source = _extract(col_source, len(line))

        if winget_id and available and available != "Unknown":
            updates.append(AppUpdate(
                name=name, winget_id=winget_id,
                installed_version=installed, available_version=available,
                source=source,
            ))

    return updates


def install_update(winget_id: str, output_cb: Callable[[str], None]) -> bool:
    """Run winget upgrade for a specific package. Returns True on success."""
    output = _run_winget(
        ["upgrade", "--id", winget_id, "--silent", "--accept-source-agreements",
         "--accept-package-agreements"],
        output_cb=output_cb,
    )
    return "successfully installed" in output.lower() or "no applicable upgrade" in output.lower()


def install_all_updates(output_cb: Callable[[str], None]) -> None:
    """Run winget upgrade --all."""
    _run_winget(
        ["upgrade", "--all", "--silent", "--accept-source-agreements",
         "--accept-package-agreements", "--include-unknown"],
        output_cb=output_cb,
    )
