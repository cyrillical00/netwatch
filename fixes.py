import subprocess
import time
from sudo_helper import SudoSession


def flush_dns(sudo: SudoSession) -> dict:
    """
    Flush macOS DNS cache.
    Silicon-specific: mDNSResponder HUP is required — dscacheutil alone is insufficient on macOS 13+.
    """
    try:
        r1 = sudo.run(["dscacheutil", "-flushcache"])
        r2 = sudo.run(["killall", "-HUP", "mDNSResponder"])
        if r1.returncode == 0 and r2.returncode == 0:
            return {"success": True, "detail": "DNS cache flushed + mDNSResponder restarted"}
        return {"success": False,
                "detail": f"DNS flush partial failure — dscacheutil: {r1.returncode}, killall: {r2.returncode}"}
    except Exception as e:
        return {"success": False, "detail": f"DNS flush failed: {e}"}


def set_fallback_dns(interface: str, sudo: SudoSession,
                     servers: list[str] = None) -> dict:
    """
    Override DNS servers to known-good public resolvers.
    Default: 8.8.8.8 (Google) + 1.1.1.1 (Cloudflare).
    """
    if servers is None:
        servers = ["8.8.8.8", "1.1.1.1"]
    try:
        r = sudo.run(["networksetup", "-setdnsservers", interface] + servers)
        if r.returncode == 0:
            return {"success": True,
                    "detail": f"DNS overridden to {', '.join(servers)} on {interface}"}
        return {"success": False, "detail": f"DNS override failed: {r.stderr.strip()}"}
    except Exception as e:
        return {"success": False, "detail": f"DNS override failed: {e}"}


def restore_dns(interface: str, sudo: SudoSession) -> dict:
    """Restore DNS to DHCP-assigned (remove manual override)."""
    try:
        r = sudo.run(["networksetup", "-setdnsservers", interface, "Empty"])
        return {"success": r.returncode == 0,
                "detail": "DNS restored to DHCP-assigned" if r.returncode == 0
                          else f"DNS restore failed: {r.stderr.strip()}"}
    except Exception as e:
        return {"success": False, "detail": f"DNS restore failed: {e}"}


def renew_dhcp(interface: str, sudo: SudoSession) -> dict:
    """
    Force DHCP lease renewal.
    Uses `ipconfig set` which is more reliable than `networksetup -setdhcp` on Silicon.
    """
    try:
        r = sudo.run(["ipconfig", "set", interface, "DHCP"])
        if r.returncode == 0:
            time.sleep(3)  # Wait for IP assignment
            return {"success": True, "detail": f"DHCP lease renewed on {interface}"}
        return {"success": False, "detail": f"DHCP renew failed: {r.stderr.strip()}"}
    except Exception as e:
        return {"success": False, "detail": f"DHCP renew failed: {e}"}


def toggle_wifi(interface: str, sudo: SudoSession,
                off_duration: float = 3.0,
                reconnect_wait: float = 8.0) -> dict:
    """
    Cycle Wi-Fi power off → on.
    Note: `networksetup -setairportpower` does NOT require sudo on most systems,
    but we use the sudo session for consistency and reliability.
    Silicon fix: recycles the Wi-Fi chipset firmware state.
    """
    try:
        # Turn off
        r_off = subprocess.run(
            ["networksetup", "-setairportpower", interface, "off"],
            capture_output=True, text=True, timeout=10
        )
        if r_off.returncode != 0:
            return {"success": False,
                    "detail": f"Wi-Fi power-off failed: {r_off.stderr.strip()}"}

        time.sleep(off_duration)

        # Turn on
        r_on = subprocess.run(
            ["networksetup", "-setairportpower", interface, "on"],
            capture_output=True, text=True, timeout=10
        )
        if r_on.returncode != 0:
            return {"success": False,
                    "detail": f"Wi-Fi power-on failed: {r_on.stderr.strip()}"}

        time.sleep(reconnect_wait)  # Allow time to associate + get DHCP

        return {"success": True,
                "detail": f"Wi-Fi cycled on {interface} — waited {reconnect_wait:.0f}s for reconnect"}
    except Exception as e:
        return {"success": False, "detail": f"Wi-Fi toggle failed: {e}"}


def disconnect_reconnect(interface: str, sudo: SudoSession) -> dict:
    """
    Disconnect from current Wi-Fi network and reconnect.
    This is a longer cycle than toggle — used as a last resort.
    Note: macOS will auto-reconnect to the last preferred network.
    We do NOT forget the network (would require stored password).
    """
    try:
        # Disassociate
        subprocess.run(
            ["/System/Library/PrivateFrameworks/Apple80211.framework/"
             "Versions/Current/Resources/airport", "-z"],
            capture_output=True, text=True, timeout=10
        )
        time.sleep(2)

        # Re-enable and let macOS reconnect to preferred network
        subprocess.run(
            ["networksetup", "-setairportpower", interface, "off"],
            capture_output=True, text=True, timeout=5
        )
        time.sleep(2)
        subprocess.run(
            ["networksetup", "-setairportpower", interface, "on"],
            capture_output=True, text=True, timeout=5
        )
        time.sleep(10)  # Longer wait for full re-association + DHCP

        return {"success": True,
                "detail": f"Disconnect/reconnect cycle complete on {interface}"}
    except FileNotFoundError:
        # airport utility not found (removed in some macOS versions)
        # Fall back to just toggling Wi-Fi with longer wait
        return toggle_wifi(interface, sudo, off_duration=5.0, reconnect_wait=12.0)
    except Exception as e:
        return {"success": False, "detail": f"Disconnect/reconnect failed: {e}"}
