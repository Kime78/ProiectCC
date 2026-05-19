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
            
        def get_initial_title(product_url):
            try:
                req = urllib.request.Request(
                    product_url, 
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                )
                response = urllib.request.urlopen(req, timeout=5)
                html = response.read().decode('utf-8', errors='ignore')
                
                # Check if it's the demo-shop to parse from its inventory JS
                if "demo-shop.html" in product_url:
                    id_match = re.search(r'\?id=([^&]+)', product_url)
                    if id_match:
                        prod_id = id_match.group(1)
                        pattern = r'id:\s*["\']' + re.escape(prod_id) + r'["\'].*?name:\s*["\'](.*?)["\']'
                        prod_match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
                        if prod_match:
                            return prod_match.group(1).strip()
                
                # Fallback to <title>
                match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
                if match:
                    return match.group(1).strip()
            except Exception as e:
                print(f"Failed to fetch initial title for {product_url}: {e}")
            return "Adding product..."
            
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
            'name': get_initial_title(url),
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


