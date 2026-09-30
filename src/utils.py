import json
import logging
import os
import yaml
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def resolve_config_value(key: str, config: Dict[str, Any], default: Any = None) -> Any:
    """Resolve a configuration value using the precedence:

        OS environment variable  >  YAML config  >  default

    An OS environment variable named ``key`` takes highest precedence so a
    developer or CI job can override committed config at runtime without
    editing files. When the environment variable overrides a value that the
    YAML config also provided, the override is logged so it is not silent.

    Args:
      key: the configuration key / environment variable name.
      config: the merged YAML config dict (from ``load_context_config``).
      default: value to use when neither the env var nor the config is set.
    """
    env_value = os.environ.get(key)
    if env_value is not None:
        if key in config and config[key] != env_value:
            # Log the fact of the override but never the values: this helper is
            # generic, so a value routed through it may be sensitive. Logging
            # only the key keeps the guardrail without risking secret leakage.
            logger.info(
                "Config '%s' overridden by OS environment variable "
                "(ignoring the YAML config value)",
                key,
            )
        return env_value
    if key in config:
        return config[key]
    return default


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_context_config(env_name: str, config_dir: str = "config") -> Dict[str, Any]:
    """
    Load AWS CDK context configuration from a YAML or JSON file.

    Supports:
      - .yaml/.yml OR .json (but not both)
      - base.yaml merged with environment config
      - Only 'dev', 'stage', or 'prod' environments are valid

    Raises:
      - ValueError if environment is invalid or multiple config files exist
      - FileNotFoundError if expected config file not found
    """

    # ✅ Validate environment name
    VALID_ENVS = {"dev", "stage", "prod"}
    if env_name not in VALID_ENVS:
        raise ValueError(
            f"Invalid environment '{env_name}'. "
            f"Must be one of: {', '.join(sorted(VALID_ENVS))}"
        )

    # Define possible config paths
    base_path = Path(config_dir) / "base.yaml"
    env_yaml = Path(config_dir) / f"{env_name}.yaml"
    env_yml = Path(config_dir) / f"{env_name}.yml"
    env_json = Path(config_dir) / f"{env_name}.json"

    def read_file(path: Path) -> Dict[str, Any]:
        """Read YAML or JSON file into a dictionary."""
        with open(path, "r") as f:
            if path.suffix in (".yaml", ".yml"):
                return yaml.safe_load(f) or {}
            elif path.suffix == ".json":
                return json.load(f)
            else:
                raise ValueError(f"Unsupported config file type: {path.suffix}")

    # Load base config (optional)
    base_config = {}
    if base_path.exists():
        base_config = read_file(base_path)

    # Detect existing env-specific file(s)
    env_files = [p for p in [env_yaml, env_yml, env_json] if p.exists()]

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

    # Load and merge configs
    env_config = read_file(env_files[0])
    merged_config = _deep_merge(base_config, env_config)

    return merged_config
