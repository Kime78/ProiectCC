import json
import os
import boto3

dynamodb = boto3.resource('dynamodb')
table_name = os.environ.get('TABLE_NAME', '')
table = dynamodb.Table(table_name)

def handler(event, context):
    try:
        product_id = event.get('pathParameters', {}).get('id')
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub', 'anonymous')
        
        if not product_id:
            return {"statusCode": 400, "body": json.dumps({"error": "Product ID is missing in path parameters"})}
            
        # Optional but good practice: First verify the product belongs to the user requesting the delete
        response = table.get_item(Key={'id': product_id})
        item = response.get('Item')
        
        if not item:
            return {"statusCode": 404, "body": json.dumps({"error": "Product not found"})}
            
        if item.get('user_id') != user_id:
            return {"statusCode": 403, "body": json.dumps({"error": "Unauthorized to delete this product"})}

        table.delete_item(Key={'id': product_id})
        
        return {
            "statusCode": 200,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"message": "Product deleted successfully"})
        }
    except Exception as e:
        print("Error:", e)
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)})
        }

