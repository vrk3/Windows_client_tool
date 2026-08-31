"""A working machine's log beside a broken one.

Aligned on **what happened**, never on when. Two machines never share a
clock, and even one machine's own clock jumps -- `setupact.log` moves ten
hours backwards at a phase boundary. Comparing by timestamp would report
every line as different and tell you nothing.

The normaliser from the clustering work is what makes the comparison
possible: two machines service different packages, so `Installing
A~31bf...` and `Installing B~31bf...` are the same STEP even though no two
characters line up.

The output answers one question -- which steps happened on one and not the
other -- plus whether a shared step ran a different number of times, because
"ran once" and "ran forty times" are not the same servicing run.

No Qt.
"""
from collections import Counter
from dataclasses import dataclass, field
from typing import List

from .clustering import normalise


@dataclass
class Comparison:
    """What differs between two logs, in their own words."""
    only_in_left: List[str] = field(default_factory=list)
    only_in_right: List[str] = field(default_factory=list)
    counts_differ: bool = False

    @property
    def identical(self) -> bool:
        return not (self.only_in_left or self.only_in_right
                    or self.counts_differ)

    def as_text(self) -> str:
        if self.identical:
            return "No differences: both logs took the same steps."
        lines = []
        if self.only_in_left:
            lines.append("Only in the first log:")
            lines.extend(f"  {message}" for message in self.only_in_left)
            lines.append("")
        if self.only_in_right:
            lines.append("Only in the second log:")
            lines.extend(f"  {message}" for message in self.only_in_right)
            lines.append("")
        if self.counts_differ:
            lines.append("Some shared steps ran a different number of times.")
        return "\n".join(lines).rstrip()


def _shapes(entries):
    """`{normalised form: (count, an example of it)}`."""
    counts = Counter()
    examples = {}
    for entry in entries or ():
        form = normalise(entry.message)
        if not form:
            continue
        counts[form] += 1
        examples.setdefault(form, entry.message)
    return counts, examples


def compare(left, right) -> Comparison:
    """What the first log did that the second did not, and vice versa.

    Reported in the log's OWN words -- an example line rather than the
    normalised form -- because `Installing <package>` is not what anybody
    wants to read back.
    """
    left_counts, left_examples = _shapes(left)
    right_counts, right_examples = _shapes(right)

    only_left = [left_examples[form] for form in left_counts
                 if form not in right_counts]
    only_right = [right_examples[form] for form in right_counts
                  if form not in left_counts]
    shared = set(left_counts) & set(right_counts)
    counts_differ = any(left_counts[form] != right_counts[form]
                        for form in shared)
    return Comparison(only_in_left=sorted(only_left),
                      only_in_right=sorted(only_right),
                      counts_differ=counts_differ)
