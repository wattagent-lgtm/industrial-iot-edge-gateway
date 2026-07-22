# เส้นทางข้อมูลจาก Client ผ่าน Gateway 4G ไปยัง AWS IoT Core

> GitHub-readable edition converted from the project Word reference guide. 
> The original formatted document remains available as 
> [IIoT_Gateway_Client_to_AWS_Data_Flow_TH_v2.docx](IIoT_Gateway_Client_to_AWS_Data_Flow_TH_v2.docx).

**Data flow:** XIAO Client → TCP :5005 → LILYGO Gateway → A7670 4G LTE → AWS IoT Core → Subscriber / Database

```text
วัตถุประสงค์ สรุปการทำงานจริงของระบบตั้งแต่ Client สร้าง JSON, Gateway รับผ่าน TCP, จัดคิว MQTT, ส่งผ่าน A7670 4G/TLS และกระจายข้อมูลด้วย AWS IoT Core ตามโครงสร้าง UNS
```

ระบบอ้างอิง: LILYGO TTGO T-A7670 R2 (ESP32 + A7670E), MicroPython, TCP port 5005, MQTT/TLS port 8883, AWS Region ap-southeast-1

## ภาพรวมระบบ

ระบบแบ่งการสื่อสารออกเป็นสองช่วงอย่างชัดเจน ช่วงแรก Client ใช้ Wi-Fi ภายในโรงงานส่ง JSON เข้า Gateway ผ่าน TCP ส่วนช่วงที่สอง Gateway ใช้โมเด็ม A7670 ส่งข้อมูลออกอินเทอร์เน็ตผ่าน 4G ไปยัง AWS IoT Core ด้วย MQTT over TLS

| ช่วง | ต้นทาง → ปลายทาง | Protocol | หน้าที่ |
| --- | --- | --- | --- |
| Edge LAN | XIAO → Gateway | Wi-Fi + TCP :5005 | รับข้อมูลหน้างานและตอบ ACK อย่างรวดเร็ว |
| Cloud WAN | Gateway → AWS | 4G + MQTT/TLS :8883 | ส่ง telemetry แบบปลอดภัยไปยัง Cloud |
| Command | AWS ↔ Gateway | MQTT request/response | รับคำสั่ง read-only และตอบสถานะกลับ |

### หลักสำคัญ

- TCP ACK หมายถึง Gateway รับ payload แล้ว ไม่ได้หมายความว่า AWS ได้รับแล้ว
- TCP และ MQTT แยกจากกัน เพื่อให้ปัญหา 4G/AWS ไม่ทำให้ Client ต้องรอหรือ TCP server หยุด
- AWS certificate อยู่ที่ Gateway เท่านั้น Client ภายในโรงงานไม่ต้องถือ Cloud credential
- MQTT queue จำกัดขนาดเพื่อป้องกัน RAM เต็มเมื่อการเชื่อมต่อ Cloud ขัดข้อง

## 1. Client สร้าง JSON Payload

Client เช่น XIAO ESP32-C3 อ่าน sensor และสถานะอุปกรณ์ แล้วสร้าง JSON ตาม schema ของระบบ ข้อมูลชุดนี้อาจเป็น telemetry, heartbeat หรือ event

```json
{ "device_id": "XIAO-C3-983DAEACB504", "device_name": "Pump-02", "message_type": "heartbeat", "device_type": "pump_monitor", "area": "process", "status": "ONLINE", "sequence": 1564 }
```

ฟิลด์ sensor, client uptime, Wi-Fi RSSI และ client free memory เป็นค่าจาก Client ไม่ใช่ค่าจาก Gateway

## 2. Client เชื่อมต่อ Gateway ผ่าน TCP

Client เชื่อมไปยัง Gateway IP 192.168.1.42 ที่ TCP port 5005 ผ่าน Wi-Fi LAN จากนั้นส่ง JSON หนึ่งชุด รอ ACK และปิด connection

```text
Client → 192.168.1.42:5005 Payload → JSON UTF-8 ACK → {"status":"OK"}
```

## 3. Gateway ตรวจสอบและจัดการ JSON

Gateway อ่านข้อความภายใต้ขนาดสูงสุด 4096 bytes แล้ว parse JSON หากถูกต้องจะอัปเดตสถิติ, Device Manager, Client IP, Last Seen, Packet Count และ Latest JSON

