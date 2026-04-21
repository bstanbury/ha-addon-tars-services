#!/usr/bin/env python3
import os, json, time, logging, random, base64, threading, hashlib, hmac, uuid
from datetime import datetime
from collections import deque, Counter
from flask import Flask, Blueprint, jsonify, request
import requests as http
import tinytuya
import sseclient

HA_URL=os.environ.get('HA_URL','http://localhost:8123')
HA_TOKEN=os.environ.get('HA_TOKEN','')
API_PORT=int(os.environ.get('API_PORT','8097'))
CORE_URL=os.environ.get('CORE_URL','http://localhost:8093')

BEDROOM_ENTITIES=['media_player.bedroom','media_player.bedroom_sonos','media_player.bedroom_echo']
ECHO_ENTITIES=['media_player.chatsworth_living_room_echo_show','media_player.chatsworth_kitchen_echo_show','media_player.bedroom_echo_show_chatsworth','media_player.chatsworth_echo_show_5_bathroom']
SILENT_HOURS=lambda: datetime.now().hour>=22 or datetime.now().hour<8
BEDROOM_CURFEW=lambda: datetime.now().hour>=21 or datetime.now().hour<8

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')

def ha_get(path):
    try:
        r=http.get(f'{HA_URL}/api{path}',headers={'Authorization':f'Bearer {HA_TOKEN}'},timeout=5)
        return r.json() if r.status_code==200 else None
    except: return None

def ha_post(path,body):
    try: http.post(f'{HA_URL}/api{path}',headers={'Authorization':f'Bearer {HA_TOKEN}','Content-Type':'application/json'},json=body,timeout=5)
    except: pass

def ha_notify(title,msg):
    ha_post('/services/notify/mobile_app_bks_home_assistant_chatsworth',{'data':{'title':title,'message':msg}})

def is_bedroom_safe():
    s=ha_get('/states/binary_sensor.bedroom_motion')
    return bool(s and s.get('state')=='on')

def is_bedroom_light(name):
    return 'bedroom' in name.lower() or 'bed room' in name.lower()

app=Flask(__name__)

# DJ
CLIENT_ID=os.environ.get('SPOTIFY_CLIENT_ID','')
CLIENT_SECRET=os.environ.get('SPOTIFY_CLIENT_SECRET','')
SONOS=os.environ.get('SONOS_ENTITY','media_player.living_room')
dj_bp=Blueprint('dj',__name__)
dj_logger=logging.getLogger('tars.dj')
dj_token=None; dj_token_exp=0; dj_recent=[]; dj_kids=False; dj_current=None; dj_tv_paused=False
dj_events=deque(maxlen=100); dj_history=deque(maxlen=20); dj_phone_ducked=False
DJ_DATA='/data/dj_stats.json'
dj_stats={'likes':{},'skips':{},'plays':{},'total_plays':0}
LIB={'morning_early':[{'id':'37i9dQZF1DWXe9gFZP0gtP','name':'Chill Morning','vibe':'gentle'},{'id':'37i9dQZF1DX1n9whBbBKoL','name':'Lo-fi Cafe','vibe':'coffee'},{'id':'37i9dQZF1DX6ziVCJnEm59','name':'Morning Motivation','vibe':'upbeat'}],'morning_late':[{'id':'5vImPKH5smp2ifK34N6XTd','name':'Energetic Upbeat Lofi','vibe':'productive'},{'id':'37i9dQZF1DX0SM0LYsmbMT','name':'Jazz Vibes','vibe':'sophisticated'},{'id':'37i9dQZF1DX4OzrY981I1W','name':'Indie Folk','vibe':'laid back'}],'afternoon':[{'id':'0CFuMybe6s77w6QQrJjW7d','name':'Chillhop Radio','vibe':'focus'},{'id':'37i9dQZF1DX0SM0LYsmbMT','name':'Jazz Vibes','vibe':'groove'},{'id':'37i9dQZF1DWVqJMsgEN0F4','name':'Acoustic Evening','vibe':'mellow'},{'id':'37i9dQZF1DX4OzrY981I1W','name':'Indie Folk','vibe':'weekend'}],'evening':[{'id':'3NXxyeM9cp3bRnxNtqhOu4','name':'Lofi Trap Beats','vibe':'chill'},{'id':'37i9dQZF1DX6VdMW310YC7','name':'Chill R&B','vibe':'smooth'},{'id':'37i9dQZF1DWVqJMsgEN0F4','name':'Acoustic Evening','vibe':'wind down'},{'id':'37i9dQZF1DX3Ogo9pFvBkY','name':'Ambient','vibe':'zen'},{'id':'37i9dQZF1DXcKnb4wcRKrO','name':'Chill Evening','vibe':'relaxed'}],'night':[{'id':'5eDufIy8WtiArgp9aPd9su','name':'Late Night Vibes','vibe':'night owl'},{'id':'37i9dQZF1DWZd79rJ6a7lp','name':'Sleep Jazz','vibe':'dreamy'},{'id':'37i9dQZF1DX3Ogo9pFvBkY','name':'Ambient','vibe':'sleep'},{'id':'6bGe4ekNk4E4h9vVkuItul','name':'Ambient Deep Sleep','vibe':'deep sleep'}],'chill':[{'id':'37i9dQZF1DX3Ogo9pFvBkY','name':'Ambient'},{'id':'37i9dQZF1DWVqJMsgEN0F4','name':'Acoustic Evening'},{'id':'0CFuMybe6s77w6QQrJjW7d','name':'Chillhop'}],'energetic':[{'id':'37i9dQZF1DX6ziVCJnEm59','name':'Morning Motivation'},{'id':'37i9dQZF1DX76Wlfdnj7AP','name':'Beast Mode'},{'id':'37i9dQZF1DX0BcQWzuB7ZO','name':'Dance Hits'}],'focus':[{'id':'37i9dQZF1DX1n9whBbBKoL','name':'Lo-fi Cafe'},{'id':'37i9dQZF1DWZeKCadgRdKQ','name':'Deep Focus'},{'id':'0CFuMybe6s77w6QQrJjW7d','name':'Chillhop'}],'party':[{'id':'37i9dQZF1DX0BcQWzuB7ZO','name':'Dance Hits'},{'id':'37i9dQZF1DXa2PjGhjTnEG','name':'Party Starters'}],'sleep':[{'id':'37i9dQZF1DWZd79rJ6a7lp','name':'Sleep Jazz'},{'id':'37i9dQZF1DX3Ogo9pFvBkY','name':'Ambient'},{'id':'6bGe4ekNk4E4h9vVkuItul','name':'Ambient Deep Sleep'}],'romantic':[{'id':'37i9dQZF1DX6VdMW310YC7','name':'Chill R&B'},{'id':'37i9dQZF1DWVqJMsgEN0F4','name':'Acoustic Evening'}],'rainy':[{'id':'37i9dQZF1DX1n9whBbBKoL','name':'Lo-fi Cafe'},{'id':'37i9dQZF1DX3Ogo9pFvBkY','name':'Ambient'}],'sunny':[{'id':'37i9dQZF1DX4OzrY981I1W','name':'Indie Folk'},{'id':'37i9dQZF1DX6ziVCJnEm59','name':'Morning Motivation'}],'kids':[{'id':'37i9dQZF1DX6aTaZa0K6VA','name':'Disney Hits'},{'id':'37i9dQZF1DWVlYsZJXBFMo','name':'Kids Pop'},{'id':'37i9dQZF1DX2M1RktxUUHE','name':'Family Road Trip'},{'id':'37i9dQZF1DXa8NOEUWPn9W','name':'Happy Hits'},{'id':'7LD17YaJftpf0WMg40h25L','name':'Kids Dance Party Clean'},{'id':'2k1TzwejfDMu9vszNPQE4s','name':'Kids Dance Party Fun'},{'id':'1P27ra5VqAizmkcUzVAvp2','name':'Kids Party Songs 2026'},{'id':'4oeElKN7O9Kb5yvtUaG0h6','name':'Music to Dance to for Kids'},{'id':'3Bnwxiui9rcgFPODnyX4JA','name':'2026 kids family dance party'},{'id':'0hq7dAuNzYCKVmI7URkvzW','name':'kids songs good for adults too'}],'dinner':[{'id':'37i9dQZF1DX4xuWVBs4FgJ','name':'Dinner Jazz'},{'id':'37i9dQZF1DWVqJMsgEN0F4','name':'Acoustic Evening'},{'id':'37i9dQZF1DWWKeNBqaIy5U','name':'Dinner Jazz Classics'}],'workout':[{'id':'37i9dQZF1DX76Wlfdnj7AP','name':'Beast Mode'},{'id':'37i9dQZF1DX0BcQWzuB7ZO','name':'Dance Hits'}],'morning_coffee':[{'id':'37i9dQZF1DX1n9whBbBKoL','name':'Lo-fi Cafe'},{'id':'37i9dQZF1DWXe9gFZP0gtP','name':'Chill Morning'}]}

