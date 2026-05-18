import json
import os
import boto3
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource('dynamodb')
ecs = boto3.client('ecs')
table_name = os.environ.get('TABLE_NAME', '')
cluster_name = os.environ.get('CLUSTER_NAME', '')
table = dynamodb.Table(table_name)

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, float):
            return str(obj)
        if hasattr(obj, 'as_tuple'):  # Simple way to catch Decimals from boto3
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def handler(event, context):
    try:
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub', 'anonymous')
        
        # Scan table for products belonging only to this user
        response = table.scan(
            FilterExpression=Attr('user_id').eq(user_id)
        )
        products = response.get('Items', [])
        
        # Check if scraper is running
        scraper_running = False
        if cluster_name:
            try:
                tasks_running = ecs.list_tasks(cluster=cluster_name, desiredStatus='RUNNING')
                tasks_pending = ecs.list_tasks(cluster=cluster_name, desiredStatus='PENDING')
                if tasks_running.get('taskArns') or tasks_pending.get('taskArns'):
                    scraper_running = True
            except Exception as e:
                print("ECS Error:", e)

        return {
            "statusCode": 200,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({
                "products": products,
                "scraper_running": scraper_running
            }, cls=DecimalEncoder)
        }
    except Exception as e:
        print("Error:", e)
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)})
        }

