"""Console harness for the TreeSize scan engine.

Usage:  .venv\\Scripts\\python.exe tools/treesize_scan.py C:\\ [--top 20]

Not part of the shipped UI. It exists to verify the engine against real
volumes and to produce the speed and memory numbers the design calls for.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from modules.treesize.store.node_store import (                    # noqa: E402
    NodeStore, COMPRESSED, DIR, SPARSE, REPARSE, ADS, HARDLINK_DUP, EXCLUDED)
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


FLAG_NAMES = (("compressed", COMPRESSED), ("sparse", SPARSE),
              ("reparse", REPARSE), ("ads", ADS),
              ("hardlink-dup", HARDLINK_DUP), ("excluded", EXCLUDED))


def flag_census(store: NodeStore) -> list[tuple[str, int]]:
    """Count nodes carrying each flag.

    Exists to answer one recurring question with data instead of a guess: when
    Size sits below Allocated, is that ordinary cluster rounding, or is
    compressed/sparse detection broken? Zero compressed AND zero sparse across
    a whole volume would be the suspicious answer.
    """
    counts = []
    for label, bit in FLAG_NAMES:
        counts.append((label, sum(1 for a in store.attrs if a & bit)))
    return counts


def top_children(result: ScanResult, limit: int = 20) -> list[tuple[str, int, int]]:
    store = result.store
    rows = [(store.name(c), store.size[c], store.alloc[c])
            for c in store.children(result.root)]
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows[:limit]


def top_owners(store, limit: int = 10):
    """(name, file count, bytes) per owner, largest first."""
    totals: dict[str, list] = {}
    for node in range(len(store)):
        if store.attrs[node] & DIR:
            continue
        name = store.owner(store.owner_id[node]) or "(unknown)"
        entry = totals.setdefault(name, [0, 0])
        entry[0] += 1
        entry[1] += store.size[node]
    ranked = sorted(totals.items(), key=lambda item: item[1][1], reverse=True)
    return [(name, count, owned) for name, (count, owned) in ranked[:limit]]


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
    if result.engine == "mft" and result.volume_info:
        # How many record slots the MFT claims to hold, so the operator can
        # compare against Nodes above. A node count far below this is the
        # signature of an MFT that was not read end to end -- fragmentation
        # being the likeliest cause, since only the first extent is followed.
        info = result.volume_info
        slots = info.mft_valid_length // max(info.bytes_per_record, 1)
        lines.append(f"MFT:       {slots:,} record slots "
                     f"({info.mft_valid_length / (1024 ** 2):,.0f} MB) "
                     f"in {result.mft_extents:,} extent(s)")
    if result.node_count and result.elapsed > 0:
        lines.append(f"Rate:      {result.node_count / result.elapsed:,.0f} nodes/s")
    if not result.complete:
        lines.insert(0, "*** INCOMPLETE SCAN -- the totals below are a LOWER BOUND ***")
        lines.append(f"Unread:    {result.error_count:,} location(s) could not be read")
        for path, why in result.errors[:5]:
            lines.append(f"           {path} -- {why}")
        if result.error_count > 5:
            lines.append(f"           ... and {result.error_count - 5:,} more")
    census = ", ".join(f"{label} {count:,}" for label, count in flag_census(store))
    lines.append(f"Flags:     {census}")
    if any(owner_id >= 0 for owner_id in store.owner_id):
        # Only printed when owners were actually collected. On the MFT engine
        # this is the ONLY way to see whether the sampled resolution turned
        # "$SECURE:<id>" into real account names -- that path needs elevation
        # and cannot be reached from a test.
        lines.append("")
        lines.append("Owners:")
        for label, count, owned in top_owners(store):
            lines.append(f"  {format_size(owned):>10}  {count:>9,} files  {label}")
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
    parser.add_argument("--owners", action="store_true",
                        help="read file owners and print a per-owner breakdown "
                             "(spec 5.8). On the walk engine this costs a "
                             "security call per file; on the MFT engine it "
                             "samples one file per distinct security id.")
    args = parser.parse_args(argv)

    if not os.path.exists(args.target):
        print(f"error: target does not exist: {args.target}", file=sys.stderr)
        return 1

    scanner = Scanner(args.target,
                      filters=FilterSet(exclude_globs=tuple(args.exclude)),
                      collect_owners=args.owners)
    result = scanner.scan()
    print(summarize(result, args.top))
    # A scan that could not read everything must not exit 0: these numbers are
    # the phase-1 acceptance figures, and an incomplete run silently passing as
    # a good one is the whole failure mode this guards against.
    return 0 if result.complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