def dj_load():
    global dj_stats
    try:
        if os.path.exists(DJ_DATA): dj_stats=json.load(open(DJ_DATA))
    except: pass

def dj_save():
    try: json.dump(dj_stats,open(DJ_DATA,'w'),indent=2)
    except: pass

def sp_token():
    global dj_token,dj_token_exp
    if dj_token and time.time()<dj_token_exp: return dj_token
    auth=base64.b64encode(f'{CLIENT_ID}:{CLIENT_SECRET}'.encode()).decode()
    r=http.post('https://accounts.spotify.com/api/token',headers={'Authorization':f'Basic {auth}','Content-Type':'application/x-www-form-urlencoded'},data={'grant_type':'client_credentials'},timeout=10)
    if r.status_code==200:
        d=r.json(); dj_token=d['access_token']; dj_token_exp=time.time()+d.get('expires_in',3600)-60; return dj_token
    return None

def time_slot():
    h=datetime.now().hour
    if 6<=h<9:return 'morning_early'
    if 9<=h<12:return 'morning_late'
    if 12<=h<17:return 'afternoon'
    if 17<=h<21:return 'evening'
    return 'night'

def get_weather():
    s=ha_get('/states/weather.forecast_home')
    return s['state'] if s else 'unknown'

def score_playlist(p):
    pid=p['id']; return dj_stats['likes'].get(pid,0)*3-dj_stats['skips'].get(pid,0)*2+dj_stats['plays'].get(pid,0)*0.5

def record_play(p,mood='auto'):
    dj_history.append({'time':datetime.now().isoformat(),'id':p['id'],'name':p.get('name',p['id']),'mood':mood,'liked':dj_stats['likes'].get(p['id'],0)>0,'skipped':dj_stats['skips'].get(p['id'],0)>0})

def pick(slot=None,mood=None):
    global dj_recent,dj_current
    if dj_kids: mood='kids'
    w=get_weather()
    if mood and mood in LIB:cands=LIB[mood]
    elif w in ['rainy','pouring']: cands=LIB.get('rainy',LIB.get(slot or time_slot(),[]))
    elif w in ['sunny','clear-night','partlycloudy'] and time_slot() in ['morning_late','afternoon']: cands=LIB.get('sunny',LIB.get(slot or time_slot(),[]))
    else:cands=LIB.get(slot or time_slot(),[])
    if not cands:cands=LIB['afternoon']
    avail=[p for p in cands if p['id'] not in dj_recent[-3:]] or cands
    if dj_stats['total_plays']>5:
        avail.sort(key=score_playlist,reverse=True); weights=[max(1,score_playlist(p)+5) for p in avail]; total=sum(weights); r=random.random()*total; c=0
        for i,w2 in enumerate(weights):
            c+=w2
            if r<=c: p=avail[i]; break
        else:p=avail[0]
    else:p=random.choice(avail)
    dj_recent.append(p['id']); dj_recent=dj_recent[-10:]; dj_current=p['id']; dj_stats['plays'][p['id']]=dj_stats['plays'].get(p['id'],0)+1; dj_stats['total_plays']+=1; dj_save(); record_play(p,mood or time_slot()); return p

def play_sonos(pid,vol=None,speaker=None,enqueue=False):
    target=speaker or SONOS
    if target in BEDROOM_ENTITIES and not is_bedroom_safe(): return False
    hh={'Authorization':f'Bearer {HA_TOKEN}','Content-Type':'application/json'}
    try: http.post(f'{HA_URL}/api/services/media_player/select_source',headers=hh,json={'entity_id':target,'source':'Spotify'},timeout=5)
    except: pass
    time.sleep(1)
    if vol is None:
        vol={'morning_early':0.22,'morning_late':0.25,'afternoon':0.28,'evening':0.25,'night':0.15}.get(time_slot(),0.25)
        if dj_kids: vol=min(vol+0.03,0.30)
    http.post(f'{HA_URL}/api/services/media_player/volume_set',headers=hh,json={'entity_id':target,'volume_level':vol},timeout=5)
    body={'entity_id':target,'media_content_id':f'spotify:playlist:{pid}','media_content_type':'spotify://playlist'}
    if enqueue: body['enqueue']='next'
    http.post(f'{HA_URL}/api/services/media_player/play_media',headers=hh,json=body,timeout=5)
    if not enqueue:
        time.sleep(1); http.post(f'{HA_URL}/api/services/media_player/shuffle_set',headers=hh,json={'entity_id':target,'shuffle':True},timeout=5)
    return True

def duck_phone_call():
    global dj_phone_ducked
    if dj_phone_ducked: return
    ha_post('/services/media_player/volume_set',{'entity_id':SONOS,'volume_level':0.08}); dj_phone_ducked=True

def unduck_phone_call():
    global dj_phone_ducked
    if not dj_phone_ducked: return
    ha_post('/services/media_player/volume_set',{'entity_id':SONOS,'volume_level':0.22}); dj_phone_ducked=False

def dj_search_spotify(query,types='playlist',limit=5):
    t=sp_token()
    if not t:return []
    r=http.get('https://api.spotify.com/v1/search',headers={'Authorization':f'Bearer {t}'},params={'q':query,'type':types,'limit':limit},timeout=8)
    if r.status_code!=200:return []
    d=r.json()
    if types=='playlist': return d.get('playlists',{}).get('items',[]) or []
    if types=='track': return d.get('tracks',{}).get('items',[]) or []
    return []

