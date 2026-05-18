import json
import os
import uuid
import boto3
import time
import urllib.request
import urllib.error
import re
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')

table_name = os.environ.get('TABLE_NAME', '')
table = dynamodb.Table(table_name)
scraper_name = os.environ.get('SCRAPER_FUNCTION_NAME', '')

def trigger_scraper():
    """Trigger the Scraper Lambda asynchronously."""
    if not scraper_name:
        print("Missing Lambda Configuration, skipping scraper trigger.")
        return
        
    try:
        lambda_client.invoke(
            FunctionName=scraper_name,
            InvocationType='Event'
        )
        print("Scraper Lambda triggered successfully.")
    except Exception as e:
        print(f"Failed to trigger Lambda: {e}")

def handler(event, context):
    try:
        body = json.loads(event.get('body', '{}'))
        url = body.get('url')
        
        if not url:
            return {"statusCode": 400, "body": json.dumps({"error": "url is required"})}
            
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub', 'anonymous')
        email = claims.get('email', 'no-email')
        
        item_id = str(uuid.uuid4())
        item = {
            'id': item_id,
            'user_id': user_id,
            'email': email,
            'url': url,
            'last_price': None,
            'name': "Adding product...",
            'image': None,
            'last_check_time': int(time.time()),
            'price_history': []
        }
        
        table.put_item(Item=item)
        
        # Trigger the scraper immediately in the background
        trigger_scraper()
        
        return {
            "statusCode": 200,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"message": "Product added to queue. Scraper is running.", "product": item})
        }
    except Exception as e:
        print("Error:", e)
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)})
        }


