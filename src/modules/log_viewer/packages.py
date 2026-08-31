r"""Which package or update a CBS line is about.

Windows servicing names its subject in almost every line, always in the same
shape: an identity, the publisher key, the architecture and a version, tilde
separated --

    HyperV-KMCL-Host-Package~31bf3856ad364e35~amd64~~10.0.26100.1
    Package_4_for_KB5044030~31bf3856ad364e35~amd64~~10.0.9277.2

The 16-hex publisher key is what makes it a package identity rather than a
sentence containing the word "package", and anchoring on it is what keeps
this from filling a column with prose.

**The shape of the real data decided what this returns.** In
`CbsPersist_20260831055247.log` only 124 of 138,683 records mention a KB at
all, while package tokens appear on tens of thousands: a KB-only column would
be empty 99.9% of the time. So the KB is returned when the name embeds one --
that is what someone hunting an update knows the thing by -- and the package
identity otherwise.

No Qt.
"""
import re

#: `name~<16 hex publisher key>~...`. The key is the anchor: without it,
#: "Planning child capability as a package" would match.
_PACKAGE = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)~[0-9a-fA-F]{16}~")

#: `Package_4_for_KB5044030` -> `KB5044030`. Servicing numbers its packages,
#: and the index is not part of the update's identity.
_KB = re.compile(r"KB\d{6,7}", re.IGNORECASE)


def package_of(message: str) -> str:
    """The package or update this line is about, or "".

    The FIRST package on the line: a CBS record routinely names a Parent as
    well, and the parent is context rather than the subject.
    """
    match = _PACKAGE.search(message or "")
    if not match:
        return ""
    name = match.group(1)
    kb = _KB.search(name)
    return kb.group(0).upper() if kb else name
