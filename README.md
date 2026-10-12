# DOT-NL Chargers for Home Assistant

🇬🇧 English · [🇳🇱 Nederlands](README.nl.md)

See which sockets of a public charge point in the Netherlands are free, and
get a notification when one becomes available. Uses the open data of
[DOT-NL](https://docs.ndw.nu/en/data-uitwisseling/interface-beschrijvingen/dafne-api/)
(NDW); no account or API key needed.

## Installation

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TerrorSource&repository=ha-dotnl-chargers&category=integration)

1. In HACS, open the three-dot menu → **Custom repositories** and add
   `https://github.com/TerrorSource/ha-dotnl-chargers` as **Integration**
   (or use the button above).
2. Download **DOT-NL Chargers** and restart Home Assistant.

## Adding a charge point

[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dotnl_chargers)

Go to **Settings → Devices & services → Add integration → DOT-NL Chargers**
and choose one of:

- **Enter the charge point ID** – the EVSE ID of a socket, e.g.
  `NL*TNM*EGL31*1*1049*07*1`. It is usually on a sticker next to the socket, and
  in most charging apps or on the invoice of a charging session. Punctuation
  and case do not matter and the socket number at the end may be left out.
- **Search on the map** – put the marker near the charge point and pick it
  from the list. No ID needed.

Repeat this for every charge point you want to follow.

## Entities

| Entity | Description |
| --- | --- |
| Available | On when at least one socket is free. |
| Socket 1, Socket 2, … | On when that socket is free. |
| Available connectors | Number of free connectors. |
| Total connectors | Number of connectors (diagnostic). |
| Last updated | Last status change reported by the operator (diagnostic). |

Data is refreshed every 60 seconds; change this with **Configure** on the
integration entry.

## How it works

DOT-NL's fast API reports *how many* connectors are free and is polled every
refresh. *Which* socket is free is only published in a large national file
(~17 MB). The integration avoids that download where it can: when all sockets
are free or all are in use, every socket is known already. Only when some are
free and some are not is the file read, and again when that situation changes.

The file can be up to a minute behind, so right after a change a socket sensor
may briefly show the previous situation.

## Notification when a charge point becomes available

[![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FTerrorSource%2Fha-dotnl-chargers%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fdotnl_chargers%2Fnotify_when_available.yaml)

Import the blueprint, create an automation from it and pick the **Available**
sensor of the charge point and the phone to notify. Select a toggle helper as
well if you want just one notification: it is only sent while the toggle is
on, and the toggle switches off afterwards.

## Automation examples

The entity IDs below belong to a charge point named *Schiekade 988*; replace
them with your own, and `notify.mobile_app_my_phone` with your phone.

**1. When the number of free sockets changes**

```yaml
triggers:
  - trigger: state
    entity_id: sensor.schiekade_988_available_connectors
    not_from: [unavailable, unknown]
    not_to: [unavailable, unknown]
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: Schiekade 988
      message: >-
        {{ trigger.to_state.state }} of
        {{ state_attr(trigger.entity_id, 'total') }} sockets free
        (was {{ trigger.from_state.state }}).
```

**2. When the charge point becomes available, or is fully occupied**

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.schiekade_988_available
    from: ["on", "off"]
    to: ["on", "off"]
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: Schiekade 988
      message: >-
        {{ 'Available again.' if trigger.to_state.state == 'on'
           else 'All sockets are in use.' }}
```

To be notified only when it becomes available again, use `from: "off"` and
`to: "on"`.

**3. When your favourite socket becomes free**

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.schiekade_988_socket_1
    from: "off"
    to: "on"
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: Schiekade 988
      message: Socket 1 is free.
```