def dj_handle_event(ev):
    global dj_tv_paused
    eid=ev.get('entity_id',''); new=ev.get('new_state',''); old=ev.get('old_state',''); sig=ev.get('significant',False); action=None
    if 'media_player.75_the_frame' in eid or ('media_player' in eid and 'frame' in eid):
        if new in ['on','playing'] and old in ['off','standby','unavailable']: ha_post('/services/media_player/media_pause',{'entity_id':SONOS}); dj_tv_paused=True; action='pause_for_tv'
        elif new in ['off','standby'] and dj_tv_paused: ha_post('/services/media_player/media_play',{'entity_id':SONOS}); dj_tv_paused=False; action='resume_after_tv'
    elif 'phone' in eid or 'iphone' in eid or 'call' in eid:
        if new in ['ringing','busy','in_call','playing'] and old!=new: duck_phone_call(); action='duck_for_phone'
        elif new in ['idle','off','paused'] and dj_phone_ducked: unduck_phone_call(); action='unduck_after_phone'
    elif 'weather' in eid and sig:
        if new in ['rainy','pouring']: p=pick(mood='rainy'); play_sonos(p['id']); action='weather_rainy'
    if action: dj_events.append({'time':datetime.now().isoformat(),'event':eid,'action':action,'old':old,'new':new})

def dj_sse_thread():
    while True:
        try:
            r=http.get(f'{CORE_URL}/events/stream',stream=True,timeout=None)
            for event in sseclient.SSEClient(r).events():
                try: dj_handle_event(json.loads(event.data))
                except: pass
        except Exception as e: dj_logger.error(f'DJ SSE: {e}')
        time.sleep(10)

@dj_bp.route('/dj/health')
def dj_health(): return jsonify({'status':'ok' if sp_token() else 'auth_failed','kids_mode':dj_kids,'tv_paused':dj_tv_paused})
@dj_bp.route('/dj/play',methods=['POST','GET'])
def dj_play(): p=pick(mood=request.args.get('mood')); play_sonos(p['id']); return jsonify({'success':True,'playing':p.get('name',p['id'])})
@dj_bp.route('/dj/mood/<mood>',methods=['POST','GET'])
def dj_mood(mood): p=pick(mood=mood); play_sonos(p['id']); return jsonify({'success':True,'mood':mood,'playing':p.get('name',p['id'])})
@dj_bp.route('/dj/kids',methods=['POST','GET'])
def dj_kids_on():
    global dj_kids; dj_kids=True; p=pick(mood='kids'); play_sonos(p['id']); return jsonify({'success':True,'kids_mode':True,'playing':p.get('name',p['id'])})
@dj_bp.route('/dj/kids/off',methods=['POST','GET'])
def dj_kids_off():
    global dj_kids; dj_kids=False; p=pick(); play_sonos(p['id']); return jsonify({'success':True,'kids_mode':False,'playing':p.get('name',p['id'])})
@dj_bp.route('/dj/like',methods=['POST','GET'])
def dj_like():
    if dj_current: dj_stats['likes'][dj_current]=dj_stats['likes'].get(dj_current,0)+1; dj_save(); return jsonify({'success':True,'liked':dj_current})
    return jsonify({'error':'Nothing playing'}),400
@dj_bp.route('/dj/skip',methods=['POST','GET'])
def dj_skip():
    if dj_current: dj_stats['skips'][dj_current]=dj_stats['skips'].get(dj_current,0)+1; dj_save(); p=pick(); play_sonos(p['id']); return jsonify({'success':True,'now_playing':p.get('name',p['id'])})
    return jsonify({'error':'Nothing playing'}),400
@dj_bp.route('/dj/volume/<int:level>',methods=['POST','GET'])
def dj_volume(level): vol=max(0,min(100,level))/100; ha_post('/services/media_player/volume_set',{'entity_id':SONOS,'volume_level':vol}); return jsonify({'success':True,'volume':vol})
@dj_bp.route('/dj/speaker/<entity>',methods=['POST','GET'])
def dj_speaker(entity):
    global SONOS
    if entity in ECHO_ENTITIES:return jsonify({'error':'Echo devices trigger TV'}),403
    if entity in BEDROOM_ENTITIES and not is_bedroom_safe():return jsonify({'error':'Bedroom blocked'}),403
    SONOS=entity; return jsonify({'success':True,'speaker':SONOS})
@dj_bp.route('/dj/search/<query>')
def dj_search(query):
    items=dj_search_spotify(query,'playlist',5)
    return jsonify([{'id':p['id'],'name':p['name'],'tracks':p.get('tracks',{}).get('total','?')} for p in items])
@dj_bp.route('/dj/request',methods=['POST'])
def dj_request():
    data=request.get_json(silent=True) or {}
    q=data.get('query','').strip()
    if not q:return jsonify({'error':'query required'}),400
    items=dj_search_spotify(q,'playlist',5)
    if not items: items=dj_search_spotify(q,'track',5)
    if not items:return jsonify({'error':'No results'}),404
    best=items[0]
    if 'uri' in best and best['uri'].startswith('spotify:track:'):
        hh={'Authorization':f'Bearer {HA_TOKEN}','Content-Type':'application/json'}
        http.post(f'{HA_URL}/api/services/media_player/play_media',headers=hh,json={'entity_id':SONOS,'media_content_id':best['uri'],'media_content_type':'music'},timeout=5)
    else:
        play_sonos(best['id'])
    record_play({'id':best.get('id',best.get('uri','?')),'name':best.get('name','?')},q)
    return jsonify({'success':True,'query':q,'match':{'id':best.get('id'),'name':best.get('name'),'uri':best.get('uri')}})
@dj_bp.route('/dj/history')
def dj_history_route(): return jsonify(list(dj_history)[-20:])
@dj_bp.route('/dj/queue',methods=['POST'])
def dj_queue():
    data=request.get_json(silent=True) or {}
    q=data.get('query','').strip()
    if not q:return jsonify({'error':'query required'}),400
    items=dj_search_spotify(q,'track',3) or dj_search_spotify(q,'playlist',3)
    if not items:return jsonify({'error':'No results'}),404
    best=items[0]; hh={'Authorization':f'Bearer {HA_TOKEN}','Content-Type':'application/json'}
    body={'entity_id':SONOS,'enqueue':'next'}
    if best.get('uri','').startswith('spotify:track:'): body.update({'media_content_id':best['uri'],'media_content_type':'music'})
    else: body.update({'media_content_id':f"spotify:playlist:{best['id']}",'media_content_type':'spotify://playlist'})
    http.post(f'{HA_URL}/api/services/media_player/play_media',headers=hh,json=body,timeout=5)
    return jsonify({'success':True,'queued':best.get('name'),'mode':'next'})
@dj_bp.route('/dj/now-playing')
def dj_now_playing():
    s=ha_get(f'/states/{SONOS}')
    return jsonify({'state':s['state'],'title':s['attributes'].get('media_title'),'artist':s['attributes'].get('media_artist'),'volume':s['attributes'].get('volume_level'),'kids_mode':dj_kids,'tv_paused':dj_tv_paused}) if s else (jsonify({'error':'failed'}),500)
