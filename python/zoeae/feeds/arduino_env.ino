/*
 * Zoeae Environmental Sensor — Lonely Binary TinkerBlock
 * TK12 (thermistor), TK20 (light), TK57 (optical/proximity)
 * Outputs JSON every 5 seconds on Serial at 9600 baud.
 *
 * Upload to Uno via Arduino IDE.
 * (c) 2026 AnnulusLabs LLC
 */

// Pin assignments — adjust to match your TinkerBlock shield wiring
const int PIN_THERMISTOR = A0;  // TK12 — analog
const int PIN_LIGHT      = A1;  // TK20 — analog
const int PIN_OPTICAL    = 2;   // TK57 — digital

// Thermistor constants (NTC 10k, beta 3950)
const float THERM_R_NOMINAL = 10000.0;
const float THERM_T_NOMINAL = 25.0;
const float THERM_B_COEFF   = 3950.0;
const float THERM_R_SERIES  = 10000.0;

float readTemperature() {
  int raw = analogRead(PIN_THERMISTOR);
  if (raw == 0) return -999.0;
  float resistance = THERM_R_SERIES / (1023.0 / raw - 1.0);
  float steinhart = log(resistance / THERM_R_NOMINAL) / THERM_B_COEFF;
  steinhart += 1.0 / (THERM_T_NOMINAL + 273.15);
  float tempC = 1.0 / steinhart - 273.15;
  return tempC;
}

float readLight() {
  int raw = analogRead(PIN_LIGHT);
  return raw / 1023.0 * 100.0;  // 0-100% scale
}

int readOptical() {
  return digitalRead(PIN_OPTICAL) == LOW ? 1 : 0;  // active low typical
}

void setup() {
  Serial.begin(9600);
  pinMode(PIN_OPTICAL, INPUT);
  delay(1000);
  Serial.println("{\"event\":\"boot\",\"device\":\"zoeae-env\",\"sensors\":[\"TK12\",\"TK20\",\"TK57\"]}");
}

void loop() {
  float tempC = readTemperature();
  float tempF = tempC * 9.0 / 5.0 + 32.0;
  float light = readLight();
  int proximity = readOptical();

  Serial.print("{\"t_c\":");
  Serial.print(tempC, 1);
  Serial.print(",\"t_f\":");
  Serial.print(tempF, 1);
  Serial.print(",\"light\":");
  Serial.print(light, 1);
  Serial.print(",\"prox\":");
  Serial.print(proximity);
  Serial.println("}");

  delay(5000);
}
