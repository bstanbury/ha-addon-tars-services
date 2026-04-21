# TARS Services v4.0.0

Consolidated Home Assistant add-on combining five services into a single Flask app on **port 8097**.

## Services

| Service | Prefix | Description |
|---------|--------|-------------|
| Spotify DJ | `/dj/` | Adaptive music with time/weather/event learning |
| Hue Entertainment | `/hue/` | Immersive lighting with auto-transitions |
| Smart Doorbell | `/doorbell/` | Ring/motion event detection & visitor classification |
| SwitchBot Bridge | `/switchbot/` | Local SwitchBot device control (lock, blinds, climate) |
| Vacuum Controller | `/vacuum/` | TinyTuya local Eufy vacuum control |

## Install

Add this repository to HA Add-on Store:
```
https://github.com/bstanbury/ha-addon-tars-services
```

## Configuration

| Option | Description |
|--------|-------------|
| `ha_url` | Home Assistant URL (default: `http://localhost:8123`) |
| `ha_token` | Long-lived access token |
| `api_port` | Service port (default: 8097) |
| `core_url` | TARS Core URL for Event Bus SSE (default: `http://localhost:8093`) |
| `spotify_client_id` | Spotify app client ID |
| `spotify_client_secret` | Spotify app client secret |
| `hue_bridge_ip` | Hue bridge IP (default: `192.168.4.39`) |
| `hue_api_key` | Hue API key |
| `switchbot_token` | SwitchBot API token |
| `switchbot_secret` | SwitchBot API secret |
| `tuya_device_id` | Eufy vacuum Tuya device ID |
| `tuya_local_key` | Tuya local encryption key |
| `tuya_device_ip` | Vacuum IP address |
| `sonos_entity` | Sonos media player entity (default: `media_player.living_room`) |

## Key Endpoints

### Root
- `GET /` — Combined service status
- `GET /health` — Combined health check

### Spotify DJ (`/dj/` prefix + backward-compat unprefixed)
- `POST /dj/play` — Smart play (time/weather aware)
- `POST /dj/mood/<mood>` — Play by mood (chill, energetic, focus, party, kids, dinner…)
- `POST /dj/kids` / `/dj/kids/off` — Kids mode
- `POST /dj/like` / `/dj/skip` — Feedback learning
- `POST /dj/volume/<0-100>` — Set volume
- `GET /dj/now-playing` — Current track info
- `GET /dj/stats` — Play stats and top playlists

### Hue Entertainment (`/hue/` prefix)
- `POST /hue/ambient/<preset>` — Apply preset (sunset, ocean, forest, fire, aurora, candlelight, neon…)
- `POST /hue/movie` — Movie mode (dim all, accent TV backlight)
- `POST /hue/energy/<calm|medium|high>` — Music sync energy level
- `POST /hue/room/<room>/<scene>` — Activate room scene
- `GET /hue/lights` — All light states

### Doorbell (`/doorbell/` prefix)
- `GET /doorbell/status` — Presence + lock state
- `GET /doorbell/events` — Visitor log
- `POST /doorbell/classify` — Manual classification

### SwitchBot (`/switchbot/` prefix)
- `GET /switchbot/devices` — Device list
- `POST /switchbot/lock` / `/switchbot/unlock` — Door lock
- `POST /switchbot/blinds/<position>` — Set blinds 0-100
- `GET /switchbot/climate` — Temperature/humidity sensors
- `GET /switchbot/door` — Door/lock state

### Vacuum (`/vacuum/` prefix)
- `POST /vacuum/start` — Start cleaning (bedroom-motion safe)
- `POST /vacuum/dock` — Return to base
- `POST /vacuum/suction/<quiet|standard|turbo|max>` — Set suction
- `POST /vacuum/find` — Locate vacuum
- `GET /vacuum/history` — Cleaning sessions
- `GET /vacuum/status` — Live device state

## Safety Features

- **Bedroom protection**: Never play audio on bedroom speakers without recent bedroom motion
- **Echo protection**: Echo entities are blocked from music playback (they trigger the TV)
- **Bedroom light curfew**: Hue won't change bedroom lights after 9pm without motion
- **Vacuum deferral**: Won't auto-start before 9am if bedroom motion detected in last 30 min
- **Silent hours**: Doorbell/SwitchBot use push notifications only 22:00–08:00
- **Cooper-aware vacuum**: Won't auto-start if Cooper is home (via TARS Intelligence)

## Architecture

All five services run as Flask Blueprints in a single process:
- 10 background threads (SSE subscribers, pollers, trackers)
- Each service connects independently to `CORE_URL/events/stream`
- Persistent data in `/data/` (dj_stats.json, hue_state.json, doorbell.json, switchbot_v2.json, cleaning_history.json)
- Port 8097 (replaces ports 8094-8099)

## Migration from v3 Individual Add-ons

Replace these add-ons:
- `ha-addon-spotify-dj` (port 8097) → `/dj/` + unprefixed backward-compat routes
- `ha-addon-hue-entertainment` (port 8096) → `/hue/`
- `ha-addon-smart-doorbell` (port 8094) → `/doorbell/`
- `ha-addon-switchbot-bridge` (port 8098) → `/switchbot/`
- `ha-addon-tinytuya-vacuum` (port 8099) → `/vacuum/`

All existing `rest_command` entries using the unprefixed DJ routes continue to work unchanged.
