import json
import os
import boto3
import urllib.request
import re
import time
import random
from decimal import Decimal
from botocore.exceptions import ClientError

table_name = os.environ.get('TABLE_NAME')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'aimaster610@gmail.com')

dynamodb = boto3.resource('dynamodb')
ses = boto3.client('ses', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
table = dynamodb.Table(table_name)

def get_demo_shop_data(url):
    print(f"Scraping: {url}")
    if "demo-shop.html" not in url:
        print(f"[SKIPPED] Only demo-shop.html is supported: {url}")
        return {"price": None, "name": url, "image": None}

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
            
        match = re.search(r'\?id=([^&]+)', url)
        if not match: 
            return {"price": None, "name": url, "image": None}
        
        prod_id = match.group(1)
        
        # Look for { id: "p1", name: "...", basePrice: ..., image: "..." }
        pattern = r'id:\s*["\']' + re.escape(prod_id) + r'["\'].*?name:\s*["\'](.*?)["\'].*?basePrice:\s*([\d\.]+).*?image:\s*["\'](.*?)["\']'
        prod_match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        
        if prod_match:
            name = prod_match.group(1)
            base_price = float(prod_match.group(2))
            image = prod_match.group(3)
            
            # Mimic the demo shop's client-side fluctuation cleanly in python
            fluctuation = (random.random() * 0.3) - 0.15
            final_price = round(base_price * (1 + fluctuation), 2)
            
            return {
                "price": Decimal(str(final_price)),
                "name": name,
                "image": image
            }
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        
    return {"price": None, "name": url, "image": None}

def send_price_alert(email, product_name, old_price, new_price, url):
    message = (
        f"Good news!\n\n"
        f"'{product_name}' dropped in price.\n\n"
        f"Old price: {old_price} Lei\n"
        f"New price: {new_price} Lei\n\n"
        f"Link:\n{url}"
    )
    try:
        ses.send_email(
            Source=SENDER_EMAIL,
            Destination={'ToAddresses': [email]},
            Message={
                'Subject': {'Data': 'eMAG Price Drop Alert!', 'Charset': 'UTF-8'},
                'Body': {'Text': {'Data': message, 'Charset': 'UTF-8'}}
            }
        )
        print(f"[EMAIL SENT] {email}")
    except ClientError as e:
        print(f"[SES ERROR] {email} -> {e}")

def get_all_items():
    items = []
    scan_kwargs = {}
    while True:
        response = table.scan(**scan_kwargs)
        items.extend(response.get('Items', []))
        last_key = response.get('LastEvaluatedKey')
        if not last_key:
            break
        scan_kwargs['ExclusiveStartKey'] = last_key
    return items

def update_product(item_id, current_price, product_name, image=None, existing_history=None):
    update_expression = "SET last_price = :p, last_check_time = :t, #n = :n"
    expression_values = {
        ':p': current_price,
        ':t': int(time.time()),
        ':n': product_name
    }
    expression_names = {'#n': 'name'}
    
    if image:
        update_expression += ", image = :i"
        expression_values[':i'] = image

    if current_price is not None:
        history = existing_history or []
        history.append({
            "timestamp": int(time.time()),
            "price": str(current_price)
        })
        update_expression += ", price_history = :ph"
        expression_values[':ph'] = history

    table.update_item(
        Key={'id': item_id},
        UpdateExpression=update_expression,
        ExpressionAttributeNames=expression_names,
        ExpressionAttributeValues=expression_values
    )

def handler(event, context):
    print("[START] Lambda Scraper running", flush=True)
    try:
        items = get_all_items()
    except Exception as e:
        print(f"[FATAL ERROR] Cannot get items from DB: {e}", flush=True)
        return
    
    processed = 0
    alerts_sent = 0
    errors = 0
    
    for item in items:
        try:
            url = item.get('url')
            if not url: continue
            
            email = item.get('email')
            last_price = item.get('last_price')
            existing_history = item.get('price_history', [])
            
            data = get_demo_shop_data(url)
            current_price = data['price']
            product_name = item.get('name') or data['name']
            image = data.get('image')
            
            if current_price is None:
                print(f"[NO PRICE] {url}", flush=True)
                errors += 1
                continue
                
            print(f"[PRICE] {product_name} -> {current_price} | Last: {last_price} ({type(last_price)}) | Email: {email}", flush=True)
            
            # Decimal check and price comparison
            try:
                if last_price is not None:
                    # Convert to Decimal just in case DynamoDB or another process stored it as a float/string
                    last_price_dec = Decimal(str(last_price))
                    
                    if current_price < last_price_dec and email and email != 'no-email':
                        print(f"    -> Sending alert to {email} (Old: {last_price_dec}, New: {current_price})", flush=True)
                        send_price_alert(email, product_name, last_price_dec, current_price, url)
                        alerts_sent += 1
                    elif current_price < last_price_dec:
                        print(f"    -> Can't send alert, invalid email: {email}", flush=True)
            except Exception as eval_err:
                print(f"[EVAL ERROR] comparing prices: {eval_err}", flush=True)
                
            # Always update so we get the graph history
            update_product(item['id'], current_price, product_name, image, existing_history)
            
            processed += 1
            
        except Exception as e:
            print(f"[ITEM ERROR] {item.get('id')} -> {e}", flush=True)
            errors += 1
            
    print(f"[FINISHED] Processed: {processed}, Alerts: {alerts_sent}, Errors: {errors}", flush=True)
