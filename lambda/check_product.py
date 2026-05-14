import json
import os
import boto3
import urllib.request
import re
import time
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
table_name = os.environ.get('TABLE_NAME', '')
table = dynamodb.Table(table_name)

def get_emag_price(url):
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
            match = re.search(r'<p class="product-new-price">([0-9\.]+)<sup>([0-9]+)</sup>', html)
            if match:
                price_main = match.group(1).replace('.', '')
                price_cents = match.group(2)
                return Decimal(f"{price_main}.{price_cents}")
    except Exception as e:
        print(f"Error fetching from {url}: {e}")
    return None

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal): return float(obj)
        return super(DecimalEncoder, self).default(obj)

def handler(event, context):
    try:
        product_id = event.get('pathParameters', {}).get('id')
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub', 'anonymous')
        
        response = table.get_item(Key={'id': product_id})
        item = response.get('Item')
        if not item or item.get('user_id') != user_id:
            return {"statusCode": 404, "body": json.dumps({"error": "Product not found"})}
            
        current_price = get_emag_price(item['url'])
        if current_price is not None:
            updated_time = int(time.time())
            table.update_item(
                Key={'id': product_id},
                UpdateExpression="set last_price = :p, last_check_time = :t",
                ExpressionAttributeValues={':p': current_price, ':t': updated_time}
            )
            item['last_price'] = current_price
            item['last_check_time'] = updated_time

        return {
            "statusCode": 200,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"message": "Checked successfully", "product": item}, cls=DecimalEncoder)
        }
    except Exception as e:
        return {"statusCode": 500, "headers": {"Access-Control-Allow-Origin": "*"}, "body": json.dumps({"error": str(e)})}
