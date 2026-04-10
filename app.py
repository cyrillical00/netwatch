import tkinter as tk
from tkinter import ttk, scrolledtext, simpledialog, messagebox
import subprocess
import threading

from monitor import MonitorThread, MonitorState
from sudo_helper import SudoSession
from logger import NetWatchLogger
from detector import get_active_interface, check_wifi_interface


# ── Colors ────────────────────────────────────────────────────────────────────
BG        = "#0F172A"
BG_LIGHT  = "#1E293B"
BORDER    = "#334155"
TEXT_PRI  = "#F1F5F9"
TEXT_SEC  = "#94A3B8"
GREEN     = "#22C55E"
AMBER     = "#F59E0B"
RED       = "#EF4444"
BLUE      = "#60A5FA"
PURPLE    = "#A78BFA"

STATUS_COLORS = {
    MonitorState.NORMAL:     GREEN,
    MonitorState.DEGRADED:   AMBER,
    MonitorState.FIXING:     BLUE,
    MonitorState.RECOVERING: AMBER,
    MonitorState.LOG_ONLY:   RED,
    MonitorState.PAUSED:     TEXT_SEC,
}

STATUS_LABELS = {
    MonitorState.NORMAL:     "Network OK",
    MonitorState.DEGRADED:   "Issue Detected",
    MonitorState.FIXING:     "Applying Fix...",
    MonitorState.RECOVERING: "Recovering",
    MonitorState.LOG_ONLY:   "Manual Action Needed",
    MonitorState.PAUSED:     "Paused",
}

LOG_COLORS = {
    "INFO":    TEXT_SEC,
    "WARNING": AMBER,
    "ERROR":   RED,
    "SUCCESS": GREEN,
    "ACTION":  BLUE,
    "FIX":     PURPLE,
}


