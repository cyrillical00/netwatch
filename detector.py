import subprocess
import socket
import re
import requests

CAPTIVE_CHECK_URL = "http://captive.apple.com/hotspot-detect.html"
CAPTIVE_EXPECTED  = "Success"
DNS_TEST_HOSTS    = ["google.com", "cloudflare.com", "apple.com"]
PING_TARGET       = "8.8.8.8"
LATENCY_WARN_MS   = 200
LATENCY_CRIT_MS   = 500
LOSS_WARN_PCT     = 20
LOSS_CRIT_PCT     = 50


def get_active_interface() -> str:
    """
    Dynamically resolve the active network interface.
    Silicon Macs: built-in Wi-Fi is en0, USB-C adapters may be en5/en6.
    Falls back to en0 if detection fails.
    """
    try:
        result = subprocess.run(
            ["route", "-n", "get", "default"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "interface:" in line:
                return line.split(":")[1].strip()
    except Exception:
        pass
    return "en0"


def get_default_gateway() -> str | None:
    """Parse default gateway from `route -n get default`."""
    try:
        result = subprocess.run(
            ["route", "-n", "get", "default"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "gateway:" in line:
                return line.split(":")[1].strip()
    except Exception:
        pass
    return None


def check_wifi_interface(interface: str) -> dict:
    """
    Check if the Wi-Fi interface is up and has an IP address.
    Silicon-specific: interface can be 'up' but have no IP after sleep.
    """
    try:
        result = subprocess.run(
            ["ifconfig", interface],
            capture_output=True, text=True, timeout=5
        )
        output = result.stdout

        if "status: active" not in output and f"{interface}:" not in output:
            return {"ok": False, "detail": f"Interface {interface} not found"}

        # Check for inet address (IPv4)
        ip_match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", output)
        if not ip_match:
            return {"ok": False, "detail": f"Interface {interface} has no IP address (possible post-sleep issue)"}

        ip = ip_match.group(1)

        # Also check Wi-Fi power state
        power_result = subprocess.run(
            ["networksetup", "-getairportpower", interface],
            capture_output=True, text=True, timeout=5
        )
        power_on = "On" in power_result.stdout

        return {
            "ok": power_on and bool(ip_match),
            "detail": f"Interface {interface} — IP: {ip} — Wi-Fi power: {'On' if power_on else 'Off'}",
            "ip": ip,
            "power": power_on,
        }
    except Exception as e:
        return {"ok": False, "detail": f"Interface check failed: {e}"}


def check_gateway(gateway: str | None) -> dict:
    """Ping the default gateway 3 times. Fast timeout."""
    if not gateway:
        return {"ok": False, "detail": "No default gateway found"}
    try:
        result = subprocess.run(
            ["ping", "-c", "3", "-W", "2000", "-q", gateway],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            loss_match = re.search(r"(\d+\.?\d*)% packet loss", result.stdout)
            loss = float(loss_match.group(1)) if loss_match else 0.0
            return {
                "ok": loss < 50,
                "detail": f"Gateway {gateway} — {loss:.0f}% packet loss",
                "loss_pct": loss,
            }
        return {"ok": False, "detail": f"Gateway {gateway} unreachable"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": "Gateway ping timed out"}
    except Exception as e:
        return {"ok": False, "detail": f"Gateway check failed: {e}"}


def check_dns() -> dict:
    """
    Attempt to resolve multiple hostnames.
    Uses socket (stdlib, no subprocess) for speed.
    Silicon-specific: DNS can fail silently after wake even when gateway is reachable.
    """
    failures = []
    for host in DNS_TEST_HOSTS:
        try:
            socket.setdefaulttimeout(5)
            socket.getaddrinfo(host, 80)
        except socket.gaierror:
            failures.append(host)

    if not failures:
        return {"ok": True, "detail": "DNS resolving normally"}
    elif len(failures) == len(DNS_TEST_HOSTS):
        return {"ok": False, "detail": f"DNS failed for all hosts: {', '.join(failures)}"}
    else:
        return {
            "ok": False,
            "detail": f"DNS partial failure: {', '.join(failures)} unreachable",
        }


def check_packet_loss_latency() -> dict:
    """
    Ping 8.8.8.8 with 5 packets, parse loss % and average RTT.
    Returns warning/critical based on thresholds.
    """
    try:
        result = subprocess.run(
            ["ping", "-c", "5", "-W", "3000", "-q", PING_TARGET],
            capture_output=True, text=True, timeout=20
        )

        loss_match = re.search(r"(\d+\.?\d*)% packet loss", result.stdout)
        rtt_match  = re.search(r"min/avg/max/stddev = [\d.]+/([\d.]+)/", result.stdout)

        loss    = float(loss_match.group(1)) if loss_match else 100.0
        avg_rtt = float(rtt_match.group(1)) if rtt_match else None

        if loss >= LOSS_CRIT_PCT:
            return {"ok": False, "severity": "critical",
                    "detail": f"Critical packet loss: {loss:.0f}% to {PING_TARGET}",
                    "loss_pct": loss, "avg_rtt_ms": avg_rtt}

        if loss >= LOSS_WARN_PCT or (avg_rtt and avg_rtt > LATENCY_WARN_MS):
            return {"ok": False, "severity": "warning",
                    "detail": f"Degraded: {loss:.0f}% loss, {avg_rtt:.0f}ms avg RTT",
                    "loss_pct": loss, "avg_rtt_ms": avg_rtt}

        return {"ok": True,
                "detail": f"{loss:.0f}% loss, {avg_rtt:.0f}ms avg RTT" if avg_rtt else "Ping OK",
                "loss_pct": loss, "avg_rtt_ms": avg_rtt}

    except subprocess.TimeoutExpired:
        return {"ok": False, "severity": "critical",
                "detail": f"Ping to {PING_TARGET} timed out (complete connectivity loss?)"}
    except Exception as e:
        return {"ok": False, "detail": f"Ping check failed: {e}"}


def check_captive_portal() -> dict:
    """
    Detect captive portal by fetching Apple's connectivity check endpoint.
    Captive portals redirect this to their login page.
    Uses 5s timeout to stay fast.
    """
    try:
        resp = requests.get(CAPTIVE_CHECK_URL, timeout=5, allow_redirects=True)
        if CAPTIVE_EXPECTED in resp.text and resp.status_code == 200:
            return {"ok": True, "detail": "No captive portal detected"}
        return {
            "ok": False,
            "detail": f"Captive portal detected (HTTP {resp.status_code}, redirected to {resp.url})",
            "portal_url": resp.url,
        }
    except requests.exceptions.ConnectionError:
        return {"ok": False, "detail": "Captive portal check failed — no connectivity"}
    except requests.exceptions.Timeout:
        return {"ok": False, "detail": "Captive portal check timed out"}
    except Exception as e:
        return {"ok": True, "detail": f"Portal check skipped: {e}"}  # Don't block on this
