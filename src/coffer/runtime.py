from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gunicorn.app.base import BaseApplication


class RuntimeConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WSGIServerSettings:
    host: str
    port: int
    workers: int
    threads: int
    timeout_seconds: int
    graceful_timeout_seconds: int
    keepalive_seconds: int
    tls_certfile: str | None
    tls_keyfile: str | None

    @classmethod
    def from_options(cls, options: Any) -> WSGIServerSettings:
        host = options.bind_host
        if (
            not host
            or host.strip() != host
            or "/" in host
            or "\x00" in host
        ):
            raise RuntimeConfigurationError("bind_host is invalid")
        tls_certfile = getattr(options, "tls_certfile", None)
        tls_keyfile = getattr(options, "tls_keyfile", None)
        if bool(tls_certfile) != bool(tls_keyfile):
            raise RuntimeConfigurationError(
                "TLS certificate and key must be configured together"
            )
        return cls(
            host=host,
            port=options.bind_port,
            workers=options.workers,
            threads=options.threads,
            timeout_seconds=options.timeout_seconds,
            graceful_timeout_seconds=options.graceful_timeout_seconds,
            keepalive_seconds=options.keepalive_seconds,
            tls_certfile=tls_certfile,
            tls_keyfile=tls_keyfile,
        )

    @property
    def bind(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"

    def gunicorn_options(self) -> dict[str, object]:
        options: dict[str, object] = {
            "bind": self.bind,
            "workers": self.workers,
            "worker_class": "gthread",
            "threads": self.threads,
            "preload_app": False,
            "timeout": self.timeout_seconds,
            "graceful_timeout": self.graceful_timeout_seconds,
            "keepalive": self.keepalive_seconds,
            "accesslog": None,
            "errorlog": "-",
            "capture_output": False,
            "umask": 0o027,
        }
        if self.tls_certfile is not None:
            options["certfile"] = self.tls_certfile
            options["keyfile"] = self.tls_keyfile
        return options


class WSGIApplication(BaseApplication):
    def __init__(
        self,
        application: Any,
        settings: WSGIServerSettings,
    ) -> None:
        self._application = application
        self._options = settings.gunicorn_options()
        super().__init__()

    def load_config(self) -> None:
        for name, value in self._options.items():
            if name in self.cfg.settings:
                self.cfg.set(name, value)

    def load(self) -> Any:
        return self._application


def run_wsgi(application: Any, settings: WSGIServerSettings) -> None:
    WSGIApplication(application, settings).run()
