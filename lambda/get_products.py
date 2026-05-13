import json
import os

def handler(event, context):
    print("Get products event:", event)
    return {
        "statusCode": 200,
        "body": json.dumps({"products": []})
    }