- JSON ถูกต้อง: เพิ่มเข้า MQTT queue เพื่อส่ง AWS
- JSON ไม่ถูกต้อง: บันทึก Warning และไม่ส่งไป AWS
- TCP server ยังทำงานต่อและไม่ crash จาก payload ผิดรูปแบบ

## 4. Gateway ตอบ ACK ทันที

หลัง Gateway รับและประมวลผล payload จะตอบ Client ด้วย ACK เดิม เพื่อรักษาความเข้ากันได้กับระบบที่ใช้งานอยู่

```json
{"status":"OK"}
```

> ข้อควรจำ ACK ยืนยันเฉพาะการรับที่ Gateway การยืนยันว่า AWS รับข้อมูลแล้วเกิดภายหลังจาก MQTT QoS 1 และ PUBACK

## 5. Gateway สร้าง UNS Topic

Gateway ใช้ area, device_type และ device_id จาก JSON เพื่อสร้าง topic แบบ Unified Namespace โดยแปลงเป็น lowercase และแทน underscore/space ด้วยเครื่องหมายขีดกลาง

```text
dt/iiot-lab/factory1/process/pump-monitor/xiao-c3-983daeacb504/telemetry
```

| Topic level | ความหมาย |
| --- | --- |
| dt | Data/Telemetry |
| iiot-lab | Application namespace |
| factory1 | Site |
| process | Area |
| pump-monitor | Device type |
| xiao-c3-... | Device identity |
| telemetry | Data class |

## 6. ข้อมูลเข้า MQTT Queue

TCP handler ไม่รอการส่ง 4G แต่เพิ่ม topic และ payload ลง RAM queue แล้วคืนการควบคุมทันที Queue ปัจจุบันเก็บได้สูงสุด 20 รายการ

```text
MQTT_QUEUE_CAPACITY = 20 queued = 0 # สถานะปกติ dropped = 0 # ไม่มีข้อมูลถูกทิ้ง
```

หาก queue เต็ม ระบบจะลบรายการเก่าสุดและเพิ่ม dropped counter เพื่อรักษาเสถียรภาพของ Gateway

## 7. A7670 ส่ง MQTT/TLS ผ่าน 4G

ESP32 ควบคุม A7670 ผ่าน UART GPIO26/GPIO27 ที่ 115200 baud โมเด็มเชื่อมต่อ AWS IoT Core ด้วย MQTT/TLS และ mutual X.509 authentication

| รายการ | ค่าที่ใช้งาน |
| --- | --- |
| Broker | YOUR_ENDPOINT-ats.iot.ap-southeast-1.amazonaws.com |
| Port | 8883 |
| Client ID | lte-gw-01 |
| QoS | 1 |
| Root CA | AmazonRootCA1.pem |
| Device identity | Device certificate + private key |

## 8. AWS IoT Core รับและยืนยันข้อมูล

AWS IoT Core ตรวจ certificate และ IoT policy ก่อนรับ MQTT connection เมื่อรับ QoS 1 Publish สำเร็จ Broker ส่ง PUBACK กลับ Gateway จากนั้น Gateway เพิ่ม published counter และลบรายการนั้นออกจาก queue

```text
Gateway PUBLISH → AWS IoT Core Gateway ← PUBACK (QoS 1) published += 1 queue.pop(0)
```

ถ้าการส่งล้มเหลว Gateway เก็บ payload ไว้ใน queue, เปลี่ยนสถานะเป็น RECONNECTING และ retry แบบ exponential backoff ตั้งแต่ 5 วินาทีจนสูงสุด 300 วินาที

## 9. AWS กระจายข้อมูลให้ Subscriber

AWS IoT Core เป็น Broker ที่รับข้อความจาก Gateway แล้วส่งสำเนาไปยังทุกระบบที่ Subscribe topic ตรงกัน ผู้ส่งไม่ต้องรู้ว่ามีผู้รับกี่ราย

- AWS MQTT Test Client สำหรับตรวจข้อมูลสด
- AWS IoT Rule สำหรับส่งต่อไป Timestream, S3 หรือ Lambda
- Dashboard, Alarm service, Analytics หรือ Grafana backend

```text
Subscribe ทั้ง Factory: dt/iiot-lab/factory1/# Subscribe Pump เท่านั้น: dt/iiot-lab/factory1/+/pump-monitor/+/telemetry
```

### Command จาก AWS กลับ Gateway

