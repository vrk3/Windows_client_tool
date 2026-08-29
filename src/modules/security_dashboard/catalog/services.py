"""Windows services, as attack surface.

Every writable entry here is a `service` step, which BackupService reverts
exactly by restoring the prior start type -- the cleanest revert in the whole
catalog.

Three groups, and the difference matters:

* **Attack surface.** Something listens, publishes, or answers the network.
  `desired=False`, and the reader already colours a running one red.
* **No opinion (`desired=None`).** A running service that is a *user feature*,
  not attack surface: Windows Search, SysMain, Bluetooth, push notifications.
  Their readers score running as red -- that polarity is deliberately retained
  (Ruling 6) because it belongs to the reader, not to this file -- but the
  catalog has no opinion, so they are never counted as problems.
  **Task 15: the "Only problems" filter must key off `desired`, NOT the
  reader's `color`.** These four are exactly why.
* **Read-only.** A service the machine needs to work at all. Turning it off is
  not hardening, it is breakage, so there is no switch and the entry says so.

Two services have TWO readers each, through two different helpers
(`check_service_diag_track` / `check_service_diagtrack`, and
`check_service_maps_broker` / `check_service_mapsbroker`). Binding both would
give one service two cards that write the same start type. One of each pair is
bound here; the other is named in NOT_A_CONTROL.
"""
from typing import Any, Dict, Tuple

from ..security_reader import (
    check_service_bthserv, check_service_defender_status, check_service_dhcp,
    check_service_diagtrack, check_service_dnscache, check_service_fax,
    check_service_fdphost, check_service_fdrespub,
    check_service_lanman_server, check_service_lanman_workstation,
    check_service_mapsbroker, check_service_net_tcp_port_sharing,
    check_service_print_spooler, check_service_remote_access_connection,
    check_service_snmp, check_service_sysmain, check_service_telephony,
    check_service_upnp, check_service_walletsvc, check_service_webclient,
    check_service_wpn, check_service_wsearch, check_service_xbox_accessory,
    check_service_xbox_game_save, check_service_xbox_live, check_wu_service,
)
from .model import Category, Risk, SecurityControl


def _svc(name: str, start_type: str) -> Dict[str, Any]:
    return {"type": "service", "name": name, "start_type": start_type}


def _attack_surface(control_id: str, service: str, title: str, reader,
                    description: str, why: str, risk: Risk = Risk.LOW,
                    on_type: str = "manual") -> SecurityControl:
    """A service that should not be running on a workstation."""
    return SecurityControl(
        id=control_id,
        title=title,
        category=Category.SERVICES,
        description=description,
        why_it_matters=why,
        reader=reader,
        on_steps=(_svc(service, on_type),),
        off_steps=(_svc(service, "disabled"),),
        desired=False,
        risk=risk,
    )


def _no_opinion(control_id: str, service: str, title: str, reader,
                description: str, why: str) -> SecurityControl:
    """Writable, but the catalog does not say which way. See Ruling 6."""
    return SecurityControl(
        id=control_id,
        title=title,
        category=Category.SERVICES,
        description=description,
        why_it_matters=why,
        reader=reader,
        on_steps=(_svc(service, "automatic"),),
        off_steps=(_svc(service, "disabled"),),
        desired=None,
        risk=Risk.LOW,
    )


