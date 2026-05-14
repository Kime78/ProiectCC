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
table_name = os.environ.get('TABLE_NAME', '')
table = dynamodb.Table(table_name)

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


def extract_price(html):
    patterns = [
        r'product-new-price[^>]*>\s*([0-9\.,\s]+)\s*<sup>([0-9]{2})</sup>',
        r'"current"\s*:\s*([0-9\.,]+)',
        r'"price"\s*:\s*"([0-9\.,]+)"',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            if len(match.groups()) == 2:
                main = re.sub(r"\D", "", match.group(1))
                cents = re.sub(r"\D", "", match.group(2))
                return parse_decimal(f"{main}.{cents}")
            return parse_decimal(match.group(1))

    return None


def extract_title(html, fallback_url):
    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not title_match:
        return fallback_url

    title = re.sub(r"\s+", " ", title_match.group(1)).strip()
    return title.replace("- eMAG.ro", "").replace("eMAG.ro", "").strip()


def extract_image(html):
    patterns = [
        r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
        r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def get_emag_data(url):
    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept-Language': 'ro-RO,ro;q=0.9,en;q=0.8'
            }
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')

            price = extract_price(html)
            name = extract_title(html, url)
            image = extract_image(html)

            return {"price": price, "name": name, "image": image}
    except urllib.error.HTTPError as e:
        print(f"HTTP error fetching {url}: {e.code}")
    except urllib.error.URLError as e:
        print(f"URL error fetching {url}: {e.reason}")
    except Exception as e:
        print(f"Error fetching from {url}: {e}")
    return {"price": None, "name": url, "image": None}

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
            'image': emag_data['image'],
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