ช่องคำสั่งใช้ topic แยกจาก telemetry เพื่อควบคุมสิทธิ์และตรวจสอบย้อนหลังได้ง่าย

```text
AWS Publish → cmd/iiot-lab/factory1/gateway/lte-gw-01/request Gateway Reply → cmd/iiot-lab/factory1/gateway/lte-gw-01/response
```

Firmware ปัจจุบันอนุญาตเฉพาะคำสั่ง read-only get_status คำสั่ง restart หรือ control จะถูก REJECTED

## เวลาโดยประมาณและพฤติกรรมเมื่อเกิดปัญหา

| ขั้นตอน | เวลาโดยทั่วไป | หมายเหตุ |
| --- | --- | --- |
| Client → Gateway TCP | 10–100 ms | ขึ้นกับ Wi-Fi LAN |
| Gateway ตอบ ACK | 10–200 ms | ไม่รอ AWS |
| Queue → A7670 | 0–500 ms | ขึ้นกับ queue depth |
| 4G → AWS | 50–1,000 ms | ขึ้นกับ LTE signal/network |
| AWS → Subscriber | 10–500 ms | Subscriber ต้อง Connected |
| รวมโดยทั่วไป | 0.2–2 s | อาจสูงขึ้นเมื่อ reconnect |

### Failure behavior

| เหตุการณ์ | พฤติกรรมระบบ |
| --- | --- |
| AWS/4G ขาดช่วงสั้น | TCP ยังตอบ ACK; payload รอใน RAM queue |
| Queue เต็ม 20 รายการ | ทิ้งรายการเก่าสุดและเพิ่ม dropped |
| Gateway restart | RAM queue หาย; certificate ใน modem ยังอยู่ |
| JSON ผิดรูปแบบ | ไม่ส่ง AWS; บันทึก Warning |
| MQTT error | ไม่กระทบ TCP ACK; reconnect อัตโนมัติ |

## สรุปสถานะสถาปัตยกรรม

> ผลลัพธ์ ระบบแยก local ingestion ออกจาก cloud transport ได้สำเร็จ Client ส่งข้อมูลผ่าน TCP ที่เสถียร ขณะที่ Gateway จัดการ TLS credential, MQTT queue, 4G reconnect และ UNS routing แทน Client

- Local TCP compatibility: รักษา port 5005 และ ACK เดิม
- Cloud security: MQTT mutual TLS ด้วย AWS IoT certificate
- UNS readiness: Topic มีโครงสร้าง Site / Area / Device Type / Device ID
- Bidirectional test: Telemetry ขึ้น AWS และ get_status command ตอบกลับสำเร็จ
- Production gap: ควรเพิ่ม SD-card store-and-forward เพื่อไม่ให้ queue หายเมื่อ reboot

## ตัวอย่าง Big System Architecture

ได้ครับ ตัวอย่าง Big System สำหรับหลายเครื่องจักร หลายโรงงาน และเชื่อม AWS IoT มีโครงสร้างดังนี้:

### 1) Factory และ Edge Layer

| Factory 1 | Industrial Edge Gateway | Factory 2 |
| --- | --- | --- |
| Sensors / PLC / Machines XIAO Pump-01, Pump-02 Wi-Fi LAN + JSON/TCP | TCP :5005 → Validation Device Manager → MQTT Queue Local Dashboard → A7670E 4G | Sensors / PLC / Machines Gateway 02 TCP, Modbus หรือ Wi-Fi |

Gateway 01 / Gateway 02 → MQTT over TLS :8883 ผ่าน 4G หรือ Ethernet → AWS

### 2) AWS IoT Core และ Cloud Services

| AWS IoT Core | Identity & State | Rules & Processing | Operations |
| --- | --- | --- | --- |
| MQTT Broker Publish / Subscribe QoS 1 + PUBACK | Thing Registry X.509 Certificate Policy + Device Shadow | IoT Rules Lambda Filtering / Routing | IoT Jobs / OTA Device Defender CloudWatch Logs |

AWS IoT Rules → Storage / Analytics / Alarm → Users and Applications

### 3) Data Platform และผู้ใช้งาน

| Storage | Processing & Alarm | Applications |
| --- | --- | --- |
| Amazon Timestream Amazon S3 DynamoDB | AWS Lambda Amazon SNS Email / SMS Alarm | Grafana Dashboard Web / Mobile App SCADA / MES / Engineer |

