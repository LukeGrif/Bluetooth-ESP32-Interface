// ESP32-WROOM-32 — BLE UART (Nordic UART Service)
// Works with Android AND iPhone. Use an app like "nRF Connect", "Serial Bluetooth Terminal" (BLE mode)
// or "LightBlue". Connect to "ESP32-BLE" — no pairing needed.
// Send "on"/"off" to toggle the LED; anything else is echoed back.

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// Nordic UART Service UUIDs (widely recognised by BLE terminal apps)
#define SERVICE_UUID "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define RX_UUID      "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  // phone -> ESP32
#define TX_UUID      "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  // ESP32 -> phone

const int LED_PIN = 2;

BLECharacteristic *txChar;
bool deviceConnected = false;
bool wasConnected = false;

void sendBLE(const String &text) {
  if (!deviceConnected) return;
  txChar->setValue(text.c_str());
  txChar->notify();
}

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *server) override {
    deviceConnected = true;
    Serial.println("Client connected");
  }
  void onDisconnect(BLEServer *server) override {
    deviceConnected = false;
    Serial.println("Client disconnected");
  }
};

class RxCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    auto value = c->getValue();          // works on ESP32 Arduino core 2.x and 3.x
    String msg = String(value.c_str());
    msg.trim();
    Serial.println("Received: " + msg);

    if (msg == "on") {
      digitalWrite(LED_PIN, HIGH);
      sendBLE("LED ON\n");
    } else if (msg == "off") {
      digitalWrite(LED_PIN, LOW);
      sendBLE("LED OFF\n");
    } else {
      sendBLE("Echo: " + msg + "\n");
    }
  }
};

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);

  BLEDevice::init("ESP32-BLE");
  BLEServer *server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  BLEService *service = server->createService(SERVICE_UUID);

  txChar = service->createCharacteristic(TX_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  txChar->addDescriptor(new BLE2902());

  BLECharacteristic *rxChar = service->createCharacteristic(
      RX_UUID, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  rxChar->setCallbacks(new RxCallbacks());

  service->start();
  BLEAdvertising *adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(SERVICE_UUID);
  adv->setScanResponse(true);
  BLEDevice::startAdvertising();

  Serial.println("BLE advertising as 'ESP32-BLE'");
}

void loop() {
  // Forward USB serial input to the connected BLE client
  if (Serial.available()) {
    sendBLE(Serial.readStringUntil('\n') + "\n");
  }

  // Restart advertising after a disconnect so you can reconnect
  if (!deviceConnected && wasConnected) {
    delay(500);
    BLEDevice::startAdvertising();
    Serial.println("Advertising again");
  }
  wasConnected = deviceConnected;

  delay(10);
}
