import json
import logging
import os
import re
import time
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

TABLE_NAME = os.environ["TABLE_NAME"]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

REQUEST_TIMEOUT = 10

# -----------------------------------------------------------------------------
# AWS
# -----------------------------------------------------------------------------

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def response(status_code: int, body: dict):
    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Content-Type": "application/json",
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


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


def extract_price(html: str):
    """
    Extract price from eMAG page.
    """

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


def extract_title(html: str, fallback: str):
    match = re.search(
        r"<title>(.*?)</title>",
        html,
        re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return fallback

    title = re.sub(r"\s+", " ", match.group(1)).strip()

    return (
        title.replace("- eMAG.ro", "")
        .replace("eMAG.ro", "")
        .strip()
    )


def extract_image(html: str):
    patterns = [
        r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
        r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)

        if match:
            return match.group(1)

    return None


def fetch_html(url: str):
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
        },
    )

    with urlopen(req, timeout=REQUEST_TIMEOUT) as res:
        return res.read().decode("utf-8", errors="ignore")


def get_emag_data(url: str):
    try:
        html = fetch_html(url)

        return {
            "price": extract_price(html),
            "name": extract_title(html, url),
            "image": extract_image(html),
        }

    except HTTPError as e:
        logger.error(f"HTTP error for {url}: {e.code}")
    except URLError as e:
        logger.error(f"URL error for {url}: {e.reason}")
    except Exception:
        logger.exception(f"Unexpected error fetching {url}")

    return {
        "price": None,
        "name": url,
        "image": None,
    }


# -----------------------------------------------------------------------------
# Lambda Handler
# -----------------------------------------------------------------------------

def handler(event, context):
    try:
        product_id = (
            event.get("pathParameters", {})
            .get("id")
        )

        if not product_id:
            return response(400, {"error": "Missing product id"})

        claims = (
            event.get("requestContext", {})
            .get("authorizer", {})
            .get("claims", {})
        )

        user_id = claims.get("sub")

        if not user_id:
            return response(401, {"error": "Unauthorized"})

        # ---------------------------------------------------------------------
        # Load product
        # ---------------------------------------------------------------------

        db_response = table.get_item(
            Key={"id": product_id}
        )

        item = db_response.get("Item")

        if not item:
            return response(404, {"error": "Product not found"})

        if item.get("user_id") != user_id:
            return response(403, {"error": "Forbidden"})

        # ---------------------------------------------------------------------
        # Scrape latest data
        # ---------------------------------------------------------------------

        emag_data = get_emag_data(item["url"])

        current_price = emag_data["price"]
        updated_time = int(time.time())

        update_parts = [
            "last_check_time = :time",
            "#name = :name",
        ]
        expression_values = {
            ":time": updated_time,
            ":name": emag_data["name"],
        }
        expression_names = {
            "#name": "name",
        }

        if current_price is not None:
            update_parts.insert(0, "last_price = :price")
            expression_values[":price"] = current_price

        if emag_data["image"]:
            update_parts.append("image = :image")
            expression_values[":image"] = emag_data["image"]

        update_expression = "SET " + ", ".join(update_parts)

        table.update_item(
            Key={"id": product_id},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values,
            ExpressionAttributeNames=expression_names,
        )

        # Update local object
        if current_price is not None:
            item["last_price"] = current_price
        item["last_check_time"] = updated_time
        item["name"] = emag_data["name"]

        if emag_data["image"]:
            item["image"] = emag_data["image"]

        logger.info(
            f"Checked product {product_id} for user {user_id}"
        )

        return response(
            200,
            {
                "message": "Checked successfully",
                "product": item,
            },
        )

    except Exception:
        logger.exception("Unhandled Lambda error")

        return response(
            500,
            {
                "error": "Internal server error",
            },
        )