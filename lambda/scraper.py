import json
import os
import boto3
import urllib.request
import re
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
ses = boto3.client('ses')

table_name = os.environ.get('TABLE_NAME', '')
sender_email = os.environ.get('SENDER_EMAIL', 'alerts@yourdomain.com')
table = dynamodb.Table(table_name)

def get_emag_price(url):
    try:
        # eMag requires a User-Agent header, otherwise it returns a 403 Forbidden
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
            
            # naive regex to find eMag's price paragraph
            # typically it looks like: <p class="product-new-price">1.234<sup>56</sup> <span>Lei</span></p>
            match = re.search(r'<p class="product-new-price">([0-9\.]+)<sup>([0-9]+)</sup>', html)
            if match:
                price_main = match.group(1).replace('.', '') # remove thousands separator
                price_cents = match.group(2)
                return Decimal(f"{price_main}.{price_cents}")
    except Exception as e:
        print(f"Error fetching from {url}: {e}")
    return None

def handler(event, context):
    print("Scraper event starting...")
    
    # 1. Fetch all items from DynamoDB
    response = table.scan()
    items = response.get('Items', [])
    
    for item in items:
        url = item.get('url')
        target_price = item.get('target_price', Decimal('0'))
        email = item.get('email')
        
        current_price = get_emag_price(url)
        
        if current_price is not None:
            print(f"Price found for {url}: {current_price}")
            
            # Update the last recorded price in DynamoDB
            table.update_item(
                Key={'id': item['id']},
                UpdateExpression="set last_price = :p",
                ExpressionAttributeValues={':p': current_price}
            )
            
            # Send Notification if the current price is less or equal to the target price
            if current_price <= target_price and email:
                message = f"Good news! The product you tracked has dropped to {current_price} Lei.\n\nLink: {url}"
                
                try:
                    ses.send_email(
                        Source=sender_email,
                        Destination={
                            'ToAddresses': [email]
                        },
                        Message={
                            'Subject': {
                                'Data': 'eMag Price Drop Alert!',
                                'Charset': 'UTF-8'
                            },
                            'Body': {
                                'Text': {
                                    'Data': message,
                                    'Charset': 'UTF-8'
                                }
                            }
                        }
                    )
                    print(f"Notification sent to {email} regarding {item['id']}")
                except Exception as ses_err:
                    print(f"Failed to send email to {email}:", ses_err)

    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Scraping complete", "items_processed": len(items)})
    }

