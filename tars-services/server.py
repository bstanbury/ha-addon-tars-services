#!/usr/bin/env python3
"""TARS Services v5.0.0 — DJ + Hue + Doorbell + SwitchBot + Vacuum on port 8097.

v5.0 changes:
  - Subscribes to Core's /events/stream SSE for real-time HA event reactions
  - Uses shared HAClient helper (from helpers.py) for consistent HA calls
  - Typed config with validation
  - TV on → auto-pause DJ; TV off → resume (replaces HA automation)
  - iPhone presence off → pause, close blinds (replaces HA automation)
  - Cooper here toggle → Hue preset + DJ kids mode (replaces HA automation)
"""
import os,json,time,logging,random,base64,threading,hashlib,hmac,uuid
from datetime import datetime
from collections import deque,Counter
from flask import Flask,Blueprint,jsonify,request
import requests as http
import tinytuya

# v5 modules (support both package and direct-script execution)
try:
    from .typed_config import ServicesConfig
    from .helpers import HAClient, ServicesClient
    from .sse_subscriber import CoreSSESubscriber
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from typed_config import ServicesConfig
    from helpers import HAClient, ServicesClient
    from sse_subscriber import CoreSSESubscriber

HA_URL=os.environ.get('HA_URL','http://localhost:8123')
HA_TOKEN=os.environ.get('HA_TOKEN','')
API_PORT=int(os.environ.get('API_PORT','8097'))
CORE_URL=os.environ.get('CORE_URL','http://localhost:8093')
SP_ID=os.environ.get('SPOTIFY_CLIENT_ID','')
SP_SECRET=os.environ.get('SPOTIFY_CLIENT_SECRET','')
SONOS=os.environ.get('SONOS_ENTITY','media_player.living_room')
HUE_IP=os.environ.get('HUE_BRIDGE_IP','192.168.4.39')
HUE_KEY=os.environ.get('HUE_API_KEY','')
HUE=f'http://{HUE_IP}/api/{HUE_KEY}'
SB_TOKEN=os.environ.get('SWITCHBOT_TOKEN','')
SB_SECRET=os.environ.get('SWITCHBOT_SECRET','')
SB_API='https://api.switch-bot.com/v1.1'
TUYA_ID=os.environ.get('TUYA_DEVICE_ID','eb4a6faf9217851dc9iop6')
TUYA_KEY=os.environ.get('TUYA_LOCAL_KEY','')
TUYA_IP=os.environ.get('TUYA_DEVICE_IP','192.168.4.31')

app=Flask(__name__)
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
logger=logging.getLogger('tars-services')

# ── SAFETY ───────────────────────────────────────────────────────────────────
BEDROOM_ENTITIES=['media_player.bedroom','media_player.bedroom_sonos','media_player.bedroom_echo_show_chatsworth']
ECHO_ENTITIES=['media_player.chatsworth_living_room_echo_show','media_player.chatsworth_kitchen_echo_show','media_player.bedroom_echo_show_chatsworth','media_player.chatsworth_echo_show_5_bathroom']

def is_bedroom_safe():
    try:
        r=http.get(f'{HA_URL}/api/states/binary_sensor.bedroom_motion',headers={'Authorization':f'Bearer {HA_TOKEN}'},timeout=5)
        if r.status_code==200: return r.json()['state']=='on'
    except: pass
    return False

def silent_hours(): h=datetime.now().hour; return h>=22 or h<8
def hh(): return {'Authorization':f'Bearer {HA_TOKEN}','Content-Type':'application/json'}
def ha_get(path):
    try:
        r=http.get(f'{HA_URL}/api{path}',headers={'Authorization':f'Bearer {HA_TOKEN}'},timeout=5)
        return r.json() if r.status_code==200 else None
    except: return None
def ha_notify(title,msg):
    try: http.post(f'{HA_URL}/api/services/notify/mobile_app_bks_home_assistant_chatsworth',headers=hh(),json={'data':{'title':title,'message':msg}},timeout=5)
    except: pass

# ═══════════════════════════════════════════════════════════════════════════════
# DJ
# ═══════════════════════════════════════════════════════════════════════════════
dj_bp=Blueprint('dj',__name__)
_sp_tok=None;_sp_exp=0;_kids=False;_cur_pid=None;_dj_recent=[];_dj_hist=deque(maxlen=20)
_dj_stats={'likes':{},'skips':{},'plays':{},'total_plays':0}
DJ_DATA='/data/dj_stats.json'

DJ_LIB={
 'morning_early':[{'id':'37i9dQZF1DWXe9gFZP0gtP','name':'Chill Morning','vibe':'gentle'},{'id':'37i9dQZF1DX1n9whBbBKoL','name':'Lo-fi Cafe','vibe':'coffee'},{'id':'37i9dQZF1DX6ziVCJnEm59','name':'Morning Motivation','vibe':'upbeat'}],
 'morning_late': [{'id':'5vImPKH5smp2ifK34N6XTd','name':'Energetic Upbeat Lofi','vibe':'productive'},{'id':'37i9dQZF1DX0SM0LYsmbMT','name':'Jazz Vibes','vibe':'sophisticated'},{'id':'37i9dQZF1DX4OzrY981I1W','name':'Indie Folk','vibe':'laid back'}],
 'afternoon':    [{'id':'0CFuMybe6s77w6QQrJjW7d','name':'Chillhop Radio','vibe':'focus'},{'id':'37i9dQZF1DX0SM0LYsmbMT','name':'Jazz Vibes','vibe':'groove'},{'id':'37i9dQZF1DWVqJMsgEN0F4','name':'Acoustic Evening','vibe':'mellow'}],
 'evening':      [{'id':'3NXxyeM9cp3bRnxNtqhOu4','name':'Lofi Trap Beats','vibe':'chill'},{'id':'37i9dQZF1DX6VdMW310YC7','name':'Chill R&B','vibe':'smooth'},{'id':'37i9dQZF1DWVqJMsgEN0F4','name':'Acoustic Evening','vibe':'wind down'},{'id':'37i9dQZF1DX3Ogo9pFvBkY','name':'Ambient','vibe':'zen'}],
 'night':        [{'id':'5eDufIy8WtiArgp9aPd9su','name':'Late Night Vibes','vibe':'night owl'},{'id':'37i9dQZF1DWZd79rJ6a7lp','name':'Sleep Jazz','vibe':'dreamy'},{'id':'37i9dQZF1DX3Ogo9pFvBkY','name':'Ambient','vibe':'sleep'},{'id':'6bGe4ekNk4E4h9vVkuItul','name':'Ambient Deep Sleep','vibe':'deep sleep'}],
 'chill':        [{'id':'37i9dQZF1DX3Ogo9pFvBkY','name':'Ambient'},{'id':'37i9dQZF1DWVqJMsgEN0F4','name':'Acoustic Evening'},{'id':'0CFuMybe6s77w6QQrJjW7d','name':'Chillhop'}],
 'energetic':    [{'id':'37i9dQZF1DX6ziVCJnEm59','name':'Morning Motivation'},{'id':'37i9dQZF1DX76Wlfdnj7AP','name':'Beast Mode'},{'id':'37i9dQZF1DX0BcQWzuB7ZO','name':'Dance Hits'}],
 'focus':        [{'id':'37i9dQZF1DX1n9whBbBKoL','name':'Lo-fi Cafe'},{'id':'37i9dQZF1DWZeKCadgRdKQ','name':'Deep Focus'},{'id':'0CFuMybe6s77w6QQrJjW7d','name':'Chillhop'}],
 'party':        [{'id':'37i9dQZF1DX0BcQWzuB7ZO','name':'Dance Hits'},{'id':'37i9dQZF1DXa2PjGhjTnEG','name':'Party Starters'}],
 'sleep':        [{'id':'37i9dQZF1DWZd79rJ6a7lp','name':'Sleep Jazz'},{'id':'37i9dQZF1DX3Ogo9pFvBkY','name':'Ambient'},{'id':'6bGe4ekNk4E4h9vVkuItul','name':'Ambient Deep Sleep'}],
 'romantic':     [{'id':'37i9dQZF1DX6VdMW310YC7','name':'Chill R&B'},{'id':'37i9dQZF1DWVqJMsgEN0F4','name':'Acoustic Evening'}],
 'rainy':        [{'id':'37i9dQZF1DX1n9whBbBKoL','name':'Lo-fi Cafe'},{'id':'37i9dQZF1DX3Ogo9pFvBkY','name':'Ambient'}],
 'sunny':        [{'id':'37i9dQZF1DX4OzrY981I1W','name':'Indie Folk'},{'id':'37i9dQZF1DX6ziVCJnEm59','name':'Morning Motivation'}],
 'kids':         [{'id':'37i9dQZF1DX6aTaZa0K6VA','name':'Disney Hits'},{'id':'37i9dQZF1DWVlYsZJXBFMo','name':'Kids Pop'},{'id':'37i9dQZF1DX2M1RktxUUHE','name':'Family Road Trip'},{'id':'7LD17YaJftpf0WMg40h25L','name':'Kids Dance Party Clean'},{'id':'2k1TzwejfDMu9vszNPQE4s','name':'Kids Dance Party Fun'},{'id':'1P27ra5VqAizmkcUzVAvp2','name':'Kids Party Songs 2026'}],
 'dinner':       [{'id':'37i9dQZF1DX4xuWVBs4FgJ','name':'Dinner Jazz'},{'id':'37i9dQZF1DWVqJMsgEN0F4','name':'Acoustic Evening'}],
 'workout':      [{'id':'37i9dQZF1DX76Wlfdnj7AP','name':'Beast Mode'},{'id':'37i9dQZF1DX0BcQWzuB7ZO','name':'Dance Hits'}],
}
VOLS={'morning_early':0.22,'morning_late':0.25,'afternoon':0.28,'evening':0.25,'night':0.15}

