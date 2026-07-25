from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gunicorn.app.base import BaseApplication


class RuntimeConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WSGIServerSettings:
    process_name: str
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
    def from_options(
        cls,
        options: Any,
        *,
        process_name: str,
    ) -> WSGIServerSettings:
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
        if (
            not process_name
            or process_name.strip() != process_name
            or any(character.isspace() for character in process_name)
        ):
            raise RuntimeConfigurationError("process_name is invalid")
        return cls(
            process_name=process_name,
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
            "proc_name": self.process_name,
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


def require_single_observable_worker(
    settings: WSGIServerSettings,
    *,
    metrics_enabled: bool,
) -> None:
    if metrics_enabled and settings.workers != 1:
        raise RuntimeConfigurationError(
            "production metrics require exactly one worker per container"
        )


class WSGIApplication(BaseApplication):
    def __init__(
        self,
        application: Any,
        settings: WSGIServerSettings,
    ) -> None:
        self._application = application
        self._options = settings.gunicorn_options()
        self._options["post_fork"] = self._post_fork
        super().__init__()

    def _post_fork(self, _server: object, _worker: object) -> None:
        mark_process_started = getattr(
            self._application,
            "mark_process_started",
            None,
        )
        if callable(mark_process_started):
            mark_process_started()

    def load_config(self) -> None:
        for name, value in self._options.items():
            if name in self.cfg.settings:
                self.cfg.set(name, value)

    def load(self) -> Any:
        return self._application


def run_wsgi(application: Any, settings: WSGIServerSettings) -> None:
    WSGIApplication(application, settings).run()