```text
เส้นทางข้อมูลหลัก Sensor / Machine → XIAO Client → TCP :5005 → LILYGO Gateway → MQTT Queue → A7670E 4G → AWS IoT Core → IoT Rule → Database / Alarm / Dashboard
```

### UNS สำหรับระบบหลายโรงงาน

```text
dt/<company>/<factory>/<area>/<line>/<device-type>/<device-id>/<data-class> dt/iiot-lab/factory1/process/line01/pump/xiao-c3-01/telemetry dt/iiot-lab/factory2/utility/line02/motor/motor-07/alarm
```

คำสั่งจาก Cloud ใช้ namespace แยกจาก telemetry เพื่อกำหนดสิทธิ์และตรวจสอบย้อนหลังได้ง่าย

```text
cmd/iiot-lab/factory1/gateway/lte-gw-01/request cmd/iiot-lab/factory1/gateway/lte-gw-01/response
```

## หลักการจัดการ Multi-rate Sampling และ JSON Payload

Parameter ของเครื่องจักรหนึ่งเครื่องอาจต้องอ่านด้วยช่วงเวลาต่างกัน หลักสำคัญคือต้องแยก Sampling rate ออกจาก Publish rate: Client อ่าน Sensor ตามรอบที่ต้องการ เก็บค่าล่าสุดหรือสถิติในหน่วยความจำ แล้วรวมเป็น JSON เพื่อส่ง Gateway ตามรอบที่เหมาะสม

```text
หลักการ Sensor sampling → Edge cache / rolling statistics → JSON aggregation → Persistent TCP/NDJSON → MQTT queue → AWS IoT Core
```

### ตัวอย่าง Sampling Schedule

| Parameter | Sampling | Samples/s | วิธีบรรจุใน JSON |
| --- | --- | --- | --- |
| Temperature | 2 s | 0.5 | ค่าล่าสุด + sample_time + age_ms |
| Flow / Pressure | 0.5 s | 2 | average / min / max หรือค่าล่าสุด |
| Vibration | 0.1 s | 10 | RMS / peak / crest factor; ไม่ส่ง raw ต่อเนื่อง |
| Machine status | 0.5 s | 2 | ส่งเมื่อเปลี่ยน + heartbeat |

### รอบการส่งที่แนะนำ

- Fast telemetry: Flow, Pressure, Vibration features และ Machine status ทุก 1 วินาที
- Slow telemetry: Temperature, Energy และ Runtime ทุก 5–30 วินาที หรือเมื่อเกิน deadband
- Event / Alarm: ส่งทันทีเมื่อสถานะเปลี่ยน โดยไม่รอรอบ telemetry
- Diagnostic waveform: ส่งเฉพาะเมื่อเกิด alarm หรือ Cloud สั่ง capture
- Heartbeat: ส่งทุก 30–60 วินาที แม้ค่าไม่เปลี่ยน เพื่อยืนยันว่า Device ยัง Online

### ตัวอย่าง Aggregated JSON ต่อช่วงเวลา 1 วินาที

```json
{ "message_type":"telemetry", "device_id":"PUMP-01", "timestamp":"2026-07-21T13:00:01.000Z", "window_ms":1000, "sequence":10521, "data":{ "temperature_c":{"value":38.5,"age_ms":1000,"quality":"GOOD"}, "flow_lpm":{"average":124.8,"minimum":123.9,"maximum":125.7,"samples":2}, "vibration_mm_s":{"rms":0.72,"peak":1.21,"samples":10}, "machine_run":{"value":true,"changed":false} } }
```

### Event-driven JSON

Machine status และ Alarm สำคัญต้องส่งทันทีเมื่อเกิดเหตุ และใช้ message_id / sequence สำหรับตรวจ duplicate หรือ packet ที่หาย

```json
{ "message_type":"event", "event_type":"machine_status_changed", "device_id":"PUMP-01", "timestamp":"2026-07-21T13:00:01.250Z", "sequence":10522, "data":{"previous_status":"RUNNING","new_status":"STOPPED","reason":"OVERLOAD"} }
```

### Deadband และ Change of Value