def _slot():
    h=datetime.now().hour
    if 6<=h<9:   return 'morning_early'
    if 9<=h<12:  return 'morning_late'
    if 12<=h<17: return 'afternoon'
    if 17<=h<21: return 'evening'
    return 'night'

def _weather():
    try:
        r=http.get(f'{HA_URL}/api/states/weather.forecast_home',headers={'Authorization':f'Bearer {HA_TOKEN}'},timeout=5)
        if r.status_code==200: return r.json()['state']
    except: pass
    return 'unknown'

def _sp_auth():
    """App-level auth (client_credentials) — used for public search when no user token available."""
    global _sp_tok,_sp_exp
    if _sp_tok and time.time()<_sp_exp: return _sp_tok
    auth=base64.b64encode(f'{SP_ID}:{SP_SECRET}'.encode()).decode()
    r=http.post('https://accounts.spotify.com/api/token',headers={'Authorization':f'Basic {auth}','Content-Type':'application/x-www-form-urlencoded'},data={'grant_type':'client_credentials'},timeout=10)
    if r.status_code==200:
        d=r.json(); _sp_tok=d['access_token']; _sp_exp=time.time()+d.get('expires_in',3600)-60; return _sp_tok
    return None

# ─── Spotify USER OAuth (authorization_code) ───────────────────────────────────────────────────
# Unlocks Discover Weekly, Liked Songs, Daily Mix, play history, recent tracks.
# Ben must visit /dj/auth/start once, approve, then TARS stores + refreshes tokens.
# Token persists in /data/spotify_user_token.json.
SP_USER_TOKEN_FILE = '/data/spotify_user_token.json'
SP_USER_SCOPES = 'user-library-read user-read-recently-played user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative user-top-read user-read-currently-playing'
_sp_user = {'access_token': None, 'refresh_token': None, 'expires_at': 0}

def _sp_user_load():
    global _sp_user
    try:
        if os.path.exists(SP_USER_TOKEN_FILE):
            _sp_user = json.load(open(SP_USER_TOKEN_FILE))
            logger.info(f'Spotify user token loaded (expires: {_sp_user.get("expires_at", 0)})')
    except Exception as e:
        logger.warning(f'Spotify user token load failed: {e}')

def _sp_user_save():
    try:
        os.makedirs('/data', exist_ok=True)
        json.dump(_sp_user, open(SP_USER_TOKEN_FILE, 'w'))
    except Exception as e:
        logger.error(f'Spotify user token save failed: {e}')

def _sp_user_token():
    """Return a valid user-scoped access token, refreshing if needed. None if user hasn't authorized."""
    if not _sp_user.get('refresh_token'): return None
    if _sp_user.get('access_token') and time.time() < _sp_user.get('expires_at', 0): return _sp_user['access_token']
    # Refresh
    auth = base64.b64encode(f'{SP_ID}:{SP_SECRET}'.encode()).decode()
    try:
        r = http.post('https://accounts.spotify.com/api/token',
                      headers={'Authorization': f'Basic {auth}', 'Content-Type': 'application/x-www-form-urlencoded'},
                      data={'grant_type': 'refresh_token', 'refresh_token': _sp_user['refresh_token']}, timeout=10)
        if r.status_code == 200:
            d = r.json()
            _sp_user['access_token'] = d['access_token']
            _sp_user['expires_at'] = time.time() + d.get('expires_in', 3600) - 60
            # Spotify may rotate refresh tokens
            if 'refresh_token' in d: _sp_user['refresh_token'] = d['refresh_token']
            _sp_user_save()
            return _sp_user['access_token']
    except Exception as e:
        logger.error(f'Spotify user refresh failed: {e}')
    return None

