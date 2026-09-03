import aws_cdk as cdk

from src.bedrock_agent_stack import BedrockAgentStack
from src.ecs_stack import EcsStack
from src.monitoring_stack import MonitoringStack
from src.network_stack import NetworkStack
from src.service_props import ServiceProps
from src.service_stack import ServiceStack
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

app_props = ServiceProps(
    container_name="sage-kb-chatbot",
    container_location=f"ghcr.io/sage-bionetworks-it/sage-kb-chatbot:{APP_VERSION}",
    # container_location="path://../sage-kb-chatbot",
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
        "SLACK_AUTHORIZED_USERGROUP": config.get(
            "SLACK_AUTHORIZED_USERGROUP", "sage-all"
        ),
        # Plain string: the secret NAME the app looks up at runtime (not the
        # secret contents). The task role grants GetSecretValue for it.
        "SLACK_AGENT_ROUTER_SECRET_ID": config.get(
            "SLACK_AGENT_ROUTER_SECRET_ID", "infra/slack-agent-router"
        ),
    },
    # temporarily disable: health check endpoint not implemented yet
    # container_healthcheck=ecs.HealthCheck(
    #     command=[
    #         "CMD-SHELL",
    #         "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8080/health')\"",
    #     ],
    #     interval=cdk.Duration.seconds(30),
    #     timeout=cdk.Duration.seconds(5),
    #     start_period=cdk.Duration.seconds(10),
    #     retries=3,
    # ),
)
app_stack = ServiceStack(
    scope=cdk_app,
    construct_id=f"{STACK_NAME_PREFIX}-app",
    vpc=network_stack.vpc,
    cluster=ecs_stack.cluster,
    props=app_props,
)

# Grant the ECS task role permission to fetch secrets at runtime.
# The app calls secretsmanager:GetSecretValue itself on startup (via boto3),
# so the permission must be on the task role, not the execution role.
secret_name = config.get("SLACK_AGENT_ROUTER_SECRET_ID", "infra/slack-agent-router")
secret_arn = f"arn:aws:secretsmanager:{cdk.Aws.REGION}:{cdk.Aws.ACCOUNT_ID}:secret:{secret_name}*"
app_stack.task_definition.task_role.add_to_policy(
    cdk.aws_iam.PolicyStatement(
        actions=["secretsmanager:GetSecretValue"],
        resources=[secret_arn],
    )
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
        target_group=app_stack.target_group,
        monitoring_config=MONITORING_CONFIG,
    )
    monitoring_stack.add_dependency(app_stack)

cdk_app.synth()
