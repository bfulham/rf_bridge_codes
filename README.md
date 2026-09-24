# RF Bridge Codes

A Home Assistant integration that **learns, saves and sends RF remote codes**
through a Sonoff RF Bridge running the Portisch `RF-Bridge-OB38S003`
firmware and ESPHome.

Name a code, press the button on your remote, done: you get a button
entity that sends it. No log digging, no B1 converter. The integration
captures the bucket-sniffing (B1) frame and converts it to a sendable B0
code for you.

## 1. Add this to your RF Bridge's ESPHome YAML

Add the `debug:` block to your existing `uart:` section, and the two
actions to your `api:` section, then install the update on the bridge.

```yaml
uart:
  # ... keep your existing tx_pin / rx_pin / baud_rate lines ...
  debug:
    direction: RX
    after:
      bytes: 512
      timeout: 20ms
    sequence:
      - if:
          condition:
            lambda: |-
              for (size_t i = 0; i + 1 < bytes.size(); i++)
                if (bytes[i] == 0xAA && bytes[i + 1] == 0xB1) return true;
              return false;
          then:
            - homeassistant.event:
                event: esphome.rf_bridge_bucket
                data:
                  raw: !lambda |-
                    std::string hex;
                    char b[3];
                    for (uint8_t c : bytes) {
                      snprintf(b, sizeof(b), "%02X", c);
                      hex += b;
                    }
                    return hex;

api:
  actions:
    - action: send_raw_code
      variables:
        raw: string
      then:
        - rf_bridge.send_raw:
            raw: !lambda 'return raw;'
    - action: start_bucket_sniffing
      then:
        - rf_bridge.start_bucket_sniffing:
```

The `debug:` block forwards the bridge's captured codes to Home Assistant,
`send_raw_code` sends them, and `start_bucket_sniffing` puts the bridge
into listening mode when you learn a code.

## 2. Install the integration

**HACS:** HACS → ⋮ → **Custom repositories** → add
`https://github.com/bfulham/rf_bridge_codes` as an **Integration** →
install **RF Bridge Codes** → restart Home Assistant.

**Manually:** copy `custom_components/rf_bridge_codes/` into your Home
Assistant `config/custom_components/` folder and restart.

Then **Settings → Devices & services → Add integration → RF Bridge Codes**.
Your bridge's send action is picked for you. Just press Submit.

## 3. Learn a code

**Settings → Devices & services → RF Bridge Codes → Configure → Learn a
new code**. Type a name (e.g. `Fan light`), press Submit, then press the
button on your remote once within 30 seconds.

The integration keeps listening for a second after the first code
arrives, because many remotes send a different "still held" code after
the first one. If it heard more than one code, you get **Try code 1**,
**Try code 2** and so on. Try each one, then press **Save** to keep the
one you tried last. If none of them work, choose **Listen again**.

Once saved, a `button.…_fan_light` entity appears. Press it to send the
code, or put it on a dashboard.

To remove a code: **Configure → Delete a code**.

### Repeats

Each code is sent 3 times back to back by default. If one press toggles
something twice (e.g. a light goes off then straight back on), lower it.
If codes are often missed, raise it. The setting is under
**Configure → Settings** and applies to all saved codes.

## Actions (for scripts and automations)

| Action | What it does |
| --- | --- |
| `rf_bridge_codes.learn_code` | Waits for a remote press and saves the first code heard under `name` |
| `rf_bridge_codes.send_code` | Sends the saved code called `name` |
| `rf_bridge_codes.delete_code` | Deletes the saved code called `name` |
| `rf_bridge_codes.add_code` | Saves a B0 `code` you already have under `name` |

```yaml
action: rf_bridge_codes.send_code
data:
  name: "Fan light"
```

## Troubleshooting

- **"No RF signal received"**: hold the remote close to the bridge and
  press the button a couple of times. Check the ESPHome logs for
  `Received RFBridge Bucket`. If that never appears, the bridge isn't
  running Portisch firmware with bucket sniffing.
- **The learned code doesn't work**: learn it again and try each code
  offered. If only one is offered and it doesn't work, the bridge probably
  missed the first burst, so choose **Listen again**.
- **One press toggles twice**: lower **Repeats** under Configure →
  Settings.

## Notes

- Codes are stored in `.storage/rf_bridge_codes_<entry_id>` and survive
  restarts.
- With more than one bridge, the actions above use the first one you set
  up. Learning and deleting from **Configure** always use that bridge.
