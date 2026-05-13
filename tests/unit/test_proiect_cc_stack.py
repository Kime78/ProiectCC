import aws_cdk as core
import aws_cdk.assertions as assertions

from proiect_cc.proiect_cc_stack import ProiectCcStack

# example tests. To run these tests, uncomment this file along with the example
# resource in proiect_cc/proiect_cc_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = ProiectCcStack(app, "proiect-cc")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
