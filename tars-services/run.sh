#!/bin/sh
set -e

CONFIG=/data/options.json

if [ ! -f "$CONFIG" ]; then
    echo "[ERROR] No config at $CONFIG"
    exit 1
fi

export HA_URL=$(python3 -c "import json; print(json.load(open('$CONFIG'))['ha_url'])")
export HA_TOKEN=$(python3 -c "import json; print(json.load(open('$CONFIG'))['ha_token'])")
export API_PORT=$(python3 -c "import json; print(json.load(open('$CONFIG'))['api_port'])")
export CORE_URL=$(python3 -c "import json; print(json.load(open('$CONFIG'))['core_url'])")
export SPOTIFY_CLIENT_ID=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('spotify_client_id',''))")
export SPOTIFY_CLIENT_SECRET=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('spotify_client_secret',''))")
export HUE_BRIDGE_IP=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('hue_bridge_ip','192.168.4.39'))")
export HUE_API_KEY=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('hue_api_key',''))")
export SWITCHBOT_TOKEN=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('switchbot_token',''))")
export SWITCHBOT_SECRET=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('switchbot_secret',''))")
export TUYA_DEVICE_ID=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('tuya_device_id',''))")
export TUYA_LOCAL_KEY=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('tuya_local_key',''))")
export TUYA_DEVICE_IP=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('tuya_device_ip',''))")
export SONOS_ENTITY=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('sonos_entity','media_player.living_room'))")

echo "[INFO] TARS Services v4.0.0"
echo "[INFO] HA: ${HA_URL} | Core: ${CORE_URL} | Port: ${API_PORT}"
echo "[INFO] Sonos: ${SONOS_ENTITY} | Hue: ${HUE_BRIDGE_IP}"

exec python3 /app/server.py
