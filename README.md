# TARS Services v4.0.0

Consolidated Home Assistant add-on suite with five merged services on port **8097**.

## Included services
- Spotify DJ, `/dj/*`, plus backward-compatible unprefixed DJ routes
- Hue Entertainment, `/hue/*`
- Smart Doorbell, `/doorbell/*`
- SwitchBot Bridge, `/switchbot/*`
- TinyTuya Vacuum, `/vacuum/*`

## New v4 additions
- `/dj/request`, `/dj/history`, `/dj/queue`
- Auto-duck DJ volume on phone-call style HA events
- Expanded Cooper-safe kids playlists
- `/hue/follow`, `/hue/schedule`, `/hue/cooper`
- `/vacuum/should_clean`, `/vacuum/schedule`
- `/switchbot/summary`, `/switchbot/blinds/auto`
- `/doorbell/digest`, `/doorbell/learn`

## Core config
Uses `core_url` default `http://localhost:8093` for consolidated Core event stream.

## Safety
- Bedroom audio protection
- Echo device blocking for music
- Bedroom light curfew
- Silent hours awareness
- Vacuum sleep-safety deferral
- Cooper-aware vacuum auto-start suppression
