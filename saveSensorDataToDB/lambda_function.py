import json
import boto3

# Initialize the DynamoDB resource
dynamodb = boto3.resource('dynamodb')
# Get a reference to the specific table
table = dynamodb.Table('SensorDataHistory')

def lambda_handler(event, context):
    # Print the incoming event from the IoT Rule for easy debugging
    print(f"Received event from IoT Rule: {json.dumps(event)}")
    
    try:
        # Construct the data item using the fields from the IoT Rule's SQL query.
        # We use .get() to safely access keys that might be missing.
        data_item = {
            'thing_name': event.get('thing_name'),
            'timestamp': event.get('timestamp'),
            'humidity': event.get('humidity'),
            'pumpState': event.get('pumpState'),
            'mode': event.get('mode')
        }

        # Filter out any keys that have a None value
        data_item = {k: v for k, v in data_item.items() if v is not None}
        
        # Write the item to the DynamoDB table
        table.put_item(Item=data_item)
        
        print("Successfully wrote data to DynamoDB.")
        
        # A Lambda invoked by an IoT Rule doesn't need to return a complex body
        return {
            'statusCode': 200,
            'body': json.dumps('Data saved successfully!')
        }
        
    except Exception as e:
        print(f"Error writing to DynamoDB: {e}")
        # It's important to raise the exception to let IoT Core know the action failed
        raise e