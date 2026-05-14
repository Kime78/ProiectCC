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
        target_price = body.get('target_price')
        
        if not url or not target_price:
            return {"statusCode": 400, "body": json.dumps({"error": "url and target_price are required"})}
            
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
            'target_price': Decimal(str(target_price)),
            'last_price': Decimal('0')
        }
        
        table.put_item(Item=item)
        
        # Convert Decimals to float/str before returning JSON
        item['target_price'] = float(item['target_price'])
        item['last_price'] = float(item['last_price'])
        
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

