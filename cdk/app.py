#!/usr/bin/env python3
import os

import aws_cdk as cdk
from stack import WhatsNewSummaryStack

app = cdk.App()

# The account comes from the AWS profile you deploy with (AWS_PROFILE).
# The region comes from AWS_REGION in config.env, defaulting to Sydney.
WhatsNewSummaryStack(
    app,
    "aws-whats-new-summary-tool",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("AWS_REGION", "ap-southeast-2"),
    ),
)

app.synth()