@dj_bp.route('/dj/playlists')
def dj_playlists(): return jsonify(LIB)
@dj_bp.route('/dj/stats')
def dj_stats_route(): return jsonify({'total_plays':dj_stats['total_plays'],'likes':dj_stats['likes'],'skips':dj_stats['skips'],'plays':dj_stats['plays']})
@dj_bp.route('/dj/recommend')
def dj_recommend(): p=pick(mood=request.args.get('mood')); return jsonify({'id':p['id'],'name':p.get('name'),'vibe':p.get('vibe'),'slot':time_slot()})
@dj_bp.route('/dj/event-log')
def dj_event_log(): return jsonify(list(dj_events)[-20:])

# Hue
hue_bp=Blueprint('hue',__name__); hue_logger=logging.getLogger('tars.hue')
BRIDGE_IP=os.environ.get('HUE_BRIDGE_IP','192.168.4.39'); HUE_KEY=os.environ.get('HUE_API_KEY','')
HUE=lambda: f'http://{BRIDGE_IP}/api/{HUE_KEY}'
hue_mode='auto'; hue_last=None; hue_events=deque(maxlen=100); HUE_DATA='/data/hue_state.json'; hue_follow_enabled=True
PRESETS={'sunset':[{'bri':200,'xy':[0.5,0.4]},{'bri':150,'xy':[0.55,0.35]},{'bri':100,'xy':[0.45,0.35]},{'bri':180,'xy':[0.6,0.38]}],'ocean':[{'bri':150,'xy':[0.17,0.2]},{'bri':180,'xy':[0.15,0.25]},{'bri':120,'xy':[0.2,0.3]},{'bri':160,'xy':[0.16,0.22]}],'forest':[{'bri':120,'xy':[0.3,0.5]},{'bri':100,'xy':[0.35,0.45]},{'bri':80,'xy':[0.25,0.4]},{'bri':140,'xy':[0.32,0.48]}],'fire':[{'bri':254,'xy':[0.6,0.38]},{'bri':200,'xy':[0.55,0.35]},{'bri':150,'xy':[0.65,0.33]},{'bri':180,'xy':[0.58,0.38]}],'aurora':[{'bri':150,'xy':[0.15,0.25]},{'bri':120,'xy':[0.3,0.15]},{'bri':180,'xy':[0.2,0.5]},{'bri':100,'xy':[0.25,0.1]}],'candlelight':[{'bri':80,'xy':[0.55,0.4]},{'bri':60,'xy':[0.58,0.38]},{'bri':70,'xy':[0.52,0.41]},{'bri':50,'xy':[0.56,0.39]}],'neon':[{'bri':254,'xy':[0.35,0.15]},{'bri':254,'xy':[0.15,0.06]},{'bri':254,'xy':[0.2,0.5]},{'bri':254,'xy':[0.55,0.35]}],'golden_hour':[{'bri':200,'xy':[0.52,0.41]},{'bri':180,'xy':[0.5,0.4]},{'bri':160,'xy':[0.48,0.39]},{'bri':140,'xy':[0.53,0.4]}],'cooper_day':[{'bri':200,'xy':[0.45,0.41]},{'bri':180,'xy':[0.44,0.4]},{'bri':160,'xy':[0.43,0.39]},{'bri':190,'xy':[0.46,0.4]}],'cooper_night':[{'bri':120,'xy':[0.50,0.40]},{'bri':100,'xy':[0.52,0.39]},{'bri':80,'xy':[0.48,0.38]},{'bri':110,'xy':[0.51,0.40]}]}
TIME_PRESETS={(14,17):'ocean',(17,19):'sunset',(19,21):'candlelight',(21,23):'candlelight'}

def hue_load():
    global hue_mode,hue_last
    try:
        if os.path.exists(HUE_DATA):
            d=json.load(open(HUE_DATA)); hue_mode=d.get('mode','auto'); hue_last=d.get('last_preset')
    except: pass

def hue_save():
    try: json.dump({'mode':hue_mode,'last_preset':hue_last,'saved':datetime.now().isoformat()},open(HUE_DATA,'w'))
    except: pass

def hue_get(p):
    try:return http.get(f'{HUE()}{p}',timeout=5).json()
    except:return {}
def hue_put(p,d):
    try:return http.put(f'{HUE()}{p}',json=d,timeout=5).json()
    except:return {}
def apply_preset(name,transition=10):
    global hue_last
    if name not in PRESETS:return False
    cs=PRESETS[name]; lights=hue_get('/lights'); lids=[lid for lid,l in lights.items() if l['state'].get('reachable')]
    for i,lid in enumerate(lids):
        lname=lights[lid].get('name','')
        if BEDROOM_CURFEW() and is_bedroom_light(lname) and not is_bedroom_safe(): continue
        hue_put(f'/lights/{lid}/state',{'on':True,**cs[i%len(cs)],'transitiontime':transition})
    hue_last=name; hue_save(); return True

def hue_follow_room(room_hint):
    groups=hue_get('/groups'); target=None
    for gid,g in groups.items():
        if room_hint.lower().replace('_',' ') in g.get('name','').lower(): target=gid; break
    if not target:return False
    for gid,g in groups.items():
        if gid==target: hue_put(f'/groups/{gid}/action',{'on':True,'bri':180,'ct':350,'transitiontime':10})
        else: hue_put(f'/groups/{gid}/action',{'on':True,'bri':40,'ct':400,'transitiontime':10})
    return True

def hue_handle_event(ev):
    global hue_mode
    eid=ev.get('entity_id',''); new=ev.get('new_state',''); old=ev.get('old_state',''); sig=ev.get('significant',False); action=None
    if ('media_player.75_the_frame' in eid or ('media_player' in eid and 'frame' in eid)) and new in ['on','playing'] and old in ['off','standby','unavailable']: hue_mode='movie'; apply_preset('candlelight',20); action='auto_movie'
    elif 'presence' in eid and new=='off':
        for gid in hue_get('/groups'): hue_put(f'/groups/{gid}/action',{'on':False,'transitiontime':20}); action='departure_off'
    elif 'motion' in eid and new=='on' and hue_follow_enabled:
        if 'living' in eid: hue_follow_room('living') and None; action='follow_living'
        elif 'kitchen' in eid: hue_follow_room('kitchen') and None; action='follow_kitchen'
        elif 'bedroom' in eid and is_bedroom_safe(): hue_follow_room('bedroom') and None; action='follow_bedroom'
    elif 'weather' in eid and sig and new in ['rainy','pouring'] and hue_mode=='auto': apply_preset('candlelight',30); action='rainy_candlelight'
    if action: hue_events.append({'time':datetime.now().isoformat(),'event':eid,'action':action,'old':old,'new':new})

def hue_sse_thread():
    while True:
        try:
            r=http.get(f'{CORE_URL}/events/stream',stream=True,timeout=None)
            for event in sseclient.SSEClient(r).events():
                try:hue_handle_event(json.loads(event.data))
                except:pass
        except Exception as e:hue_logger.error(f'Hue SSE: {e}')
        time.sleep(10)

def hue_time_loop():
    last=None
    while True:
        if hue_mode=='auto':
            h=datetime.now().hour
            for (s,e),preset in TIME_PRESETS.items():
                if s<=h<e and preset!=last: apply_preset(preset,100); last=preset; break
        time.sleep(300)
