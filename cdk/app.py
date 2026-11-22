#!/usr/bin/env python3
import aws_cdk as cdk
from stack import WhatsNewSummaryStack

app = cdk.App()

WhatsNewSummaryStack(
    app,
    "aws-whats-new-summary-tool",
    env=cdk.Environment(
        account="288206176536",
        region="ap-southeast-2",
    ),
)

app.synth()
