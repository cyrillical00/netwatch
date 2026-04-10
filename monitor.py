import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from detector import (
    get_active_interface, get_default_gateway,
    check_wifi_interface, check_gateway, check_dns,
    check_packet_loss_latency, check_captive_portal,
)
from fixes import (
    flush_dns, set_fallback_dns, restore_dns,
    renew_dhcp, toggle_wifi, disconnect_reconnect,
)
from sudo_helper import SudoSession
from logger import NetWatchLogger


class MonitorState(Enum):
    NORMAL     = "normal"
    DEGRADED   = "degraded"
    FIXING     = "fixing"
    RECOVERING = "recovering"
    LOG_ONLY   = "log_only"
    PAUSED     = "paused"


@dataclass
class CheckResult:
    wifi:    dict = field(default_factory=dict)
    gateway: dict = field(default_factory=dict)
    dns:     dict = field(default_factory=dict)
    latency: dict = field(default_factory=dict)
    captive: dict = field(default_factory=dict)

    @property
    def all_ok(self) -> bool:
        return all([
            self.wifi.get("ok", True),
            self.gateway.get("ok", True),
            self.dns.get("ok", True),
            self.latency.get("ok", True),
            self.captive.get("ok", True),
        ])

    @property
    def issues(self) -> list[str]:
        problems = []
        if not self.wifi.get("ok", True):    problems.append("wifi")
        if not self.gateway.get("ok", True): problems.append("gateway")
        if not self.dns.get("ok", True):     problems.append("dns")
        if not self.latency.get("ok", True): problems.append("latency")
        if not self.captive.get("ok", True): problems.append("captive")
        return problems