@hue_bp.route('/hue/health')
def hue_health(): c=hue_get('/config'); return jsonify({'status':'ok' if c else 'unreachable','bridge':c.get('name','?') if c else '?','mode':hue_mode})
@hue_bp.route('/hue/lights')
def hue_lights(): d=hue_get('/lights'); return jsonify([{'id':k,'name':v['name'],'on':v['state']['on'],'bri':v['state'].get('bri',0)} for k,v in d.items()])
@hue_bp.route('/hue/status')
def hue_status(): d=hue_get('/lights'); return jsonify({v['name']:{'on':v['state']['on'],'bri':v['state'].get('bri',0)} for k,v in d.items()})
@hue_bp.route('/hue/ambient/<preset>',methods=['POST','GET'])
def hue_ambient(preset):
    global hue_mode
    if preset not in PRESETS:return jsonify({'error':f'Use: {list(PRESETS.keys())}'}),400
    apply_preset(preset); hue_mode='manual'; return jsonify({'success':True,'preset':preset})
@hue_bp.route('/hue/movie',methods=['POST','GET'])
def hue_movie():
    global hue_mode
    hue_mode='movie'; apply_preset('candlelight',20); return jsonify({'success':True,'mode':'movie'})
@hue_bp.route('/hue/energy/<level>',methods=['POST','GET'])
def hue_energy(level):
    if level=='calm': apply_preset('candlelight',10)
    elif level=='medium': apply_preset('sunset',5)
    elif level=='high': apply_preset('neon',2)
    else:return jsonify({'error':'Use calm/medium/high'}),400
    return jsonify({'success':True,'energy':level})
@hue_bp.route('/hue/room/<room>/<action>',methods=['POST','GET'])
def hue_room(room,action): return jsonify({'success':hue_follow_room(room),'room':room,'action':action})
@hue_bp.route('/hue/scene/<scene>',methods=['POST','GET'])
def hue_scene(scene): return jsonify({'success':apply_preset(scene if scene in PRESETS else 'sunset'),'scene':scene})
@hue_bp.route('/hue/follow',methods=['POST'])
def hue_follow():
    data=request.get_json(silent=True) or {}
    room=data.get('room','')
    if not room:return jsonify({'error':'room required'}),400
    return jsonify({'success':hue_follow_room(room),'room':room})
@hue_bp.route('/hue/schedule')
def hue_schedule():
    h=datetime.now().hour; active=next((preset for (s,e),preset in TIME_PRESETS.items() if s<=h<e),None)
    return jsonify({'mode':hue_mode,'active_time_preset':active,'rooms':['living_room','kitchen','bedroom','bathroom'],'adaptive_lighting':'assumed_external'})
@hue_bp.route('/hue/cooper',methods=['POST','GET'])
def hue_cooper():
    preset='cooper_day' if 8<=datetime.now().hour<20 else 'cooper_night'
    apply_preset(preset,20)
    groups=hue_get('/groups')
    for gid,g in groups.items():
        if 'hall' in g.get('name','').lower(): hue_put(f'/groups/{gid}/action',{'on':True,'bri':30,'ct':420,'transitiontime':10})
    return jsonify({'success':True,'preset':preset,'hallway_nightlight':True})

# Doorbell
doorbell_bp=Blueprint('doorbell',__name__); db_logger=logging.getLogger('tars.doorbell')
KNOWN=set(json.loads(os.environ.get('KNOWN_DEVICES','[]'))); DATA_DB='/data/doorbell.json'
visitors=[]; learned_macs=set(); db_events=deque(maxlen=200); freq=Counter(); delivery=Counter(); labels=[]; last_motion=None; last_unlock=None

def db_load():
    global learned_macs,visitors,freq,delivery,labels
    try:
        if os.path.exists(DATA_DB):
            d=json.load(open(DATA_DB)); learned_macs=set(d.get('macs',[])); visitors=d.get('visitors',[]); freq=Counter(d.get('frequency_map',{})); delivery=Counter(d.get('delivery_windows',{})); labels=d.get('labels',[])
    except: pass

def db_save():
    try: json.dump({'macs':list(learned_macs),'visitors':visitors[-200:],'frequency_map':dict(freq),'delivery_windows':dict(delivery),'labels':labels[-200:]},open(DATA_DB,'w'),indent=2)
    except: pass

def net_devices():
    states=ha_get('/states')
    if not states:return []
    return [{'mac':s['attributes'].get('mac',''),'name':s['attributes'].get('friendly_name','?'),'ip':s['attributes'].get('ip','')} for s in states if s['entity_id'].startswith('device_tracker.') and 'stan_wifi' in s['entity_id'] and s['state']=='home' and s['attributes'].get('mac')]

def classify(source='poll'):
    h=datetime.now().hour; day=datetime.now().strftime('%a'); home=(ha_get('/states/binary_sensor.iphone_presence') or {}).get('state')=='on'; devs=net_devices(); new=[d for d in devs if d['mac'] not in learned_macs and d['mac'] not in KNOWN]
    if 9<=h<=18 and not home: cls,conf='delivery','high'
    elif new: cls,conf='visitor','medium'
    elif home: cls,conf='household','high'
    else: cls,conf='unknown','low'
    ev={'time':datetime.now().isoformat(),'type':cls,'confidence':conf,'home':home,'hour':h,'day':day,'new_devices':[d['name'] for d in new],'source':source}
    visitors.append(ev); key=f'{day}_{h}'; freq[key]+=1
    if cls=='delivery': delivery[key]+=1
    db_save()
    if cls=='delivery': ha_notify('\U0001f4e6 Possible Delivery',f'Front motion at {h}:00')
    elif cls=='visitor': ha_notify('\U0001f6b6 Visitor',f'Motion + unknown device')
    return ev

def check_let_in():
    global last_motion,last_unlock
    if last_motion and last_unlock:
        gap=abs((last_unlock-last_motion).total_seconds())
        if gap<=60: visitors.append({'time':datetime.now().isoformat(),'type':'let_in','confidence':'high','gap_seconds':round(gap),'source':'correlation'}); db_save(); last_motion=None; last_unlock=None

def db_handle_event(ev):
    global last_motion,last_unlock
    eid=ev.get('entity_id',''); new=ev.get('new_state',''); action=None
    if ('front' in eid and 'motion' in eid and new=='on') or ('ring' in eid.lower() and 'motion' in eid and new=='on'): last_motion=datetime.now(); er=classify('event_bus'); action=f'motion_{er["type"]}'; check_let_in()
    elif 'lock' in eid and new=='unlocked': last_unlock=datetime.now(); check_let_in(); action='unlock'
    if action: db_events.append({'time':datetime.now().isoformat(),'event':eid,'action':action})

def db_sse_thread():
    while True:
        try:
            r=http.get(f'{CORE_URL}/events/stream',stream=True,timeout=None)
            for event in sseclient.SSEClient(r).events():
                try: db_handle_event(json.loads(event.data))
                except: pass
        except Exception as e: db_logger.error(f'DB SSE: {e}')
        time.sleep(10)
