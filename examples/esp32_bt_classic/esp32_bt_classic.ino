// ESP32-WROOM-32 — Bluetooth Classic (Serial Port Profile)
// Pair your phone/PC with "ESP32-BT", then open a Bluetooth serial terminal.
// Anything you type in the Arduino Serial Monitor is sent over Bluetooth, and vice versa.
// Android app: "Serial Bluetooth Terminal". Note: iPhones do NOT support Classic SPP; use the BLE sketch.

#include "BluetoothSerial.h"

#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED)
#error Bluetooth is not enabled. Use an ESP32 (not S2/S3/C3) board and the standard partition scheme.
#endif

BluetoothSerial SerialBT;

const int LED_PIN = 2;  // Onboard LED on most ESP32 DevKit boards

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);

  SerialBT.begin("ESP32-BT");  // Bluetooth device name
  Serial.println("Bluetooth started. Pair with 'ESP32-BT'.");
}

void loop() {
  // USB serial -> Bluetooth
  if (Serial.available()) {
    SerialBT.write(Serial.read());
  }

  // Bluetooth -> handle commands and echo to USB serial
  if (SerialBT.available()) {
    String msg = SerialBT.readStringUntil('\n');
    msg.trim();
    Serial.println("Received: " + msg);

    if (msg == "on") {
      digitalWrite(LED_PIN, HIGH);
      SerialBT.println("LED ON");
    } else if (msg == "off") {
      digitalWrite(LED_PIN, LOW);
      SerialBT.println("LED OFF");
    } else {
      SerialBT.println("Echo: " + msg);
    }
  }

  delay(10);
}
