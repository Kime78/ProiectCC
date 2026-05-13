import json
import os

def handler(event, context):
    print("Scraper event (triggered by EventBridge):", event)
    # logic to lookup user sites and notify via SNS if price drops
    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Scraping complete"})
    }