@doorbell_bp.route('/doorbell/health')
def db_health(): return jsonify({'status':'ok','known':len(learned_macs)+len(KNOWN),'silent_hours':SILENT_HOURS()})
@doorbell_bp.route('/doorbell/status')
def db_status(): p=ha_get('/states/binary_sensor.iphone_presence'); l=ha_get('/states/lock.front_door_lock'); return jsonify({'home':p['state']=='on' if p else None,'lock':l['state'] if l else None,'last_visitor':visitors[-1] if visitors else None})
@doorbell_bp.route('/doorbell/events')
def db_events_route(): return jsonify(visitors[-int(request.args.get('limit',20)):])
@doorbell_bp.route('/doorbell/known')
def db_known(): return jsonify(list(learned_macs|KNOWN))
@doorbell_bp.route('/doorbell/classify',methods=['POST','GET'])
def db_classify(): return jsonify(classify('manual'))
@doorbell_bp.route('/doorbell/digest')
def db_digest():
    overnight=[v for v in visitors if (int(v['time'][11:13])>=22 or int(v['time'][11:13])<8)]
    by_type=Counter(v.get('type','unknown') for v in overnight[-50:])
    return jsonify({'count':len(overnight[-50:]),'by_type':dict(by_type),'events':overnight[-20:]})
@doorbell_bp.route('/doorbell/learn',methods=['POST'])
def db_learn():
    data=request.get_json(silent=True) or {}
    label=data.get('label'); idx=data.get('index',-1)
    if label not in ['delivery','neighbor','animal','known']: return jsonify({'error':'invalid label'}),400
    if not visitors:return jsonify({'error':'no events'}),404
    target=visitors[idx] if isinstance(idx,int) else visitors[-1]
    labels.append({'time':datetime.now().isoformat(),'event_time':target.get('time'),'label':label})
    target['trained_label']=label; db_save(); return jsonify({'success':True,'label':label,'event':target})

# SwitchBot
switchbot_bp=Blueprint('switchbot',__name__); sb_logger=logging.getLogger('tars.switchbot')
TOKEN=os.environ.get('SB_TOKEN',''); SECRET=os.environ.get('SB_SECRET',''); POLL_INTERVAL=int(os.environ.get('SB_POLL_INTERVAL','30')); SB_API='https://api.switch-bot.com/v1.1'; SB_DATA='/data/switchbot_v2.json'
device_list=[]; device_cache={}; cache_lock=threading.Lock(); NAMES={}; ALIASES={}; MOTION_SENSORS={}; LOCK_DEVICES={}; BLIND_DEVICES={}; FAN_DEVICES={}; CLIMATE_SENSORS={}; events_log=[]; door_history=[]; last_door_state=None; battery_trends={}; motion_reliability={}; sb_events=deque(maxlen=100)

def sb_load():
    global battery_trends,motion_reliability
    try:
        if os.path.exists(SB_DATA): d=json.load(open(SB_DATA)); battery_trends=d.get('battery_trends',{}); motion_reliability=d.get('motion_reliability',{})
    except: pass

def sb_save():
    try: json.dump({'battery_trends':battery_trends,'motion_reliability':motion_reliability,'saved':datetime.now().isoformat()},open(SB_DATA,'w'),indent=2)
    except: pass

def sb_headers():
    t=str(int(time.time()*1000)); nonce=str(uuid.uuid4()); sign=base64.b64encode(hmac.new(SECRET.encode(),f'{TOKEN}{t}{nonce}'.encode(),hashlib.sha256).digest()).decode(); return {'Authorization':TOKEN,'t':t,'sign':sign,'nonce':nonce,'Content-Type':'application/json'}
def sb_get(path):
    try:
        r=http.get(f'{SB_API}{path}',headers=sb_headers(),timeout=10); d=r.json();
        if d.get('statusCode')==100:return d.get('body',{})
    except Exception as e: sb_logger.error(e)
    return None
def sb_post(path,body):
    try:return http.post(f'{SB_API}{path}',headers=sb_headers(),json=body,timeout=10).json()
    except Exception as e:return {'statusCode':-1,'message':str(e)}
def fetch_devices():
    global device_list,NAMES,ALIASES,MOTION_SENSORS,LOCK_DEVICES,BLIND_DEVICES,FAN_DEVICES,CLIMATE_SENSORS
    data=sb_get('/devices');
    if not data:return []
    device_list=data.get('deviceList',[])
    for d in device_list:
        did=d['deviceId']; name=d.get('deviceName',did); dtype=d.get('deviceType',''); NAMES[did]=name; alias=name.lower().replace(' ','_').replace('(','').replace(')',''); ALIASES[alias]=did; ALIASES[did]=did
        if 'Motion' in dtype: MOTION_SENSORS[did]=name
        elif 'Lock' in dtype: LOCK_DEVICES[did]=name
        elif 'Roller' in dtype or 'Blind' in dtype or 'Curtain' in dtype: BLIND_DEVICES[did]=name
        elif 'Fan' in dtype or 'Circulator' in dtype: FAN_DEVICES[did]=name
        elif 'Meter' in dtype or 'Sensor' in dtype or 'WoIO' in dtype: CLIMATE_SENSORS[did]=name
    return device_list
def fetch_status(did):
    data=sb_get(f'/devices/{did}/status')
    if data:
        with cache_lock: device_cache[did]={'status':data,'timestamp':time.time(),'name':NAMES.get(did,did)}
    return data
def track_door():
    global last_door_state
    for did in LOCK_DEVICES:
        with cache_lock:c=device_cache.get(did,{}).get('status',{})
        door=c.get('doorState','unknown')
        if last_door_state is not None and door!=last_door_state: door_history.append({'time':datetime.now().isoformat(),'from':last_door_state,'to':door}); door_history[:]=door_history[-100:]
        last_door_state=door
def poll_loop():
    critical=list(MOTION_SENSORS.keys())+list(LOCK_DEVICES.keys())
    while True:
        for did in critical: fetch_status(did)
        track_door(); time.sleep(POLL_INTERVAL)
def sb_sse_thread():
    while True:
        try:
            r=http.get(f'{CORE_URL}/events/stream',stream=True,timeout=None)
            for event in sseclient.SSEClient(r).events():
                try: sb_events.append({'time':datetime.now().isoformat(),'event':json.loads(event.data).get('entity_id','')})
                except: pass
        except Exception as e: sb_logger.error(e)
        time.sleep(10)
def resolve_id(x): return ALIASES.get(x.lower().replace(' ','_'),x)
@switchbot_bp.route('/switchbot/health')
def sb_health(): return jsonify({'status':'ok','devices':len(device_list),'cached':len(device_cache),'poll_interval':POLL_INTERVAL})
@switchbot_bp.route('/switchbot/devices')
def sb_devices():
    if not device_list: fetch_devices()
    return jsonify([{'id':d['deviceId'],'name':d.get('deviceName',''),'type':d.get('deviceType','')} for d in device_list])
@switchbot_bp.route('/switchbot/motion')
def sb_motion():
    return jsonify({NAMES.get(did,did):device_cache.get(did,{}).get('status',{}) for did in MOTION_SENSORS})
@switchbot_bp.route('/switchbot/climate')
def sb_climate():
    results={}
    for did in CLIMATE_SENSORS: data=fetch_status(did) or {}; results[NAMES.get(did,did)]={'temperature':data.get('temperature'),'humidity':data.get('humidity'),'battery':data.get('battery'),'co2':data.get('CO2')}
    return jsonify(results)
