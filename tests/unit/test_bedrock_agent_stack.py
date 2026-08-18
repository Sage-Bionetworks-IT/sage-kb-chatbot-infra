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


def test_bedrock_agent_foundation_model():
    app = core.App()
    stack = BedrockAgentStack(
        app, "BedrockAgentStack", foundation_model_id="us.anthropic.claude-sonnet-4-6"
    )
    template = assertions.Template.from_stack(stack)
    template.has_resource_properties(
        "AWS::Bedrock::Agent",
        {
            "FoundationModel": "us.anthropic.claude-sonnet-4-6",
        },
    )


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
    app = core.App()
    stack = BedrockAgentStack(app, "BedrockAgentStack")
    template = assertions.Template.from_stack(stack)
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "RoleName": "slack-agent-router-bedrock-agent-role",
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


def test_bedrock_agent_role_has_invoke_model_policy():
    app = core.App()
    stack = BedrockAgentStack(app, "BedrockAgentStack")
    template = assertions.Template.from_stack(stack)
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "Policies": assertions.Match.array_with(
                [
                    assertions.Match.object_like(
                        {
                            "PolicyName": "BedrockAgentModelAccess",
                            "PolicyDocument": assertions.Match.object_like(
                                {
                                    "Statement": assertions.Match.array_with(
                                        [
                                            assertions.Match.object_like(
                                                {
                                                    "Action": "bedrock:InvokeModel",
                                                    "Effect": "Allow",
                                                }
                                            )
                                        ]
                                    )
                                }
                            ),
                        }
                    )
                ]
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
        app, "BedrockAgentStack", search_confluence_jira_state="DISABLED"
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
