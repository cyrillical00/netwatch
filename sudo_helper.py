import subprocess
import threading


class SudoSession:
    """
    Holds admin credentials for the session.
    Password lives only in memory — cleared on close().
    """

    def __init__(self):
        self._password: str | None = None
        self._lock = threading.Lock()

    def authenticate(self, password: str) -> bool:
        """Validate the password by running a harmless sudo command."""
        result = subprocess.run(
            ["sudo", "-S", "echo", "ok"],
            input=password + "\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            with self._lock:
                self._password = password
            return True
        return False

    @property
    def authenticated(self) -> bool:
        return self._password is not None

    def run(self, cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """Run a command with sudo. Raises RuntimeError if not authenticated."""
        with self._lock:
            if not self._password:
                raise RuntimeError("Not authenticated")
            pw = self._password

        return subprocess.run(
            ["sudo", "-S"] + cmd,
            input=pw + "\n",
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def clear(self):
        with self._lock:
            self._password = None