def _sp_user_get(path, params=None):
    """GET from Spotify Web API using user token."""
    t = _sp_user_token()
    if not t: return None
    try:
        r = http.get(f'https://api.spotify.com/v1{path}', headers={'Authorization': f'Bearer {t}'}, params=params or {}, timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.error(f'Spotify user GET {path}: {e}')
        return None

def _dj_load():
    global _dj_stats
    try:
        if os.path.exists(DJ_DATA):
            with open(DJ_DATA) as f: _dj_stats=json.load(f)
    except: pass

def _dj_save():
    try:
        with open(DJ_DATA,'w') as f: json.dump(_dj_stats,f)
    except: pass

def _pick(mood=None):
    global _dj_recent,_cur_pid
    if _kids: mood='kids'
    w=_weather()
    if mood and mood in DJ_LIB: cands=DJ_LIB[mood]
    elif w in ['rainy','pouring']: cands=DJ_LIB.get('rainy',DJ_LIB[_slot()])
    elif w in ['sunny','clear-night'] and _slot() in ['morning_late','afternoon']: cands=DJ_LIB.get('sunny',DJ_LIB[_slot()])
    else: cands=DJ_LIB.get(_slot(),[])
    if not cands: cands=DJ_LIB['afternoon']
    avail=[p for p in cands if p['id'] not in _dj_recent[-3:]] or cands
    p=random.choice(avail)
    _dj_recent.append(p['id']); _dj_recent=_dj_recent[-10:]; _cur_pid=p['id']
    _dj_stats['plays'][p['id']]=_dj_stats['plays'].get(p['id'],0)+1; _dj_stats['total_plays']+=1; _dj_save()
    return p

def _play(pid,vol=None,entity=None):
    global SONOS
    target=entity or SONOS
    if target in BEDROOM_ENTITIES and not is_bedroom_safe(): logger.warning(f'Blocking bedroom {target}'); return False
    if target in ECHO_ENTITIES: logger.warning(f'Blocking Echo {target}'); return False
    h=hh()
    try: http.post(f'{HA_URL}/api/services/media_player/select_source',headers=h,json={'entity_id':target,'source':'Spotify'},timeout=5)
    except: pass
    time.sleep(1)
    if vol is None: vol=VOLS.get(_slot(),0.25); vol=min(vol+0.03,0.30) if _kids else vol
    http.post(f'{HA_URL}/api/services/media_player/volume_set',headers=h,json={'entity_id':target,'volume_level':vol},timeout=5)
    http.post(f'{HA_URL}/api/services/media_player/play_media',headers=h,json={'entity_id':target,'media_content_id':f'spotify:playlist:{pid}','media_content_type':'spotify://playlist'},timeout=5)
    time.sleep(1)
    http.post(f'{HA_URL}/api/services/media_player/shuffle_set',headers=h,json={'entity_id':target,'shuffle':True},timeout=5)
    _dj_hist.append({'time':datetime.now().isoformat(),'playlist':pid,'speaker':target})
    return True

def _play_crossfade(pid, target_vol=None, entity=None, fade_sec=3):
    """Play a new playlist with volume crossfade: fade down, switch, fade up.
    Much smoother than _play() for mood transitions. P2 added 2026-04-29."""
    global SONOS
    target = entity or SONOS
    if target in BEDROOM_ENTITIES and not is_bedroom_safe(): return False
    if target in ECHO_ENTITIES: return False
    h = hh()
    # Get current volume
    cur_state = ha_get(f'/states/{target}')
    cur_vol = float((cur_state or {}).get('attributes', {}).get('volume_level', 0.25))
    if target_vol is None:
        target_vol = VOLS.get(_slot(), 0.25)
        target_vol = min(target_vol + 0.03, 0.30) if _kids else target_vol
    # Fade down in steps
    steps = 6
    for i in range(steps, 0, -1):
        v = cur_vol * (i / steps)
        http.post(f'{HA_URL}/api/services/media_player/volume_set', headers=h,
                  json={'entity_id': target, 'volume_level': round(v, 3)}, timeout=5)
        time.sleep(fade_sec / (steps * 2))
    # Switch playlist (muted-ish)
    http.post(f'{HA_URL}/api/services/media_player/play_media', headers=h,
              json={'entity_id': target, 'media_content_id': f'spotify:playlist:{pid}',
                    'media_content_type': 'spotify://playlist'}, timeout=5)
    time.sleep(1.5)
    http.post(f'{HA_URL}/api/services/media_player/shuffle_set', headers=h,
              json={'entity_id': target, 'shuffle': True}, timeout=5)
    # Fade up
    for i in range(1, steps + 1):
        v = target_vol * (i / steps)
        http.post(f'{HA_URL}/api/services/media_player/volume_set', headers=h,
                  json={'entity_id': target, 'volume_level': round(v, 3)}, timeout=5)
        time.sleep(fade_sec / (steps * 2))
    _dj_hist.append({'time': datetime.now().isoformat(), 'playlist': pid,
                     'speaker': target, 'transition': 'crossfade'})
    return True

@dj_bp.route('/health')
def dj_health(): return jsonify({'status':'ok' if _sp_auth() else 'auth_failed','slot':_slot(),'kids_mode':_kids})

@dj_bp.route('/recommend',methods=['GET','POST'])
def dj_recommend(): p=_pick(mood=request.args.get('mood')); return jsonify({'id':p['id'],'name':p.get('name','?'),'vibe':p.get('vibe',''),'slot':_slot(),'weather':_weather()})

@dj_bp.route('/play',methods=['GET','POST'])
def dj_play(): p=_pick(mood=request.args.get('mood')); _play(p['id']); return jsonify({'success':True,'playing':p.get('name',p['id']),'slot':_slot(),'kids_mode':_kids})

@dj_bp.route('/mood/<mood>',methods=['GET','POST'])
def dj_mood(mood):
    if mood not in DJ_LIB: return jsonify({'error':f'Unknown. Try: {list(DJ_LIB.keys())}'}),400
    # Use crossfade when currently playing (smoother mood shift); hard-switch otherwise
    crossfade = request.args.get('crossfade', 'auto').lower()
    cur_state = ha_get(f'/states/{SONOS}')
    is_playing = cur_state and cur_state.get('state') == 'playing'
    use_crossfade = crossfade == 'true' or (crossfade == 'auto' and is_playing)
    p = _pick(mood=mood)
    if use_crossfade:
        _play_crossfade(p['id'])
        return jsonify({'success': True, 'mood': mood, 'playing': p.get('name', p['id']), 'transition': 'crossfade'})
    _play(p['id'])
    return jsonify({'success': True, 'mood': mood, 'playing': p.get('name', p['id']), 'transition': 'hard'})

@dj_bp.route('/kids',methods=['GET','POST'])
def dj_kids_on(): global _kids; _kids=True; p=_pick(mood='kids'); _play(p['id']); return jsonify({'success':True,'kids_mode':True,'playing':p.get('name',p['id'])})

@dj_bp.route('/kids/off',methods=['GET','POST'])
def dj_kids_off(): global _kids; _kids=False; p=_pick(); _play(p['id']); return jsonify({'success':True,'kids_mode':False,'playing':p.get('name',p['id'])})

@dj_bp.route('/like',methods=['GET','POST'])
def dj_like():
    if not _cur_pid: return jsonify({'error':'Nothing playing'}),400
    _dj_stats['likes'][_cur_pid]=_dj_stats['likes'].get(_cur_pid,0)+1; _dj_save(); return jsonify({'success':True,'liked':_cur_pid})

@dj_bp.route('/skip',methods=['GET','POST'])
def dj_skip():
    if not _cur_pid: return jsonify({'error':'Nothing playing'}),400
    _dj_stats['skips'][_cur_pid]=_dj_stats['skips'].get(_cur_pid,0)+1; _dj_save()
    p=_pick(); _play(p['id']); return jsonify({'success':True,'skipped':_cur_pid,'now_playing':p.get('name',p['id'])})

@dj_bp.route('/volume/<int:level>',methods=['GET','POST'])
def dj_volume(level): vol=max(0,min(100,level))/100; http.post(f'{HA_URL}/api/services/media_player/volume_set',headers=hh(),json={'entity_id':SONOS,'volume_level':vol},timeout=5); return jsonify({'success':True,'volume':vol})

@dj_bp.route('/speaker/<entity>',methods=['GET','POST'])
def dj_speaker(entity):
    global SONOS
    if entity in ECHO_ENTITIES: return jsonify({'error':'Echo triggers TV — use Sonos'}),403
    if entity in BEDROOM_ENTITIES and not is_bedroom_safe(): return jsonify({'error':'Bedroom blocked — no motion'}),403
    SONOS=entity; return jsonify({'success':True,'speaker':SONOS})

@dj_bp.route('/now-playing')
def dj_now():
    try:
        r=http.get(f'{HA_URL}/api/states/{SONOS}',headers={'Authorization':f'Bearer {HA_TOKEN}'},timeout=5)
        if r.status_code==200:
            d=r.json(); return jsonify({'state':d['state'],'title':d['attributes'].get('media_title'),'artist':d['attributes'].get('media_artist'),'volume':d['attributes'].get('volume_level'),'kids_mode':_kids})
    except: pass
    return jsonify({'error':'failed'}),500

@dj_bp.route('/playlists')
def dj_playlists(): return jsonify(DJ_LIB)

@dj_bp.route('/stats')
def dj_stats(): return jsonify({'total_plays':_dj_stats['total_plays'],'kids_mode':_kids,'likes':_dj_stats['likes'],'skips':_dj_stats['skips']})

@dj_bp.route('/search/<query>')
def dj_search(query):
    t=_sp_auth()
    if not t: return jsonify({'error':'auth failed'}),500
    r=http.get('https://api.spotify.com/v1/search',headers={'Authorization':f'Bearer {t}'},params={'q':query,'type':'playlist','limit':5},timeout=5)
    if r.status_code==200: return jsonify([{'id':p['id'],'name':p['name']} for p in r.json().get('playlists',{}).get('items',[])])
    return jsonify({'error':'search failed'}),500

@dj_bp.route('/request',methods=['POST'])
def dj_request():
    query=(request.json or {}).get('query','')
    if not query: return jsonify({'error':'Provide query'}),400
    t=_sp_auth()
    if not t: return jsonify({'error':'Spotify auth failed'}),500
    r=http.get('https://api.spotify.com/v1/search',headers={'Authorization':f'Bearer {t}'},params={'q':query,'type':'playlist','limit':1},timeout=5)
    if r.status_code==200:
        items=r.json().get('playlists',{}).get('items',[])
        if items: _play(items[0]['id']); return jsonify({'success':True,'playing':items[0]['name'],'id':items[0]['id']})
    return jsonify({'error':'No results'}),404

@dj_bp.route('/history')
def dj_history(): return jsonify(list(_dj_hist))

# ─── Spotify user OAuth endpoints (P1 added 2026-04-29) ────────────────────────────────────────
@dj_bp.route('/auth/start')
def dj_auth_start():
    """Visit this URL in browser to begin Spotify user OAuth."""
    import urllib.parse as up
    # Redirect URI must match what's registered in Spotify dev app dashboard.
    redirect_uri = request.args.get('redirect_uri', f'http://100.125.148.75:8097/dj/auth/callback')
    params = {
        'client_id': SP_ID,
        'response_type': 'code',
        'redirect_uri': redirect_uri,
        'scope': SP_USER_SCOPES,
        'show_dialog': 'true',
    }
    auth_url = 'https://accounts.spotify.com/authorize?' + up.urlencode(params)
    return jsonify({'auth_url': auth_url, 'instructions': 'Visit auth_url in browser, approve, then Spotify will redirect back.'})

@dj_bp.route('/auth/callback')
def dj_auth_callback():
    """Spotify redirects here with ?code=... after user approves."""
    code = request.args.get('code')
    err = request.args.get('error')
    if err: return jsonify({'error': err}), 400
    if not code: return jsonify({'error': 'missing code'}), 400
    redirect_uri = f'http://100.125.148.75:8097/dj/auth/callback'
    auth = base64.b64encode(f'{SP_ID}:{SP_SECRET}'.encode()).decode()
    try:
        r = http.post('https://accounts.spotify.com/api/token',
                      headers={'Authorization': f'Basic {auth}', 'Content-Type': 'application/x-www-form-urlencoded'},
                      data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri}, timeout=10)
        if r.status_code == 200:
            d = r.json()
            _sp_user['access_token'] = d['access_token']
            _sp_user['refresh_token'] = d.get('refresh_token')
            _sp_user['expires_at'] = time.time() + d.get('expires_in', 3600) - 60
            _sp_user_save()
            return jsonify({'success': True, 'message': 'Spotify user auth complete — TARS now has access to Discover Weekly, liked songs, etc.'})
        return jsonify({'error': 'token exchange failed', 'status': r.status_code, 'body': r.text[:200]}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@dj_bp.route('/auth/status')
def dj_auth_status():
    t = _sp_user_token()
    if not t: return jsonify({'authorized': False, 'hint': 'Visit /dj/auth/start to begin OAuth'})
    # Verify token works by fetching profile
    profile = _sp_user_get('/me')
    return jsonify({'authorized': True, 'profile': profile.get('display_name') if profile else '(unknown)',
                    'expires_in_sec': int(max(0, _sp_user.get('expires_at', 0) - time.time()))})

@dj_bp.route('/personal/recent')
def dj_personal_recent():
    """Recently played tracks from Ben's Spotify account."""
    d = _sp_user_get('/me/player/recently-played', {'limit': 20})
    if not d: return jsonify({'error': 'no user auth — visit /dj/auth/start'}), 401
    return jsonify([{
        'track': it['track']['name'],
        'artist': ', '.join(a['name'] for a in it['track']['artists']),
        'played_at': it['played_at'],
    } for it in d.get('items', [])])

@dj_bp.route('/personal/top')
def dj_personal_top():
    """User's top tracks this month."""
    term = request.args.get('range', 'short_term')  # short_term, medium_term, long_term
    d = _sp_user_get('/me/top/tracks', {'limit': 20, 'time_range': term})
    if not d: return jsonify({'error': 'no user auth'}), 401
    return jsonify([{
        'track': t['name'], 'artist': ', '.join(a['name'] for a in t['artists']),
        'popularity': t.get('popularity'),
    } for t in d.get('items', [])])

@dj_bp.route('/personal/playlists')
def dj_personal_playlists():
    """User's own playlists (including Discover Weekly, Daily Mix, Release Radar)."""
    d = _sp_user_get('/me/playlists', {'limit': 50})
    if not d: return jsonify({'error': 'no user auth'}), 401
    out = []
    for p in d.get('items', []) or []:
        if not p: continue
        tracks_info = p.get('tracks') or {}
        owner_info = p.get('owner') or {}
        out.append({
            'id': p.get('id'),
            'name': p.get('name', '?'),
            'tracks': tracks_info.get('total', 0) if isinstance(tracks_info, dict) else 0,
            'owner': owner_info.get('display_name', '?'),
            'collaborative': p.get('collaborative', False),
        })
    return jsonify(out)

@dj_bp.route('/personal/play-mine',methods=['POST','GET'])
def dj_play_mine():
    """Play the user's Discover Weekly or another personal playlist by name."""
    name = request.args.get('name', 'Discover Weekly').lower()
    d = _sp_user_get('/me/playlists', {'limit': 50})
    if not d: return jsonify({'error': 'no user auth'}), 401
    match = next((p for p in d.get('items', []) if name in p['name'].lower()), None)
    if not match: return jsonify({'error': f'No playlist matching "{name}"'}), 404
    _play(match['id'])
    return jsonify({'success': True, 'playing': match['name'], 'id': match['id']})


# ═══════════════════════════════════════════════════════════════════════════════
# HUE
# ═══════════════════════════════════════════════════════════════════════════════
hue_bp=Blueprint('hue',__name__,url_prefix='/hue')
_hue_mode='auto'; _hue_last=None

HUE_P={
 'sunset':     [{'bri':200,'xy':[0.5,0.4]},{'bri':150,'xy':[0.55,0.35]},{'bri':100,'xy':[0.45,0.35]},{'bri':180,'xy':[0.6,0.38]}],
 'ocean':      [{'bri':150,'xy':[0.17,0.2]},{'bri':180,'xy':[0.15,0.25]},{'bri':120,'xy':[0.2,0.3]},{'bri':160,'xy':[0.16,0.22]}],
 'forest':     [{'bri':120,'xy':[0.3,0.5]},{'bri':100,'xy':[0.35,0.45]},{'bri':80,'xy':[0.25,0.4]},{'bri':140,'xy':[0.32,0.48]}],
 'fire':       [{'bri':254,'xy':[0.6,0.38]},{'bri':200,'xy':[0.55,0.35]},{'bri':150,'xy':[0.65,0.33]},{'bri':180,'xy':[0.58,0.38]}],
 'aurora':     [{'bri':150,'xy':[0.15,0.25]},{'bri':120,'xy':[0.3,0.15]},{'bri':180,'xy':[0.2,0.5]},{'bri':100,'xy':[0.25,0.1]}],
 'candlelight':[{'bri':80,'xy':[0.55,0.4]},{'bri':60,'xy':[0.58,0.38]},{'bri':70,'xy':[0.52,0.41]},{'bri':50,'xy':[0.56,0.39]}],
 'neon':       [{'bri':254,'xy':[0.35,0.15]},{'bri':254,'xy':[0.15,0.06]},{'bri':254,'xy':[0.2,0.5]},{'bri':254,'xy':[0.55,0.35]}],
 'cooper':     [{'bri':180,'xy':[0.45,0.41]},{'bri':160,'xy':[0.44,0.40]},{'bri':140,'xy':[0.43,0.39]},{'bri':170,'xy':[0.46,0.40]}],
}

def _hg(path):
    try: return http.get(f'{HUE}{path}',timeout=5).json()
    except: return {}
def _hp(path,d):
    try: return http.put(f'{HUE}{path}',json=d,timeout=5).json()
    except Exception as e: return {'error':str(e)}

def _preset(name,tr=10):
    global _hue_last
    if name not in HUE_P: return False
    cs=HUE_P[name]; lights=_hg('/lights')
    for i,(lid,l) in enumerate(lights.items()):
        if l.get('state',{}).get('reachable'): _hp(f'/lights/{lid}/state',{'on':True,**cs[i%len(cs)],'transitiontime':tr})
    _hue_last=name; return True

@hue_bp.route('/health')
def hue_health():
    bridge_ok = _hg('/config') is not None
    return jsonify({'status':'ok' if bridge_ok else 'unreachable','bridge_ip':HUE_IP,'mode':_hue_mode})

@hue_bp.route('/ambient/<preset>',methods=['GET','POST'])
def hue_ambient(preset):
    global _hue_mode
    if preset not in HUE_P: return jsonify({'error':f'Available: {list(HUE_P.keys())}'}),400
    _preset(preset); _hue_mode='manual'; return jsonify({'success':True,'preset':preset})

@hue_bp.route('/movie',methods=['GET','POST'])
def hue_movie():
    global _hue_mode; _hue_mode='movie'
    lights=_hg('/lights')
    for lid,l in lights.items():
        n=l.get('name','').lower()
        if any(k in n for k in ['tv','lightstrip','play','gradient']): _hp(f'/lights/{lid}/state',{'on':True,'bri':40,'ct':400,'transitiontime':20})
        elif 'back' in n: _hp(f'/lights/{lid}/state',{'on':True,'bri':20,'ct':454,'transitiontime':20})
        else: _hp(f'/lights/{lid}/state',{'on':False,'transitiontime':20})
    return jsonify({'success':True,'mode':'movie'})

@hue_bp.route('/energy/<level>',methods=['GET','POST'])
def hue_energy(level):
    lids=list(_hg('/lights').keys())
    if level=='calm':
        for lid in lids: _hp(f'/lights/{lid}/state',{'on':True,'bri':80,'ct':400,'transitiontime':10})
    elif level=='medium':
        cs=HUE_P['sunset']
        for i,lid in enumerate(lids): _hp(f'/lights/{lid}/state',{'on':True,**cs[i%len(cs)],'transitiontime':5})
    elif level=='high':
        cs=HUE_P['neon']
        for i,lid in enumerate(lids): _hp(f'/lights/{lid}/state',{'on':True,**cs[i%len(cs)],'transitiontime':2})
    else: return jsonify({'error':'Use: calm/medium/high'}),400
    return jsonify({'success':True,'energy':level})

@hue_bp.route('/lights')
def hue_lights():
    d=_hg('/lights')
    return jsonify([{'id':k,'name':v['name'],'on':v['state']['on'],'bri':v['state'].get('bri',0),'reachable':v['state'].get('reachable',False)} for k,v in d.items()])

@hue_bp.route('/status')
def hue_status():
    d=_hg('/lights')
    return jsonify({v['name']:{'on':v['state']['on'],'bri':v['state'].get('bri',0)} for k,v in d.items()})

@hue_bp.route('/follow',methods=['POST'])
def hue_follow():
    motion=ha_get('/states/binary_sensor.bathroom_motion_motion')
    if motion and motion.get('state')=='on': _preset('ocean',5); return jsonify({'success':True,'followed':'bathroom','preset':'ocean'})
    p='candlelight' if datetime.now().hour>=20 else 'sunset'
    _preset(p,10); return jsonify({'success':True,'followed':'living_room','preset':p})

@hue_bp.route('/cooper',methods=['GET','POST'])
def hue_cooper(): _preset('cooper',20); return jsonify({'success':True,'preset':'cooper'})

# ─── Album-art color sync (P2 added 2026-04-29) ────────────────────────────────────────────
# Extracts up to 4 dominant colors from currently-playing album art (Sonos entity_picture),
# converts RGB → CIE xy for Hue, and paints reachable lights.
def _rgb_to_xy(r, g, b):
    """Convert sRGB (0-255) to CIE 1931 xy for Philips Hue."""
    r, g, b = r/255.0, g/255.0, b/255.0
    # Gamma correction (sRGB)
    r = ((r + 0.055) / 1.055) ** 2.4 if r > 0.04045 else r / 12.92
    g = ((g + 0.055) / 1.055) ** 2.4 if g > 0.04045 else g / 12.92
    b = ((b + 0.055) / 1.055) ** 2.4 if b > 0.04045 else b / 12.92
    # Wide RGB D65 formula (Hue gamut)
    X = r * 0.664511 + g * 0.154324 + b * 0.162028
    Y = r * 0.283881 + g * 0.668433 + b * 0.047685
    Z = r * 0.000088 + g * 0.072310 + b * 0.986039
    total = X + Y + Z
    if total == 0: return [0.3127, 0.3290]  # D65 white
    return [round(X / total, 4), round(Y / total, 4)]

def _extract_palette(image_url, n_colors=4):
    """Download image, quantize to n_colors, return list of (rgb, xy, bri) tuples."""
    try:
        from PIL import Image
        from io import BytesIO
    except ImportError:
        return None
    # If URL is relative (HA proxy), prepend HA_URL
    url = image_url if image_url.startswith('http') else f'{HA_URL}{image_url}'
    try:
        r = http.get(url, headers={'Authorization': f'Bearer {HA_TOKEN}'} if HA_URL in url else {}, timeout=10)
        if r.status_code != 200: return None
        img = Image.open(BytesIO(r.content)).convert('RGB')
        # Resize to speed up quantize
        img.thumbnail((150, 150))
        # Quantize to palette
        pal = img.quantize(colors=n_colors, kmeans=n_colors)
        pal_rgb = pal.getpalette()[:n_colors*3]
        colors = []
        for i in range(n_colors):
            r, g, b = pal_rgb[i*3], pal_rgb[i*3+1], pal_rgb[i*3+2]
            # Reject near-black (min brightness 30)
            if max(r, g, b) < 30: continue
            bri = min(254, int(max(r, g, b) / 255 * 254))
            colors.append({'rgb': [r, g, b], 'xy': _rgb_to_xy(r, g, b), 'bri': max(bri, 100)})
        return colors
    except Exception as e:
        logger.error(f'album-art palette extract failed: {e}')
        return None

@hue_bp.route('/sync/albumart', methods=['GET', 'POST'])
def hue_sync_albumart():
    """Sync Hue lights to currently-playing album art colors."""
    global _hue_mode
    # Get album art URL from Sonos
    s = ha_get(f'/states/{SONOS}')
    if not s: return jsonify({'error': 'Sonos state unavailable'}), 500
    if s.get('state') != 'playing': return jsonify({'error': f'Not playing (state: {s.get("state")})'}), 400
    attrs = s.get('attributes', {})
    art_url = attrs.get('entity_picture')
    if not art_url: return jsonify({'error': 'No album art available'}), 404
    colors = _extract_palette(art_url, n_colors=4)
    if not colors: return jsonify({'error': 'Color extraction failed (PIL missing or image unreadable)'}), 500
    # Apply to reachable lights
    lights = _hg('/lights') or {}
    reachable = [(lid, l) for lid, l in lights.items() if l.get('state', {}).get('reachable')]
    painted = []
    for i, (lid, l) in enumerate(reachable):
        c = colors[i % len(colors)]
        if _hp(f'/lights/{lid}/state', {'on': True, 'xy': c['xy'], 'bri': c['bri'], 'transitiontime': 10}):
            painted.append({'light': l.get('name'), 'color': c['rgb']})
    _hue_mode = 'albumart'
    return jsonify({
        'success': True,
        'track': attrs.get('media_title', '?'),
        'artist': attrs.get('media_artist', '?'),
        'album': attrs.get('media_album_name', '?'),
        'palette': colors,
        'painted_lights': len(painted),
        'painted': painted[:10],
    })

@hue_bp.route('/sync/albumart/auto', methods=['GET', 'POST'])
def hue_sync_albumart_auto():
    """Toggle auto-sync: re-extract palette every 30s while music plays."""
    global _albumart_auto
    _albumart_auto = not globals().get('_albumart_auto', False)
    if _albumart_auto and not globals().get('_albumart_thread_started', False):
        globals()['_albumart_thread_started'] = True
        threading.Thread(target=_albumart_loop, daemon=True).start()
    return jsonify({'auto_sync': _albumart_auto})

def _albumart_loop():
    last_art = None
    while True:
        try:
            if globals().get('_albumart_auto', False):
                s = ha_get(f'/states/{SONOS}')
                if s and s.get('state') == 'playing':
                    art = s.get('attributes', {}).get('entity_picture', '')
                    if art and art != last_art:
                        # Art URL changed — re-extract palette
                        colors = _extract_palette(art, n_colors=4)
                        if colors:
                            lights = _hg('/lights') or {}
                            reachable = [(lid, l) for lid, l in lights.items() if l.get('state', {}).get('reachable')]
                            for i, (lid, l) in enumerate(reachable):
                                c = colors[i % len(colors)]
                                _hp(f'/lights/{lid}/state', {'on': True, 'xy': c['xy'], 'bri': c['bri'], 'transitiontime': 10})
                            last_art = art
        except Exception as e:
            logger.error(f'albumart_loop: {e}')
        time.sleep(30)

# ═══════════════════════════════════════════════════════════════════════════════
# DOORBELL
# ═══════════════════════════════════════════════════════════════════════════════
db_bp=Blueprint('doorbell',__name__,url_prefix='/doorbell')
_db_visitors=[];_db_learned=set()
DB_DATA='/data/doorbell.json'

def _db_load():
    global _db_visitors,_db_learned
    try:
        if os.path.exists(DB_DATA):
            d=json.load(open(DB_DATA)); _db_learned=set(d.get('macs',[])); _db_visitors=d.get('visitors',[])
    except: pass

def _db_save():
    try: json.dump({'macs':list(_db_learned),'visitors':_db_visitors[-200:]},open(DB_DATA,'w'),indent=2)
    except: pass

def _db_classify(source='poll'):
    h=datetime.now().hour; home=(ha_get('/states/binary_sensor.iphone_presence') or {}).get('state')=='on'
    cls='delivery' if (9<=h<=18 and not home) else ('household' if home else 'unknown')
    ev={'time':datetime.now().isoformat(),'type':cls,'home':home,'hour':h,'source':source}
    _db_visitors.append(ev); _db_save()
    if not silent_hours():
        if cls=='delivery': ha_notify('📦 Possible Delivery',f'Front door motion at {h}:00')
        elif cls=='visitor': ha_notify('🚶 Visitor','Front door motion detected')
    return ev

@db_bp.route('/health')
def db_health():
    return jsonify({'status':'ok','visitors_tracked':len(_db_visitors),'known_faces':len(_db_learned)})

@db_bp.route('/status')
def db_status():
    p=ha_get('/states/binary_sensor.iphone_presence'); l=ha_get('/states/lock.front_door_lock')
    return jsonify({'home':p['state']=='on' if p else None,'lock':l['state'] if l else None,'last_visitor':_db_visitors[-1] if _db_visitors else None,'silent_hours':silent_hours()})

@db_bp.route('/events')
def db_events(): return jsonify(_db_visitors[-int(request.args.get('limit',20)):])

@db_bp.route('/known')
def db_known(): return jsonify(list(_db_learned))

@db_bp.route('/digest')
def db_digest():
    since=datetime.now().replace(hour=0,minute=0,second=0)
    today=[v for v in _db_visitors if v.get('time','')>=since.isoformat()]
    return jsonify({'date':since.strftime('%Y-%m-%d'),'total':len(today),'by_type':dict(Counter(v['type'] for v in today)),'events':today[-10:]})

# ═══════════════════════════════════════════════════════════════════════════════
# SWITCHBOT
# ═══════════════════════════════════════════════════════════════════════════════
sb_bp=Blueprint('switchbot',__name__,url_prefix='/switchbot')
_sb_devs=[];_sb_cache={};_sb_names={};_sb_aliases={};_sb_motion={};_sb_locks={};_sb_blinds={};_sb_climate={};_sb_lock=threading.Lock()

def _sbh():
    t=str(int(time.time()*1000)); n=str(uuid.uuid4())
    sign=base64.b64encode(hmac.new(SB_SECRET.encode(),f'{SB_TOKEN}{t}{n}'.encode(),hashlib.sha256).digest()).decode()
    return {'Authorization':SB_TOKEN,'t':t,'sign':sign,'nonce':n,'Content-Type':'application/json'}

def _sbg(path):
    try:
        r=http.get(f'{SB_API}{path}',headers=_sbh(),timeout=10); d=r.json()
        if d.get('statusCode')==100: return d.get('body',{})
    except Exception as e: logger.error(f'SB get: {e}')
    return None

def _sbp(path,body):
    try: return http.post(f'{SB_API}{path}',headers=_sbh(),json=body,timeout=10).json()
    except Exception as e: return {'statusCode':-1,'message':str(e)}

def _sb_load():
    global _sb_devs,_sb_names,_sb_aliases,_sb_motion,_sb_locks,_sb_blinds,_sb_climate
    data=_sbg('/devices')
    if not data: return
    _sb_devs=data.get('deviceList',[])
    for d in _sb_devs:
        did=d['deviceId']; name=d.get('deviceName',did); dtype=d.get('deviceType','')
        _sb_names[did]=name; alias=name.lower().replace(' ','_'); _sb_aliases[alias]=did; _sb_aliases[did]=did
        if 'Motion' in dtype: _sb_motion[did]=name
        elif 'Lock' in dtype: _sb_locks[did]=name
        elif any(k in dtype for k in ['Roller','Blind','Curtain']): _sb_blinds[did]=name
        elif any(k in dtype for k in ['Meter','Sensor']): _sb_climate[did]=name

def _sb_fetch(did):
    data=_sbg(f'/devices/{did}/status')
    if data:
        with _sb_lock: _sb_cache[did]={'status':data,'ts':time.time(),'name':_sb_names.get(did,did)}
    return data

def _sb_res(s): return _sb_aliases.get(s.lower().replace(' ','_'),s)

@sb_bp.route('/health')
def sb_health():
    return jsonify({'status':'ok' if _sb_devs else 'no_devices','devices_count':len(_sb_devs) if _sb_devs else 0})

@sb_bp.route('/devices')
def sb_devices():
    if not _sb_devs: _sb_load()
    return jsonify([{'id':d['deviceId'],'name':d.get('deviceName',''),'type':d.get('deviceType','')} for d in _sb_devs])

@sb_bp.route('/motion')
def sb_motion():
    return jsonify({n:{'detected':_sb_cache.get(d,{}).get('status',{}).get('moveDetected',False),'battery':_sb_cache.get(d,{}).get('status',{}).get('battery')} for d,n in _sb_motion.items()})

@sb_bp.route('/climate')
def sb_climate():
    return jsonify({n:{'temperature':(_sb_fetch(d) or {}).get('temperature'),'humidity':(_sb_fetch(d) or {}).get('humidity'),'battery':(_sb_fetch(d) or {}).get('battery')} for d,n in _sb_climate.items()})

@sb_bp.route('/door')
def sb_door():
    for did in _sb_locks:
        with _sb_lock: c=_sb_cache.get(did,{}).get('status',{})
        return jsonify({'lock':c.get('lockState'),'door':c.get('doorState'),'battery':c.get('battery')})
    return jsonify({'error':'No lock'}),404

@sb_bp.route('/lock',methods=['GET','POST'])
def sb_lock_cmd():
    for did in _sb_locks: return jsonify(_sbp(f'/devices/{did}/commands',{'command':'lock','parameter':'default','commandType':'command'}))
    return jsonify({'error':'No lock'}),404

@sb_bp.route('/unlock',methods=['GET','POST'])
def sb_unlock():
    for did in _sb_locks: return jsonify(_sbp(f'/devices/{did}/commands',{'command':'unlock','parameter':'default','commandType':'command'}))
    return jsonify({'error':'No lock'}),404

@sb_bp.route('/blinds/<int:position>',methods=['GET','POST'])
def sb_blinds_set(position):
    if not 0<=position<=100: return jsonify({'error':'0-100'}),400
    results={n:_sbp(f'/devices/{d}/commands',{'command':'setPosition','parameter':f'0,ff,{position}','commandType':'command'}) for d,n in _sb_blinds.items()}
    return jsonify({'success':True,'position':position,'results':results})

@sb_bp.route('/summary')
def sb_summary():
    with _sb_lock:
        summary={_sb_names.get(did,did):{'battery':v.get('status',{}).get('battery'),'age_s':round(time.time()-v.get('ts',0))} for did,v in _sb_cache.items()}
    return jsonify({'devices':len(_sb_devs),'cached':len(_sb_cache),'summary':summary})

@sb_bp.route('/blinds/auto',methods=['GET','POST'])
def sb_blinds_auto():
    h=datetime.now().hour
    pos=100 if 7<=h<10 else (50 if 11<=h<15 else (80 if 15<=h<19 else 0))
    results={n:_sbp(f'/devices/{d}/commands',{'command':'setPosition','parameter':f'0,ff,{pos}','commandType':'command'}) for d,n in _sb_blinds.items()}
    return jsonify({'success':True,'position':pos,'hour':h,'results':results})

# ═══════════════════════════════════════════════════════════════════════════════
# VACUUM
# ═══════════════════════════════════════════════════════════════════════════════
vac_bp=Blueprint('vacuum',__name__,url_prefix='/vacuum')
_vac_hist=[];_vac_sess=None;_vac_st={};_vac_stl=threading.Lock();_vac_bm=None
VAC_HIST='/data/cleaning_history.json'
VAC_WORK={0:'standby',1:'cleaning',2:'paused',5:'returning',34:'docked'}
VAC_SUC=['Quiet','Standard','Turbo','Max']

def _vd(): d=tinytuya.Device(TUYA_ID,TUYA_IP,TUYA_KEY,version=3.3); d.set_socketTimeout(5); d.set_socketRetryLimit(2); return d

def _vac_load():
    global _vac_hist
    try:
        if os.path.exists(VAC_HIST):
            with open(VAC_HIST) as f: _vac_hist=json.load(f)
    except: pass

def _vac_save():
    try:
        with open(VAC_HIST,'w') as f: json.dump(_vac_hist[-50:],f)
    except: pass

def _vac_status():
    try:
        d=_vd(); raw=d.status(); dps=raw.get('dps',{})
        wc=dps.get('6',-1)
        # S1 Pro state detection via DPS 152/153 (base64 protobuf) if available
        dps152 = dps.get('152', '')
        dps153 = dps.get('153', '')
        state = VAC_WORK.get(wc, f'unknown_{wc}')
        is_cleaning = wc == 1
        is_docked = wc in [34, 0]
        # Override with S1 Pro protocol if present
        if dps152 == 'AggO': state = 'cleaning'; is_cleaning = True; is_docked = False
        elif dps152 == 'AggN': state = 'paused'; is_cleaning = False; is_docked = False
        elif dps152 == 'AggG': state = 'returning'; is_cleaning = False; is_docked = False
        data = {
            'online': True,
            'state': state,
            'battery': dps.get('8', 0),
            'suction': dps.get('158', '?'),
            'is_cleaning': is_cleaning,
            'is_docked': is_docked,
            'fan_mode': dps.get('9', '?'),
            'water_level': dps.get('10', '?'),
            'mop': dps.get('40', '?'),
            'timestamp': time.time(),
        }
        with _vac_stl: _vac_st.update(data)
        return data
    except Exception as e: return {'online':False,'error':str(e),'timestamp':time.time()}

def _vac_days():
    if not _vac_hist: return 999
    try: return (datetime.now()-datetime.fromisoformat(_vac_hist[-1].get('end',_vac_hist[-1].get('start','')))).total_seconds()/86400
    except: return 999

def _vac_defer():
    if datetime.now().hour>=9: return False
    if _vac_bm and (datetime.now()-_vac_bm).total_seconds()/60<30: return True
    return is_bedroom_safe()

def _vac_cooper():
    try:
        r=http.get(f'{CORE_URL}/cooper',timeout=3)
        if r.status_code==200: return r.json().get('here',False)
    except: pass
    return False

def _vac_track():
    global _vac_sess
    while True:
        try:
            data=_vac_status(); state=data.get('state','')
            if state=='cleaning' and _vac_sess is None: _vac_sess={'start':datetime.now().isoformat(),'battery_start':data.get('battery',0)}
            elif state in ['docked','standby'] and _vac_sess:
                _vac_sess['end']=datetime.now().isoformat(); _vac_sess['battery_end']=data.get('battery',0)
                try: _vac_sess['duration_min']=round((datetime.fromisoformat(_vac_sess['end'])-datetime.fromisoformat(_vac_sess['start'])).total_seconds()/60,1)
                except: pass
                _vac_hist.append(_vac_sess); _vac_save(); ha_notify('🧹 Clean Complete',f"Session ended. {round(_vac_days(),1)}d since last."); _vac_sess=None
        except: pass
        time.sleep(30)

@vac_bp.route('/health')
def vac_health():
    return jsonify({'status':'ok','history_count':len(_vac_hist),'days_since_clean':round(_vac_days(),1)})

@vac_bp.route('/status')
def vac_status():
    with _vac_stl:
        if _vac_st and (time.time()-_vac_st.get('timestamp',0))<15: return jsonify({**_vac_st,'source':'cache'})
    return jsonify({**_vac_status(),'source':'live'})

@vac_bp.route('/history')
def vac_history(): return jsonify({'total':len(_vac_hist),'sessions':_vac_hist[-request.args.get('limit',10,type=int):],'current':_vac_sess})

# S1 Pro native commands (DPS 152, base64-encoded). Verified via tkoba1974/ha-eufy-robovac-s1-pro
S1_PRO_CMD = {
    'start':    'AA==',   # Start clean
    'cleaning': 'AggO',   # Confirm cleaning state
    'pause':    'AggN',   # Pause
    'return':   'AggG',   # Return to dock
}
# S1 Pro sets both DPS 9 (mode) and DPS 158 (suction label) together
S1_PRO_FAN = {
    'Quiet':    ('gentle', 'Quiet'),
    'Standard': ('normal', 'Standard'),
    'Turbo':    ('strong', 'Turbo'),
    'Max':      ('max',    'Max'),
}

@vac_bp.route('/start',methods=['GET','POST'])
def vac_start():
    if _vac_defer(): return jsonify({'success':False,'deferred':True,'reason':'Bedroom motion + before 9am'})
    if _vac_cooper(): return jsonify({'success':False,'reason':'Cooper is home'})
    try:
        d = _vd()
        # S1 Pro: use DPS 152 base64 command (more reliable than DPS 160)
        d.set_value(152, S1_PRO_CMD['start'])
        time.sleep(0.8)
        d.set_value(152, S1_PRO_CMD['cleaning'])
        time.sleep(0.3)
        # Set mode to smart (matches app behavior)
        try: d.set_value(5, 'smart')
        except: pass
        # Also ping DPS 160 as fallback for older firmware
        try: d.set_value(160, True)
        except: pass
        return jsonify({'success': True, 'message': 'Start sent (S1 Pro protocol)'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@vac_bp.route('/pause', methods=['GET', 'POST'])
def vac_pause():
    """S1 Pro-specific pause via DPS 152."""
    try:
        d = _vd()
        d.set_value(152, S1_PRO_CMD['pause'])
        time.sleep(0.3)
        try: d.set_value(5, 'pause')
        except: pass
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@vac_bp.route('/dock',methods=['GET','POST'])
def vac_dock():
    try:
        d = _vd()
        # S1 Pro: use DPS 152 return command
        d.set_value(152, S1_PRO_CMD['return'])
        time.sleep(0.3)
        try: d.set_value(5, 'charge')
        except: pass
        # Fallback
        try: d.set_value(160, False)
        except: pass
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@vac_bp.route('/suction/<level>',methods=['GET','POST'])
def vac_suction(level):
    m={'quiet':'Quiet','q':'Quiet','standard':'Standard','s':'Standard','turbo':'Turbo','t':'Turbo','max':'Max','m':'Max'}
    t=m.get(level.lower(),level.capitalize())
    if t not in VAC_SUC: return jsonify({'error':f'Use: {VAC_SUC}'}),400
    try:
        d = _vd()
        # S1 Pro: set BOTH DPS 9 (mode) and DPS 158 (label) to keep them consistent
        dps9, dps158 = S1_PRO_FAN.get(t, ('normal', t))
        d.set_value(9, dps9)
        time.sleep(0.2)
        d.set_value(158, dps158)
        return jsonify({'success': True, 'suction': t, 'dps9': dps9, 'dps158': dps158})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@vac_bp.route('/find',methods=['GET','POST'])
def vac_find():
    try: d=_vd(); d.set_value(159,False); time.sleep(1); d.set_value(159,True); return jsonify({'success':True})
    except Exception as e: return jsonify({'success':False,'error':str(e)}),500

@vac_bp.route('/should_clean')
def vac_should_clean():
    days=_vac_days(); avg=2.0
    if len(_vac_hist)>=3:
        gaps=[]
        for i in range(1,len(_vac_hist)):
            try: gaps.append((datetime.fromisoformat(_vac_hist[i]['start'])-datetime.fromisoformat(_vac_hist[i-1].get('end',_vac_hist[i-1]['start']))).total_seconds()/86400)
            except: pass
        if gaps: avg=round(sum(gaps)/len(gaps),1)
    return jsonify({'should_clean':days>=avg,'days_since_last':round(days,1),'avg_gap_days':avg,'message':f"{'Time to clean!' if days>=avg else 'Not due yet.'} Last: {round(days,1)}d ago."})

# Zone/room cleaning for Eufy S1 Pro (T2080)
# The S1 Pro does NOT expose zone/room cleaning via its local Tuya protocol.
# Room commands are encoded in protobuf over DPS 154/152 via Eufy's cloud API.
# Reverse-engineering would require capturing Eufy app traffic (MITM).
# See: https://github.com/tkoba1974/ha-eufy-robovac-s1-pro/issues/4 (open since Nov 2025)
# This remains blocked upstream; documented so we remember not to keep chasing it.
VAC_ZONE_DPS = None  # Not available on S1 Pro
VAC_ROOMS = {}  # Cannot be populated via local Tuya

@vac_bp.route('/zones')
def vac_zones_list():
    """List configured zones. Returns empty dict + known limitation for S1 Pro."""
    return jsonify({
        'zones': VAC_ROOMS,
        'supported': False,
        'reason': 'Eufy S1 Pro (T2080) does not expose zone/room cleaning via local Tuya protocol.',
        'workaround': 'Use the Eufy Clean app directly for room selection. Schedule cleans by time instead.',
        'upstream_issue': 'https://github.com/tkoba1974/ha-eufy-robovac-s1-pro/issues/4',
    })

@vac_bp.route('/clean/<room>', methods=['GET', 'POST'])
def vac_clean_zone(room):
    """Zone cleaning not supported on Eufy S1 Pro via local protocol. Returns explanatory error."""
    return jsonify({
        'success': False,
        'error': 'Zone/room cleaning not supported on Eufy S1 Pro via local Tuya protocol.',
        'alternative': 'Use whole-house /vacuum/start, or schedule via Eufy app.',
        'upstream_issue': 'https://github.com/tkoba1974/ha-eufy-robovac-s1-pro/issues/4',
    }), 501  # Not Implemented

# ===========================================================================
# ALARM (Ring Alarm Pro via ring-mqtt) - v5.1 added 2026-04-29
# ===========================================================================
# Wraps HA alarm_control_panel.* service calls. No code required (disarm_code left blank).
# Primary location: Chatsworth. VLP available via location_id param.

alarm_bp = Blueprint('alarm', __name__, url_prefix='/alarm')

ALARM_ENTITIES = {
    'chatsworth': 'alarm_control_panel.chatsworth_alarm',
    'vlp':        'alarm_control_panel.villa_las_palmas_alarm',
}
DEFAULT_LOCATION = 'chatsworth'

def _alarm_entity(location=None):
    loc = (location or DEFAULT_LOCATION).lower()
    return ALARM_ENTITIES.get(loc, ALARM_ENTITIES[DEFAULT_LOCATION])

def _alarm_state(entity):
    s = ha_get(f'/states/{entity}')
    if not s: return {'state': 'unknown', 'entity': entity}
    return {'state': s['state'], 'entity': entity,
            'last_changed': s.get('last_changed'),
            'attributes': s.get('attributes', {})}

@alarm_bp.route('/health')
def alarm_health():
    """Alarm base station connectivity."""
    out = {'status': 'ok', 'locations': {}}
    for loc, entity in ALARM_ENTITIES.items():
        s = ha_get(f'/states/{entity}')
        if s:
            out['locations'][loc] = {'state': s['state'], 'available': s['state'] != 'unavailable'}
        else:
            out['locations'][loc] = {'state': 'unreachable', 'available': False}
            out['status'] = 'degraded'
    return jsonify(out)

@alarm_bp.route('/status')
@alarm_bp.route('/status/<location>')
def alarm_status(location=None):
    """GET /alarm/status[/<location>] - current state of a panel."""
    entity = _alarm_entity(location)
    return jsonify(_alarm_state(entity))

@alarm_bp.route('/arm/home', methods=['GET', 'POST'])
@alarm_bp.route('/arm/home/<location>', methods=['GET', 'POST'])
def alarm_arm_home(location=None):
    """Arm in Home mode (perimeter-only)."""
    entity = _alarm_entity(location)
    try:
        http.post(f'{HA_URL}/api/services/alarm_control_panel/alarm_arm_home',
                  headers=hh(), json={'entity_id': entity}, timeout=5)
        time.sleep(1.5)
        return jsonify({'success': True, 'mode': 'home', 'location': location or DEFAULT_LOCATION,
                        **_alarm_state(entity)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@alarm_bp.route('/arm/away', methods=['GET', 'POST'])
@alarm_bp.route('/arm/away/<location>', methods=['GET', 'POST'])
def alarm_arm_away(location=None):
    """Arm in Away mode (all sensors)."""
    entity = _alarm_entity(location)
    try:
        http.post(f'{HA_URL}/api/services/alarm_control_panel/alarm_arm_away',
                  headers=hh(), json={'entity_id': entity}, timeout=5)
        time.sleep(1.5)
        return jsonify({'success': True, 'mode': 'away', 'location': location or DEFAULT_LOCATION,
                        **_alarm_state(entity)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@alarm_bp.route('/disarm', methods=['GET', 'POST'])
@alarm_bp.route('/disarm/<location>', methods=['GET', 'POST'])
def alarm_disarm(location=None):
    """Disarm the panel."""
    entity = _alarm_entity(location)
    try:
        http.post(f'{HA_URL}/api/services/alarm_control_panel/alarm_disarm',
                  headers=hh(), json={'entity_id': entity}, timeout=5)
        time.sleep(1.5)
        return jsonify({'success': True, 'mode': 'disarmed', 'location': location or DEFAULT_LOCATION,
                        **_alarm_state(entity)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@alarm_bp.route('/trigger', methods=['POST'])
@alarm_bp.route('/trigger/<location>', methods=['POST'])
def alarm_trigger(location=None):
    """Manually trigger the alarm. Use sparingly - siren will sound."""
    entity = _alarm_entity(location)
    try:
        http.post(f'{HA_URL}/api/services/alarm_control_panel/alarm_trigger',
                  headers=hh(), json={'entity_id': entity}, timeout=5)
        time.sleep(1.5)
        return jsonify({'success': True, 'mode': 'triggered', 'location': location or DEFAULT_LOCATION,
                        **_alarm_state(entity)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@alarm_bp.route('/locations')
def alarm_locations():
    """List configured locations."""
    return jsonify({'locations': ALARM_ENTITIES, 'default': DEFAULT_LOCATION})

# ═══════════════════════════════════════════════════════════════════════════════
# ROOT & HEALTH
# ═══════════════════════════════════════════════════════════════════════════════
@app.route('/')
def root(): return jsonify({'name':'TARS Services','version':'5.1.0','services':['dj','hue','doorbell','switchbot','vacuum','alarm'],'port':API_PORT,'slot':_slot(),'kids_mode':_kids,'hue_mode':_hue_mode,'dj_total_plays':_dj_stats['total_plays'],'vac_days_since_clean':round(_vac_days(),1),'sse':_sse_subscriber.status() if _sse_subscriber else {'enabled':False}})

@app.route('/health')
def health():
    # v5.1: check alarm availability too
    alarm_ok = False
    try:
        s = ha_get(f'/states/{ALARM_ENTITIES[DEFAULT_LOCATION]}')
        alarm_ok = bool(s and s.get('state') not in ('unavailable', 'unknown', None))
    except Exception: pass
    return jsonify({'status':'ok','dj':'ok' if _sp_auth() else 'auth_failed','hue':'ok' if _hg('/config') else 'unreachable','switchbot':'ok' if _sb_devs else 'no_devices','vacuum':'ok','doorbell':'ok','alarm':'ok' if alarm_ok else 'unavailable'})

# Register blueprints — DJ twice for backward compat (unprefixed) + /dj/ prefix
app.register_blueprint(dj_bp)
app.register_blueprint(dj_bp,url_prefix='/dj',name='dj_prefixed')
app.register_blueprint(hue_bp)
app.register_blueprint(db_bp)
app.register_blueprint(sb_bp)
app.register_blueprint(vac_bp)
app.register_blueprint(alarm_bp)  # v5.1 added 2026-04-29

@app.route('/sse/status')
def sse_status_endpoint():
    """v5: Expose SSE subscriber status."""
    if _sse_subscriber is None:
        return jsonify({'enabled': False, 'reason': 'not yet started'})
    return jsonify({'enabled': True, **_sse_subscriber.status()})

# ==============================================================================
# v5: SSE Reactors (replace HA automations with in-process handlers)
# ==============================================================================

_sse_subscriber = None
_dj_paused_by_tv = False  # Track if we paused DJ because TV turned on

def react_tv(old, new, eid, attrs):
    """Samsung Frame TV state change → pause/resume DJ."""
    global _dj_paused_by_tv
    if new == 'on' and old != 'on':
        # Only pause if DJ is currently playing
        state = ha_get(f'/states/{SONOS}')
        if state and state.get('state') == 'playing':
            logger.info('SSE react: TV on → pausing DJ')
            http.post(f'{HA_URL}/api/services/media_player/media_pause',
                      headers=hh(), json={'entity_id': SONOS}, timeout=5)
            _dj_paused_by_tv = True
    elif new in ('off', 'standby') and _dj_paused_by_tv:
        logger.info('SSE react: TV off → resuming DJ')
        http.post(f'{HA_URL}/api/services/media_player/media_play',
                  headers=hh(), json={'entity_id': SONOS}, timeout=5)
        _dj_paused_by_tv = False

def react_presence(old, new, eid, attrs):
    """iPhone presence change → depart/arrive actions."""
    if new == 'off' and old == 'on':
        logger.info('SSE react: iPhone departed — pausing music + closing blinds')
        http.post(f'{HA_URL}/api/services/media_player/media_pause',
                  headers=hh(), json={'entity_id': SONOS}, timeout=5)
        # Close SwitchBot blinds
        try:
            for did, name in _sb_blinds.items():
                _sbp(f'/devices/{did}/commands',
                     {'command': 'setPosition', 'parameter': '0,ff,0', 'commandType': 'command'})
        except Exception as e:
            logger.error(f'blind close on depart: {e}')

def react_cooper(old, new, eid, attrs):
    """Cooper here toggle → Hue preset + DJ kids mode."""
    global _kids
    if new == 'on' and old != 'on':
        logger.info('SSE react: Cooper arrived — Hue cooper preset + kids mode ON')
        try: _preset('cooper', 20)
        except Exception as e: logger.error(f'hue cooper: {e}')
        _kids = True
    elif new == 'off' and old == 'on':
        logger.info('SSE react: Cooper gone — kids mode OFF')
        _kids = False

def react_alarm(old, new, eid, attrs):
    """Alarm panel state change → coordinated reactions. v5.1."""
    if not eid.startswith('alarm_control_panel.'): return
    location = 'chatsworth' if 'chatsworth' in eid else ('vlp' if 'villa_las' in eid else 'unknown')
    logger.info(f'SSE react: {location} alarm {old} → {new}')

    if new == 'triggered':
        # Emergency: flash all lights red + loud notification
        logger.warning(f'🚨 ALARM TRIGGERED at {location}')
        try:
            lights = _hg('/lights') or {}
            for lid in lights:
                _hp(f'/lights/{lid}/state', {'on': True, 'xy': [0.675, 0.322], 'bri': 254, 'alert': 'lselect'})
        except Exception as e:
            logger.error(f'alarm light flash failed: {e}')
        ha_notify(f'🚨 ALARM: {location.upper()}', f'Alarm triggered. Check cameras immediately.')

    elif new in ('armed_home', 'armed_away') and old == 'disarmed':
        # Armed — send confirmation push
        mode = 'Home' if 'home' in new else 'Away'
        logger.info(f'SSE react: {location} armed ({mode})')
        ha_notify(f'🔒 {location.capitalize()} Armed', f'Mode: {mode}. Stay safe.')

    elif new == 'disarmed' and old in ('armed_home', 'armed_away'):
        logger.info(f'SSE react: {location} disarmed')
        ha_notify(f'🔓 {location.capitalize()} Disarmed', 'Alarm off.')

SSE_REACTORS = {
    'media_player.75_the_frame_3':                react_tv,
    'binary_sensor.iphone_presence':              react_presence,
    'input_boolean.cooper_here':                  react_cooper,
    'alarm_control_panel.chatsworth_alarm':       react_alarm,
    'alarm_control_panel.villa_las_palmas_alarm': react_alarm,
}

if __name__=='__main__':
    logger.info(f'TARS Services v5.0.0 on port {API_PORT}')
    _dj_load(); _db_load(); _vac_load(); _sp_user_load()
    threading.Thread(target=_sb_load,daemon=True).start()
    threading.Thread(target=_vac_track,daemon=True).start()
    logger.info(f'Spotify app-auth: {"OK" if _sp_auth() else "FAILED"}')
    logger.info(f'Spotify user-auth: {"OK" if _sp_user_token() else "not authorized (visit /dj/auth/start)"}')
    # v5: SSE subscriber to Core event stream
    _sse_subscriber = CoreSSESubscriber(
        core_url=CORE_URL,
        reactors=SSE_REACTORS,
        on_connect=lambda: logger.info('SSE: connected to Core event stream'),
    )
    _sse_subscriber.start()
    app.run(host='0.0.0.0',port=API_PORT,debug=False)
