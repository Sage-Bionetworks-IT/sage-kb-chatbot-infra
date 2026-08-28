import aws_cdk as cdk

from aws_cdk import (
    aws_bedrock as bedrock,
    aws_iam as iam,
)
from constructs import Construct


class BedrockAgentStack(cdk.Stack):
    """Bedrock Agent for the Slack Agent Router.

    Creates an agent with a RETURN_CONTROL action group (SearchConfluenceJira) and a live alias.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        agent_name: str = "slack-agent-router",
        foundation_model_id: str = "us.anthropic.claude-sonnet-4-6",
        agent_alias_name: str = "live",
        search_confluence_jira_state: str = "ENABLED",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # -----------------------------------------------------------------
        # IAM role that the Bedrock Agent assumes
        # -----------------------------------------------------------------
        agent_role = iam.Role(
            self,
            "BedrockAgentRole",
            role_name=f"{agent_name}-bedrock-agent-role",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {
                        "aws:SourceAccount": self.account,
                    }
                },
            ),
            inline_policies={
                "BedrockAgentModelAccess": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="AllowModelInvocation",
                            effect=iam.Effect.ALLOW,
                            actions=["bedrock:InvokeModel"],
                            resources=[
                                f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/*",
                                "arn:aws:bedrock:*::foundation-model/*",
                            ],
                        )
                    ]
                )
            },
        )

        # -----------------------------------------------------------------
        # Bedrock Agent with SearchConfluenceJira RETURN_CONTROL action group
        # -----------------------------------------------------------------
        agent = bedrock.CfnAgent(
            self,
            "SlackAgentRouterAgent",
            agent_name=agent_name,
            agent_resource_role_arn=agent_role.role_arn,
            foundation_model=foundation_model_id,
            auto_prepare=True,
            description=(
                "Routes Slack questions to the Confluence/Jira knowledge backend "
                "via Rovo MCP, synthesizes answers with citations."
            ),
            instruction=(
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
            ),
            idle_session_ttl_in_seconds=3600,
            action_groups=[
                bedrock.CfnAgent.AgentActionGroupProperty(
                    action_group_name="SearchConfluenceJira",
                    action_group_state=search_confluence_jira_state,
                    description=(
                        "Search Confluence wiki pages and Jira issues via Atlassian "
                        "Rovo to find internal documentation, policies, project "
                        "information, and issue details."
                    ),
                    action_group_executor=bedrock.CfnAgent.ActionGroupExecutorProperty(
                        custom_control="RETURN_CONTROL",
                    ),
                    function_schema=bedrock.CfnAgent.FunctionSchemaProperty(
                        functions=[
                            bedrock.CfnAgent.FunctionProperty(
                                name="find_content",
                                description=(
                                    "Search Confluence and Jira content for information "
                                    "relevant to the user's question. Returns matching "
                                    "documents with summaries and source URLs."
                                ),
                                parameters={
                                    "query": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description=(
                                            "The search query to find relevant Confluence "
                                            "pages and Jira issues."
                                        ),
                                        required=True,
                                    )
                                },
                            )
                        ]
                    ),
                )
            ],
        )

        # -----------------------------------------------------------------
        # Agent alias (points to the latest prepared version)
        # -----------------------------------------------------------------
        agent_alias = bedrock.CfnAgentAlias(
            self,
            "SlackAgentRouterAlias",
            agent_id=agent.attr_agent_id,
            agent_alias_name=agent_alias_name,
            description=f"Alias for {agent_name} using {foundation_model_id}",
        )
        agent_alias.add_dependency(agent)

        # -----------------------------------------------------------------
        # Outputs
        # -----------------------------------------------------------------
        self.agent_id = agent.attr_agent_id
        self.agent_alias_id = agent_alias.attr_agent_alias_id
        self.agent_arn = agent.attr_agent_arn
        self.agent_role_arn = agent_role.role_arn

        cdk.CfnOutput(
            self,
            "AgentId",
            description="Bedrock Agent ID (set as BEDROCK_AGENT_ID env var)",
            value=agent.attr_agent_id,
        )
        cdk.CfnOutput(
            self,
            "AgentAliasId",
            description="Bedrock Agent Alias ID (set as BEDROCK_AGENT_ALIAS_ID env var)",
            value=agent_alias.attr_agent_alias_id,
        )
        cdk.CfnOutput(
            self,
            "AgentArn",
            description="Full ARN of the Bedrock Agent",
            value=agent.attr_agent_arn,
        )
        cdk.CfnOutput(
            self,
            "AgentRoleArn",
            description="IAM role ARN assumed by the Bedrock Agent",
            value=agent_role.role_arn,
        )
