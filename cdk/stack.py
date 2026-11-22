from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_scheduler as scheduler,
    CfnOutput,
)
from constructs import Construct
import os


class WhatsNewSummaryStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ---- DynamoDB: deduplication tracking table ----------------------

        table = dynamodb.Table(
            self,
            "ProcessedAnnouncementsTable",
            table_name=f"{construct_id}-processed-announcements",
            partition_key=dynamodb.Attribute(
                name="guid",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ---- CloudWatch Log Group ----------------------------------------

        log_group = logs.LogGroup(
            self,
            "SummaryFunctionLogGroup",
            log_group_name=f"/aws/lambda/{construct_id}-summary",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ---- IAM: Lambda execution role ---------------------------------

        role = iam.Role(
            self,
            "LambdaExecutionRole",
            role_name=f"{construct_id}-lambda-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        role.add_to_policy(
            iam.PolicyStatement(
                sid="DynamoDBAccess",
                actions=[
                    "dynamodb:Scan",
                    "dynamodb:BatchWriteItem",
                    "dynamodb:PutItem",
                ],
                resources=[table.table_arn],
            )
        )

        role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockInvoke",
                actions=["bedrock:InvokeModel"],
                resources=["*"],
            )
        )

        role.add_to_policy(
            iam.PolicyStatement(
                sid="SESSendEmail",
                actions=["ses:SendEmail", "ses:SendRawEmail"],
                resources=["*"],
            )
        )

        # ---- Lambda: summary function ------------------------------------

        # Settings come from environment variables (normally loaded from
        # config.env by scripts/deploy.sh). A --context value overrides them.
        def setting(context_key: str, env_key: str, default: str = "") -> str:
            return str(
                self.node.try_get_context(context_key)
                or os.environ.get(env_key)
                or default
            )

        recipient_email = setting("recipient_email", "RECIPIENT_EMAIL")
        sender_email = setting("sender_email", "SENDER_EMAIL", recipient_email)
        if not recipient_email:
            raise ValueError(
                "RECIPIENT_EMAIL is not set. Copy config.env.example to "
                "config.env, fill in your values, and deploy with "
                "./scripts/deploy.sh"
            )
        bedrock_model_id = setting("bedrock_model_id", "BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
        max_announcements = setting("max_announcements", "MAX_ANNOUNCEMENTS", "50")
        schedule_expression = setting("schedule_expression", "SCHEDULE_EXPRESSION", "cron(0 17 * * ? *)")

        fn = lambda_.Function(
            self,
            "SummaryFunction",
            function_name=f"{construct_id}-summary",
            description="Fetches AWS What's New RSS, summarises with Bedrock, emails via SES.",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "lambda"),
                bundling={
                    "image": lambda_.Runtime.PYTHON_3_12.bundling_image,
                    "command": [
                        "bash", "-c",
                        "pip install -r requirements.txt -t /asset-output && cp handler.py /asset-output/",
                    ],
                },
            ),
            timeout=Duration.seconds(300),
            memory_size=256,
            role=role,
            environment={
                "DYNAMODB_TABLE": table.table_name,
                "SES_SENDER": sender_email,
                "SES_RECIPIENT": recipient_email,
                "BEDROCK_MODEL_ID": bedrock_model_id,
                "MAX_ANNOUNCEMENTS": max_announcements,
            },
            log_group=log_group,
        )

        # ---- EventBridge Scheduler IAM role -----------------------------

        scheduler_role = iam.Role(
            self,
            "SchedulerRole",
            role_name=f"{construct_id}-scheduler-role",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )

        scheduler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[fn.function_arn],
            )
        )

        # ---- EventBridge Scheduler (default: daily 17:00 UTC = 03:00 AEST) -

        cfn_schedule = scheduler.CfnSchedule(
            self,
            "DailySchedule",
            name=f"{construct_id}-daily",
            description=f"AWS What's New summary, schedule {schedule_expression} (UTC)",
            schedule_expression=schedule_expression,
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="OFF",
            ),
            target=scheduler.CfnSchedule.TargetProperty(
                arn=fn.function_arn,
                role_arn=scheduler_role.role_arn,
                input='{"source": "scheduled"}',
            ),
            state="ENABLED",
        )

        # ---- Lambda permission for Scheduler ----------------------------

        lambda_.CfnPermission(
            self,
            "LambdaSchedulerPermission",
            action="lambda:InvokeFunction",
            function_name=fn.function_name,
            principal="scheduler.amazonaws.com",
            source_arn=cfn_schedule.attr_arn,
        )

        # ---- Outputs ----------------------------------------------------

        CfnOutput(
            self,
            "LambdaFunctionName",
            value=fn.function_name,
            description="Lambda function name (use for on-demand invocation)",
            export_name=f"{construct_id}-FunctionName",
        )

        CfnOutput(
            self,
            "DynamoDBTableName",
            value=table.table_name,
            description="DynamoDB deduplication table",
            export_name=f"{construct_id}-TableName",
        )

        CfnOutput(
            self,
            "ScheduleName",
            value=cfn_schedule.ref,
            description="EventBridge Scheduler schedule name",
        )
