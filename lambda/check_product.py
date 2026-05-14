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
                name = title_match.group(1).replace('- eMAG.ro', '').replace('eMAG.ro', '').strip()
                
            image = None
            img_m = re.search(r'<meta\s+(?:[^>]*\s+)?property="og:image"\s+(?:[^>]*\s+)?content="([^"]+)"', html, re.IGNORECASE)
            if not img_m:
                img_m = re.search(r'<meta\s+(?:[^>]*\s+)?content="([^"]+)"\s+(?:[^>]*\s+)?property="og:image"', html, re.IGNORECASE)
            if img_m:
                image = img_m.group(1)
                
            return {"price": price, "name": name, "image": image}
    except Exception as e:
        print(f"Error fetching from {url}: {e}")
    return {"price": None, "name": url, "image": None}

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
            
        emag_data = get_emag_data(item['url'])
        current_price = emag_data['price']
        
        if current_price is not None:
            updated_time = int(time.time())
            
            # Prepare optional image update
            update_expr = "set last_price = :p, last_check_time = :t, #n = :n"
            expr_names = {'#n': 'name'}
            expr_vals = {':p': current_price, ':t': updated_time, ':n': emag_data['name']}
            
            if emag_data['image']:
                update_expr += ", image = :img"
                expr_vals[':img'] = emag_data['image']
            
            table.update_item(
                Key={'id': product_id},
                UpdateExpression=update_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_vals
            )
            item['last_price'] = current_price
            item['last_check_time'] = updated_time
            item['name'] = emag_data['name']
            if emag_data['image']:
                item['image'] = emag_data['image']

        return {
            "statusCode": 200,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"message": "Checked successfully", "product": item}, cls=DecimalEncoder)
        }
    except Exception as e:
        return {"statusCode": 500, "headers": {"Access-Control-Allow-Origin": "*"}, "body": json.dumps({"error": str(e)})}
