"""First-run desktop setup and foreground runner for a DEN node."""

from __future__ import annotations

import logging
import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from monitor.client import MonitorRequestError
from node.agent import AgentConfig, NodeAgent


def _data_directory() -> Path:
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA")
        if root:
            return Path(root) / "DEN"
    root = os.environ.get("XDG_DATA_HOME")
    if root:
        return Path(root) / "den"
    return Path.home() / ".local" / "share" / "den"


class _QueueHandler(logging.Handler):
    def __init__(self, messages: queue.Queue[str]) -> None:
        super().__init__()
        self.messages = messages

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.put(self.format(record))


class NodeSetupApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("DEN Node")
        self.root.minsize(520, 460)
        self.data_directory = _data_directory()
        self.settings_path = self.data_directory / "settings.json"
        self.messages: queue.Queue[str] = queue.Queue()
        self.agent: NodeAgent | None = None
        self.agent_thread: threading.Thread | None = None
        self._handler = _QueueHandler(self.messages)
        self._handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        logging.getLogger().addHandler(self._handler)
        logging.getLogger().setLevel(logging.INFO)

        frame = ttk.Frame(root, padding=16)
        frame.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)

        ttk.Label(frame, text="Join a DEN monitoring server", font=("TkDefaultFont", 14, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12)
        )
        self.name = tk.StringVar(value=os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "DEN-node")
        self.url = tk.StringVar()
        self.code = tk.StringVar()
        self.ca_path = tk.StringVar()
        self._load_settings()
        self._field(frame, 1, "Node name", self.name)
        self._field(frame, 2, "Monitor URL", self.url)
        ttk.Label(frame, text="Example: https://192.168.1.10:8443", foreground="#666").grid(
            row=2, column=1, columnspan=2, sticky="w"
        )
        self._field(frame, 3, "Enrollment code", self.code)

        ttk.Label(frame, text="Monitor CA certificate (public .crt/.pem file)").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(8, 2)
        )
        ttk.Entry(frame, textvariable=self.ca_path).grid(row=5, column=0, columnspan=2, sticky="ew")
        self.browse_button = ttk.Button(frame, text="Browse…", command=self._browse_ca)
        self.browse_button.grid(row=5, column=2, padx=(8, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=3, sticky="ew", pady=12)
        self.start_button = ttk.Button(buttons, text="Connect", command=self._start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(buttons, text="Stop", command=self._stop, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        ttk.Label(frame, text="Status and connection messages").grid(
            row=7, column=0, columnspan=3, sticky="w"
        )
        self.status = tk.Text(frame, height=10, state="disabled", wrap="word")
        self.status.grid(row=8, column=0, columnspan=3, sticky="nsew")
        frame.rowconfigure(8, weight=1)

        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(150, self._drain_messages)

    @staticmethod
    def _field(
        parent: ttk.Frame,
        row: int,
        title: str,
        variable: tk.StringVar,
    ) -> None:
        ttk.Label(parent, text=title).grid(row=row, column=0, sticky="w", pady=4)
        entry = ttk.Entry(parent, textvariable=variable, show="*" if title == "Enrollment code" else "")
        entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)

    def _browse_ca(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select the DEN monitor CA certificate",
            filetypes=(("CA certificates", "*.crt *.pem"), ("All files", "*")),
        )
        if selected:
            self.ca_path.set(selected)

    def _load_settings(self) -> None:
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        except (OSError, json.JSONDecodeError) as exc:
            logging.warning("Could not load saved setup: %s", exc)
            data = {}
        if isinstance(data, dict):
            name, url = data.get("node_name"), data.get("monitor_url")
            if isinstance(name, str) and name:
                self.name.set(name)
            if isinstance(url, str):
                self.url.set(url)
        installed_ca = self.data_directory / "monitor-ca.crt"
        if installed_ca.is_file():
            self.ca_path.set(str(installed_ca))

    def _save_settings(self, node_name: str, monitor_url: str, ca_path: Path) -> None:
        self.data_directory.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps(
                {"node_name": node_name, "monitor_url": monitor_url, "monitor_ca_file": str(ca_path)},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if os.name != "nt":
            self.settings_path.chmod(0o600)

    def _start(self) -> None:
        node_name, monitor_url, code, ca_path = (
            self.name.get().strip(),
            self.url.get().strip(),
            self.code.get().strip(),
            Path(self.ca_path.get()).expanduser(),
        )
        if not node_name or not ca_path.is_file():
            messagebox.showerror("Setup incomplete", "Enter a node name and choose the CA certificate.")
            return

        self.data_directory.mkdir(parents=True, exist_ok=True)
        identity_directory = self.data_directory / "identity"
        credential_file = identity_directory / "monitor-credential.json"
        if not code and not credential_file.is_file():
            messagebox.showerror("Enrollment code required", "Enter the one-time enrollment code for this device.")
            return
        installed_ca = self.data_directory / "monitor-ca.crt"
        try:
            installed_ca.write_bytes(ca_path.read_bytes())
            self._save_settings(node_name, monitor_url, installed_ca)
            config = AgentConfig(
                node_name=node_name,
                data_dir=identity_directory,
                monitor_url=monitor_url,
                monitor_ca_file=installed_ca,
                heartbeat_interval_seconds=5,
                protocol_version="0.1",
            )
            agent = NodeAgent(config)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Cannot start DEN node", str(exc))
            return

        self.code.set("")
        self.agent = agent
        self.agent_thread = threading.Thread(
            target=self._run_agent,
            args=(agent, code),
            name="den-node-agent",
            daemon=True,
        )
        self.agent_thread.start()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.messages.put("Connecting. The enrollment code is used only if this device is not enrolled yet.")

    def _run_agent(self, agent: NodeAgent, code: str) -> None:
        try:
            agent.run(code)
        except (OSError, RuntimeError, ValueError, MonitorRequestError) as exc:
            logging.error("Node stopped: %s", exc)
        finally:
            self.messages.put("__agent_stopped__")

    def _stop(self) -> None:
        if self.agent is not None:
            self.agent.stop()
            self.stop_button.configure(state="disabled")
            self.messages.put("Stopping node…")

    def _reset_buttons(self) -> None:
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def _drain_messages(self) -> None:
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            if message == "__agent_stopped__":
                self._reset_buttons()
                continue
            self.status.configure(state="normal")
            self.status.insert("end", message + "\n")
            self.status.see("end")
            self.status.configure(state="disabled")
        self.root.after(150, self._drain_messages)

    def _close(self) -> None:
        if self.agent is not None:
            self.agent.stop()
        logging.getLogger().removeHandler(self._handler)
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    NodeSetupApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
