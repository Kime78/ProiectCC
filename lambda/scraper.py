import json
import os
import boto3
import urllib.request
import urllib.error
import re
import time
from decimal import Decimal
from botocore.exceptions import ClientError

# AWS Clients
dynamodb = boto3.resource('dynamodb')
ses = boto3.client('ses')

# Environment Variables
TABLE_NAME = os.environ.get('TABLE_NAME')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'alerts@yourdomain.com')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL')

# DynamoDB Table
table = dynamodb.Table(TABLE_NAME)

# Constants
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3


def fetch_url(url):
    """
    Fetch URL with retries and headers.
    """
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/122.0 Safari/537.36'
        )
    }

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
                return response.read().decode('utf-8', errors='ignore')

        except urllib.error.HTTPError as e:
            print(f"[HTTP ERROR] {url} -> {e.code}")

            if e.code == 404:
                return None

        except Exception as e:
            print(f"[FETCH ERROR] Attempt {attempt + 1}: {url} -> {e}")

        time.sleep(2 ** attempt)

    return None


def extract_price(html):
    """
    Extract price from eMAG HTML.
    """

    patterns = [
        r'product-new-price[^>]*>\s*([0-9\.,]+)\s*<sup>([0-9]{2})</sup>',
        r'"current"\s*:\s*([0-9\.]+)',
        r'"price"\s*:\s*"([0-9\.]+)"'
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)

        if match:
            if len(match.groups()) == 2:
                main = match.group(1).replace('.', '').replace(',', '')
                cents = match.group(2)

                return Decimal(f"{main}.{cents}")

            return Decimal(match.group(1))

    return None


def extract_title(html, fallback_url):
    """
    Extract product title safely.
    """

    title_match = re.search(
        r'<title>(.*?)</title>',
        html,
        re.IGNORECASE | re.DOTALL
    )

    if not title_match:
        return fallback_url

    title = title_match.group(1)

    title = re.sub(r'\s+', ' ', title)
    title = title.replace('- eMAG.ro', '')
    title = title.replace('eMAG.ro', '')

    return title.strip()


def get_emag_data(url):
    """
    Fetch and parse eMAG product data.
    """

    html = fetch_url(url)

    if not html:
        return {
            "price": None,
            "name": url
        }

    return {
        "price": extract_price(html),
        "name": extract_title(html, url)
    }


def send_price_alert(email, product_name, old_price, new_price, url):
    """
    Send SES email alert.
    """

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
                'Subject': {
                    'Data': 'eMAG Price Drop Alert!',
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

        print(f"[EMAIL SENT] {email}")

    except ClientError as e:
        print(f"[SES ERROR] {email} -> {e}")


def get_all_items():
    """
    Scan entire DynamoDB table with pagination.
    """

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


def update_product(item_id, current_price, product_name):
    """
    Update DynamoDB item.
    """

    table.update_item(
        Key={'id': item_id},
        UpdateExpression=(
            "SET last_price = :p, "
            "last_check_time = :t, "
            "#n = :n"
        ),
        ExpressionAttributeNames={
            '#n': 'name'
        },
        ExpressionAttributeValues={
            ':p': current_price,
            ':t': int(time.time()),
            ':n': product_name
        }
    )


def handler(event, context):

    print("[START] eMAG scraper")

    items = get_all_items()

    processed = 0
    alerts_sent = 0
    errors = 0

    for item in items:

        try:
            url = item.get('url')

            if not url:
                continue

            email = item.get('email')
            last_price = item.get('last_price')

            emag_data = get_emag_data(url)

            current_price = emag_data['price']
            product_name = item.get('name') or emag_data['name']

            if current_price is None:
                print(f"[NO PRICE] {url}")
                errors += 1
                continue

            print(f"[PRICE] {product_name} -> {current_price}")

            # Send alert if price dropped
            if (
                last_price is not None
                and isinstance(last_price, Decimal)
                and current_price < last_price
                and email
            ):
                send_price_alert(
                    email=email,
                    product_name=product_name,
                    old_price=last_price,
                    new_price=current_price,
                    url=url
                )

                alerts_sent += 1

            # Update DB only if needed
            if (
                current_price != last_price
                or item.get('name') != product_name
            ):
                update_product(
                    item['id'],
                    current_price,
                    product_name
                )

            processed += 1

        except Exception as e:
            print(f"[ITEM ERROR] {item.get('id')} -> {e}")
            errors += 1

    # Optional admin summary
    if ADMIN_EMAIL:
        try:
            summary = (
                f"eMAG scraper completed.\n\n"
                f"Processed: {processed}\n"
                f"Alerts sent: {alerts_sent}\n"
                f"Errors: {errors}\n"
            )

            ses.send_email(
                Source=SENDER_EMAIL,
                Destination={'ToAddresses': [ADMIN_EMAIL]},
                Message={
                    'Subject': {
                        'Data': 'eMAG Scraper Summary',
                        'Charset': 'UTF-8'
                    },
                    'Body': {
                        'Text': {
                            'Data': summary,
                            'Charset': 'UTF-8'
                        }
                    }
                }
            )

        except Exception as e:
            print(f"[ADMIN EMAIL ERROR] {e}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Scraping complete",
            "processed": processed,
            "alerts_sent": alerts_sent,
            "errors": errors
        })
    }