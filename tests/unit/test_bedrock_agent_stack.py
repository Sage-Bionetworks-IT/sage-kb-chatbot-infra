import aws_cdk as core
import aws_cdk.assertions as assertions

from src.bedrock_agent_stack import BedrockAgentStack


def test_bedrock_agent_created():
    app = core.App()
    stack = BedrockAgentStack(app, "BedrockAgentStack")
    template = assertions.Template.from_stack(stack)
    template.has_resource_properties(
        "AWS::Bedrock::Agent",
        {
            "AgentName": "slack-agent-router",
            "AutoPrepare": True,
        },
    )


def test_bedrock_agent_custom_name():
    app = core.App()
    stack = BedrockAgentStack(app, "BedrockAgentStack", agent_name="my-custom-agent")
    template = assertions.Template.from_stack(stack)
    template.has_resource_properties(
        "AWS::Bedrock::Agent",
        {
            "AgentName": "my-custom-agent",
        },
    )


def test_bedrock_agent_uses_cross_region_inference_profile():
    """A ``us.`` prefixed model resolves to a cross-region inference profile."""
    app = core.App()
    stack = BedrockAgentStack(
        app, "BedrockAgentStack", foundation_model_id="us.anthropic.claude-sonnet-4-6"
    )
    template = assertions.Template.from_stack(stack)
    # The L2 CrossRegionInferenceProfile renders FoundationModel as an
    # inference-profile ARN joined with the region-prefixed model id.
    agents = template.find_resources("AWS::Bedrock::Agent")
    assert len(agents) == 1
    foundation_model = next(iter(agents.values()))["Properties"]["FoundationModel"]
    # It is a Fn::Join referencing the inference profile, not a plain string.
    assert "Fn::Join" in foundation_model
    joined = "".join(
        part for part in foundation_model["Fn::Join"][1] if isinstance(part, str)
    )
    assert "us.anthropic.claude-sonnet-4-6" in joined


def test_bedrock_agent_alias_created():
    app = core.App()
    stack = BedrockAgentStack(app, "BedrockAgentStack")
    template = assertions.Template.from_stack(stack)
    template.has_resource_properties(
        "AWS::Bedrock::AgentAlias",
        {
            "AgentAliasName": "live",
        },
    )


def test_bedrock_agent_alias_custom_name():
    app = core.App()
    stack = BedrockAgentStack(app, "BedrockAgentStack", agent_alias_name="production")
    template = assertions.Template.from_stack(stack)
    template.has_resource_properties(
        "AWS::Bedrock::AgentAlias",
        {
            "AgentAliasName": "production",
        },
    )


def test_bedrock_agent_role_created():
    """The L2 Agent construct creates a service role trusted by Bedrock."""
    app = core.App()
    stack = BedrockAgentStack(app, "BedrockAgentStack")
    template = assertions.Template.from_stack(stack)
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "AssumeRolePolicyDocument": assertions.Match.object_like(
                {
                    "Statement": assertions.Match.array_with(
                        [
                            assertions.Match.object_like(
                                {
                                    "Effect": "Allow",
                                    "Principal": {"Service": "bedrock.amazonaws.com"},
                                    "Action": "sts:AssumeRole",
                                }
                            )
                        ]
                    )
                }
            ),
        },
    )


def test_bedrock_agent_role_can_invoke_model():
    """The L2 Agent grants its role permission to invoke the model."""
    app = core.App()
    stack = BedrockAgentStack(app, "BedrockAgentStack")
    template = assertions.Template.from_stack(stack)
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": assertions.Match.object_like(
                {
                    "Statement": assertions.Match.array_with(
                        [
                            assertions.Match.object_like(
                                {
                                    "Action": assertions.Match.array_with(
                                        ["bedrock:InvokeModel*"]
                                    ),
                                    "Effect": "Allow",
                                }
                            )
                        ]
                    )
                }
            ),
        },
    )


def test_action_group_configured():
    app = core.App()
    stack = BedrockAgentStack(app, "BedrockAgentStack")
    template = assertions.Template.from_stack(stack)
    template.has_resource_properties(
        "AWS::Bedrock::Agent",
        {
            "ActionGroups": assertions.Match.array_with(
                [
                    assertions.Match.object_like(
                        {
                            "ActionGroupName": "SearchConfluenceJira",
                            "ActionGroupState": "ENABLED",
                            "ActionGroupExecutor": {"CustomControl": "RETURN_CONTROL"},
                        }
                    )
                ]
            ),
        },
    )


def test_action_group_disabled():
    app = core.App()
    stack = BedrockAgentStack(
        app, "BedrockAgentStack", search_confluence_jira_enabled=False
    )
    template = assertions.Template.from_stack(stack)
    template.has_resource_properties(
        "AWS::Bedrock::Agent",
        {
            "ActionGroups": assertions.Match.array_with(
                [
                    assertions.Match.object_like(
                        {
                            "ActionGroupName": "SearchConfluenceJira",
                            "ActionGroupState": "DISABLED",
                        }
                    )
                ]
            ),
        },
    )


def test_outputs_exist():
    app = core.App()
    stack = BedrockAgentStack(app, "BedrockAgentStack")
    template = assertions.Template.from_stack(stack)
    template.has_output("AgentId", {})
    template.has_output("AgentAliasId", {})
    template.has_output("AgentArn", {})
    template.has_output("AgentRoleArn", {})


def test_idle_session_ttl():
    app = core.App()
    stack = BedrockAgentStack(app, "BedrockAgentStack")
    template = assertions.Template.from_stack(stack)
    template.has_resource_properties(
        "AWS::Bedrock::Agent",
        {
            "IdleSessionTTLInSeconds": 3600,
        },
    )
