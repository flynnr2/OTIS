# OTIS_ENABLE_H1_DAC_SWEEP notes

## 3. Bench Smoke Test, DAC Not Connected To OCXO

DAC unloaded voltage check, **before** resistor, VOUT/+ pin, GND common, VCOCXO tune disconnected:
0x7000 = 1.094 V
0x8000 = 1.250 V
0x9000 = 1.407 V
AD5693R appears to be internal 2.5 V reference, 1x gain.

DAC unloaded voltage check, **after** resistor, VOUT/+ pin, GND common, VCOCXO tune disconnected:
0x7000 = 1.094 V
0x8000 = 1.249 V
0x9000 = 1.406 V
AD5693R appears to be internal 2.5 V reference, 1x gain.

## 4. Capture And Parse A Real Sweep Run

DAC unloaded voltage check, **after** resistor, VOUT/+ pin, GND common, VCOCXO tune disconnected:
SWEEP LOAD tiny_plus_minus_1
1.249 V -> 1.288 V -> 1.249 V -> 1.210 V -> 1.249 V

DAC unloaded voltage check, **after** resistor, VOUT/+ pin, GND common, VCOCXO tune disconnected:
SWEEP LOAD tiny_plus_minus_2
1.249 V -> 1.288 V -> 1.249 V -> 1.210 V -> 1.249 V -> 1.327 V -> 1.249 V -> 1.171 V -> 1.249 V

## Stage 1: OCXO / VCOCXO Observe Only & Stage 2: DAC Verify, Still Not Connected To Tune Pin
DAC MID -> 1.249 V
DAC ZERO -> 1.093 V
DAC SET 0x8000 -> 1.249 V
DAC SET 0x7000 -> 1.093 V
DAC SET 0x9000 -> 1.405 V

## 2. Capture A Short Manual Step Log at vcocxo pin 4
0x7000 -> Vc = 1.091 V
0x8000 -> Vc = 1.246 V
0x9000 -> Vc = 1.401 V
0x8000 repeat -> Vc = 1.246 V

