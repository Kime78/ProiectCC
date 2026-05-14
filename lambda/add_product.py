import json
import os
import uuid
import boto3
import time
import urllib.request
import re
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
table_name = os.environ.get('TABLE_NAME', '')
table = dynamodb.Table(table_name)

def get_emag_data(url):
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
            
            price = None
            match = re.search(r'<p class="product-new-price">([0-9\.]+)<sup>([0-9]+)</sup>', html)
            if match:
                price_main = match.group(1).replace('.', '')
                price_cents = match.group(2)
                price = Decimal(f"{price_main}.{price_cents}")
                
            name = url
            title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
            if title_match:
                # Strip out common eMag title suffixes
                name = title_match.group(1).replace('- eMAG.ro', '').replace('eMAG.ro', '').strip()
                
            return {"price": price, "name": name}
    except Exception as e:
        print(f"Error fetching from {url}: {e}")
    return {"price": None, "name": url}

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
        
        emag_data = get_emag_data(url)
        
        item_id = str(uuid.uuid4())
        item = {
            'id': item_id,
            'user_id': user_id,
            'email': email,
            'url': url,
            'last_price': emag_data['price'],
            'name': emag_data['name'],
            'last_check_time': int(time.time())
        }
        
        table.put_item(Item=item)
        
        if item['last_price'] is not None:
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