CONTROLS: Tuple[SecurityControl, ...] = (

    # -- attack surface -----------------------------------------------------
    _attack_surface(
        "service_webclient", "WebClient", "WebClient (WebDAV)",
        check_service_webclient,
        "Lets Windows mount WebDAV shares as drives.",
        "A live WebDAV client turns a UNC path in a document into an outbound "
        "authenticated request to an attacker's server. Almost nothing on a "
        "workstation needs it."),

    _attack_surface(
        "service_rasman", "RasMan",
        "Remote Access Connection Manager", check_service_remote_access_connection,
        "RasMan: dial-up and VPN connection management.",
        "It is the service behind VPN connections; with no VPN configured it "
        "is a listening component nobody uses. Turning it off breaks any VPN "
        "this machine dials.", risk=Risk.MEDIUM),

    _attack_surface(
        "service_print_spooler", "Spooler", "Print Spooler",
        check_service_print_spooler,
        "Queues print jobs, and accepts driver installation requests.",
        "PrintNightmare, PrintDemon and a decade of spooler bugs run through "
        "this service, several of them remotely. Turning it off stops all "
        "printing, including to PDF.", risk=Risk.MEDIUM),

    _attack_surface(
        "service_upnp", "upnphost", "UPnP Device Host", check_service_upnp,
        "Hosts UPnP devices, announcing this machine on the local network.",
        "UPnP advertises services to anyone on the same network and has a "
        "long history of parsing bugs."),

    _attack_surface(
        "service_fdphost", "fdPHost", "Function Discovery Provider Host",
        check_service_fdphost,
        "Discovers devices and services on the local network.",
        "Half of network discovery: it asks the network what is out there, "
        "over WSD and SSDP."),

    _attack_surface(
        "service_fdrespub", "FDResPub", "Function Discovery Resource Publication",
        check_service_fdrespub,
        "Publishes this machine and its shares to the local network.",
        "The other half: it tells the network what this machine offers, which "
        "is the first thing an attacker on the same segment enumerates."),

    _attack_surface(
        "service_snmp", "SNMP", "SNMP Service", check_service_snmp,
        "Simple Network Management Protocol agent.",
        "SNMP v1 and v2c authenticate with a community string sent in "
        "cleartext, and 'public' is still the default almost everywhere."),

    _attack_surface(
        "service_net_tcp_port_sharing", "NetTcpPortSharing",
        "Net.Tcp Port Sharing", check_service_net_tcp_port_sharing,
        "Lets several WCF applications share one TCP port.",
        "A port multiplexer with no purpose outside a machine hosting WCF "
        "services."),

    _attack_surface(
        "service_telephony", "TapiSrv", "Telephony", check_service_telephony,
        "TAPI: the telephony API service.",
        "A remotable RPC surface from the modem era, still present and still "
        "reachable."),

    _attack_surface(
        "service_fax", "Fax", "Fax Service", check_service_fax,
        "Sends and receives faxes.",
        "It answers a modem line, parses documents, and is on nobody's patch "
        "list."),

    _attack_surface(
        "service_walletsvc", "WalletService", "Wallet Service",
        check_service_walletsvc,
        "Backs the Microsoft Wallet.",
        "It handles payment-instrument data for a feature almost nobody uses."),

    _attack_surface(
        "service_diagtrack", "DiagTrack",
        "Connected User Experiences and Telemetry", check_service_diagtrack,
        "Collects diagnostic data and sends it to Microsoft.",
        "It is a continuous outbound channel carrying data about what runs on "
        "this machine. A privacy question first, and a channel second."),

    _attack_surface(
        "service_mapsbroker", "MapsBroker", "Downloaded Maps Manager",
        check_service_mapsbroker,
        "Downloads and updates offline maps.",
        "It runs whether or not the Maps app was ever opened, and fetches "
        "content over the network."),

    _attack_surface(
        "service_xbox_live", "XboxNetApiSvc", "Xbox Live Networking",
        check_service_xbox_live,
        "Networking support for Xbox Live.",
        "It opens network paths for a service that is unused on any machine "
        "that does not game."),

    _attack_surface(
        "service_xbox_accessory", "XboxGipSvc", "Xbox Accessory Management",
        check_service_xbox_accessory,
        "Manages Xbox controllers and accessories.",
        "Driver-adjacent code for hardware most machines never see."),

    _attack_surface(
        "service_xbox_game_save", "XblGameSave", "Xbox Game Save",
        check_service_xbox_game_save,
        "Syncs Xbox game saves to the cloud.",
        "Another outbound sync for an unused feature."),

    SecurityControl(
        id="service_lanman_server",
        title="Server (LanmanServer)",
        category=Category.SERVICES,
        description="The SMB server: it is what makes this machine's files "
                    "and admin shares reachable over the network.",
        why_it_matters="Turning it off closes SMB inbound entirely -- no file "
                       "shares, no C$, no remote management. That is real "
                       "hardening on a machine that shares nothing, and real "
                       "breakage on one that does.",
        reader=check_service_lanman_server,
        on_steps=(_svc("LanmanServer", "automatic"),),
        off_steps=(_svc("LanmanServer", "disabled"),),
        desired=False,
        risk=Risk.MEDIUM,
        requires_reboot=True,
    ),

    # -- writable, but the catalog has no opinion (Ruling 6) ----------------
    _no_opinion(
        "service_wsearch", "WSearch", "Windows Search", check_service_wsearch,
        "Indexes files so Start and Explorer can search them.",
        "Its reader scores a running service red, which is a performance and "
        "telemetry judgement rather than attack surface. The catalog "
        "deliberately has no opinion (`desired=None`) so this is never counted "
        "as a security problem."),

    _no_opinion(
        "service_sysmain", "SysMain", "SysMain (Superfetch)",
        check_service_sysmain,
        "Pre-loads frequently used applications into memory.",
        "Same shape as Windows Search: a performance trade, not attack "
        "surface. `desired=None` on purpose."),

    _no_opinion(
        "service_bthserv", "bthserv", "Bluetooth Support Service",
        check_service_bthserv,
        "Discovers and pairs Bluetooth devices.",
        "Bluetooth is genuine radio attack surface on a machine that has none "
        "paired -- and it is also how the keyboard works on a machine that "
        "does. The catalog cannot know which this is, so it has no opinion."),

    _no_opinion(
        "service_wpn", "WpnService", "Windows Push Notifications",
        check_service_wpn,
        "Delivers push notifications to apps and the action centre.",
        "A persistent outbound connection to Microsoft, and also the thing "
        "that makes notifications work. No opinion."),

    # -- Windows Update: this one should be RUNNING -------------------------
    SecurityControl(
        id="service_windows_update",
        title="Windows Update service",
        category=Category.SERVICES,
        description="The service that finds, downloads and installs updates.",
        why_it_matters="Almost everything else on this page is a mitigation "
                       "for something a patch already fixed. A disabled "
                       "Windows Update is the one setting that makes every "
                       "other one matter more.",
        reader=check_wu_service,
        # wuauserv is TRIGGER-started: stopped is its normal state, so
        # comparing "running" would flag every healthy machine. Disabled is
        # the finding.
        read_value=lambda d: (None if d.get("disabled") is None
                              else not d["disabled"]),
        on_steps=(_svc("wuauserv", "manual"),),
        off_steps=(_svc("wuauserv", "disabled"),),
        desired=True,
        risk=Risk.MEDIUM,
    ),

    # -- read-only ----------------------------------------------------------
    SecurityControl(
        id="service_defender",
        title="Microsoft Defender Antivirus Service",
        category=Category.SERVICES,
        description="WinDefend: the service the whole Defender tab depends on.",
        why_it_matters="If it is not running, every green card on the Defender "
                       "tab is describing configuration that nothing is "
                       "enforcing.",
        reader=check_service_defender_status,
        read_only_reason="Tamper Protection refuses changes to Defender's own "
                         "service, and Windows restarts it anyway. A switch "
                         "here would report a failure every time.",
    ),

    SecurityControl(
        id="service_dhcp",
        title="DHCP Client",
        category=Category.SERVICES,
        description="Obtains this machine's IP address from the network.",
        why_it_matters="Its reader scores a stopped DHCP client red, and that "
                       "is right: without it the machine has no address on any "
                       "network that assigns them.",
        reader=check_service_dhcp,
        read_only_reason="Disabling it takes this machine off the network. It "
                         "is a dependency, not attack surface, and there is "
                         "no hardening version of turning it off.",
    ),

    SecurityControl(
        id="service_dnscache",
        title="DNS Client",
        category=Category.SERVICES,
        description="Resolves and caches DNS names for every process.",
        why_it_matters="Stopping it does not stop name resolution -- it "
                       "removes the cache and the single place where DNS "
                       "policy is applied.",
        reader=check_service_dnscache,
        read_only_reason="A dependency of nearly everything that uses the "
                         "network. Disabling it breaks name resolution "
                         "policy, and hardens nothing.",
    ),

    SecurityControl(
        id="service_lanman_workstation",
        title="Workstation (LanmanWorkstation)",
        category=Category.SERVICES,
        description="The SMB *client*: how this machine reaches other "
                    "machines' shares.",
        why_it_matters="This is the outbound half of SMB. It is where SMB "
                       "signing and EPA are enforced, both of which are "
                       "controls on the Firewall & Network tab.",
        reader=check_service_lanman_workstation,
        read_only_reason="Disabling the SMB client breaks every mapped drive "
                         "and UNC path on the machine. Harden it with SMB "
                         "signing and EPA instead -- both are controls here.",
    ),
)
