import json
import logging
import os
import time
from decimal import Decimal

import boto3

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

TABLE_NAME = os.environ["TABLE_NAME"]
CLUSTER_NAME = os.environ.get("CLUSTER_NAME", "")
TASK_DEFINITION = os.environ.get("TASK_DEFINITION", "")
SUBNETS = os.environ.get("SUBNETS", "").split(",")

# -----------------------------------------------------------------------------
# AWS
# -----------------------------------------------------------------------------

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
ecs = boto3.client("ecs")

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

def trigger_scraper():
    """Trigger the Fargate Scraper Task asynchronously."""
    if not CLUSTER_NAME or not TASK_DEFINITION or not SUBNETS[0]:
        logger.error("Missing ECS Configuration, skipping scraper trigger.")
        return
        
    try:
        ecs.run_task(
            cluster=CLUSTER_NAME,
            launchType='FARGATE',
            taskDefinition=TASK_DEFINITION,
            networkConfiguration={
                'awsvpcConfiguration': {
                    'subnets': SUBNETS,
                    'assignPublicIp': 'ENABLED'
                }
            }
        )
        logger.info("Scraper Fargate Task triggered successfully.")
    except Exception as e:
        logger.error(f"Failed to trigger Fargate task: {e}")

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
        # Proceed with logic
        # ---------------------------------------------------------------------

        res = table.get_item(Key={"id": product_id})
        item = res.get("Item")

        if not item:
            return response(404, {"error": "Product not found"})

        if item.get("user_id") != user_id:
            return response(403, {"error": "Forbidden"})

        # Update last check time immediately
        table.update_item(
            Key={"id": product_id},
            UpdateExpression=(
                "SET last_check_time = :t"
            ),
            ExpressionAttributeValues={
                ":t": int(time.time()),
            },
        )

        item["last_check_time"] = int(time.time())

        # Trigger the scraper
        trigger_scraper()

        return response(200, {
            "message": "Update requested. Fargate task started.",
            "product": item,
        })

    except Exception:
        logger.exception("Unexpected error in check_product Lambda")
        return response(500, {"error": "Internal server error"})
