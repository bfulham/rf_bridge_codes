# RF Bridge Codes

A small Home Assistant custom integration for managing named raw RF codes
captured from a Sonoff RF Bridge running the Portisch/`RF-Bridge-OB38S003`
firmware via ESPHome's `rf_bridge` component.

It doesn't do RF capture itself (Portisch's bucket-sniffing output only
shows up in the ESPHome logs, not as an HA event), but once you've got a
B0-format code - via the ESPHome logs and the
[B1 converter tool](https://jonajona.nl/convertB1.html) - this integration
gives you:

- A place to save it under a friendly name, that survives restarts
- A `button` entity per saved code, so it shows up on your dashboard like
  a first-class device
- Services (`rf_bridge_codes.add_code`, `.delete_code`, `.send_code`) so
  scripts and automations can manage/trigger codes without touching YAML

## Requirements

Your ESPHome device needs a raw-send action exposed as a Home Assistant
service. Add this to your `rf-bridge.yaml` (alongside your existing `api:`
block) if you haven't already:

```yaml
api:
  actions:
    - action: send_raw_code
      variables:
        raw: string
      then:
        - rf_bridge.send_raw:
            raw: !lambda 'return raw;'
```

This exposes a service like `esphome.rf_bridge_send_raw_code` (the exact
name depends on your device's `esphome: name:`) - that's what you'll point
this integration at during setup.

## Installation

### Via HACS (custom repository)

1. Push this folder to your own GitHub repository
2. In HACS: **Integrations → ⋮ menu → Custom repositories**, add your repo
   URL with category **Integration**
3. Install **RF Bridge Codes** from HACS, then restart Home Assistant

### Manually

Copy `custom_components/rf_bridge_codes/` into your Home Assistant
`config/custom_components/` folder, then restart Home Assistant.

## Setup

**Settings → Devices & Services → Add Integration → RF Bridge Codes**

Enter the send service from the Requirements section above (e.g.
`esphome.rf_bridge_send_raw_code`) and the parameter name it expects
(`raw`, unless you named it something else in your YAML).

## Usage

**Add a code** (Developer Tools → Actions, or from a script/automation):

```yaml
action: rf_bridge_codes.add_code
data:
  name: "Fan light"
  code: "AAA5070008001000ABC12355"
```

A `button.fan_light` entity appears immediately - press it to transmit
that code.

**Send a code from an automation** without needing the button entity:

```yaml
action: rf_bridge_codes.send_code
data:
  name: "Fan light"
```

**Delete a code:**

```yaml
action: rf_bridge_codes.delete_code
data:
  name: "Fan light"
```

## Notes

- Codes are stored in `.storage/rf_bridge_codes_<entry_id>` and survive
  restarts.
- Only one set of services is registered even if you configure multiple
  RF Bridge Codes entries (e.g. for more than one bridge) - `add_code` /
  `delete_code` currently apply to the first configured entry. If you run
  multiple bridges and want this scoped per-entry, that's the first thing
  worth extending.
