# TARS Services v4.0.0

Consolidated Home Assistant add-on: **Spotify DJ + Hue Entertainment + Smart Doorbell + SwitchBot + Vacuum** in a single Flask app on port **8097**.

## Installation

Add this repository to Home Assistant Add-on Store:
```
https://github.com/bstanbury/ha-addon-tars-services
```

## Route Reference

### Root
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Combined status of all services |
| GET | `/health` | Per-service health check |

### DJ (unprefixed for backward compat + `/dj/` prefix)
| Method | Route | Description |
|--------|-------|-------------|
| GET/POST | `/play` | Auto-pick playlist by time/weather/kids mode |
| GET/POST | `/recommend` | Recommend without playing |
| GET/POST | `/mood/<mood>` | Play by mood (chill/energetic/focus/party/sleep/kids/dinner/etc) |
| GET/POST | `/kids` | Enable kids mode |
| GET/POST | `/kids/off` | Disable kids mode |
| GET/POST | `/like` | Like current playlist |
| GET/POST | `/skip` | Skip to next playlist |
| GET/POST | `/volume/<0-100>` | Set volume |
| GET/POST | `/speaker/<entity>` | Switch speaker (blocks Echo + bedroom) |
| GET | `/now-playing` | Current playback state |
| GET | `/playlists` | Full playlist library |
| GET | `/stats` | Likes/skips/plays |
| GET | `/search/<query>` | Search Spotify playlists |
| POST | `/dj/request` | `{"query": "fun kids music"}` — search + play |
| GET | `/dj/history` | Last 20 plays |

### Hue (`/hue/`)
| Method | Route | Description |
|--------|-------|-------------|
| GET/POST | `/hue/ambient/<preset>` | Apply preset (sunset/ocean/forest/fire/aurora/candlelight/neon) |
| GET/POST | `/hue/movie` | Movie mode (dim/off non-TV lights) |
| GET/POST | `/hue/energy/<level>` | Music sync (calm/medium/high) |
| GET | `/hue/lights` | List all lights |
| GET | `/hue/status` | Light states |
| POST | `/hue/follow` | Motion-based follow-me lighting |
| GET/POST | `/hue/cooper` | Kid-safe warm preset |

### Doorbell (`/doorbell/`)
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/doorbell/status` | Home/lock/last visitor |
| GET | `/doorbell/events` | Visitor event log |
| GET | `/doorbell/known` | Known MAC addresses |
| GET | `/doorbell/digest` | Today's motion summary |

### SwitchBot (`/switchbot/`)
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/switchbot/devices` | Device list |
| GET | `/switchbot/motion` | Motion sensor states |
| GET | `/switchbot/climate` | Temperature/humidity |
| GET | `/switchbot/door` | Lock/door state |
| GET/POST | `/switchbot/lock` | Lock door |
| GET/POST | `/switchbot/unlock` | Unlock door |
| GET/POST | `/switchbot/blinds/<0-100>` | Set blind position |
| GET | `/switchbot/summary` | All-device condensed status |
| GET/POST | `/switchbot/blinds/auto` | Sun-position auto control |

### Vacuum (`/vacuum/`)
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/vacuum/status` | Current vacuum state |
| GET | `/vacuum/history` | Cleaning session history |
| GET/POST | `/vacuum/start` | Start cleaning (bedroom/Cooper-aware) |
| GET/POST | `/vacuum/dock` | Return to dock |
| GET/POST | `/vacuum/suction/<level>` | Set suction (quiet/standard/turbo/max) |
| GET/POST | `/vacuum/find` | Locate vacuum |
| GET | `/vacuum/should_clean` | Smart cleaning recommendation |

## Safety
- Bedroom speakers blocked unless `binary_sensor.bedroom_motion` is active
- Echo devices blocked for music playback (prevents TV trigger)
- Silent hours (22:00–08:00): doorbell notifications push-only
- Vacuum deferred if bedroom motion detected before 9am
- Vacuum skipped if Cooper is home

## Environment Variables
`HA_URL`, `HA_TOKEN`, `API_PORT` (8097), `CORE_URL`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `HUE_BRIDGE_IP`, `HUE_API_KEY`, `SWITCHBOT_TOKEN`, `SWITCHBOT_SECRET`, `TUYA_DEVICE_ID`, `TUYA_LOCAL_KEY`, `TUYA_DEVICE_IP`, `SONOS_ENTITY`
