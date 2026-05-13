import json
import os

def handler(event, context):
    print("Delete product event:", event)
    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Product deleted successfully"})
    }