@switchbot_bp.route('/switchbot/lock',methods=['POST','GET'])
def sb_lock():
    for did in LOCK_DEVICES:return jsonify(sb_post(f'/devices/{did}/commands',{'command':'lock','parameter':'default','commandType':'command'}))
    return jsonify({'error':'No lock'}),404
@switchbot_bp.route('/switchbot/unlock',methods=['POST','GET'])
def sb_unlock():
    for did in LOCK_DEVICES:return jsonify(sb_post(f'/devices/{did}/commands',{'command':'unlock','parameter':'default','commandType':'command'}))
    return jsonify({'error':'No lock'}),404
@switchbot_bp.route('/switchbot/blinds/<int:position>',methods=['POST','GET'])
def sb_blinds(position):
    if position<0 or position>100:return jsonify({'error':'Position 0-100'}),400
    return jsonify({NAMES.get(did,did):sb_post(f'/devices/{did}/commands',{'command':'setPosition','parameter':f'0,ff,{position}','commandType':'command'}) for did in BLIND_DEVICES})
@switchbot_bp.route('/switchbot/fan/<speed>',methods=['POST','GET'])
def sb_fan(speed):
    out={}
    for did in FAN_DEVICES:
        if speed.lower()=='off': cmd={'command':'turnOff','parameter':'default','commandType':'command'}
        elif speed.lower()=='on': cmd={'command':'turnOn','parameter':'default','commandType':'command'}
        else: cmd={'command':'setSpeed','parameter':str(int(speed)),'commandType':'command'}
        out[NAMES.get(did,did)]=sb_post(f'/devices/{did}/commands',cmd)
    return jsonify(out)
@switchbot_bp.route('/switchbot/door')
def sb_door():
    for did in LOCK_DEVICES:return jsonify(device_cache.get(did,{}).get('status',{}))
    return jsonify({'error':'No lock'}),404
@switchbot_bp.route('/switchbot/history')
def sb_history(): return jsonify(door_history[-20:])
@switchbot_bp.route('/switchbot/summary')
def sb_summary():
    out=[]
    for did,d in device_cache.items():
        out.append({'id':did,'name':d.get('name'),'age':round(time.time()-d.get('timestamp',0)),'keys':list((d.get('status') or {}).keys())[:6],'status':d.get('status')})
    return jsonify({'count':len(out),'devices':out})
@switchbot_bp.route('/switchbot/blinds/auto',methods=['POST','GET'])
def sb_blinds_auto():
    weather=ha_get('/states/weather.forecast_home') or {}; temp=(weather.get('attributes') or {}).get('temperature',72); sun=ha_get('/states/sun.sun') or {}; pos=20 if sun.get('state')=='above_horizon' and temp>78 else 70
    return jsonify({'success':True,'position':pos,'results':{NAMES.get(did,did):sb_post(f'/devices/{did}/commands',{'command':'setPosition','parameter':f'0,ff,{pos}','commandType':'command'}) for did in BLIND_DEVICES}})

# Vacuum
vacuum_bp=Blueprint('vacuum',__name__); vac_logger=logging.getLogger('tars.vacuum')
DEVICE_ID=os.environ.get('TUYA_DEVICE_ID',''); LOCAL_KEY=os.environ.get('TUYA_LOCAL_KEY',''); DEVICE_IP=os.environ.get('TUYA_DEVICE_IP',''); PROTOCOL=float(os.environ.get('TUYA_PROTOCOL','3.3')); AUTO_CLEAN_DAYS=int(os.environ.get('AUTO_CLEAN_DAYS','2')); SCHEDULE_FILE='/data/vacuum_schedule.json'; HISTORY_FILE='/data/cleaning_history.json'
WORK_STATUS={0:'standby',1:'cleaning',2:'paused',5:'returning',34:'docked'}; SUCTION_LEVELS=['Quiet','Standard','Turbo','Max']
last_status={}; status_lock=threading.Lock(); cleaning_history=[]; current_session=None; vac_events=deque(maxlen=100); vac_last_bedroom_motion=None; preferred_schedule={'time':'11:00'}

def vac_load():
    global cleaning_history,preferred_schedule
    try:
        if os.path.exists(HISTORY_FILE): cleaning_history=json.load(open(HISTORY_FILE))
    except: pass
    try:
        if os.path.exists(SCHEDULE_FILE): preferred_schedule=json.load(open(SCHEDULE_FILE))
    except: pass

def vac_save():
    try: json.dump(cleaning_history[-50:],open(HISTORY_FILE,'w'),indent=2)
    except: pass
    try: json.dump(preferred_schedule,open(SCHEDULE_FILE,'w'),indent=2)
    except: pass

def get_device():
    d=tinytuya.Device(DEVICE_ID,DEVICE_IP,LOCAL_KEY,version=PROTOCOL); d.set_socketTimeout(5); d.set_socketRetryLimit(2); return d
def get_status_data():
    try:
        d=get_device(); raw=d.status(); dps=raw.get('dps',{}); wc=dps.get('6',-1); data={'online':True,'state':WORK_STATUS.get(wc,f'unknown_{wc}'),'state_code':wc,'battery':dps.get('8',0),'suction':dps.get('158','?'),'water_level':dps.get('10','?'),'is_cleaning':wc==1,'is_docked':wc in [34,0],'timestamp':time.time(),'raw_dps':dps}
        with status_lock:last_status.update(data)
        return data
    except Exception as e:return {'online':False,'error':str(e),'timestamp':time.time()}
def days_since_last_clean():
    if not cleaning_history:return 999
    try:return (datetime.now()-datetime.fromisoformat(cleaning_history[-1].get('end',cleaning_history[-1].get('start')))).total_seconds()/86400
    except:return 999
def should_defer_vacuum():
    now=datetime.now()
    if now.hour>=9:return False
    if vac_last_bedroom_motion and (now-vac_last_bedroom_motion).total_seconds()/60<30:return True
    return is_bedroom_safe()
def is_cooper_here():
    try:
        r=http.get(f'{CORE_URL}/cooper',timeout=3)
        if r.status_code==200:return r.json().get('here',False)
    except: pass
    return False
def anyone_home():
    return (ha_get('/states/binary_sensor.iphone_presence') or {}).get('state')=='on'
def should_clean_now():
    h=datetime.now().hour; days=days_since_last_clean(); return {'should_clean':days>=AUTO_CLEAN_DAYS and not anyone_home() and 9<=h<=18 and not is_cooper_here(),'days_since_last':round(days,1),'home':anyone_home(),'hour':h,'cooper_here':is_cooper_here()}
def vac_handle_event(ev):
    global vac_last_bedroom_motion
    eid=ev.get('entity_id',''); new=ev.get('new_state',''); old=ev.get('old_state',''); action=None
    if 'bedroom' in eid and 'motion' in eid and new=='on': vac_last_bedroom_motion=datetime.now()
    if 'presence' in eid and new=='off' and old=='on':
        if is_cooper_here(): action='skip_cooper'
        elif should_defer_vacuum(): action='defer_sleeping'; ha_notify('\U0001f916 Vacuum Deferred','Sleeping safety triggered.')
        else:
            try:get_device().set_value(160,True); action='start_departure'
            except Exception as e: action=f'fail:{e}'
    if action: vac_events.append({'time':datetime.now().isoformat(),'event':eid,'action':action})
