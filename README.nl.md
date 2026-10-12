# DOT-NL Chargers voor Home Assistant

[🇬🇧 English](README.md) · 🇳🇱 Nederlands

Zie welke aansluitingen van een openbare laadpaal in Nederland vrij zijn en
krijg een melding zodra er een beschikbaar komt. Gebruikt de open data van
[DOT-NL](https://docs.ndw.nu/data-uitwisseling/interface-beschrijvingen/dafne-api/)
(NDW); geen account of API-key nodig.

## Installatie

[![Openen in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TerrorSource&repository=ha-dotnl-chargers&category=integration)

1. Open in HACS het menu met de drie puntjes → **Aangepaste repositories** en
   voeg `https://github.com/TerrorSource/ha-dotnl-chargers` toe als
   **Integratie** (of gebruik de knop hierboven).
2. Download **DOT-NL Chargers** en herstart Home Assistant.

## Een laadpaal toevoegen

[![Integratie toevoegen](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dotnl_chargers)

Ga naar **Instellingen → Apparaten & diensten → Integratie toevoegen →
DOT-NL Chargers** en kies een van beide:

- **Laadpaal-ID invullen** – het EVSE-ID van een aansluiting, bijvoorbeeld
  `NL*TNM*EGL31*1*1049*07*1`. Het staat meestal op een sticker naast de
  aansluiting, en in de meeste laad-apps of op de factuur van een laadsessie.
  Leestekens en hoofdletters maken niet uit en het nummer van de aansluiting
  aan het eind mag je weglaten.
- **Zoeken op de kaart** – zet de marker bij de laadpaal en kies hem uit de
  lijst. Geen ID nodig.

Herhaal dit voor elke laadpaal die je wilt volgen.

## Entiteiten

| Entiteit | Omschrijving |
| --- | --- |
| Beschikbaar | Aan zodra minstens één aansluiting vrij is. |
| Aansluiting 1, Aansluiting 2, … | Aan als die aansluiting vrij is. |
| Vrije aansluitingen | Aantal vrije aansluitingen. |
| Totaal aansluitingen | Aantal aansluitingen (diagnostisch). |
| Laatst bijgewerkt | Laatste statuswijziging die de exploitant meldde (diagnostisch). |

De gegevens worden elke 60 seconden ververst; pas dit aan via **Configureren**
bij de integratie.

## Hoe het werkt

De snelle API van DOT-NL meldt *hoeveel* aansluitingen vrij zijn en wordt bij
elke verversing opgehaald. *Welke* aansluiting vrij is staat alleen in een
groot landelijk bestand (~17 MB). De integratie vermijdt die download waar het
kan: zijn alle aansluitingen vrij of allemaal bezet, dan is elke aansluiting
al bekend. Alleen als een deel vrij is en een deel niet wordt het bestand
gelezen, en opnieuw zodra die situatie verandert.

Het bestand kan tot een minuut achterlopen, dus vlak na een wijziging kan een
aansluiting kort de vorige situatie tonen.

## Melding wanneer een laadpaal beschikbaar komt

[![Blueprint importeren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FTerrorSource%2Fha-dotnl-chargers%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fdotnl_chargers%2Fmelding_bij_beschikbaar.yaml)

Importeer de blueprint, maak er een automatisering van en kies de sensor
**Beschikbaar** van de laadpaal en de telefoon die de melding krijgt. Kies er
een schakelaar-helper bij als je maar één melding wilt: die wordt alleen
verstuurd als de schakelaar aan staat, en de schakelaar gaat daarna uit.

## Voorbeelden van automatiseringen

De entiteit-ID's hieronder horen bij een laadpaal met de naam *Schiekade 988*;
vervang ze door je eigen ID's, en `notify.mobile_app_mijn_telefoon` door je
telefoon.

**1. Als het aantal vrije aansluitingen verandert**

```yaml
triggers:
  - trigger: state
    entity_id: sensor.schiekade_988_vrije_aansluitingen
    not_from: [unavailable, unknown]
    not_to: [unavailable, unknown]
actions:
  - action: notify.mobile_app_mijn_telefoon
    data:
      title: Schiekade 988
      message: >-
        {{ trigger.to_state.state }} van de
        {{ state_attr(trigger.entity_id, 'total') }} aansluitingen vrij
        (was {{ trigger.from_state.state }}).
```

**2. Als de laadpaal beschikbaar komt, of helemaal bezet raakt**

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.schiekade_988_beschikbaar
    from: ["on", "off"]
    to: ["on", "off"]
actions:
  - action: notify.mobile_app_mijn_telefoon
    data:
      title: Schiekade 988
      message: >-
        {{ 'Weer beschikbaar.' if trigger.to_state.state == 'on'
           else 'Alle aansluitingen zijn bezet.' }}
```

Wil je alleen een melding als hij weer beschikbaar komt, gebruik dan
`from: "off"` en `to: "on"`.

**3. Als je favoriete aansluiting vrijkomt**

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.schiekade_988_aansluiting_1
    from: "off"
    to: "on"
actions:
  - action: notify.mobile_app_mijn_telefoon
    data:
      title: Schiekade 988
      message: Aansluiting 1 is vrij.
```

**4. Laadcheck bij aankomst**

Als je met een lage accu in de buurt van huis komt, hoor je of je
voorkeurslaadpaal bezet is en welke alternatieven vrij zijn. Hiervoor heb je
een afstandssensor van de integratie
[Proximity](https://www.home-assistant.io/integrations/proximity/) nodig en
een accusensor van je auto.

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.thuis_dichtstbijzijnde_afstand
    below: 2500
conditions:
  - condition: numeric_state
    entity_id: sensor.auto_accuniveau
    below: 50
actions:
  - variables:
      voorkeur:
        - binary_sensor.schiekade_988_beschikbaar
      alternatieven:
        - binary_sensor.schiekade_730_beschikbaar
        - binary_sensor.schiekade_522_beschikbaar
      vrij: >-
        {{ alternatieven | select('is_state', 'on')
           | map('device_attr', 'name') | list }}
  - if: "{{ voorkeur | select('is_state', 'on') | list | count == 0 }}"
    then:
      - action: notify.mobile_app_mijn_telefoon
        data:
          title: Voorkeurslaadpaal bezet
          message: >-
            {{ 'Vrije alternatieven: ' ~ vrij | join(', ') if vrij
               else 'Alle laadpalen zijn bezet.' }}
```

**5. Wachten op een plek**

Maak een schakelaar-helper aan (**Instellingen → Apparaten & diensten →
Helpers → Helper aanmaken → Schakelaar**) met de naam *Wacht op laadpaal*. Zet
hem aan als alles bezet is: je krijgt één melding zodra een van de laadpalen
vrij is, en de schakelaar gaat weer uit.

```yaml
triggers:
  - trigger: state
    entity_id:
      - binary_sensor.schiekade_988_beschikbaar
      - binary_sensor.schiekade_730_beschikbaar
    from: "off"
    to: "on"
conditions:
  - condition: state
    entity_id: input_boolean.wacht_op_laadpaal
    state: "on"
actions:
  - action: notify.mobile_app_mijn_telefoon
    data:
      title: Laadpaal beschikbaar
      message: "{{ device_attr(trigger.entity_id, 'name') }} is vrij."
  - action: input_boolean.turn_off
    target:
      entity_id: input_boolean.wacht_op_laadpaal
```

Optionele dashboardtegel voor de schakelaar, die alleen zichtbaar is zolang
alle laadpalen bezet zijn:

```yaml
type: tile
entity: input_boolean.wacht_op_laadpaal
tap_action:
  action: toggle
visibility:
  - condition: state
    entity: binary_sensor.schiekade_988_beschikbaar
    state: "off"
  - condition: state
    entity: binary_sensor.schiekade_730_beschikbaar
    state: "off"
```