class NetWatchApp:
    VERSION = "1.0.0"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.sudo = SudoSession()
        self.log = NetWatchLogger()
        self.monitor: MonitorThread | None = None
        self._paused = False

        self._setup_window()
        self._build_ui()
        self._authenticate()
        self._start_monitor()
        self.root.after(200, self._poll_log_queue)

    def _setup_window(self):
        self.root.title("NetWatch")
        self.root.geometry("760x580")
        self.root.minsize(600, 450)
        self.root.configure(bg=BG)
        try:
            self.root.tk.call("::tk::unsupported::MacWindowStyle", "style",
                              self.root._w, "document", "closeBox")
        except Exception:
            pass

    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────────
        header = tk.Frame(self.root, bg=BG_LIGHT, height=64)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        self._status_dot = tk.Label(header, text="●", font=("Menlo", 22),
                                    fg=TEXT_SEC, bg=BG_LIGHT)
        self._status_dot.pack(side=tk.LEFT, padx=(16, 6), pady=12)

        title_frame = tk.Frame(header, bg=BG_LIGHT)
        title_frame.pack(side=tk.LEFT, pady=10)

        tk.Label(title_frame, text="NetWatch", font=("Menlo", 15, "bold"),
                 fg=TEXT_PRI, bg=BG_LIGHT).pack(anchor="w")

        self._status_label = tk.Label(title_frame, text="Starting...",
                                      font=("Menlo", 10), fg=TEXT_SEC, bg=BG_LIGHT)
        self._status_label.pack(anchor="w")

        self._strip_label = tk.Label(header, text="", font=("Menlo", 10),
                                     fg=TEXT_SEC, bg=BG_LIGHT)
        self._strip_label.pack(side=tk.RIGHT, padx=16)

        # ── Divider ─────────────────────────────────────────────────────────
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill=tk.X)

        # ── Notebook (tabs) ─────────────────────────────────────────────────
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG_LIGHT, foreground=TEXT_SEC,
                        font=("Menlo", 11), padding=[12, 6])
        style.map("TNotebook.Tab",
                  background=[("selected", BG)],
                  foreground=[("selected", TEXT_PRI)])

        self._notebook = ttk.Notebook(self.root)
        self._notebook.pack(fill=tk.BOTH, expand=True)

        self._build_events_tab()
        self._build_diagnostics_tab()
        self._build_settings_tab()

        # ── Footer ──────────────────────────────────────────────────────────
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill=tk.X)
        footer = tk.Frame(self.root, bg=BG_LIGHT, height=44)
        footer.pack(fill=tk.X)
        footer.pack_propagate(False)

        self._pause_btn = tk.Button(
            footer, text="⏸  Pause", font=("Menlo", 11),
            bg=BG, fg=TEXT_SEC, relief=tk.FLAT, cursor="hand2",
            activebackground=BG_LIGHT, activeforeground=TEXT_PRI,
            command=self._toggle_pause
        )
        self._pause_btn.pack(side=tk.LEFT, padx=12, pady=8)

        tk.Button(
            footer, text="Run Diagnostics", font=("Menlo", 11),
            bg=BLUE, fg="#0F172A", relief=tk.FLAT, cursor="hand2",
            activebackground="#3B82F6",
            command=self._run_diagnostics_now
        ).pack(side=tk.LEFT, padx=4, pady=8)

        tk.Button(
            footer, text="Open Log File", font=("Menlo", 11),
            bg=BG, fg=TEXT_SEC, relief=tk.FLAT, cursor="hand2",
            command=self._open_log_file
        ).pack(side=tk.RIGHT, padx=12, pady=8)

        tk.Label(footer, text=f"v{self.VERSION}",
                 font=("Menlo", 9), fg=BORDER, bg=BG_LIGHT).pack(side=tk.RIGHT, padx=4)

    def _build_events_tab(self):
        frame = tk.Frame(self._notebook, bg=BG)
        self._notebook.add(frame, text="  Events  ")

        self._event_log = scrolledtext.ScrolledText(
            frame, font=("Menlo", 11), bg=BG, fg=TEXT_SEC,
            insertbackground=TEXT_PRI, relief=tk.FLAT,
            wrap=tk.WORD, state=tk.DISABLED,
            padx=12, pady=8,
        )
        self._event_log.pack(fill=tk.BOTH, expand=True)

        for level, color in LOG_COLORS.items():
            self._event_log.tag_configure(level, foreground=color)
        self._event_log.tag_configure("TIMESTAMP", foreground="#475569")

    def _build_diagnostics_tab(self):
        frame = tk.Frame(self._notebook, bg=BG)
        self._notebook.add(frame, text="  Diagnostics  ")

        self._diag_frame = tk.Frame(frame, bg=BG)
        self._diag_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)

        tk.Label(self._diag_frame, text="Last Diagnostic Results",
                 font=("Menlo", 12, "bold"), fg=TEXT_PRI, bg=BG).pack(anchor="w", pady=(0, 12))

        self._diag_rows: dict[str, tk.Label] = {}
        checks = [
            ("wifi",    "Wi-Fi Interface"),
            ("gateway", "Default Gateway"),
            ("dns",     "DNS Resolution"),
            ("latency", "Packet Loss / Latency"),
            ("captive", "Captive Portal"),
        ]
        for key, label in checks:
            row = tk.Frame(self._diag_frame, bg=BG_LIGHT, pady=6)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=label, font=("Menlo", 11), fg=TEXT_SEC,
                     bg=BG_LIGHT, width=22, anchor="w").pack(side=tk.LEFT, padx=10)
            status_lbl = tk.Label(row, text="—", font=("Menlo", 11),
                                  fg=TEXT_SEC, bg=BG_LIGHT, anchor="w")
            status_lbl.pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)
            self._diag_rows[key] = status_lbl

        tk.Label(self._diag_frame,
                 text="Click 'Run Diagnostics' in the footer to refresh.",
                 font=("Menlo", 10), fg="#475569", bg=BG).pack(anchor="w", pady=(16, 0))

    def _build_settings_tab(self):
        frame = tk.Frame(self._notebook, bg=BG)
        self._notebook.add(frame, text="  Settings  ")

        inner = tk.Frame(frame, bg=BG)
        inner.pack(fill=tk.BOTH, expand=True, padx=24, pady=20)

        tk.Label(inner, text="Check Interval", font=("Menlo", 12, "bold"),
                 fg=TEXT_PRI, bg=BG).pack(anchor="w")
        tk.Label(inner, text="How often to check network health (seconds)",
                 font=("Menlo", 10), fg=TEXT_SEC, bg=BG).pack(anchor="w", pady=(2, 8))

        self._interval_var = tk.IntVar(value=15)
        slider_frame = tk.Frame(inner, bg=BG)
        slider_frame.pack(fill=tk.X, pady=(0, 16))
        tk.Scale(slider_frame, from_=5, to=60, orient=tk.HORIZONTAL,
                 variable=self._interval_var, bg=BG, fg=TEXT_PRI,
                 troughcolor=BG_LIGHT, highlightthickness=0,
                 command=self._on_interval_change).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._interval_lbl = tk.Label(slider_frame, text="15s",
                                      font=("Menlo", 11), fg=TEXT_SEC, bg=BG, width=4)
        self._interval_lbl.pack(side=tk.LEFT, padx=6)

        tk.Frame(inner, bg=BORDER, height=1).pack(fill=tk.X, pady=12)

        tk.Label(inner, text="Automated Fixes", font=("Menlo", 12, "bold"),
                 fg=TEXT_PRI, bg=BG).pack(anchor="w")
        tk.Label(inner, text="When disabled, issues are logged but no fixes are attempted.",
                 font=("Menlo", 10), fg=TEXT_SEC, bg=BG).pack(anchor="w", pady=(2, 8))

        self._autofix_var = tk.BooleanVar(value=True)
        tk.Checkbutton(inner, text="Enable automated fixes",
                       variable=self._autofix_var,
                       font=("Menlo", 11), fg=TEXT_PRI, bg=BG,
                       selectcolor=BG_LIGHT, activebackground=BG,
                       command=self._on_autofix_change).pack(anchor="w")

        tk.Frame(inner, bg=BORDER, height=1).pack(fill=tk.X, pady=12)

        tk.Label(inner, text="Log File", font=("Menlo", 12, "bold"),
                 fg=TEXT_PRI, bg=BG).pack(anchor="w")
        tk.Label(inner, text=str(self.log.log_path), font=("Menlo", 10),
                 fg=BLUE, bg=BG, cursor="hand2").pack(anchor="w", pady=(4, 0))

    # ── Authentication ───────────────────────────────────────────────────────

    def _authenticate(self):
        """Show password dialog at launch. Required for all automated fixes."""
        dialog = _PasswordDialog(self.root)
        password = dialog.result

        if not password:
            messagebox.showwarning(
                "No Admin Password",
                "NetWatch will run in log-only mode.\n"
                "Automated fixes require admin access."
            )
            self.log.warning("Started without admin password — automated fixes disabled")
            return

        if self.sudo.authenticate(password):
            self.log.success("Admin authentication successful — automated fixes enabled")
        else:
            messagebox.showerror(
                "Authentication Failed",
                "Incorrect password. NetWatch will run in log-only mode."
            )
            self.log.error("Admin authentication failed — automated fixes disabled")

    # ── Monitor control ──────────────────────────────────────────────────────

    def _start_monitor(self):
        self.monitor = MonitorThread(
            sudo=self.sudo,
            log=self.log,
            interval=self._interval_var.get(),
            on_state_change=self._on_state_change,
        )
        self.monitor.FIX_ENABLED = self._autofix_var.get() and self.sudo.authenticated
        self.monitor.start()
        self._update_strip()

    def _toggle_pause(self):
        if not self.monitor:
            return
        if self._paused:
            self.monitor.resume()
            self._pause_btn.config(text="⏸  Pause")
            self._paused = False
        else:
            self.monitor.pause()
            self._pause_btn.config(text="▶  Resume")
            self._paused = True

    def _on_state_change(self, state: MonitorState):
        """Called from monitor thread — schedule UI update on main thread."""
        self.root.after(0, self._update_status_ui, state)

    def _update_status_ui(self, state: MonitorState):
        color = STATUS_COLORS.get(state, TEXT_SEC)
        label = STATUS_LABELS.get(state, str(state.value))
        self._status_dot.config(fg=color)
        self._status_label.config(text=label, fg=color)

    def _update_strip(self):
        """Update interface/IP info strip. Scheduled every 5s."""
        try:
            iface = get_active_interface()
            info = check_wifi_interface(iface)
            ip = info.get("ip", "no IP")
            self._strip_label.config(
                text=f"{iface} · {ip}",
                fg=TEXT_SEC if info.get("ok") else AMBER
            )
        except Exception:
            pass
        self.root.after(5000, self._update_strip)

    # ── Log queue polling ────────────────────────────────────────────────────

    def _poll_log_queue(self):
        """Drain the log queue and write to the Events text widget."""
        try:
            while True:
                event = self.log.ui_queue.get_nowait()
                self._append_event(event)
        except Exception:
            pass
        self.root.after(200, self._poll_log_queue)

    def _append_event(self, event: dict):
        self._event_log.config(state=tk.NORMAL)
        self._event_log.insert(tk.END, f"{event['timestamp']} ", "TIMESTAMP")
        level_tag = event.get("level", "INFO")
        self._event_log.insert(tk.END,
                               f"[{level_tag:<7}] {event['message']}\n", level_tag)
        self._event_log.see(tk.END)
        self._event_log.config(state=tk.DISABLED)

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def _run_diagnostics_now(self):
        def _run():
            self.log.info("Running manual diagnostics...")
            result = self.monitor.run_diagnostics()
            self.root.after(0, self._show_diagnostics, result)

        threading.Thread(target=_run, daemon=True).start()
        self._notebook.select(1)  # Switch to Diagnostics tab

    def _show_diagnostics(self, result):
        check_map = {
            "wifi":    result.wifi,
            "gateway": result.gateway,
            "dns":     result.dns,
            "latency": result.latency,
            "captive": result.captive,
        }
        for key, data in check_map.items():
            ok     = data.get("ok", True)
            detail = data.get("detail", "—")
            icon   = "✓" if ok else "✗"
            color  = GREEN if ok else RED
            self._diag_rows[key].config(text=f"{icon}  {detail}", fg=color)

    # ── Settings callbacks ───────────────────────────────────────────────────

    def _on_interval_change(self, val):
        secs = int(float(val))
        self._interval_lbl.config(text=f"{secs}s")
        if self.monitor:
            self.monitor.set_interval(secs)

    def _on_autofix_change(self):
        if self.monitor:
            self.monitor.FIX_ENABLED = self._autofix_var.get() and self.sudo.authenticated
            state = "enabled" if self.monitor.FIX_ENABLED else "disabled"
            self.log.info(f"Automated fixes {state}")

    # ── Utilities ────────────────────────────────────────────────────────────

    def _open_log_file(self):
        subprocess.run(["open", str(self.log.log_path)])

    def on_close(self):
        if self.monitor:
            self.monitor.stop()
        self.sudo.clear()
        self.root.destroy()


class _PasswordDialog(simpledialog.Dialog):
    """Native-style password prompt at launch."""

    def body(self, master):
        tk.Label(master,
                 text="NetWatch needs your admin password\nto apply automated network fixes.",
                 justify=tk.CENTER).grid(row=0, column=0, columnspan=2, pady=(0, 12))
        tk.Label(master, text="Password:").grid(row=1, column=0, sticky=tk.W)
        self._entry = tk.Entry(master, show="•", width=28)
        self._entry.grid(row=1, column=1, padx=6)
        return self._entry

    def apply(self):
        self.result = self._entry.get()

    def cancel(self):
        self.result = None
        super().cancel()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    app = NetWatchApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
