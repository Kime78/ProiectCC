import json
import os
import boto3
import urllib.request
import re
import time
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
ses = boto3.client('ses')

table_name = os.environ.get('TABLE_NAME', '')
sender_email = os.environ.get('SENDER_EMAIL', 'alerts@yourdomain.com')
table = dynamodb.Table(table_name)

def get_emag_data(url):
    try:
        # eMag requires a User-Agent header, otherwise it returns a 403 Forbidden
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
            else:
                json_match = re.search(r'"current":([0-9\.]+),', html)
                if json_match:
                    price = Decimal(json_match.group(1))
                
            name = url
            title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
            if title_match:
                name = title_match.group(1).replace('- eMAG.ro', '').replace('eMAG.ro', '').strip()
                
            return {"price": price, "name": name}
    except Exception as e:
        print(f"Error fetching from {url}: {e}")
    return {"price": None, "name": url}

def handler(event, context):
    print("Scraper event starting...")
    
    # 1. Fetch all items from DynamoDB
    response = table.scan()
    items = response.get('Items', [])
    
    
    for item in items:
        url = item.get('url')
        last_price = item.get('last_price')
        email = item.get('email')
        
        emag_data = get_emag_data(url)
        current_price = emag_data['price']
        fetched_name = emag_data['name']
        product_name = item.get('name', fetched_name)
        
        if current_price is not None:
            print(f"Price found for {url}: {current_price}")
            
            # Send Notification if the current price is strictly less than the last known price
            if last_price and current_price < last_price and email:
                message = f"Good news! '{product_name}' has dropped from {last_price} to {current_price} Lei.\n\nLink: {url}"
                
                try:
                    ses.send_email(
                        Source=sender_email,
                        Destination={'ToAddresses': [email]},
                        Message={
                            'Subject': {'Data': 'eMag Price Drop Alert!', 'Charset': 'UTF-8'},
                            'Body': {'Text': {'Data': message, 'Charset': 'UTF-8'}}
                        }
                    )
                except Exception as ses_err:
                    print(f"Failed to send email to {email}:", ses_err)
            
            table.update_item(
                Key={'id': item['id']},
                UpdateExpression="set last_price = :p, last_check_time = :t, #n = :n",
                ExpressionAttributeNames={'#n': 'name'},
                ExpressionAttributeValues={':p': current_price, ':t': int(time.time()), ':n': product_name}
            )

    # Email the admin about the automatic check
    try:
        ses.send_email(
            Source=sender_email,
            Destination={'ToAddresses': ['mihalachemihai824@gmail.com']},
            Message={
                'Subject': {'Data': 'eMag Scraper Automatic Check Completed', 'Charset': 'UTF-8'},
                'Body': {'Text': {'Data': f'The scraper successfully ran an automatic check on {len(items)} tracked products.', 'Charset': 'UTF-8'}}
            }
        )
    except Exception as e:
        print("Failed to send admin email:", e)

    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Scraping complete", "items_processed": len(items)})
    }