| Parameter | ตัวอย่าง Deadband | กฎการส่ง |
| --- | --- | --- |
| Temperature | 0.2 °C | ส่งเมื่อเปลี่ยนเกินเกณฑ์หรือครบ heartbeat |
| Flow | 1 L/min | ส่งค่า summary เมื่อเปลี่ยนเกินเกณฑ์ |
| Pressure | 0.05 bar | ส่งค่าใหม่พร้อม quality |
| Vibration RMS | 0.05 mm/s | ส่ง summary; raw เฉพาะ diagnostic |

## กฎคำนวณ Data-flow Traffic

ให้คำนวณแยกแต่ละช่วง เพราะ JSON payload, TCP framing, MQTT topic, TLS และ Cellular network มี overhead ต่างกัน การวัดต้องใช้จำนวน UTF-8 bytes จริง ไม่ใช่จำนวนตัวอักษร

### ตัวแปรและสูตรหลัก

| ตัวแปร | ความหมาย | สูตร |
| --- | --- | --- |
| P | JSON payload (bytes) | UTF-8 byte count ของ JSON |
| T | MQTT topic (bytes) | UTF-8 byte count ของ topic |
| R | Publish rate | messages/second |
| D | จำนวนวัน | เช่น 30 days/month |
| O | MQTT/TLS/IP overhead | ประมาณ 100 bytes/message สำหรับ planning |

```text
JSON bytes/s = P × R TCP LAN bytes/s = (P + 1 newline + TCP/IP/ACK overhead) × R 4G bytes/day ≈ (P + T + O) × R × 86,400 4G bytes/month ≈ (P + T + O) × R × 86,400 × D
```

> Planning margin เพิ่ม 10–20% สำหรับ TLS handshake, MQTT reconnect, retransmission และความผันผวนของเครือข่าย 4G

### ตัวอย่าง: JSON 800 bytes, Topic 70 bytes, 1 msg/s

```text
Monthly traffic ≈ (800 + 70 + 100) × 1 × 86,400 × 30 = 2,514,240,000 bytes ≈ 2.51 GB/month With 20% margin ≈ 3.02 GB/month per Gateway
```

### ตารางประมาณการ 4G ที่ 1 message/second

| JSON size | โดยประมาณ/วัน | โดยประมาณ/30 วัน | คำแนะนำ |
| --- | --- | --- | --- |
| 300 B | ~41 MB | ~1.2 GB | Telemetry ขนาดเล็ก |
| 500 B | ~58 MB | ~1.7 GB | 10–20 tags แบบกระชับ |
| 1,000 B | ~101 MB | ~3.0 GB | 20–30 tags ที่แนะนำ |
| 2,000 B | ~187 MB | ~5.6 GB | ควรลด field หรือ rate |
| 4,000 B | ~360 MB | ~10.8 GB | ใกล้ TCP frame limit; ไม่แนะนำต่อเนื่อง |

### ข้อกำหนดสำหรับ Gateway ปัจจุบัน

- ขนาด TCP JSON สูงสุด 4,096 bytes แต่ production payload ควรอยู่ประมาณ 1 KB
- แนะนำ 20–30 tags ต่อ aggregated JSON และ publish 1 message/second
- ใช้ Persistent TCP/NDJSON เพื่อลด handshake, RAM allocation และ latency
- TCP ACK ยืนยันว่า Gateway รับ frame แล้ว ไม่ได้ยืนยันว่า DynamoDB บันทึกสำเร็จ
- ติดตาม MQTT queued / dropped / published และ DynamoDB throttling แยกจาก TCP success
- ใช้ TTL หรือ retention policy เพื่อควบคุมจำนวน items และ storage ใน Cloud

### Checklist ออกแบบ Payload

- ทุก message มี device_id, message_id, timestamp, sequence และ quality
- กำหนด sampling interval, publish interval, deadband และ heartbeat ต่อ parameter
- Fast signal ส่งสถิติ; Raw waveform ส่งเฉพาะเหตุการณ์หรือคำสั่ง diagnostic
- Event/Alarm แยกจาก periodic telemetry และมี priority สูงกว่า
- วัด JSON ด้วย UTF-8 bytes และเผื่อ network overhead 10–20%

### คำศัพท์ย่อ

