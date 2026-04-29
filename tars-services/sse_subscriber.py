"""TARS Services v5.0.0 — Core event stream subscriber.

Subscribes to Core's /events/stream SSE endpoint and reacts to HA events
in real-time, replacing HA automation middleware for common cases.

Reactions wired:
  - media_player.75_the_frame_3 ON    → auto-pause DJ
  - media_player.75_the_frame_3 OFF   → resume DJ if was paused by us
  - binary_sensor.iphone_presence OFF → close blinds, pause music
  - binary_sensor.iphone_presence ON  → welcome sequence (if calendar clear)
  - input_boolean.cooper_here ON      → Hue cooper preset + DJ kids mode
  - input_boolean.cooper_here OFF     → kids mode off
  - Any motion event                  → refresh our own state cache
  - weather change                    → react via weather handler

Reactor functions accept (old_state, new_state, entity_id, attrs) and are
registered in ENTITY_REACTORS. Extensible without touching the subscriber.
"""
import logging
import threading
import time
import json

logger = logging.getLogger('tars-services.sse')


class CoreSSESubscriber:
    """Background thread subscribing to Core's SSE event stream."""

    def __init__(self, core_url: str, reactors: dict, on_connect=None):
        self.core_url = core_url.rstrip('/')
        self.reactors = reactors
        self.on_connect = on_connect
        self.connected = False
        self.last_event_ts = None
        self.events_received = 0
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name='sse-subscriber')
        self._thread.start()
        logger.info(f'SSE subscriber started → {self.core_url}/events/stream')

    def stop(self):
        self._stop.set()

    def _run(self):
        import requests as http
        import sseclient
        backoff = 1
        while not self._stop.is_set():
            try:
                r = http.get(f'{self.core_url}/events/stream', stream=True, timeout=30)
                if r.status_code != 200:
                    logger.warning(f'SSE: HTTP {r.status_code}, retry in {backoff}s')
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                self.connected = True
                backoff = 1
                if self.on_connect:
                    try: self.on_connect()
                    except Exception as e: logger.error(f'on_connect: {e}')
                client = sseclient.SSEClient(r)
                for event in client.events():
                    if self._stop.is_set(): break
                    try:
                        data = json.loads(event.data) if event.data else {}
                        self.events_received += 1
                        self.last_event_ts = time.time()
                        self._dispatch(data)
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        logger.error(f'SSE dispatch error: {e}')
            except Exception as e:
                logger.warning(f'SSE stream broken: {e} — reconnecting in {backoff}s')
                self.connected = False
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _dispatch(self, ev: dict):
        """Route an event to matching reactors."""
        eid = ev.get('entity_id', '')
        if not eid: return
        old = ev.get('old_state', '')
        new = ev.get('new_state', '')
        attrs = ev.get('attributes', {})

        # Exact-match reactors
        exact = self.reactors.get(eid)
        if exact:
            for fn in exact if isinstance(exact, list) else [exact]:
                try: fn(old, new, eid, attrs)
                except Exception as e: logger.error(f'reactor {fn.__name__} on {eid}: {e}')

        # Prefix reactors (e.g. "binary_sensor.*_motion")
        for pattern, fns in self.reactors.items():
            if pattern.endswith('*') and eid.startswith(pattern[:-1]):
                for fn in fns if isinstance(fns, list) else [fns]:
                    try: fn(old, new, eid, attrs)
                    except Exception as e: logger.error(f'prefix reactor {fn.__name__} on {eid}: {e}')

    def status(self) -> dict:
        return {
            'connected': self.connected,
            'core_url': self.core_url,
            'events_received': self.events_received,
            'last_event_ago_sec': round(time.time() - self.last_event_ts) if self.last_event_ts else None,
        }