class MonitorThread(threading.Thread):
    COOLDOWN_SECS = 90
    MAX_ATTEMPTS  = 3
    FIX_ENABLED   = True  # toggled by Settings tab

    def __init__(
        self,
        sudo: SudoSession,
        log: NetWatchLogger,
        interval: int = 15,
        on_state_change: Callable | None = None,
    ):
        super().__init__(daemon=True, name="NetWatchMonitor")
        self.sudo = sudo
        self.log = log
        self.interval = interval
        self.on_state_change = on_state_change

        self._stop_event  = threading.Event()
        self._pause_event = threading.Event()

        self.state = MonitorState.NORMAL
        self.interface = "en0"
        self.last_result: CheckResult | None = None
        self.fix_attempts: dict[str, int] = {}
        self.last_fix_time: float = 0.0
        self.dns_overridden: bool = False

    def run(self):
        self.interface = get_active_interface()
        self.log.info(f"Monitor started — interface: {self.interface} — interval: {self.interval}s")

        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                time.sleep(1)
                continue

            self._run_cycle()
            self._stop_event.wait(self.interval)

    def _run_cycle(self):
        """One full check-and-fix cycle."""
        self.interface = get_active_interface()
        gateway = get_default_gateway()

        result = CheckResult(
            wifi    = check_wifi_interface(self.interface),
            gateway = check_gateway(gateway),
            dns     = check_dns(),
            latency = check_packet_loss_latency(),
            captive = check_captive_portal(),
        )
        self.last_result = result

        if result.all_ok:
            if self.state != MonitorState.NORMAL:
                self.log.success("Network restored — all checks passing")
                if self.dns_overridden:
                    restore_dns(self.interface, self.sudo)
                    self.dns_overridden = False
                    self.log.info("DNS restored to DHCP-assigned")
                self.fix_attempts.clear()
            self._set_state(MonitorState.NORMAL)
            self.log.info(f"Check OK — {result.latency.get('detail', 'network healthy')}")
        else:
            for issue in result.issues:
                detail = self._get_detail(result, issue)
                if self.state == MonitorState.NORMAL:
                    self.log.warning(f"Issue detected: [{issue.upper()}] {detail}")
            self._set_state(MonitorState.DEGRADED)

            if self.FIX_ENABLED and self.state != MonitorState.LOG_ONLY:
                self._attempt_fixes(result)

    def _attempt_fixes(self, result: CheckResult):
        """Escalating fix sequence based on issue type and attempt count."""
        now = time.time()
        if now - self.last_fix_time < self.COOLDOWN_SECS:
            remaining = int(self.COOLDOWN_SECS - (now - self.last_fix_time))
            self.log.info(f"Fix cooldown active — {remaining}s remaining")
            return

        issues = result.issues

        # Captive portal: can't auto-fix, needs user
        if issues == ["captive"]:
            self.log.warning(
                f"Captive portal detected: {result.captive.get('portal_url', 'unknown')} "
                "— open a browser to complete sign-in"
            )
            self._set_state(MonitorState.LOG_ONLY)
            return

        # DNS-only failure: flush first, then fallback
        if "dns" in issues and "wifi" not in issues and "gateway" not in issues:
            attempts = self.fix_attempts.get("dns", 0)
            if attempts == 0:
                self._apply_fix("dns", flush_dns(self.sudo), "Flush DNS cache")
            elif attempts == 1:
                fix_result = set_fallback_dns(self.interface, self.sudo)
                self._apply_fix("dns", fix_result, "Set fallback DNS (8.8.8.8 / 1.1.1.1)")
                if fix_result["success"]:
                    self.dns_overridden = True
            elif attempts >= 2:
                self._apply_fix("dns", toggle_wifi(self.interface, self.sudo),
                                "Toggle Wi-Fi (DNS fix of last resort)")
            self.fix_attempts["dns"] = attempts + 1

        # Wi-Fi down
        elif "wifi" in issues:
            attempts = self.fix_attempts.get("wifi", 0)
            if attempts == 0:
                self._apply_fix("wifi", toggle_wifi(self.interface, self.sudo),
                                "Toggle Wi-Fi power")
            elif attempts == 1:
                self._apply_fix("wifi", disconnect_reconnect(self.interface, self.sudo),
                                "Disconnect/reconnect cycle")
            else:
                self.log.error("Wi-Fi fix failed after 2 attempts — check hardware or contact IT")
                self._set_state(MonitorState.LOG_ONLY)
                return
            self.fix_attempts["wifi"] = attempts + 1

        # Gateway unreachable or packet loss
        elif "gateway" in issues or "latency" in issues:
            attempts = self.fix_attempts.get("gateway", 0)
            if attempts == 0:
                self._apply_fix("gateway", renew_dhcp(self.interface, self.sudo),
                                "Renew DHCP lease")
            elif attempts == 1:
                self._apply_fix("gateway", toggle_wifi(self.interface, self.sudo),
                                "Toggle Wi-Fi (gateway fix)")
            elif attempts == 2:
                self._apply_fix("gateway", disconnect_reconnect(self.interface, self.sudo),
                                "Disconnect/reconnect")
            else:
                self.log.error("Gateway/latency fix failed after 3 attempts — logging only")
                self._set_state(MonitorState.LOG_ONLY)
                return
            self.fix_attempts["gateway"] = attempts + 1

        total_attempts = sum(self.fix_attempts.values())
        if total_attempts >= self.MAX_ATTEMPTS * 2:
            self._set_state(MonitorState.LOG_ONLY)

    def _apply_fix(self, issue: str, result: dict, label: str):
        self._set_state(MonitorState.FIXING)
        self.log.action(f"Applying fix: {label}")
        if result["success"]:
            self.log.fix(f"Fix applied: {result['detail']}")
        else:
            self.log.error(f"Fix failed: {result['detail']}")
        self.last_fix_time = time.time()
        self._set_state(MonitorState.RECOVERING)

    def _set_state(self, state: MonitorState):
        if self.state != state:
            self.state = state
            if self.on_state_change:
                self.on_state_change(state)

    def _get_detail(self, result: CheckResult, issue: str) -> str:
        return {
            "wifi":    result.wifi.get("detail", ""),
            "gateway": result.gateway.get("detail", ""),
            "dns":     result.dns.get("detail", ""),
            "latency": result.latency.get("detail", ""),
            "captive": result.captive.get("detail", ""),
        }.get(issue, "")

    def pause(self):
        self._pause_event.set()
        self._set_state(MonitorState.PAUSED)
        self.log.info("Monitoring paused")

    def resume(self):
        self._pause_event.clear()
        self.fix_attempts.clear()
        self._set_state(MonitorState.NORMAL)
        self.log.info("Monitoring resumed")

    def stop(self):
        self._stop_event.set()
        self.log.info("Monitor stopped")

    def set_interval(self, seconds: int):
        self.interval = max(5, min(60, seconds))
        self.log.info(f"Check interval updated to {self.interval}s")

    def run_diagnostics(self) -> CheckResult:
        """On-demand full diagnostic run (called from Diagnostics tab)."""
        self.interface = get_active_interface()
        gateway = get_default_gateway()
        return CheckResult(
            wifi    = check_wifi_interface(self.interface),
            gateway = check_gateway(gateway),
            dns     = check_dns(),
            latency = check_packet_loss_latency(),
            captive = check_captive_portal(),
        )
