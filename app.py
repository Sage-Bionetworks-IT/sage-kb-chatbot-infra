import aws_cdk as cdk
from aws_cdk import aws_ecs as ecs

from src.bedrock_agent_stack import BedrockAgentStack
from src.ecs_stack import EcsStack
from src.load_balancer_stack import LoadBalancerStack
from src.monitoring_stack import MonitoringStack
from src.network_stack import NetworkStack
from src.service_props import ServiceProps, ServiceSecret
from src.service_stack import LoadBalancedServiceStack
from src.utils import load_context_config

cdk_app = cdk.App()
env_name = cdk_app.node.try_get_context("env") or "dev"
config = load_context_config(env_name=env_name)
STACK_NAME_PREFIX = f"sage-kb-chatbot-{env_name}"
FQDN = config["FQDN"]
TAGS = config["TAGS"]
APP_VERSION = "latest"
MONITORING_CONFIG = config.get("MONITORING", {})

# recursively apply tags to all stack resources
if TAGS:
    for key, value in TAGS.items():
        cdk.Tags.of(cdk_app).add(key, value)

network_stack = NetworkStack(
    scope=cdk_app,
    construct_id=f"{STACK_NAME_PREFIX}-network",
    vpc_cidr=config["VPC_CIDR"],
)

bedrock_agent_stack = BedrockAgentStack(
    scope=cdk_app,
    construct_id=f"{STACK_NAME_PREFIX}-bedrock-agent",
)

ecs_stack = EcsStack(
    scope=cdk_app,
    construct_id=f"{STACK_NAME_PREFIX}-ecs",
    vpc=network_stack.vpc,
    namespace=FQDN,
    container_insights=bool(MONITORING_CONFIG.get("enabled", False)),
)
ecs_stack.add_dependency(bedrock_agent_stack)

# From AWS docs https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-connect-concepts-deploy.html
# The public discovery and reachability should be created last by AWS CloudFormation, including the frontend
# client service. The services need to be created in this order to prevent an time period when the frontend
# client service is running and available the public, but a backend isn't.
load_balancer_stack = LoadBalancerStack(
    scope=cdk_app,
    construct_id=f"{STACK_NAME_PREFIX}-load-balancer",
    vpc=network_stack.vpc,
)
load_balancer_stack.add_dependency(ecs_stack)

app_props = ServiceProps(
    container_name="sage-kb-chatbot",
    container_location=f"ghcr.io/sage-bionetworks-it/sage-kb-chatbot:{APP_VERSION}",
    container_port=8080,
    ecs_task_cpu=256,
    ecs_task_memory=512,
    container_env_vars={
        "APP_VERSION": APP_VERSION,
        "BEDROCK_AGENT_ID": bedrock_agent_stack.agent_id,
        "BEDROCK_AGENT_ALIAS_ID": bedrock_agent_stack.agent_alias_id,
        "ROVO_MCP_SERVER_URL": config.get(
            "ROVO_MCP_SERVER_URL", "https://mcp.atlassian.com/v1/mcp"
        ),
        "ATLASSIAN_CLOUD_ID": config.get("ATLASSIAN_CLOUD_ID", ""),
        "ATLASSIAN_SERVICE_USER": config.get("ATLASSIAN_SERVICE_USER", ""),
        "SLACK_AGENT_ROUTER_SECRET_ID": config.get(
            "SECRET_ID", "infra/slack-agent-router"
        ),
    },
    container_secrets=[
        ServiceSecret(
            secret_name=config.get("SECRET_ID", "infra/slack-agent-router"),
            environment_key="SLACK_AGENT_ROUTER_SECRETS",
        ),
    ],
    container_healthcheck=ecs.HealthCheck(
        command=[
            "CMD-SHELL",
            "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8080/health')\"",
        ],
        interval=cdk.Duration.seconds(30),
        timeout=cdk.Duration.seconds(5),
        start_period=cdk.Duration.seconds(10),
        retries=3,
    ),
)
app_stack = LoadBalancedServiceStack(
    scope=cdk_app,
    construct_id=f"{STACK_NAME_PREFIX}-app",
    vpc=network_stack.vpc,
    cluster=ecs_stack.cluster,
    props=app_props,
    load_balancer=load_balancer_stack.alb,
    health_check_path="/health",
)

# Grant the ECS task permission to invoke the Bedrock Agent
app_stack.task_definition.task_role.add_to_policy(
    cdk.aws_iam.PolicyStatement(
        actions=["bedrock:InvokeAgent"],
        resources=[
            f"arn:aws:bedrock:{cdk.Aws.REGION}:{cdk.Aws.ACCOUNT_ID}:agent-alias/*",
        ],
    )
)

if MONITORING_CONFIG.get("enabled", False):
    monitoring_stack = MonitoringStack(
        scope=cdk_app,
        construct_id=f"{STACK_NAME_PREFIX}-monitoring",
        service=app_stack.service,
        cluster=ecs_stack.cluster,
        load_balancer=load_balancer_stack.alb,
        target_group=app_stack.target_group,
        monitoring_config=MONITORING_CONFIG,
    )
    monitoring_stack.add_dependency(app_stack)

cdk_app.synth()