def vac_sse_thread():
    while True:
        try:
            r=http.get(f'{CORE_URL}/events/stream',stream=True,timeout=None)
            for event in sseclient.SSEClient(r).events():
                try: vac_handle_event(json.loads(event.data))
                except: pass
        except Exception as e: vac_logger.error(e)
        time.sleep(10)
def track_cleaning():
    global current_session
    while True:
        data=get_status_data(); state=data.get('state','unknown')
        if state=='cleaning' and current_session is None: current_session={'start':datetime.now().isoformat(),'battery_start':data.get('battery',0),'suction':data.get('suction','?')}
        elif state in ['docked','standby'] and current_session is not None:
            current_session['end']=datetime.now().isoformat(); current_session['battery_end']=data.get('battery',0); current_session['duration_min']=round((time.time()-datetime.fromisoformat(current_session['start']).timestamp())/60,1); cleaning_history.append(current_session); vac_save(); current_session=None
        time.sleep(30)
def vac_schedule_loop():
    while True:
        now=datetime.now().strftime('%H:%M')
        if preferred_schedule.get('time')==now:
            s=should_clean_now()
            if s['should_clean']:
                try:get_device().set_value(160,True); ha_notify('\U0001f916 Scheduled Vacuum','Scheduled cleaning started.')
                except: pass
            time.sleep(60)
        time.sleep(20)
@vacuum_bp.route('/vacuum/health')
def vac_health(): return jsonify({'status':'ok','device_id':DEVICE_ID,'sessions':len(cleaning_history),'days_since_last':round(days_since_last_clean(),1)})
@vacuum_bp.route('/vacuum/status')
def vac_status():
    with status_lock:
        if last_status and time.time()-last_status.get('timestamp',0)<15:return jsonify({**last_status,'source':'cache'})
    return jsonify({**get_status_data(),'source':'live'})
@vacuum_bp.route('/vacuum/history')
def vac_history(): return jsonify({'total_sessions':len(cleaning_history),'sessions':cleaning_history[-10:],'current_session':current_session})
@vacuum_bp.route('/vacuum/start',methods=['POST','GET'])
def vac_start():
    if should_defer_vacuum(): return jsonify({'success':False,'deferred':True,'reason':'bedroom motion + early hour'})
    try:get_device().set_value(160,True); return jsonify({'success':True})
    except Exception as e:return jsonify({'success':False,'error':str(e)}),500
@vacuum_bp.route('/vacuum/dock',methods=['POST','GET'])
def vac_dock():
    try:get_device().set_value(160,False); return jsonify({'success':True})
    except Exception as e:return jsonify({'success':False,'error':str(e)}),500
@vacuum_bp.route('/vacuum/suction/<level>',methods=['POST','GET'])
def vac_suction(level):
    m={'quiet':'Quiet','q':'Quiet','standard':'Standard','s':'Standard','turbo':'Turbo','t':'Turbo','max':'Max','m':'Max'}; target=m.get(level.lower(),level)
    if target not in SUCTION_LEVELS:return jsonify({'error':f'Use: {SUCTION_LEVELS}'}),400
    try:d=get_device(); d.set_value(158,target); return jsonify({'success':True,'suction':target})
    except Exception as e:return jsonify({'success':False,'error':str(e)}),500
@vacuum_bp.route('/vacuum/find',methods=['POST','GET'])
def vac_find():
    try:d=get_device(); d.set_value(159,False); time.sleep(1); d.set_value(159,True); return jsonify({'success':True})
    except Exception as e:return jsonify({'success':False,'error':str(e)}),500
@vacuum_bp.route('/vacuum/should_clean')
def vac_should_clean(): return jsonify(should_clean_now())
@vacuum_bp.route('/vacuum/schedule',methods=['POST'])
def vac_schedule():
    global preferred_schedule
    data=request.get_json(silent=True) or {}; t=data.get('time','').strip()
    if len(t)!=5 or ':' not in t:return jsonify({'error':'time must be HH:MM'}),400
    preferred_schedule={'time':t}; vac_save(); return jsonify({'success':True,'schedule':preferred_schedule})

app.register_blueprint(dj_bp); app.register_blueprint(hue_bp); app.register_blueprint(doorbell_bp); app.register_blueprint(switchbot_bp); app.register_blueprint(vacuum_bp)
@app.route('/')
def root(): return jsonify({'name':'TARS Services','version':'4.0.0','services':['dj','hue','doorbell','switchbot','vacuum'],'port':API_PORT})
@app.route('/health')
def root_health(): return jsonify({'status':'ok','version':'4.0.0','dj':{'plays':dj_stats.get('total_plays',0)},'hue':{'mode':hue_mode},'doorbell':{'visitors':len(visitors)},'switchbot':{'devices':len(device_list)},'vacuum':{'sessions':len(cleaning_history)}})
@app.route('/play',methods=['POST','GET'])
def compat_play(): return dj_play()
@app.route('/mood/<mood>',methods=['POST','GET'])
def compat_mood(mood): return dj_mood(mood)
@app.route('/kids',methods=['POST','GET'])
def compat_kids(): return dj_kids_on()
@app.route('/kids/off',methods=['POST','GET'])
def compat_kids_off(): return dj_kids_off()
@app.route('/like',methods=['POST','GET'])
def compat_like(): return dj_like()
@app.route('/skip',methods=['POST','GET'])
def compat_skip(): return dj_skip()
@app.route('/volume/<int:level>',methods=['POST','GET'])
def compat_volume(level): return dj_volume(level)
@app.route('/speaker/<entity>',methods=['POST','GET'])
def compat_speaker(entity): return dj_speaker(entity)
@app.route('/search/<query>')
def compat_search(query): return dj_search(query)
@app.route('/now-playing')
def compat_now_playing(): return dj_now_playing()
@app.route('/playlists')
def compat_playlists(): return dj_playlists()
@app.route('/stats')
def compat_stats(): return dj_stats_route()
@app.route('/recommend')
def compat_recommend(): return dj_recommend()
@app.route('/event-log')
def compat_event_log(): return dj_event_log()

if __name__=='__main__':
    logging.getLogger('tars').info(f'TARS Services v4.0.0 on :{API_PORT}')
    dj_load(); hue_load(); db_load(); sb_load(); vac_load(); fetch_devices()
    threading.Thread(target=dj_sse_thread,daemon=True).start(); threading.Thread(target=hue_sse_thread,daemon=True).start(); threading.Thread(target=hue_time_loop,daemon=True).start(); threading.Thread(target=db_sse_thread,daemon=True).start(); threading.Thread(target=poll_loop,daemon=True).start(); threading.Thread(target=sb_sse_thread,daemon=True).start(); threading.Thread(target=vac_sse_thread,daemon=True).start(); threading.Thread(target=track_cleaning,daemon=True).start(); threading.Thread(target=vac_schedule_loop,daemon=True).start()
    app.run(host='0.0.0.0',port=API_PORT,debug=False)
