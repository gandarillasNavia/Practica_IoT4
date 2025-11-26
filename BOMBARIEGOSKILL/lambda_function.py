# lambda_function.py

import json
import boto3

# --- AWS Service Clients Initialization ---
# Initialize the boto3 client for AWS IoT Data Plane to interact with Device Shadows.
iot_client = boto3.client('iot-data')
# Initialize the boto3 resource for DynamoDB to interact with the database.
dynamodb = boto3.resource('dynamodb')
# Get a reference to our specific DynamoDB table.
user_thing_table = dynamodb.Table('user_thing')

# --- Main Handler - Entry point for all Alexa requests ---
def lambda_handler(event, context):
    # Log the entire incoming event from Alexa for easy debugging in CloudWatch.
    print(f"Event received from Alexa: {json.dumps(event)}")
    
    request_type = event['request']['type']
    
    # Handler for when the user opens the skill without a specific command (e.g., "Alexa, open control de riego").
    if request_type == "LaunchRequest":
        return build_response("Bienvenido al control de riego. Puedes pedirme el estado, cambiar el modo, o controlar la bomba.")

    # Handler for when the user gives a specific command.
    elif request_type == "IntentRequest":
        # First, identify which device belongs to this specific Alexa user.
        thing_name = get_thing_name_for_user(event)
        if not thing_name:
            return build_response("Lo siento, no he podido encontrar un dispositivo asociado a tu cuenta.")

        intent_name = event['request']['intent']['name']
        
        # --- Intent Router ---
        # Directs the request to the appropriate handler function based on the intent name.
        if intent_name == "PumpControlIntent":
            return handle_pump_control(event, thing_name)
        elif intent_name == "SetThresholdIntent":
            return handle_set_threshold(event, thing_name)
        elif intent_name == "GetStateIntent":
            return handle_get_state(event, thing_name)
        elif intent_name == "GetHumidityOnlyIntent": 
            return handle_get_humidity_only(event, thing_name)
        elif intent_name == "SetModeIntent":
            return handle_set_mode(event, thing_name)
        elif intent_name in ["AMAZON.HelpIntent"]:
            return build_response("Puedes pedirme el estado, encender o apagar la bomba, cambiar a modo auto o manual, o configurar el umbral de humedad.")
        elif intent_name in ["AMAZON.CancelIntent", "AMAZON.StopIntent"]:
            return build_response("Adiós.")
        else:
            return build_response("No he entendido esa acción.")
    else:
        return build_response("No sé cómo manejar este tipo de petición.")


# --- Helper Function: Get Thing Name from DynamoDB ---
def get_thing_name_for_user(event):
    # This function maps the Alexa user ID to a specific AWS IoT Thing name.
    try:
        user_id = event['session']['user']['userId']
        response = user_thing_table.get_item(Key={'user_id': user_id})
        if 'Item' in response:
            return response['Item']['thing_name']
        else:
            return None # User not found in the database
    except Exception as e:
        print(f"Error getting thing_name from DynamoDB: {e}")
        return None

# --- Intent Handlers ---

def handle_pump_control(event, thing_name):
    # Handles turning the pump ON or OFF. Also forces the system into MANUAL mode.
    state_alexa = event['request']['intent']['slots']['state']['value']
    desired_state = "ON" if state_alexa == "ON" else "OFF"
    # The payload updates both the desired pump state and the mode.
    payload = {"state": {"desired": {"pumpState": desired_state, "mode": "MANUAL"}}}
    iot_client.update_thing_shadow(thingName=thing_name, payload=json.dumps(payload))
    speech_text = f"Hecho, he puesto la bomba en {state_alexa.lower()} y he cambiado a modo manual."
    return build_response(speech_text)

def handle_set_threshold(event, thing_name):
    # Handles setting the humidity threshold for AUTO mode.
    humidity = event['request']['intent']['slots']['humidity']['value']
    payload = {"state": {"desired": {"humidityThreshold": int(humidity)}}}
    iot_client.update_thing_shadow(thingName=thing_name, payload=json.dumps(payload))
    speech_text = f"Entendido, he configurado el umbral de humedad en {humidity} por ciento."
    return build_response(speech_text)
    
def handle_set_mode(event, thing_name):
    # Handles changing the system's operating mode between AUTO and MANUAL.
    mode_alexa = event['request']['intent']['slots']['mode']['value']
    desired_mode = "AUTO" if mode_alexa.lower() in ["automático", "auto"] else "MANUAL"
    payload = {"state": {"desired": {"mode": desired_mode}}}
    iot_client.update_thing_shadow(thingName=thing_name, payload=json.dumps(payload))
    speech_text = f"Perfecto, he cambiado el sistema a modo {desired_mode.lower()}."
    return build_response(speech_text)

def handle_get_state(event, thing_name):
    # Handles the request for a full system status report.
    try:
        # Get the latest state from the Device Shadow.
        shadow = iot_client.get_thing_shadow(thingName=thing_name)
        payload = json.loads(shadow['payload'].read())
        # Check if the device has ever reported its state.
        if 'reported' in payload['state']:
            reported = payload['state']['reported']
            humidity = reported.get('humidity', 'desconocida')
            mode = reported.get('mode', 'desconocido')
            pump = reported.get('pumpState', 'desconocido')
            threshold = reported.get('humidityThreshold', 'desconocido')
            speech_text = f"El estado actual es: modo {mode}, humedad del {humidity} por ciento, umbral en {threshold}, y la bomba está en {pump}."
        else:
            speech_text = "El dispositivo aún no ha reportado su estado. Inténtalo más tarde."
    except Exception:
        speech_text = "Lo siento, no pude obtener el estado del dispositivo."
    return build_response(speech_text)

# --- NUEVO INTENT HANDLER AÑADIDO ---
def handle_get_humidity_only(event, thing_name):
    # Handles the specific request for only the current humidity level.
    try:
        shadow = iot_client.get_thing_shadow(thingName=thing_name)
        payload = json.loads(shadow['payload'].read())
        if 'reported' in payload['state'] and 'humidity' in payload['state']['reported']:
            humidity = payload['state']['reported']['humidity']
            speech_text = f"La humedad actual reportada por el sensor es de {humidity} por ciento."
        else:
            speech_text = "Aún no tengo una lectura de humedad del sensor. Inténtalo de nuevo en un momento."
    except Exception:
        speech_text = "Lo siento, no pude obtener la lectura de humedad."
    return build_response(speech_text)


# --- Helper Function: Build Alexa's JSON Response ---
def build_response(speech_text, should_end_session=True):
    # This function formats the response into the JSON structure that Alexa expects.
    response = {
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": speech_text},
            "shouldEndSession": should_end_session
        }
    }
    # Log the response for debugging purposes.
    print(f"Respuesta enviada a Alexa: {json.dumps(response)}")
    return response