| คำศัพท์ | ความหมาย |
| --- | --- |
| Publish | ส่งข้อความไปยัง MQTT topic |
| Subscribe | รอรับข้อความจาก topic หรือ topic filter |
| Broker | ศูนย์กลางรับและกระจาย MQTT message; ในระบบนี้คือ AWS IoT Core |
| QoS 1 | ส่งอย่างน้อยหนึ่งครั้งและมี PUBACK; ผู้รับต้องรองรับ duplicate |
| UNS | Unified Namespace: โครงสร้าง topic กลางของข้อมูลอุตสาหกรรม |
| TLS | การเข้ารหัสและตรวจสอบตัวตนระหว่าง Gateway กับ AWS |
| Store-and-forward | เก็บข้อมูลระหว่าง offline แล้วส่งต่อเมื่อเชื่อมกลับ |

## ผลการทดสอบเปรียบเทียบ Payload แบบเดิมและ Multi-rate

ทำการทดสอบ A/B บน Gateway เดียวกันเป็นเวลา 180 วินาทีต่อแนวคิด ผ่าน TCP port 5005 และส่งต่อไปยัง AWS IoT Core ผ่าน A7670E 4G เพื่อวัดผลตั้งแต่ TCP ACK, JSON payload, MQTT queue จนถึง traffic บนเครือข่ายโดยประมาณ

```text
เงื่อนไขการทดสอบ แบบเดิมส่ง Full JSON snapshot ของทุก parameter ทุก 100 ms โดยไม่มี aggregation/deadband ส่วนแบบใหม่อ่าน Sensor ตาม sampling rate จริง แล้วส่ง fast/slow/event/diagnostic แยกกัน พร้อม aggregation และ deadband
```

### ผล A/B Test วันที่ 21 กรกฎาคม 2026

| ตัวชี้วัด | แบบเดิม | Multi-rate | ผลการเปลี่ยนแปลง |
| --- | --- | --- | --- |
| TCP success | 100% | 100% | คงความน่าเชื่อถือ |
| Messages attempted | 587 | 209 | ลดลง 64.4% |
| JSON payload | 260,863 B | 101,002 B | ลดลง 61.3% |
| Estimated 4G traffic | 360,653 B | 136,532 B | ลดลง 62.1% |
| Average TCP ACK latency | 210.7 ms | 204.9 ms | ดีขึ้น 2.8% |
| Maximum TCP ACK latency | 501.7 ms | 495.9 ms | ดีขึ้นเล็กน้อย |
| MQTT published | 181 | 178 | ข้อมูลถึง Cloud ใกล้เคียงกัน |
| MQTT dropped | 387 | 16 | ลดลง 95.9% |
| MQTT failed | 0 | 0 | ไม่พบ publish failure |
| MQTT queue ตอนจบ | 20 | 18 | ยังมี backlog เล็กน้อย |

### การกระจาย Message ของ Multi-rate

| Data class | จำนวน | วัตถุประสงค์ |
| --- | --- | --- |
| telemetry/fast | 153 | Flow และ Vibration summary |
| telemetry/slow | 40 | Temperature ที่ผ่าน deadband |
| event | 11 | Machine status change ส่งทันที |
| diagnostic | 5 | Vibration samples สำหรับวิเคราะห์ |

### ข้อสรุปเชิงวิศวกรรม

- แบบเดิมรับ TCP สำเร็จ 100% แต่ MQTT drop 387 จาก 587 messages หรือประมาณ 65.9% เพราะสร้างข้อมูลเร็วกว่าความสามารถส่งผ่าน A7670E/AWS
- แบบ Multi-rate ลด MQTT drop เหลือ 16 จาก 209 messages หรือประมาณ 7.7% โดยจำนวน MQTT published ใกล้เคียงแบบเดิม
- การลด messages และ payload ไม่ได้ทำให้สูญเสียความละเอียดในการตรวจวัด เพราะ Vibration ยัง sampling ทุก 100 ms แต่ส่ง RMS/peak แบบ aggregated
- Event สำคัญยังส่งทันที จึงไม่ควรรวม Event/Alarm ไว้รอรอบ periodic telemetry
- TCP ACK 100% ยืนยันว่า Gateway รับข้อมูลครบ แต่ต้องตรวจ mqtt_published, mqtt_dropped และ queue_end เพิ่มเติมเพื่อยืนยันเส้นทางถึง Cloud

> ข้อสรุป Multi-rate + aggregation + deadband ลด estimated 4G traffic ประมาณ 62.1% และลด MQTT drop ประมาณ 95.9% เมื่อเทียบกับ Full Snapshot โดยยังรักษา TCP success 100% และจำนวนข้อมูลที่ publish ถึง AWS ใกล้เคียงกัน

