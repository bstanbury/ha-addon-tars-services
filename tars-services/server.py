#!/usr/bin/env python3
"""TARS Services v4.0.0 — DJ + Hue + Doorbell + SwitchBot + Vacuum on port 8097"""
import os,json,time,logging,random,base64,threading,hashlib,hmac,uuid
from datetime import datetime
from collections import deque,Counter
from flask import Flask,Blueprint,jsonify,request
import requests as http
import tinytuya

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
    global _sp_tok,_sp_exp
    if _sp_tok and time.time()<_sp_exp: return _sp_tok
    auth=base64.b64encode(f'{SP_ID}:{SP_SECRET}'.encode()).decode()
    r=http.post('https://accounts.spotify.com/api/token',headers={'Authorization':f'Basic {auth}','Content-Type':'application/x-www-form-urlencoded'},data={'grant_type':'client_credentials'},timeout=10)
    if r.status_code==200:
        d=r.json(); _sp_tok=d['access_token']; _sp_exp=time.time()+d.get('expires_in',3600)-60; return _sp_tok
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

@dj_bp.route('/health')
def dj_health(): return jsonify({'status':'ok' if _sp_auth() else 'auth_failed','slot':_slot(),'kids_mode':_kids})

@dj_bp.route('/recommend',methods=['GET','POST'])
def dj_recommend(): p=_pick(mood=request.args.get('mood')); return jsonify({'id':p['id'],'name':p.get('name','?'),'vibe':p.get('vibe',''),'slot':_slot(),'weather':_weather()})

@dj_bp.route('/play',methods=['GET','POST'])
def dj_play(): p=_pick(mood=request.args.get('mood')); _play(p['id']); return jsonify({'success':True,'playing':p.get('name',p['id']),'slot':_slot(),'kids_mode':_kids})

@dj_bp.route('/mood/<mood>',methods=['GET','POST'])
def dj_mood(mood):
    if mood not in DJ_LIB: return jsonify({'error':f'Unknown. Try: {list(DJ_LIB.keys())}'}),400
    p=_pick(mood=mood); _play(p['id']); return jsonify({'success':True,'mood':mood,'playing':p.get('name',p['id'])})

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
        if cls=='delivery': ha_notify('\U0001f4e6 Possible Delivery',f'Front door motion at {h}:00')
        elif cls=='visitor': ha_notify('\U0001f6b6 Visitor','Front door motion detected')
    return ev

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
        d=_vd(); raw=d.status(); dps=raw.get('dps',{}); wc=dps.get('6',-1)
        data={'online':True,'state':VAC_WORK.get(wc,f'unknown_{wc}'),'battery':dps.get('8',0),'suction':dps.get('158','?'),'is_cleaning':wc==1,'is_docked':wc in[34,0],'timestamp':time.time()}
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
                _vac_hist.append(_vac_sess); _vac_save(); ha_notify('\U0001f9f9 Clean Complete',f"Session ended. {round(_vac_days(),1)}d since last."); _vac_sess=None
        except: pass
        time.sleep(30)

@vac_bp.route('/status')
def vac_status():
    with _vac_stl:
        if _vac_st and (time.time()-_vac_st.get('timestamp',0))<15: return jsonify({**_vac_st,'source':'cache'})
    return jsonify({**_vac_status(),'source':'live'})

@vac_bp.route('/history')
def vac_history(): return jsonify({'total':len(_vac_hist),'sessions':_vac_hist[-request.args.get('limit',10,type=int):],'current':_vac_sess})

@vac_bp.route('/start',methods=['GET','POST'])
def vac_start():
    if _vac_defer(): return jsonify({'success':False,'deferred':True,'reason':'Bedroom motion + before 9am'})
    if _vac_cooper(): return jsonify({'success':False,'reason':'Cooper is home'})
    try: _vd().set_value(160,True); return jsonify({'success':True,'message':'Start sent'})
    except Exception as e: return jsonify({'success':False,'error':str(e)}),500

@vac_bp.route('/dock',methods=['GET','POST'])
def vac_dock():
    try: _vd().set_value(160,False); return jsonify({'success':True})
    except Exception as e: return jsonify({'success':False,'error':str(e)}),500

@vac_bp.route('/suction/<level>',methods=['GET','POST'])
def vac_suction(level):
    m={'quiet':'Quiet','q':'Quiet','standard':'Standard','s':'Standard','turbo':'Turbo','t':'Turbo','max':'Max','m':'Max'}
    t=m.get(level.lower(),level.capitalize())
    if t not in VAC_SUC: return jsonify({'error':f'Use: {VAC_SUC}'}),400
    try: _vd().set_value(158,t); return jsonify({'success':True,'suction':t})
    except Exception as e: return jsonify({'success':False,'error':str(e)}),500

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

# ═══════════════════════════════════════════════════════════════════════════════
# ROOT & HEALTH
# ═══════════════════════════════════════════════════════════════════════════════
@app.route('/')
def root(): return jsonify({'name':'TARS Services','version':'4.0.0','services':['dj','hue','doorbell','switchbot','vacuum'],'port':API_PORT,'slot':_slot(),'kids_mode':_kids,'hue_mode':_hue_mode,'dj_total_plays':_dj_stats['total_plays'],'vac_days_since_clean':round(_vac_days(),1)})

@app.route('/health')
def health(): return jsonify({'status':'ok','dj':'ok' if _sp_auth() else 'auth_failed','hue':'ok' if _hg('/config') else 'unreachable','switchbot':'ok' if _sb_devs else 'no_devices','vacuum':'ok','doorbell':'ok'})

# Register blueprints — DJ twice for backward compat (unprefixed) + /dj/ prefix
app.register_blueprint(dj_bp)
app.register_blueprint(dj_bp,url_prefix='/dj',name='dj_prefixed')
app.register_blueprint(hue_bp)
app.register_blueprint(db_bp)
app.register_blueprint(sb_bp)
app.register_blueprint(vac_bp)

if __name__=='__main__':
    logger.info(f'TARS Services v4.0.0 on port {API_PORT}')
    _dj_load(); _db_load(); _vac_load()
    threading.Thread(target=_sb_load,daemon=True).start()
    threading.Thread(target=_vac_track,daemon=True).start()
    logger.info(f'Spotify: {"OK" if _sp_auth() else "FAILED"}')
    app.run(host='0.0.0.0',port=API_PORT,debug=False)
