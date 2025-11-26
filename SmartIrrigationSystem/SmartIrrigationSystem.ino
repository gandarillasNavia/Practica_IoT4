#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "time.h" 

//  USER CONFIG 

// WiFi Credentials 
const char* WIFI_SSID = "UCB-IoT";       // WIFI NETWORK
const char* WIFI_PASS = "sistemasyteleco"; // PASSWORD

// --- AWS IoT Details ---
const char* MQTT_BROKER = "a250fg572lqga2-ats.iot.us-east-1.amazonaws.com"; // AWS Endpoint
const char* CLIENT_ID = "SistemaBombaRiego_ESP32";                               // thing Name

// --- Device Certificates ---
const char AMAZON_ROOT_CA1[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
-----END CERTIFICATE-----
)EOF";

const char CERTIFICATE[] PROGMEM = R"KEY(
-----BEGIN CERTIFICATE-----
-----END CERTIFICATE-----
)KEY";

const char PRIVATE_KEY[] PROGMEM = R"KEY(
-----BEGIN RSA PRIVATE KEY-----
-----END RSA PRIVATE KEY-----
)KEY";

// --- AWS IoT Shadow Topics ---
const char* UPDATE_TOPIC = "$aws/things/SistemaBombaRiego_ESP32/shadow/update";       
const char* UPDATE_DELTA_TOPIC = "$aws/things/SistemaBombaRiego_ESP32/shadow/update/delta"; 

// Main Logic

// --- Hardware Pin Definitions ---
#define SOIL_MOISTURE_PIN 32
#define PUMP_RELAY_PIN    33

// --- Application Timing Configuration ---
const long SENSOR_READ_INTERVAL_MS = 30000;
const int SENSOR_DRY_VALUE = 4095;
const int SENSOR_WET_VALUE = 1700;

// --- Global State Variables ---
String pumpState = "OFF";
String mode = "AUTO";
int humidityThreshold = 40;
float currentHumidity = 0.0;
int lastReportedHumidityRange = -1; // -1 to force the first report on boot

// --- MQTT and System Objects ---
WiFiClientSecure wiFiClient;
PubSubClient client(wiFiClient);
StaticJsonDocument<512> inputDoc;
StaticJsonDocument<512> outputDoc;
char outputBuffer[512];

// Helper function to get humidity range
int getHumidityRange(float humidity) {
  if (humidity <= 25) return 0; // Very Dry
  if (humidity <= 50) return 1; // Dry
  if (humidity <= 75) return 2; // Moist
  return 3;                     // Saturated
}

void publishShadowState() {
  outputDoc.clear();
  JsonObject state = outputDoc.createNestedObject("state");
  JsonObject reported = state.createNestedObject("reported");
  
  reported["pumpState"] = pumpState;
  reported["mode"] = mode;
  reported["humidityThreshold"] = humidityThreshold;
  reported["humidity"] = currentHumidity;

  serializeJson(outputDoc, outputBuffer);
  client.publish(UPDATE_TOPIC, outputBuffer);
  Serial.println("Published state to AWS Shadow:");
  Serial.println(outputBuffer);
}

void callback(char* topic, byte* payload, unsigned int length) {
  Serial.println("---");
  Serial.print("Message received from topic: ");
  Serial.println(topic);
  
  inputDoc.clear();
  DeserializationError err = deserializeJson(inputDoc, payload, length);
  if (err) {
    Serial.printf("Failed to parse JSON: %s\n", err.c_str());
    return;
  }

  JsonObject state = inputDoc["state"];
  
  if (state.containsKey("pumpState")) pumpState = state["pumpState"].as<String>();
  if (state.containsKey("mode")) mode = state["mode"].as<String>();
  if (state.containsKey("humidityThreshold")) humidityThreshold = state["humidityThreshold"];

  Serial.println("Local state updated from cloud delta.");
  publishShadowState();
  lastReportedHumidityRange = getHumidityRange(currentHumidity); // Resync range after cloud update
  Serial.println("---");
}

void setupWiFi() {
  delay(10);
  Serial.print("\nConnecting to WiFi...");
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");
  
  Serial.print("Synchronizing time...");
  configTime(0, 0, "pool.ntp.org");
  time_t now = time(nullptr);
  while (now < 8 * 3600 * 2) {
    delay(500);
    Serial.print(".");
    now = time(nullptr);
  }
  Serial.println("\nTime synchronized!");
}

void setup() {
  Serial.begin(115200);
  pinMode(PUMP_RELAY_PIN, OUTPUT);
  digitalWrite(PUMP_RELAY_PIN, LOW); 
  
  setupWiFi();

  wiFiClient.setCACert(AMAZON_ROOT_CA1);
  wiFiClient.setCertificate(CERTIFICATE);
  wiFiClient.setPrivateKey(PRIVATE_KEY);

  client.setServer(MQTT_BROKER, 8883); 
  client.setCallback(callback);
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection to AWS...");
    if (client.connect(CLIENT_ID)) {
      Serial.println(" connected!");
      client.subscribe(UPDATE_DELTA_TOPIC);
      Serial.printf("Subscribed to: %s\n", UPDATE_DELTA_TOPIC);
      delay(100);
       // On reconnect, we force a state publish. Let's read the sensor first.
      long rawValue = analogRead(SOIL_MOISTURE_PIN);
      long mappedValue = map(rawValue, SENSOR_DRY_VALUE, SENSOR_WET_VALUE, 0, 100);
      currentHumidity = constrain(mappedValue, 0, 100);
      lastReportedHumidityRange = getHumidityRange(currentHumidity);
      publishShadowState(); 
    } else {
      Serial.print(" failed, rc=");
      Serial.print(client.state());
      Serial.println(". Retrying in 5 seconds...");
      delay(5000);
    }
  }
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  static unsigned long lastSensorReadMillis = 0;
  if (millis() - lastSensorReadMillis > SENSOR_READ_INTERVAL_MS) {
    lastSensorReadMillis = millis();
    long rawValue = analogRead(SOIL_MOISTURE_PIN);
    long mappedValue = map(rawValue, SENSOR_DRY_VALUE, SENSOR_WET_VALUE, 0, 100);
    currentHumidity = constrain(mappedValue, 0, 100);
    Serial.printf("[SENSOR READ] Current humidity: %.1f%%\n", currentHumidity);
  }
  
  if (mode == "MANUAL") {
    digitalWrite(PUMP_RELAY_PIN, (pumpState == "ON") ? HIGH : LOW);
  } else if (mode == "AUTO") {
    if (currentHumidity < humidityThreshold) {
      if (pumpState != "ON") { pumpState = "ON"; digitalWrite(PUMP_RELAY_PIN, HIGH); }
    } else {
      if (pumpState != "OFF") { pumpState = "OFF"; digitalWrite(PUMP_RELAY_PIN, LOW); }
    }
  }

  // Reporting Logic 
  int currentRange = getHumidityRange(currentHumidity);
  if (currentRange != lastReportedHumidityRange) {
    Serial.printf("Humidity has changed range. Old: %d, New: %d. Reporting to cloud.\n", lastReportedHumidityRange, currentRange);
    publishShadowState();
    lastReportedHumidityRange = currentRange; // Update the last reported range
  }
}