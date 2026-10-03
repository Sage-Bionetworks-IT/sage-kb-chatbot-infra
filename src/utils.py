import logging
from pathlib import Path
from typing import Any, Dict, Tuple, Type

from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

logger = logging.getLogger(__name__)

VALID_ENVS = {"dev", "stage", "prod"}


class Settings(BaseSettings):
    """Typed deployment configuration.

    Values are resolved with the precedence (highest first):

        OS environment variable  >  {env}.yaml  >  base.yaml  >  field default

    An OS environment variable whose name matches a field (case-insensitive)
    overrides any value from the YAML files, letting a developer or CI job
    override committed config at runtime without editing files. The two YAML
    files are deep-merged so an environment file may override individual nested
    keys (e.g. a single ``MONITORING`` alarm threshold) while inheriting the
    rest of the defaults from ``base.yaml``.

    Build an instance with :func:`load_context_config`, which wires the correct
    per-environment YAML files into the settings sources.
    """

    model_config = SettingsConfigDict(
        extra="allow",
        case_sensitive=True,
    )

    # Required scalars — no default: a missing value must fail loudly rather
    # than synthesize bad network/DNS wiring.
    FQDN: str = Field(...)
    VPC_CIDR: str = Field(...)

    # Optional scalars with defaults mirroring the previous app.py fallbacks.
    APP_VERSION: str = "latest"
    # Default is derived from APP_VERSION (see validator below) unless an
    # explicit value is provided via env var or YAML config. None is a sentinel
    # meaning "not set"; it is replaced before the model is used.
    CONTAINER_LOCATION: str | None = None
    BEDROCK_AGENT_ID: str = ""
    BEDROCK_AGENT_ALIAS_ID: str = ""
    ROVO_MCP_SERVER_URL: str = "https://mcp.atlassian.com/v1/mcp"
    ATLASSIAN_CLOUD_ID: str = ""
    ATLASSIAN_SERVICE_USER: str = ""
    SLACK_AUTHORIZED_USERGROUPS: str = ""
    SLACK_AGENT_ROUTER_SECRET_ID: str = "infra/slack-agent-router"

    # Nested free-form structures. Kept as plain dicts so the YAML deep-merge
    # of base.yaml + {env}.yaml preserves nested defaults (e.g. MONITORING
    # alarm thresholds) and callers can use dict-style .get() access.
    TAGS: Dict[str, Any] = Field(default_factory=dict)
    MONITORING: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _default_container_location(self) -> "Settings":
        # Preserve the previous behavior: when CONTAINER_LOCATION is not set,
        # derive it from APP_VERSION so overriding only APP_VERSION still bumps
        # the image tag.
        if self.CONTAINER_LOCATION is None:
            self.CONTAINER_LOCATION = (
                f"ghcr.io/sage-bionetworks-it/sage-kb-chatbot:{self.APP_VERSION}"
            )
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        # init kwargs win (used to inject the resolved file paths), then OS env
        # vars, then the YAML files (base + env, deep-merged). Earlier sources
        # take precedence, so an env var overrides any YAML value.
        config_files = init_settings.init_kwargs.pop("_config_files", [])
        file_source: PydanticBaseSettingsSource
        if config_files and str(config_files[-1]).endswith(".json"):
            # JSON env file (base is always YAML; only the env file may be JSON).
            file_source = _json_then_yaml_source(settings_cls, config_files)
        else:
            file_source = YamlConfigSettingsSource(
                settings_cls, yaml_file=config_files, deep_merge=True
            )
        return (init_settings, env_settings, file_source)


def _json_then_yaml_source(
    settings_cls: Type[BaseSettings], config_files: list
) -> PydanticBaseSettingsSource:
    """Build a source that deep-merges a YAML base with a JSON env file.

    ``base.yaml`` is always YAML; only the environment-specific file may be
    JSON. We load each with its matching source and merge them so the behavior
    matches a homogeneous YAML pair.
    """
    yaml_files = [p for p in config_files if str(p).endswith((".yaml", ".yml"))]
    json_files = [p for p in config_files if str(p).endswith(".json")]
    yaml_source = YamlConfigSettingsSource(
        settings_cls, yaml_file=yaml_files, deep_merge=True
    )
    json_source = JsonConfigSettingsSource(
        settings_cls, json_file=json_files, deep_merge=True
    )

    class _Merged(PydanticBaseSettingsSource):
        def get_field_value(self, field, field_name):  # pragma: no cover
            raise NotImplementedError

        def __call__(self) -> Dict[str, Any]:
            merged = yaml_source()
            return _deep_merge(merged, json_source())

    return _Merged(settings_cls)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_context_config(env_name: str, config_dir: str = "config") -> Settings:
    """Load AWS CDK deployment configuration as a typed :class:`Settings`.

    Resolution precedence (highest first):
        OS environment variable  >  {env}.yaml  >  base.yaml  >  field default

    Supports:
      - ``base.yaml`` (optional) deep-merged with one environment file
      - the environment file as ``.yaml``/``.yml`` OR ``.json`` (not both)
      - only ``dev``, ``stage``, or ``prod`` environments

    Raises:
      - ValueError if the environment is invalid or multiple env files exist
      - FileNotFoundError if no environment file is found
      - pydantic.ValidationError if a required value (FQDN, VPC_CIDR) is missing
    """
    if env_name not in VALID_ENVS:
        raise ValueError(
            f"Invalid environment '{env_name}'. "
            f"Must be one of: {', '.join(sorted(VALID_ENVS))}"
        )

    config_path = Path(config_dir)
    base_yaml = config_path / "base.yaml"
    env_yaml = config_path / f"{env_name}.yaml"
    env_yml = config_path / f"{env_name}.yml"
    env_json = config_path / f"{env_name}.json"

    env_files = [p for p in (env_yaml, env_yml, env_json) if p.exists()]
    if not env_files:
        raise FileNotFoundError(
            f"No config file found for environment '{env_name}' "
            f"in {config_dir}. Expected one of: {env_yaml}, {env_yml}, {env_json}"
        )
    if len(env_files) > 1:
        raise ValueError(
            f"Multiple config files found for environment '{env_name}': {env_files}. "
            f"Use only one (.yaml/.yml OR .json)."
        )

    # base first (lowest file precedence), then the env file (overrides base).
    config_files = []
    if base_yaml.exists():
        config_files.append(base_yaml)
    config_files.append(env_files[0])

    return Settings(_config_files=config_files)
