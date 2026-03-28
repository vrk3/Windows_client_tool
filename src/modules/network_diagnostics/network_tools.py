# src/modules/network_diagnostics/network_tools.py
import socket
import subprocess
import concurrent.futures
import psutil
import re
from typing import List, Tuple, Callable, Optional

CREATE_NO_WINDOW = 0x08000000


def ping(host: str, count: int = 4) -> str:
    """Run ping and return raw output."""
    result = subprocess.run(
        ["ping", "-n", str(count), host],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        timeout=30,
    )
    return result.stdout + result.stderr


def traceroute(host: str) -> List[Tuple[int, str, str]]:
    """Run tracert and return list of (hop_num, ip, time_ms)."""
    result = subprocess.run(
        ["tracert", "-d", "-w", "1000", host],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        timeout=120,
    )
    hops = []
    for line in result.stdout.splitlines():
        # Match lines that start with a hop number, e.g.:
        #   1    <1 ms    <1 ms    <1 ms  192.168.1.1
        #   2     *        *        *     Request timed out.
        m = re.match(r"^\s*(\d+)\s+", line)
        if not m:
            continue
        hop_num = int(m.group(1))
        tokens = line.split()
        # Last token is either an IP or "out." / "out"
        ip = tokens[-1] if tokens else "*"
        # Clean up trailing period from "timed out."
        if ip.endswith("."):
            ip = ip[:-1]
        # Time: find first numeric ms value or "<1"
        time_str = "*"
        for tok in tokens[1:]:
            if tok == "*":
                time_str = "*"
                break
            if re.match(r"^[<\d]", tok) and "ms" not in tok:
                time_str = tok
                break
            if tok.endswith("ms"):
                time_str = tok
                break
        hops.append((hop_num, ip, time_str))
    return hops


def dns_lookup(host: str, record_type: str = "A") -> str:
    """Run nslookup and return raw output."""
    result = subprocess.run(
        ["nslookup", f"-type={record_type}", host],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        timeout=15,
    )
    return result.stdout + result.stderr


def scan_ports(
    host: str,
    start: int,
    end: int,
    on_progress: Optional[Callable[[int, int], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> List[Tuple[int, str]]:
    """Scan TCP ports; return list of (port, 'open'). Processes in batches of 100."""
    open_ports: List[Tuple[int, str]] = []
    total = end - start + 1
    scanned = 0

    def check_port(port: int) -> Tuple[int, bool]:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        result = s.connect_ex((host, port))
        s.close()
        return port, result == 0

    ports = list(range(start, end + 1))
    batch_size = 100
    for batch_start in range(0, len(ports), batch_size):
        if is_cancelled and is_cancelled():
            break
        batch = ports[batch_start : batch_start + batch_size]
        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as ex:
            for port, is_open in ex.map(check_port, batch):
                if is_open:
                    open_ports.append((port, "open"))
        scanned += len(batch)
        if on_progress:
            on_progress(scanned, total)
    return open_ports


def get_connections() -> List[dict]:
    """Return active network connections via psutil."""
    conns = []
    for c in psutil.net_connections(kind="inet"):
        try:
            laddr = f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else ""
            raddr = f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else ""
            try:
                pname = psutil.Process(c.pid).name() if c.pid else ""
            except Exception:
                pname = ""
            conns.append(
                {
                    "local": laddr,
                    "remote": raddr,
                    "status": c.status,
                    "pid": str(c.pid or ""),
                    "process": pname,
                }
            )
        except Exception:
            continue
    return conns


def get_wifi_profiles() -> List[str]:
    """Return a list of saved Wi-Fi profile names."""
    result = subprocess.run(
        ["netsh", "wlan", "show", "profiles"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    profiles = []
    for line in result.stdout.splitlines():
        if ":" in line:
            parts = line.split(":")
            if len(parts) >= 2:
                name = parts[-1].strip()
                if name:
                    profiles.append(name)
    return profiles


def get_wifi_profile_detail(name: str) -> str:
    """Return full detail (including key) for a Wi-Fi profile."""
    result = subprocess.run(
        ["netsh", "wlan", "show", "profile", f"name={name}", "key=clear"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    return result.stdout


def get_adapter_info() -> List[dict]:
    """Return a list of network adapter info dicts."""
    adapters = []
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    gateways = {}
    try:
        gw_info = psutil.net_if_stats()  # fallback; real gateways via net_default_gateway
        # psutil doesn't expose gateways directly; skip silently
    except Exception:
        pass

    for name, addr_list in addrs.items():
        ip = mac = netmask = dns = ""
        for a in addr_list:
            family_name = a.family.name if hasattr(a.family, "name") else str(a.family)
            upper = family_name.upper()
            if "INET" in upper and "6" not in upper:
                ip = a.address
                netmask = a.netmask or ""
            elif "LINK" in upper or "PACKET" in upper:
                mac = a.address
        stat = stats.get(name)
        adapters.append(
            {
                "Name": name,
                "IP": ip,
                "MAC": mac,
                "Netmask": netmask,
                "Gateway": gateways.get(name, ""),
                "DNS": dns,
                "Speed": f"{stat.speed} Mbps" if stat else "",
                "Up": "Yes" if (stat and stat.isup) else "No",
            }
        )
    return adapters
