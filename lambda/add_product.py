import json
import os

def handler(event, context):
    print("Add product event:", event)
    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Product added successfully"})
    }
