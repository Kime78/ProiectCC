import json
import os
import boto3
import time
import re
from decimal import Decimal
from botocore.exceptions import ClientError
from playwright.sync_api import sync_playwright

# AWS Clients (using default session info from ECS Task Role)
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
ses = boto3.client('ses', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Environment Variables
TABLE_NAME = os.environ.get('TABLE_NAME')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'alerts@yourdomain.com')

table = dynamodb.Table(TABLE_NAME)

def parse_decimal(raw_value):
    if raw_value is None:
        return None
    raw_value = raw_value.strip()
    if "," in raw_value and "." in raw_value:
        raw_value = raw_value.replace(".", "").replace(",", ".")
    elif "," in raw_value:
        raw_value = raw_value.replace(",", ".")
    try:
        return Decimal(raw_value)
    except Exception:
        return None

def extract_price(page):
    # Try generic demo shop first
    try:
        price_el = page.locator("#product-price")
        if price_el.count() > 0:
            return parse_decimal(price_el.inner_text())
    except Exception:
        pass

    patterns = [
        r'product-new-price[^>]*>\s*([0-9\.,\s]+)\s*<sup>([0-9]{2})</sup>',
        r'"current"\s*:\s*([0-9\.,]+)',
        r'"price"\s*:\s*"([0-9\.,]+)"'
    ]
    html = page.content()
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            if len(match.groups()) == 2:
                main = re.sub(r"\D", "", match.group(1))
                cents = re.sub(r"\D", "", match.group(2))
                return parse_decimal(f"{main}.{cents}")
            return parse_decimal(match.group(1))

    return None

def extract_title(page, fallback_url):
    try:
        title_el = page.locator("#product-title")
        if title_el.count() > 0:
            return title_el.inner_text().strip()
    except Exception:
        pass

    try:
        title = page.title()
        if title:
            return re.sub(r'\s+', ' ', title.replace('- eMAG.ro', '').replace('eMAG.ro', '')).strip()
    except Exception:
        pass
    return fallback_url

def extract_image(page):
    try:
        img_el = page.locator("#product-image")
        if img_el.count() > 0:
            return img_el.get_attribute("src")
    except Exception:
        pass
        
    try:
        # og:image
        meta = page.query_selector("meta[property='og:image']")
        if meta:
            return meta.get_attribute("content")
    except Exception:
        pass
    return None

def get_emag_data(url):
    print(f"Scraping: {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        
        try:
            # Navigate and explicitly wait for some data to load into the page DOM
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            
            # Adding a sleep helps bypass elements loading via dynamic asynchronous scripts
            page.wait_for_timeout(3000)
            
            price = extract_price(page)
            name = extract_title(page, url)
            image = extract_image(page)
            
            return {
                "price": price,
                "name": name,
                "image": image
            }
        except Exception as e:
            print(f"[PLAYWRIGHT ERROR] {url} -> {e}")
            return {
                "price": None,
                "name": url,
                "image": None
            }
        finally:
            browser.close()

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

def run():
    print("[START] Fargate eMAG scraper using Playwright")
    items = get_all_items()
    
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
            
            emag_data = get_emag_data(url)
            current_price = emag_data['price']
            product_name = item.get('name') or emag_data['name']
            image = emag_data.get('image')
            
            if current_price is None:
                print(f"[NO PRICE] {url}")
                errors += 1
                continue
                
            print(f"[PRICE] {product_name} -> {current_price}")
            
            if last_price is not None and isinstance(last_price, Decimal) and current_price < last_price and email:
                send_price_alert(email, product_name, last_price, current_price, url)
                alerts_sent += 1
                
            # Always update so we get the graph history
            update_product(item['id'], current_price, product_name, image, existing_history)
            
            processed += 1
            
        except Exception as e:
            print(f"[ITEM ERROR] {item.get('id')} -> {e}")
            errors += 1
            
    print(f"[FINISHED] Processed: {processed}, Alerts: {alerts_sent}, Errors: {errors}")

if __name__ == "__main__":
    run()
