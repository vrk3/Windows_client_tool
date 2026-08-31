r"""Reducing a line to the sentence it is, without the object it is about.

A real CBS archive holds 138,683 records and a few hundred distinct
sentences. `Appl: detectParent: parent found: <this package>` appears
thousands of times, once per package, and counting those verbatim answers
"every line is unique", which is true and useless.

Each rule below was written against a real line shape from this machine, and
the order matters: the package token has to go before the version and the
number rules, or its `~~10.0.26100.1` is eaten piecemeal and two different
packages stop matching each other.

**What is deliberately NOT normalised: error codes.** `0x800f0805` and
`0x80073701` are the distinction, not noise. Collapsing them would merge
every failure into one row and throw away the reason -- the opposite of what
someone reading a log wants.

No Qt.
"""
import re
from functools import lru_cache

#: Order is load-bearing; see the module docstring.
_RULES = (
    # `{33D6CF13-224E-459B-AD4F-AF8C5E3CC469}` -- an UpdateID, not a fact.
    (re.compile(r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}"), "{GUID}"),
    # `HyperV-KMCL-Host-Package~31bf3856ad364e35~amd64~~10.0.26100.1`, whole:
    # the publisher key anchors it, and taking it in one piece is what keeps
    # the version rule below from chewing its tail.
    (re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*~[0-9a-fA-F]{16}~[^\s,;]*"),
     "<package>"),
    # `Update: Microsoft-Hyper-V-All` / `Update: 40a47c9430ed2427f5a958ac...`
    # -- the object the line is about, in either of the two forms CBS writes.
    # Key-anchored so it cannot eat prose: 13,093 of the 16,417 forms that
    # survived the rules above differed only here.
    (re.compile(r"(?<=Update: )[^,\n]+"), "<update>"),
    # A bare 32-hex digest, wherever else one turns up.
    (re.compile(r"\b[0-9a-fA-F]{32}\b"), "<digest>"),
    # `31275276_4079573531` -- a session id.
    (re.compile(r"\b\d{6,}_\d{6,}\b"), "<session>"),
    # `amd64_microsoft-windows-directui_31bf...` -- a component manifest
    # name. Anchored on the architecture prefix CBS always writes, so it
    # cannot swallow an ordinary word.
    (re.compile(r"\b(?:amd64|x86|wow64|msil)_[A-Za-z0-9._-]+"),
     "<component>"),
    # `00000da2 Scavenge: ...` -- the record id CBS prints at line start.
    # Anchored to the start and to the following space so an eight-digit
    # HRESULT elsewhere in the line is untouched.
    (re.compile(r"^\s*[0-9a-f]{8}(?= )"), "<id>"),
    # `@0x1a044547900` -- a pointer. Nine digits or more, so an eight-digit
    # HRESULT is left alone.
    (re.compile(r"\b0[xX][0-9a-fA-F]{9,}\b"), "<addr>"),
    # `10.0.26100.1`
    (re.compile(r"\b\d+\.\d+\.\d+(?:\.\d+)?\b"), "<version>"),
    # Anything else numeric: counts, sizes, indices.
    (re.compile(r"\b\d+\b"), "<n>"),
)


#: Log lines repeat heavily -- 35,657 distinct messages across the real
#: archive's 138,683 records -- so three quarters of the work is the same
#: string over again. Caching took a Summary refresh from 1.9s to 0.7s.
@lru_cache(maxsize=100_000)
def normalise(message: str) -> str:
    """`message` with the varying parts replaced by placeholders.

    Never returns an empty string for a non-empty input: a line that is
    nothing but a number would otherwise collapse to blank and show up as an
    empty row at the top of the counts.
    """
    if not message:
        return ""
    text = message
    for pattern, placeholder in _RULES:
        text = pattern.sub(placeholder, text)
    return text if text.strip() else message
