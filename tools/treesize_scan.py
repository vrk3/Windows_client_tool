"""Console harness for the TreeSize scan engine.

Usage:  .venv\\Scripts\\python.exe tools/treesize_scan.py C:\\ [--top 20]

Not part of the shipped UI. It exists to verify the engine against real
volumes and to produce the speed and memory numbers the design calls for.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from modules.treesize.store.node_store import NodeStore            # noqa: E402
from modules.treesize.scan.filters import FilterSet                # noqa: E402
from modules.treesize.scan.scanner import Scanner, ScanResult      # noqa: E402

UNITS = ("B", "KB", "MB", "GB", "TB", "PB")

# Every parallel column in NodeStore. Listed rather than introspected so that
# adding a column without revisiting the memory budget shows up as a test
# failure instead of a silently shrinking bytes/node figure.
COLUMNS = ("parent", "name_off", "name_len", "size", "alloc", "mtime", "ctime",
           "atime", "attrs", "owner_id", "first_child", "next_sibling",
           "file_count", "folder_count")


def format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    value = float(n)
    for unit in UNITS[1:]:
        value /= 1024.0
        if value < 1024.0:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} PB"


def bytes_per_node(store: NodeStore) -> float:
    """Measured footprint per node: fixed columns plus this store's name blob.

    The plan budgeted 52 bytes. The columns actually measure 74 on Win64, and
    names add ~30 more, which is where the corrected 104-byte figure comes from.
    """
    if not len(store):
        return 0.0
    fixed = sum(getattr(store, column).itemsize for column in COLUMNS)
    return fixed + len(store.names) / len(store)


def filter_warning(engine: str, exclude_globs) -> str:
    """Non-empty when the user asked for filters the selected engine ignores."""
    if engine == "mft" and exclude_globs:
        return ("WARNING: the MFT engine does not apply filters, so --exclude was "
                "ignored and 'Excluded' below is 0. Scan a directory path instead "
                "of a whole drive to filter.")
    return ""


def top_children(result: ScanResult, limit: int = 20) -> list[tuple[str, int, int]]:
    store = result.store
    rows = [(store.name(c), store.size[c], store.alloc[c])
            for c in store.children(result.root)]
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows[:limit]


def summarize(result: ScanResult, limit: int = 20) -> str:
    store = result.store
    root = result.root
    names_mb = len(store.names) / (1024 * 1024)
    lines = [
        f"Engine:    {result.engine}",
        f"Elapsed:   {result.elapsed:.2f}s",
        f"Nodes:     {result.node_count:,}",
        f"Size:      {format_size(store.size[root])}",
        f"Allocated: {format_size(store.alloc[root])}",
        f"Files:     {store.file_count[root]:,}",
        f"Folders:   {store.folder_count[root]:,}",
        f"Excluded:  {result.excluded:,}",
        f"Names:     {names_mb:.1f} MB blob, ~{bytes_per_node(store):.0f} bytes/node",
    ]
    if result.volume_info:
        lines.append(f"Cluster:   {result.volume_info.bytes_per_cluster:,} bytes")
    if result.node_count and result.elapsed > 0:
        lines.append(f"Rate:      {result.node_count / result.elapsed:,.0f} nodes/s")
    lines.append("")
    lines.append(f"Top {limit} under {store.name(root)}:")
    for name, size, alloc in top_children(result, limit):
        lines.append(f"  {format_size(size):>10}  {format_size(alloc):>10}  {name}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TreeSize engine console harness")
    parser.add_argument("target", help="drive (C:\\) or directory path")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--exclude", action="append", default=[],
                        help="glob to exclude, repeatable")
    args = parser.parse_args(argv)

    if not os.path.exists(args.target):
        print(f"error: target does not exist: {args.target}", file=sys.stderr)
        return 1

    excludes = tuple(args.exclude)
    scanner = Scanner(args.target, filters=FilterSet(exclude_globs=excludes))
    warning = filter_warning(scanner.select_engine(), excludes)
    if warning:
        print(warning, file=sys.stderr)
    print(summarize(scanner.scan(), args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
