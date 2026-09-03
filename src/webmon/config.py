"""Typed, validated application configuration.

Loaded from YAML/TOML into a tree of pydantic models. Secrets are referenced
with ``${ENV:VAR}`` placeholders and resolved from the environment at load
time, so no credential is ever stored in the config file.

The public entry point is :func:`load_settings`; everything else takes a
``Settings`` instance by dependency injection (no global state).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, Field, model_validator

# ``tomllib`` is stdlib from 3.11; on 3.10 TOML configs are simply unsupported.
# A ``sys.version_info`` guard (rather than try/except) keeps this branch
# statically analysable, so mypy type-checks cleanly against either version.
if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    tomllib = None

_ENV_PLACEHOLDER = re.compile(r"\$\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}")

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
CheckKind = Literal["http", "ssl", "dns", "ping", "port", "content", "api"]
ReportFormat = Literal["html", "json", "csv", "markdown", "pdf"]
AuthKind = Literal["none", "basic", "bearer", "apikey"]


class ConfigError(Exception):
    """Raised when configuration cannot be loaded or is invalid."""


def _resolve_env(obj: Any) -> Any:
    """Recursively replace ``${ENV:VAR}`` placeholders with env values."""
    if isinstance(obj, str):
        return _ENV_PLACEHOLDER.sub(lambda m: os.environ.get(m.group(1), ""), obj)
    if isinstance(obj, dict):
        return {k: _resolve_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env(v) for v in obj]
    return obj


# --------------------------------------------------------------------------- #
# Sub-models
# --------------------------------------------------------------------------- #
class AppConfig(BaseModel):
    environment: str = "production"
    data_dir: str = "."


class Defaults(BaseModel):
    interval_seconds: int = Field(default=60, ge=5)
    timeout_seconds: float = Field(default=10.0, gt=0, le=300)
    retries: int = Field(default=2, ge=0, le=10)
    retry_backoff_seconds: float = Field(default=0.5, ge=0)
    verify_ssl: bool = True
    follow_redirects: bool = True
    max_redirects: int = Field(default=5, ge=0, le=20)
    max_response_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    ssl_warning_days: int = Field(default=21, ge=1)
    domain_warning_days: int = Field(default=30, ge=1)
    max_response_time_ms: int = Field(default=3000, ge=1)
    user_agent: str = "WebsiteMonitoringAutomation/1.0"
    dns_servers: list[str] = Field(default_factory=list)


class PerformanceConfig(BaseModel):
    max_concurrency: int = Field(default=20, ge=1, le=500)
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)


class SecurityConfig(BaseModel):
    allowed_schemes: list[str] = Field(default_factory=lambda: ["http", "https"])
    block_private_networks: bool = True
    validate_redirects: bool = True
    allowlist_hosts: list[str] = Field(default_factory=list)
    blocklist_hosts: list[str] = Field(default_factory=lambda: ["169.254.169.254"])


class AuthConfig(BaseModel):
    type: AuthKind = "none"
    username: str = ""
    password: str = ""
    token: str = ""
    api_key_header: str = "X-API-Key"
    api_key: str = ""


class JsonPathCheck(BaseModel):
    path: str
    equals: Any = None
    exists: bool = True


class Target(BaseModel):
    name: str
    url: str
    enabled: bool = True
    checks: list[CheckKind] = Field(default_factory=lambda: cast("list[CheckKind]", ["http"]))
    expected_status: list[int] = Field(default_factory=lambda: [200])
    expected_keywords: list[str] = Field(default_factory=list)
    forbidden_keywords: list[str] = Field(default_factory=list)
    content_hash_check: bool = False
    dns_record_types: list[str] = Field(default_factory=lambda: ["A"])
    ports: list[int] = Field(default_factory=list)
    json_path_checks: list[JsonPathCheck] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)
    auth: AuthConfig = Field(default_factory=AuthConfig)

    # Optional per-target overrides (None => inherit from Defaults).
    interval_seconds: int | None = Field(default=None, ge=5)
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    verify_ssl: bool | None = None
    follow_redirects: bool | None = None
    max_response_time_ms: int | None = None
    ssl_warning_days: int | None = None

    @property
    def slug(self) -> str:
        """Stable identifier derived from the name (used as a DB/monitor key)."""
        return re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-") or "target"


class EmailChannel(BaseModel):
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    use_tls: bool = True          # STARTTLS on a plain connection (port 587/25)
    use_ssl: bool = False         # implicit TLS from the first byte (port 465)
    username: str = ""
    password: str = ""
    from_addr: str = ""
    to_addrs: list[str] = Field(default_factory=list)


class TelegramChannel(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


class WebhookLikeChannel(BaseModel):
    enabled: bool = False
    webhook_url: str = ""


class GenericWebhookChannel(BaseModel):
    enabled: bool = False
    url: str = ""
    secret: str = ""


class AlertChannels(BaseModel):
    email: EmailChannel = Field(default_factory=EmailChannel)
    telegram: TelegramChannel = Field(default_factory=TelegramChannel)
    slack: WebhookLikeChannel = Field(default_factory=WebhookLikeChannel)
    discord: WebhookLikeChannel = Field(default_factory=WebhookLikeChannel)
    webhook: GenericWebhookChannel = Field(default_factory=GenericWebhookChannel)


class AlertingConfig(BaseModel):
    enabled: bool = False
    failure_threshold: int = Field(default=2, ge=1)
    notify_on_recovery: bool = True
    renotify_seconds: int = Field(default=3600, ge=0)
    channels: AlertChannels = Field(default_factory=AlertChannels)


class DatabaseConfig(BaseModel):
    enabled: bool = True
    path: str = "database/webmon.db"
    retention_days: int = Field(default=90, ge=0)


class LoggingConfig(BaseModel):
    level: LogLevel = "INFO"
    console: bool = True
    directory: str = "logs"
    rotate_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    rotate_backup_count: int = Field(default=7, ge=0)
    date_stamped_files: bool = True
    audit_log: bool = True


class ReportConfig(BaseModel):
    formats: list[ReportFormat] = Field(
        default_factory=lambda: cast("list[ReportFormat]", ["html", "json"])
    )
    directory: str = "reports"
    export_directory: str = "exports"


class WebConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8899, ge=1, le=65535)
    api_token: str = ""
    enable_metrics: bool = True


class SchedulerConfig(BaseModel):
    enabled: bool = True


# --------------------------------------------------------------------------- #
# Root
# --------------------------------------------------------------------------- #
class Settings(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    defaults: Defaults = Field(default_factory=Defaults)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    targets: list[Target] = Field(default_factory=list)
    alerting: AlertingConfig = Field(default_factory=AlertingConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)

    base_dir: Path = Field(default_factory=Path.cwd)

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="after")
    def _resolve_base(self) -> Settings:
        base = Path(os.path.expandvars(self.app.data_dir)).expanduser()
        if not base.is_absolute():
            base = (self.base_dir / base).resolve()
        object.__setattr__(self, "base_dir", base)
        return self

    def _under_base(self, value: str) -> Path:
        p = Path(os.path.expandvars(value)).expanduser()
        return p if p.is_absolute() else (self.base_dir / p)

    @property
    def log_dir(self) -> Path:
        return self._under_base(self.logging.directory)

    @property
    def report_dir(self) -> Path:
        return self._under_base(self.report.directory)

    @property
    def export_dir(self) -> Path:
        return self._under_base(self.report.export_directory)

    @property
    def database_path(self) -> Path:
        return self._under_base(self.database.path)

    def ensure_directories(self) -> None:
        for directory in (self.log_dir, self.report_dir, self.export_dir):
            directory.mkdir(parents=True, exist_ok=True)
        if self.database.enabled:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)

    def enabled_targets(self) -> list[Target]:
        return [t for t in self.targets if t.enabled]


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def _read_mapping(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(raw) or {}
    elif suffix == ".toml":
        if tomllib is None:  # pragma: no cover
            raise ConfigError("TOML config requires Python 3.11+ (tomllib).")
        data = tomllib.loads(raw)
    else:
        raise ConfigError(f"Unsupported config format: {suffix!r}")
    if not isinstance(data, dict):
        raise ConfigError("Config root must be a mapping.")
    return data


def load_settings(
    config_path: str | os.PathLike[str] | None = None,
    *,
    base_dir: str | os.PathLike[str] | None = None,
) -> Settings:
    """Load and validate :class:`Settings` from a YAML/TOML file (or defaults)."""
    if config_path is None:
        data: dict[str, Any] = {}
        resolved_base = Path(base_dir).resolve() if base_dir else Path.cwd()
    else:
        path = Path(config_path).expanduser()
        if not path.is_file():
            raise ConfigError(f"Config file not found: {path}")
        data = _resolve_env(_read_mapping(path))
        if base_dir is not None:
            resolved_base = Path(base_dir).resolve()
        elif path.parent.name == "config":
            resolved_base = path.parent.parent.resolve()
        else:
            resolved_base = path.parent.resolve()

    data.setdefault("base_dir", resolved_base)
    try:
        return Settings.model_validate(data)
    except Exception as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc


def find_default_config(start: str | os.PathLike[str] | None = None) -> Path | None:
    """Locate ``config/config.yaml`` (then the example) walking upward."""
    current = Path(start).resolve() if start else Path.cwd()
    for directory in (current, *current.parents):
        for name in ("config/config.yaml", "config/config.yml", "config/config.example.yaml"):
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None
