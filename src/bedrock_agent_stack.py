import aws_cdk as cdk
from aws_cdk import (
    aws_bedrock_alpha as bedrock,
    aws_iam as iam,
)
from constructs import Construct

# Instructions the agent uses to orchestrate and synthesize answers.
_AGENT_INSTRUCTION = (
    "You are a helpful assistant for Sage Bionetworks employees. "
    "When a user asks a question, use SearchConfluenceJira to search "
    "internal knowledge sources.\n\n"
    "Use SearchConfluenceJira for questions about internal processes, "
    "projects, policies, HR topics, IT procedures, or anything tracked "
    "in Confluence wiki pages or Jira issues.\n\n"
    "After receiving results from the tool, synthesize a single "
    "coherent answer. Always cite your sources by including the URLs "
    "returned by the tool. Format citations as a numbered list at "
    "the end of your answer.\n\n"
    "If no relevant information is found, say so clearly. Do not "
    "make up or hallucinate answers.\n\n"
    "Keep answers concise but complete. Use plain language appropriate "
    "for a workplace setting.\n\n"
    "If there is any reason to question the source, such as being "
    "multiple years old, say so clearly."
)


def _resolve_model(foundation_model_id: str) -> bedrock.IBedrockInvokable:
    """Resolve a model ID string to an L2 IBedrockInvokable.

    A ``us.``/``eu.``/``apac.`` prefix denotes a cross-region inference
    profile; otherwise the ID is treated as a plain foundation model.
    """
    prefix_to_region = {
        "us.": bedrock.CrossRegionInferenceProfileRegion.US,
        "eu.": bedrock.CrossRegionInferenceProfileRegion.EU,
        "apac.": bedrock.CrossRegionInferenceProfileRegion.APAC,
    }
    for prefix, geo_region in prefix_to_region.items():
        if foundation_model_id.startswith(prefix):
            model = bedrock.BedrockFoundationModel(
                foundation_model_id.removeprefix(prefix),
                supports_agents=True,
                supports_cross_region=True,
            )
            return bedrock.CrossRegionInferenceProfile.from_config(
                geo_region=geo_region,
                model=model,
            )
    return bedrock.BedrockFoundationModel(foundation_model_id, supports_agents=True)


class BedrockAgentStack(cdk.Stack):
    """Bedrock Agent for the Slack Agent Router.

    Creates an agent with a RETURN_CONTROL action group (SearchConfluenceJira) and a live alias.
    Uses the official AWS CDK L2 constructs from ``aws_cdk.aws_bedrock_alpha``.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        agent_name: str = "slack-agent-router",
        foundation_model_id: str = "us.anthropic.claude-sonnet-4-6",
        agent_alias_name: str = "live",
        search_confluence_jira_enabled: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # -----------------------------------------------------------------
        # SearchConfluenceJira action group (RETURN_CONTROL / Rovo MCP)
        # -----------------------------------------------------------------
        search_action_group = bedrock.AgentActionGroup(
            name="SearchConfluenceJira",
            description=(
                "Search Confluence wiki pages and Jira issues via Atlassian "
                "Rovo to find internal documentation, policies, project "
                "information, and issue details."
            ),
            executor=bedrock.ActionGroupExecutor.RETURN_CONTROL,
            enabled=search_confluence_jira_enabled,
            function_schema=bedrock.FunctionSchema(
                functions=[
                    bedrock.FunctionProps(
                        name="find_content",
                        description=(
                            "Search Confluence and Jira content for information "
                            "relevant to the user's question. Returns matching "
                            "documents with summaries and source URLs."
                        ),
                        parameters={
                            "query": bedrock.FunctionParameterProps(
                                type=bedrock.ParameterType.STRING,
                                required=True,
                                description=(
                                    "The search query to find relevant Confluence "
                                    "pages and Jira issues."
                                ),
                            ),
                        },
                    ),
                ]
            ),
        )

        model = _resolve_model(foundation_model_id)

        # -----------------------------------------------------------------
        # IAM role that the Bedrock Agent assumes
        # -----------------------------------------------------------------
        # Supply a custom role (rather than letting the L2 Agent auto-create
        # one) so the trust policy is scoped to this account with an
        # aws:SourceAccount condition. This guards against the confused-deputy
        # problem when the stack is deployed across multiple accounts or via
        # shared pipelines. Because a custom role is supplied, the L2 Agent
        # does NOT auto-grant model-invoke permissions, so we grant them
        # explicitly below.
        agent_role = iam.Role(
            self,
            "BedrockAgentRole",
            role_name=f"{agent_name}-bedrock-agent-role",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {
                        "aws:SourceArn": (
                            f"arn:aws:bedrock:{self.region}:{self.account}:agent/*"
                        )
                    },
                },
            ),
        )

        # Allow the agent role to invoke the foundation model (and, for a
        # cross-region inference profile, the model in all routed regions).
        model.grant_invoke(agent_role)

        # -----------------------------------------------------------------
        # Bedrock Agent
        # -----------------------------------------------------------------
        agent = bedrock.Agent(
            self,
            "SlackAgentRouterAgent",
            agent_name=agent_name,
            foundation_model=model,
            instruction=_AGENT_INSTRUCTION,
            existing_role=agent_role,
            description=(
                "Routes Slack questions to the Confluence/Jira knowledge backend "
                "via Rovo MCP, synthesizes answers with citations."
            ),
            idle_session_ttl=cdk.Duration.seconds(3600),
            should_prepare_agent=True,
            action_groups=[search_action_group],
        )

        # -----------------------------------------------------------------
        # Agent alias (points to the latest prepared version)
        # -----------------------------------------------------------------
        agent_alias = bedrock.AgentAlias(
            self,
            "SlackAgentRouterAlias",
            agent=agent,
            agent_alias_name=agent_alias_name,
            description=f"Alias for {agent_name} using {foundation_model_id}",
        )

        # -----------------------------------------------------------------
        # Outputs
        # -----------------------------------------------------------------
        self.agent_id = agent.agent_id
        self.agent_alias_id = agent_alias.alias_id
        self.agent_arn = agent.agent_arn
        self.agent_role_arn = agent_role.role_arn

        cdk.CfnOutput(
            self,
            "AgentId",
            description="Bedrock Agent ID (set as BEDROCK_AGENT_ID env var)",
            value=agent.agent_id,
        )
        cdk.CfnOutput(
            self,
            "AgentAliasId",
            description="Bedrock Agent Alias ID (set as BEDROCK_AGENT_ALIAS_ID env var)",
            value=agent_alias.alias_id,
        )
        cdk.CfnOutput(
            self,
            "AgentArn",
            description="Full ARN of the Bedrock Agent",
            value=agent.agent_arn,
        )
        cdk.CfnOutput(
            self,
            "AgentRoleArn",
            description="IAM role ARN assumed by the Bedrock Agent",
            value=agent_role.role_arn,
        )