### ค่าที่แนะนำสำหรับการใช้งานต่อเนื่อง

| รายการ | ค่าที่แนะนำ | หมายเหตุ |
| --- | --- | --- |
| Vibration sampling | 100 ms | คำนวณ RMS/peak ที่ Edge |
| Flow/status sampling | 500 ms | เก็บ latest/min/max/average |
| Temperature sampling | 2,000 ms | sampling ไม่จำเป็นต้องเท่ากับ publish |
| Fast publish | 1,500 ms | ลดโอกาส MQTT queue เต็ม |
| Slow publish | 5,000 ms | ส่งเมื่อเกิน deadband หรือครบ heartbeat |
| Diagnostic publish | 60,000 ms | ควรเปลี่ยนเป็น on-demand ใน production |
| Event/Alarm | ทันที | ไม่ผ่าน deadband และให้ priority สูง |

แหล่งข้อมูลการทดสอบ: concept-comparison-20260721-222805.csv และ multirate-20260721-223128.csv

## สรุปการปรับปรุงโปรแกรม Gateway

สถานะระบบ ณ วันที่ 22 กรกฎาคม 2026 | Firmware 2.0.1

ระบบเดิมยังคง TCP port 5005 และ ACK {"status":"OK"} ไว้ครบถ้วน แต่ได้รับการยกระดับให้เป็น Industrial IoT Gateway แบบ modular ซึ่งแยกการรับข้อมูลภายในโรงงาน ออกจากการส่งข้อมูลผ่าน 4G/AWS เพื่อลดผลกระทบจาก latency และการเชื่อมต่อ Cloud ที่ไม่แน่นอน

### ภาพรวมสถาปัตยกรรมที่ใช้งานอยู่

| ชั้นระบบ | องค์ประกอบ | หน้าที่หลัก |
| --- | --- | --- |
| Client | XIAO ESP32-C3 / Sensor Node | อ่าน tag ตาม sampling rate, สร้าง JSON และส่ง TCP |
| Local ingestion | TCP Server :5005 | ตรวจ frame/JSON และตอบ ACK ทันที |
| Edge processing | Device Manager / Logger / Queue | อัปเดตอุปกรณ์, log, priority และ coalescing |
| Cellular | A7670E 4G LTE | MQTT/TLS ผ่าน APN พร้อมตรวจ registration และ internet |
| Cloud broker | AWS IoT Core | รับ telemetry, กระจาย UNS topic และรับ command |
| Data platform | AWS IoT Rule / DynamoDB | จัดเก็บข้อมูลตาม device_id และ received_at |

### รายการปรับปรุงโปรแกรม

| ด้าน | การปรับปรุง | ผลลัพธ์ |
| --- | --- | --- |
| Modular architecture | แยก boot, gateway, TCP, Web, Device, Modem, MQTT, Logger และ Utilities | เพิ่มฟังก์ชันและบำรุงรักษาได้โดยไม่รื้อระบบเดิม |
| TCP stability | รองรับ bounded JSON/NDJSON, persistent connection, timeout และ immediate ACK | Cloud/LTE ไม่บล็อก ACK ของ Client |
| Async MQTT | ใช้ bounded asynchronous queue แยกจาก TCP handler | TCP ทำงานต่อแม้ AWS ช้าหรือ reconnect |
| Priority/coalescing | Event มี priority และ telemetry ล่าสุดแทนค่าซ้ำใน queue | ลด traffic โดยไม่ทิ้งเหตุการณ์สำคัญ |
| Multi-rate payload | แยก fast, slow, event และ diagnostic พร้อม deadband/delta | รองรับ sampling rate ที่ต่างกันในเครื่องเดียว |
| LTE management | ควบคุม A7670E, SIM, registration, CSQ, APN, mobile IP และ internet test | มองเห็นสุขภาพ 4G และ reconnect ได้ |
| AWS IoT | MQTT/TLS, X.509, UNS topic, command/response | ส่งข้อมูลผ่าน 4G และควบคุมแบบ read-only ได้ |
| DynamoDB | AWS IoT Rule ส่ง telemetry เข้า DynamoDB | ตรวจข้อมูลย้อนหลังด้วย device_id/received_at |
| Dashboard/API | Dashboard responsive และ REST API รวม /api/health | ติดตาม Gateway, network, devices, logs และ statistics |
| Network identity | Static IP 192.168.1.42 ทั้ง boot และ Wi-Fi recovery | Client และ monitoring หา Gateway เดิมหลัง reboot |
| Service recovery | Wi-Fi/HTTP supervisor, request limit และ bounded writer close | ลด service hang และ socket leak |
| Fatal recovery | บันทึก crash.log แล้ว hardware reset หลัง unhandled exception | ล้าง stale lwIP sockets และกลับ online อัตโนมัติ |
| Memory control | จำกัด queue/log/device/request และเรียก GC ตาม memory pressure | ลดโอกาส RAM หมดและ memory leak |

