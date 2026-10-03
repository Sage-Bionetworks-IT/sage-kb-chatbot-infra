import json
import tempfile
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.utils import Settings, _deep_merge, load_context_config

# A minimal set of required fields so test configs validate.
REQUIRED = {"FQDN": "example.com", "VPC_CIDR": "10.0.0.0/16"}


def _write(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        if path.suffix == ".json":
            json.dump(data, f)
        else:
            yaml.dump(data, f)


class TestDeepMerge:
    """Test suite for the _deep_merge function."""

    def test_flat_merge(self):
        """Merging flat dicts behaves like shallow merge."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        assert _deep_merge(base, override) == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge_preserves_base_keys(self):
        """Nested override only replaces specified keys."""
        base = {
            "MONITORING": {
                "notification_email": "",
                "alarms": {"ecs_cpu_threshold": 80, "ecs_memory_threshold": 80},
            }
        }
        override = {"MONITORING": {"notification_email": "team@example.com"}}
        result = _deep_merge(base, override)
        assert result["MONITORING"]["notification_email"] == "team@example.com"
        assert result["MONITORING"]["alarms"]["ecs_cpu_threshold"] == 80
        assert result["MONITORING"]["alarms"]["ecs_memory_threshold"] == 80

    def test_nested_merge_overrides_specific_keys(self):
        """Specific nested keys can be overridden."""
        base = {"alarms": {"cpu": 80, "memory": 80}}
        override = {"alarms": {"cpu": 70}}
        assert _deep_merge(base, override) == {"alarms": {"cpu": 70, "memory": 80}}

    def test_does_not_mutate_base(self):
        """The base dict is not modified."""
        base = {"a": {"b": 1}}
        _deep_merge(base, {"a": {"b": 2}})
        assert base == {"a": {"b": 1}}

    def test_override_dict_with_non_dict(self):
        """A non-dict value replaces a dict value."""
        base = {"a": {"b": 1}}
        assert _deep_merge(base, {"a": "string"}) == {"a": "string"}


class TestLoadContextConfig:
    """Test suite for load_context_config, which returns a typed Settings."""

    @pytest.mark.parametrize(
        "invalid_env", ["invalid", "test", "production", "development", ""]
    )
    def test_invalid_environment_raises_value_error(self, invalid_env):
        """Invalid environment names raise ValueError."""
        with pytest.raises(ValueError, match=f"Invalid environment '{invalid_env}'"):
            load_context_config(invalid_env)

    @pytest.mark.parametrize("valid_env", ["dev", "stage", "prod"])
    def test_valid_environments(self, valid_env):
        """Valid environment names load their config file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            _write(
                Path(temp_dir) / f"{valid_env}.yaml",
                {**REQUIRED, "FQDN": f"{valid_env}.example.com"},
            )
            result = load_context_config(valid_env, temp_dir)
            assert isinstance(result, Settings)
            assert result.FQDN == f"{valid_env}.example.com"

    def test_returns_settings_instance(self):
        """The loader returns a typed Settings object with attribute access."""
        with tempfile.TemporaryDirectory() as temp_dir:
            _write(Path(temp_dir) / "dev.yaml", REQUIRED)
            result = load_context_config("dev", temp_dir)
            assert isinstance(result, Settings)
            assert result.VPC_CIDR == "10.0.0.0/16"

    def test_no_config_file_raises_file_not_found_error(self):
        """Missing config files raise FileNotFoundError."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(
                FileNotFoundError, match="No config file found for environment 'dev'"
            ):
                load_context_config("dev", temp_dir)

    @pytest.mark.parametrize(
        "file_extensions", [(".yaml", ".json"), (".yaml", ".yml"), (".yml", ".json")]
    )
    def test_multiple_config_files_raises_value_error(self, file_extensions):
        """Multiple config files for the same environment raise ValueError."""
        with tempfile.TemporaryDirectory() as temp_dir:
            ext1, ext2 = file_extensions
            _write(Path(temp_dir) / f"dev{ext1}", {"test": "file1"})
            _write(Path(temp_dir) / f"dev{ext2}", {"test": "file2"})
            with pytest.raises(
                ValueError, match="Multiple config files found for environment 'dev'"
            ):
                load_context_config("dev", temp_dir)

    @pytest.mark.parametrize("file_extension", [".yaml", ".yml", ".json"])
    def test_load_config_file_formats(self, file_extension):
        """Config loads from .yaml, .yml, and .json env files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            _write(Path(temp_dir) / f"dev{file_extension}", REQUIRED)
            result = load_context_config("dev", temp_dir)
            assert result.FQDN == "example.com"
            assert result.VPC_CIDR == "10.0.0.0/16"

    def test_required_field_missing_raises_validation_error(self):
        """A missing required value (FQDN) raises a pydantic ValidationError."""
        with tempfile.TemporaryDirectory() as temp_dir:
            _write(Path(temp_dir) / "dev.yaml", {"VPC_CIDR": "10.0.0.0/16"})
            with pytest.raises(ValidationError, match="FQDN"):
                load_context_config("dev", temp_dir)

    def test_env_file_overrides_base(self):
        """The environment file overrides base.yaml on conflicting keys."""
        with tempfile.TemporaryDirectory() as temp_dir:
            _write(
                Path(temp_dir) / "base.yaml",
                {"VPC_CIDR": "10.0.0.0/16", "ATLASSIAN_CLOUD_ID": "from-base"},
            )
            _write(
                Path(temp_dir) / "dev.yaml",
                {"FQDN": "dev.example.com", "ATLASSIAN_CLOUD_ID": "from-env"},
            )
            result = load_context_config("dev", temp_dir)
            assert result.VPC_CIDR == "10.0.0.0/16"  # inherited from base
            assert result.ATLASSIAN_CLOUD_ID == "from-env"  # env overrides base

    def test_base_config_deep_merging(self):
        """Nested dicts (MONITORING) are deep-merged across base and env."""
        with tempfile.TemporaryDirectory() as temp_dir:
            _write(
                Path(temp_dir) / "base.yaml",
                {
                    "MONITORING": {
                        "notification_email": "",
                        "alarms": {
                            "ecs_cpu_threshold": 80,
                            "ecs_memory_threshold": 80,
                        },
                    }
                },
            )
            _write(
                Path(temp_dir) / "dev.yaml",
                {
                    **REQUIRED,
                    "MONITORING": {
                        "notification_email": "team@example.com",
                        "alarms": {"ecs_cpu_threshold": 70},
                    },
                },
            )
            result = load_context_config("dev", temp_dir)
            assert result.MONITORING["notification_email"] == "team@example.com"
            # overridden nested value
            assert result.MONITORING["alarms"]["ecs_cpu_threshold"] == 70
            # inherited nested value preserved by the deep merge
            assert result.MONITORING["alarms"]["ecs_memory_threshold"] == 80

    def test_json_env_file_deep_merges_with_yaml_base(self):
        """A JSON env file deep-merges with the YAML base."""
        with tempfile.TemporaryDirectory() as temp_dir:
            _write(
                Path(temp_dir) / "base.yaml",
                {"MONITORING": {"enabled": False, "alarms": {"ecs_cpu_threshold": 80}}},
            )
            _write(
                Path(temp_dir) / "dev.json",
                {
                    **REQUIRED,
                    "MONITORING": {
                        "enabled": True,
                        "alarms": {"ecs_cpu_threshold": 70},
                    },
                },
            )
            result = load_context_config("dev", temp_dir)
            assert result.MONITORING["enabled"] is True
            assert result.MONITORING["alarms"]["ecs_cpu_threshold"] == 70

    def test_no_base_config(self):
        """Config loads when base.yaml does not exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            _write(Path(temp_dir) / "dev.yaml", {**REQUIRED, "FQDN": "dev.example.com"})
            result = load_context_config("dev", temp_dir)
            assert result.FQDN == "dev.example.com"

    def test_empty_base_config(self):
        """An empty base.yaml is treated as no defaults."""
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "base.yaml").write_text("")
            _write(Path(temp_dir) / "dev.yaml", {**REQUIRED, "FQDN": "dev.example.com"})
            result = load_context_config("dev", temp_dir)
            assert result.FQDN == "dev.example.com"

    def test_empty_env_config_falls_back_to_base(self):
        """An empty env file falls back to values from base.yaml."""
        with tempfile.TemporaryDirectory() as temp_dir:
            _write(
                Path(temp_dir) / "base.yaml", {**REQUIRED, "FQDN": "base.example.com"}
            )
            (Path(temp_dir) / "dev.yaml").write_text("")
            result = load_context_config("dev", temp_dir)
            assert result.FQDN == "base.example.com"

    def test_custom_config_dir(self):
        """A custom config directory is honored."""
        with tempfile.TemporaryDirectory() as temp_dir:
            custom = Path(temp_dir) / "custom_config"
            custom.mkdir()
            _write(custom / "dev.yaml", {**REQUIRED, "FQDN": "custom.example.com"})
            result = load_context_config("dev", str(custom))
            assert result.FQDN == "custom.example.com"

    def test_os_env_var_overrides_yaml(self, monkeypatch):
        """An OS environment variable wins over a value from YAML config."""
        monkeypatch.setenv("FQDN", "env.example.com")
        with tempfile.TemporaryDirectory() as temp_dir:
            _write(
                Path(temp_dir) / "dev.yaml", {**REQUIRED, "FQDN": "yaml.example.com"}
            )
            result = load_context_config("dev", temp_dir)
            assert result.FQDN == "env.example.com"

    def test_os_env_var_used_when_absent_from_yaml(self, monkeypatch):
        """An OS environment variable supplies a value absent from YAML."""
        monkeypatch.setenv("ATLASSIAN_SERVICE_USER", "svc@example.com")
        with tempfile.TemporaryDirectory() as temp_dir:
            _write(Path(temp_dir) / "dev.yaml", REQUIRED)
            result = load_context_config("dev", temp_dir)
            assert result.ATLASSIAN_SERVICE_USER == "svc@example.com"

    @pytest.mark.parametrize(
        "file_extension,invalid_content,expected_exception",
        [
            (".yaml", "invalid: yaml: content: [unclosed", yaml.YAMLError),
            (".yml", "invalid: yaml: content: [unclosed", yaml.YAMLError),
            (".json", '{"invalid": json content}', json.JSONDecodeError),
        ],
    )
    def test_invalid_config_content(
        self, file_extension, invalid_content, expected_exception
    ):
        """Malformed config file content raises a parse error."""
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / f"dev{file_extension}").write_text(invalid_content)
            with pytest.raises(expected_exception):
                load_context_config("dev", temp_dir)


class TestContainerLocationDefault:
    """CONTAINER_LOCATION is derived from APP_VERSION unless set explicitly."""

    def test_defaults_to_latest(self):
        """With no overrides the image tag is :latest."""
        with tempfile.TemporaryDirectory() as temp_dir:
            _write(Path(temp_dir) / "dev.yaml", REQUIRED)
            result = load_context_config("dev", temp_dir)
            assert (
                result.CONTAINER_LOCATION
                == "ghcr.io/sage-bionetworks-it/sage-kb-chatbot:latest"
            )

    def test_app_version_bumps_image_tag(self):
        """Setting APP_VERSION (and not CONTAINER_LOCATION) bumps the tag."""
        with tempfile.TemporaryDirectory() as temp_dir:
            _write(Path(temp_dir) / "dev.yaml", {**REQUIRED, "APP_VERSION": "v1.2.3"})
            result = load_context_config("dev", temp_dir)
            assert (
                result.CONTAINER_LOCATION
                == "ghcr.io/sage-bionetworks-it/sage-kb-chatbot:v1.2.3"
            )

    def test_explicit_container_location_wins(self):
        """An explicit CONTAINER_LOCATION is not overwritten by the derivation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            _write(
                Path(temp_dir) / "dev.yaml",
                {
                    **REQUIRED,
                    "APP_VERSION": "v9",
                    "CONTAINER_LOCATION": "path://../app",
                },
            )
            result = load_context_config("dev", temp_dir)
            assert result.CONTAINER_LOCATION == "path://../app"
