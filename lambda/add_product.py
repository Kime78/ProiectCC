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
ecs = boto3.client('ecs')

table_name = os.environ.get('TABLE_NAME', '')
table = dynamodb.Table(table_name)
cluster_name = os.environ.get('CLUSTER_NAME', '')
task_definition = os.environ.get('TASK_DEFINITION', '')
subnets = os.environ.get('SUBNETS', '').split(',')

def trigger_scraper():
    """Trigger the Fargate Scraper Task asynchronously."""
    if not cluster_name or not task_definition or not subnets[0]:
        print("Missing ECS Configuration, skipping scraper trigger.")
        return
        
    try:
        ecs.run_task(
            cluster=cluster_name,
            launchType='FARGATE',
            taskDefinition=task_definition,
            networkConfiguration={
                'awsvpcConfiguration': {
                    'subnets': subnets,
                    'assignPublicIp': 'DISABLED'
                }
            }
        )
        print("Scraper Fargate Task triggered successfully.")
    except Exception as e:
        print(f"Failed to trigger Fargate task: {e}")

def handler(event, context):
    try:
        body = json.loads(event.get('body', '{}'))
        url = body.get('url')
        
        if not url:
            return {"statusCode": 400, "body": json.dumps({"error": "url is required"})}
            
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
            'name': "Adding product...",
            'image': None,
            'last_check_time': int(time.time())
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