### ลำดับการประมวลผลข้อมูล

- Client อ่าน sensor ตาม sampling schedule และรวมข้อมูลเป็น fast/slow/event/diagnostic JSON
- Client ส่ง JSON ไปยัง 192.168.1.42:5005 ผ่าน TCP
- Gateway ตรวจขนาด frame และ parse JSON ภายใต้ขอบเขตที่กำหนด
- Gateway ตอบ ACK ทันทีหลัง validation โดยไม่รอ LTE หรือ AWS
- Gateway อัปเดต Device Manager แล้วเพิ่มข้อมูลเข้า asynchronous MQTT queue
- Queue ใช้ priority และ coalescing เพื่อลด backlog และรักษา Event สำคัญ
- A7670E ส่ง MQTT/TLS ไป AWS IoT Core ผ่าน 4G
- AWS IoT Rule ส่งข้อความไป DynamoDB และ subscriber อื่นตาม UNS topic

### Recovery และข้อควรระวังในการปฏิบัติงาน

- Static IP ถูกกำหนดในโปรแกรม แต่ควรทำ DHCP reservation ใน Router เพื่อป้องกัน IP conflict
- เมื่อเกิด unhandled exception ระบบบันทึก crash.log, รอ 5 วินาที และ reset เพื่อคืน TCP/HTTP/MQTT
- คำสั่ง mpremote repl หรือ mpremote exec สามารถ interrupt main.py ได้ จึงห้ามใช้ระหว่าง reliability/load test
- TCP ACK ยืนยันเฉพาะว่า Gateway รับ frame แล้ว ต้องตรวจ MQTT published/dropped/failed และ DynamoDB แยกต่างหาก
- Production ขั้นถัดไปควรเพิ่ม SD-card store-and-forward เพื่อรักษาข้อมูลระหว่าง 4G outage หรือ reboot

### ผล Validation ต่อเนื่อง 30 นาที

| ตัวชี้วัด | ผลทดสอบ | สถานะ |
| --- | --- | --- |
| ระยะเวลา | 1,800.2 วินาที | PASS |
| TCP ACK | 2,032 / 2,032 (100%) | PASS |
| Gateway availability | 60 / 60 samples (100%) | PASS |
| TCP/HTTP offline | 0 samples | PASS |
| Gateway restart | 0 ครั้ง | PASS |
| MQTT publish / coalesced | 1,440 / 630 messages | PASS |
| MQTT dropped / failed | 0 / 0 | PASS |
| MQTT queue ตอนจบ | 0 | PASS |
| TCP latency | เฉลี่ย 182.9 ms, สูงสุด 627.2 ms | PASS |
| Free memory | เริ่ม 68.2 KB, ต่ำสุด 29.3 KB, จบ 67.7 KB | PASS |
| LTE signal | เฉลี่ย -70.4 dBm | PASS |
| Estimated 4G traffic | ประมาณ 1.34 MB / 30 นาที | OBSERVED |

### ข้อสรุปสถานะปัจจุบัน

Gateway ผ่านการทดสอบต่อเนื่อง 30 นาทีโดยไม่มี TCP failure, service restart, LTE failure หรือ MQTT drop ระบบสามารถรับข้อมูลเฉลี่ยประมาณ 1.2 messages/second และแตะสูงสุด 3.32 messages/second พร้อมระบาย MQTT queue จนหมด ทั้งนี้ต้องทดสอบ 2–5 ชั่วโมงเพิ่มเติมเพื่อยืนยัน long-term stability ก่อนนำไปใช้ production และควรเพิ่ม persistent store-and-forward เป็นลำดับถัดไป

แหล่งข้อมูลผลทดสอบ: multirate-20260722-212828.csv และ reliability-20260722-212835.csv
