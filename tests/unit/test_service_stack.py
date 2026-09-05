import aws_cdk as cdk
import aws_cdk.assertions as assertions
import pytest

from src.network_stack import NetworkStack
from src.ecs_stack import EcsStack
from src.service_props import ServiceProps, ServiceSecret, ContainerVolume
from src.service_stack import ServiceStack


def _build_stack_with_location(container_location: str) -> ServiceStack:
    """Create a ServiceStack using the given container_location."""
    cdk_app = cdk.App()
    network_stack = NetworkStack(cdk_app, "NetworkStack", vpc_cidr="10.254.192.0/24")
    ecs_stack = EcsStack(
        cdk_app, "EcsStack", vpc=network_stack.vpc, namespace="dev.app.io"
    )
    app_props = ServiceProps(
        container_name="app",
        container_location=container_location,
        container_port=8010,
        ecs_task_cpu=256,
        ecs_task_memory=512,
    )
    return ServiceStack(
        scope=cdk_app,
        construct_id="app",
        vpc=network_stack.vpc,
        cluster=ecs_stack.cluster,
        props=app_props,
    )


def test_service_stack_created():
    cdk_app = cdk.App()
    vpc_cidr = "10.254.192.0/24"
    network_stack = NetworkStack(cdk_app, "NetworkStack", vpc_cidr=vpc_cidr)
    ecs_stack = EcsStack(
        cdk_app, "EcsStack", vpc=network_stack.vpc, namespace="dev.app.io"
    )

    app_props = ServiceProps(
        container_name="app",
        container_location="ghcr.io/sage-bionetworks/app:1.0",
        container_port=8010,
        ecs_task_cpu=256,
        ecs_task_memory=512,
        container_secrets=[
            ServiceSecret(
                secret_name="/app/secret",
                environment_key="APP_SECRET",
            )
        ],
        container_volumes=[ContainerVolume(path="/work")],
        container_command=["test"],
        container_healthcheck=cdk.aws_ecs.HealthCheck(command=["CMD", "/healthcheck"]),
    )
    app_stack = ServiceStack(
        scope=cdk_app,
        construct_id="app",
        vpc=network_stack.vpc,
        cluster=ecs_stack.cluster,
        props=app_props,
    )

    template = assertions.Template.from_stack(app_stack)
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": [
                {
                    "Image": "ghcr.io/sage-bionetworks/app:1.0",
                    "MountPoints": [{"ContainerPath": "/work"}],
                    "Secrets": [{"Name": "APP_SECRET"}],
                    "Command": ["test"],
                    "HealthCheck": {"Command": ["CMD", "/healthcheck"]},
                }
            ],
            "Cpu": "256",
            "Memory": "512",
        },
    )


def test_container_healthcheck_renders_with_durations():
    """A HealthCheck with durations renders command + interval/timeout/retries.

    Mirrors the /health probe wired up in app.py so the full shape
    (command plus the second-valued duration fields) is covered, not
    just the command.
    """
    cdk_app = cdk.App()
    network_stack = NetworkStack(cdk_app, "NetworkStack", vpc_cidr="10.254.192.0/24")
    ecs_stack = EcsStack(
        cdk_app, "EcsStack", vpc=network_stack.vpc, namespace="dev.app.io"
    )

    app_props = ServiceProps(
        container_name="app",
        container_location="ghcr.io/sage-bionetworks/app:1.0",
        container_port=8080,
        ecs_task_cpu=256,
        ecs_task_memory=512,
        container_healthcheck=cdk.aws_ecs.HealthCheck(
            command=[
                "CMD-SHELL",
                'python -c "import urllib.request; '
                "urllib.request.urlopen('http://localhost:8080/health')\"",
            ],
            interval=cdk.Duration.seconds(30),
            timeout=cdk.Duration.seconds(5),
            start_period=cdk.Duration.seconds(10),
            retries=3,
        ),
    )
    app_stack = ServiceStack(
        scope=cdk_app,
        construct_id="app",
        vpc=network_stack.vpc,
        cluster=ecs_stack.cluster,
        props=app_props,
    )

    template = assertions.Template.from_stack(app_stack)
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": [
                {
                    "HealthCheck": {
                        "Command": [
                            "CMD-SHELL",
                            'python -c "import urllib.request; '
                            "urllib.request.urlopen('http://localhost:8080/health')\"",
                        ],
                        "Interval": 30,
                        "Timeout": 5,
                        "StartPeriod": 10,
                        "Retries": 3,
                    },
                }
            ],
        },
    )


def test_build_from_path_invalid_directory_raises():
    """A path:// location pointing at a non-existent directory raises ValueError."""
    with pytest.raises(ValueError, match="is not a valid directory"):
        _build_stack_with_location("path://this/does/not/exist")


def test_build_from_path_missing_dockerfile_raises(tmp_path):
    """A path:// location without a Dockerfile raises FileNotFoundError."""
    build_dir = tmp_path / "build_context"
    build_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="No Dockerfile found"):
        _build_stack_with_location(f"path://{build_dir}")


def test_build_from_path_with_dockerfile_succeeds(tmp_path):
    """A path:// location with a valid directory and Dockerfile builds an asset image."""
    build_dir = tmp_path / "build_context"
    build_dir.mkdir()
    (build_dir / "Dockerfile").write_text("FROM nginx:latest\n")

    app_stack = _build_stack_with_location(f"path://{build_dir}")

    template = assertions.Template.from_stack(app_stack)
    template.resource_count_is("AWS::ECS::TaskDefinition", 1)
