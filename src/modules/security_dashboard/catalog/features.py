"""Optional Windows features -- what is installed that need not be.

`dism` is the writer. Two things about it are load-bearing:

* Unelevated it **exits 740 with its complaint on STDOUT**, which Task 2's
  step capture now records as a failure rather than a success.
* `Get-WindowsOptionalFeature`, the reader's side, needs elevation too. So on
  an unelevated run every card here reads "Unknown / available=False" rather
  than guessing, and that is correct: the snapshot says so, and
  `SecurityControl.read()` turns it into None.

Most entries are `desired=False` -- legacy components nobody needs. Three are
`desired=None` because their presence is a dependency question rather than a
security verdict: .NET 3.5, Hyper-V (which is what VBS and Credential Guard
run on) and Windows Sandbox (a security *tool*).
"""
from typing import Any, Dict, Tuple

from ..security_reader import (
    check_feature_direct_play, check_feature_iis,
    check_feature_internet_explorer, check_feature_legacy_components,
    check_feature_netfx3, check_feature_print_xps, check_feature_simple_tcpip,
    check_feature_windows_fax_scan, check_feature_windows_media_player,
    check_feature_work_folders, check_hyperv, check_powershell_v2,
    check_sandbox, check_wsl,
)
from .model import Category, Risk, SecurityControl


def _dism(feature: str, enable: bool) -> Dict[str, Any]:
    verb = "enable-feature" if enable else "disable-feature"
    return {"type": "command",
            "cmd": f"dism /online /{verb} /featurename:{feature} /norestart"}


def _feature(control_id: str, feature: str, title: str, reader,
             description: str, why: str, desired=False,
             risk: Risk = Risk.LOW, reboot: bool = False) -> SecurityControl:
    return SecurityControl(
        id=control_id,
        title=title,
        category=Category.FEATURES,
        description=description,
        why_it_matters=why,
        reader=reader,
        on_steps=(_dism(feature, True),),
        off_steps=(_dism(feature, False),),
        desired=desired,
        risk=risk,
        requires_reboot=reboot,
    )


CONTROLS: Tuple[SecurityControl, ...] = (

    _feature(
        "feature_powershell_v2", "MicrosoftWindowsPowerShellV2Root",
        "Windows PowerShell 2.0 engine", check_powershell_v2,
        "The PowerShell 2.0 engine, kept for compatibility.",
        "PowerShell 2.0 predates AMSI, script block logging and transcription, "
        "so `powershell -version 2` is a documented way to run script that "
        "nothing on this page can see. It is the highest-value feature to "
        "remove.",
        risk=Risk.LOW, reboot=True),

    _feature(
        "feature_internet_explorer", "Internet-Explorer-Optional-amd64",
        "Internet Explorer 11", check_feature_internet_explorer,
        "The Internet Explorer 11 browser.",
        "Out of support, still scriptable through COM, and still reachable "
        "from Office documents through the MSHTML engine.",
        risk=Risk.LOW, reboot=True),

    _feature(
        "feature_iis", "IIS-WebServerRole", "Internet Information Services",
        check_feature_iis,
        "The IIS web server.",
        "A web server listening on a workstation is inbound attack surface "
        "for something nobody is browsing to."),

    _feature(
        "feature_simple_tcpip", "SimpleTCP", "Simple TCP/IP Services",
        check_feature_simple_tcpip,
        "echo, daytime, chargen, quote of the day and discard.",
        "Protocols from RFC 862-864 with no authentication, still usable "
        "today as UDP amplification reflectors."),

    _feature(
        "feature_legacy_components", "LegacyComponents", "Legacy Components",
        check_feature_legacy_components,
        "The container feature for DirectPlay and other retired components.",
        "It exists only so decades-old software still runs, and it brings "
        "code that stopped being maintained with it."),

    _feature(
        "feature_direct_play", "DirectPlay", "DirectPlay",
        check_feature_direct_play,
        "The networking layer of DirectX 8-era games.",
        "Retired in 2007, parses network input, and is present only for "
        "games older than that."),

    _feature(
        "feature_print_xps", "Printing-XPSServices-Features",
        "XPS Document Services", check_feature_print_xps,
        "Printing to, and rendering, XPS documents.",
        "An additional document parser in the print path, for a format that "
        "lost to PDF."),

    _feature(
        "feature_windows_fax_scan", "Printing-Fax-Features",
        "Windows Fax and Scan", check_feature_windows_fax_scan,
        "The fax and scan application and its print driver.",
        "Fax parsing code in the print path, on a machine with no fax modem."),

    _feature(
        "feature_media_player", "MediaPlayback", "Windows Media Player",
        check_feature_windows_media_player,
        "The legacy Windows Media Player and its codecs.",
        "Media parsers are a classic memory-safety target, and this is the "
        "old one that opens whatever a file claims to be."),

    _feature(
        "feature_work_folders", "WorkFolders-Client", "Work Folders Client",
        check_feature_work_folders,
        "Syncs files with a corporate Work Folders server.",
        "A sync client with a configured server is an outbound channel; with "
        "no server it is unused code."),

    # -- present-or-not is a dependency question, not a verdict -------------
    _feature(
        "feature_netfx3", "NetFx3", ".NET Framework 3.5",
        check_feature_netfx3,
        ".NET Framework 3.5, including 2.0 and 3.0.",
        "Older runtimes mean older code paths, but plenty of working software "
        "still needs this one. The catalog has no opinion (`desired=None`); "
        "note that its READER scores 'enabled' as green, which is the "
        "opposite polarity to every other feature here.",
        desired=None, reboot=True),

    _feature(
        "feature_hyperv", "Microsoft-Hyper-V-All", "Hyper-V",
        check_hyperv,
        "The Hyper-V hypervisor and its management tools.",
        "Hyper-V is a large privileged surface AND the thing VBS, HVCI and "
        "Credential Guard are built on -- turning it off disables all three. "
        "No opinion, deliberately.",
        desired=None, risk=Risk.HIGH, reboot=True),

    _feature(
        "feature_sandbox", "Containers-DisposableClientVM", "Windows Sandbox",
        check_sandbox,
        "A disposable virtual machine for running untrusted software.",
        "This is a security tool, not attack surface: its presence is a "
        "reason to be safer, not less safe. No opinion either way.",
        desired=None, reboot=True),

    SecurityControl(
        id="feature_wsl",
        title="Windows Subsystem for Linux",
        category=Category.FEATURES,
        description="Runs Linux distributions on this machine.",
        why_it_matters="WSL2 runs its own kernel with its own network stack, "
                       "and files inside a distribution are not covered by "
                       "the same tooling as the Windows filesystem.",
        reader=check_wsl,
        read_only_reason="This reader asks `wsl --status`, not the optional-"
                         "feature list, so a dism change here could not be "
                         "read back and verified. Removing WSL also removes "
                         "the distributions installed inside it, which is a "
                         "data-loss operation and not a toggle.",
    ),
)
