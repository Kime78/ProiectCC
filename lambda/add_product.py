import json
import os
import uuid
import boto3
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
table_name = os.environ.get('TABLE_NAME', '')
table = dynamodb.Table(table_name)

def handler(event, context):
    try:
        body = json.loads(event.get('body', '{}'))
        url = body.get('url')
        
        if not url:
            return {"statusCode": 400, "body": json.dumps({"error": "url is required"})}
            
        # Get user details from the Cognito Authorizer context
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub', 'anonymous')
        email = claims.get('email', 'no-email')
        
        item_id = str(uuid.uuid4())
        item = {
            'id': item_id,
            'user_id': user_id,
            'email': email,
            'url': url,
            # Initially we don't know the price. The scraper will find it.
            'last_price': None
        }
        
        table.put_item(Item=item)
        
        return {
            "statusCode": 200,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"message": "Product added successfully", "product": item})
        }
    except Exception as e:
        print("Error:", e)
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)})
        }

