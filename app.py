# from flask import Flask, render_template
# from flask_socketio import SocketIO
# import pytchat
# import threading
# import time
# import requests
# import re
# import os

from gevent import monkey
monkey.patch_all()

import os
from flask import Flask, render_template
from flask_socketio import SocketIO
import pytchat
import threading
import time
import requests
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
# socketio = SocketIO(app, cors_allowed_origins="*")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# Handle channel kamu
CHANNEL_HANDLE = "@aceanthem2"
STATUS_CHECK_INTERVAL = 10
CHAT_POLL_INTERVAL = 1
LIVE_RECHECK_INTERVAL = 5

def get_live_video_id(handle):
    """Mendeteksi Video ID live stream aktif (hanya jika benar-benar sedang live)."""
    url = f"https://www.youtube.com/{handle}/live"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        html = response.text

        # /live bisa tetap mengarah ke video lama. Pastikan benar-benar status live.
        is_live_now = False
        if '"isLiveNow":true' in html or '"isLive":true' in html:
            is_live_now = True

        if not is_live_now:
            return None

        # Cari pola videoId di dalam HTML live page YouTube
        match = re.search(r'\"videoId\":\"([a-zA-Z0-9_-]{11})\"', html)
        if match:
            return match.group(1)
        # Pola alternatif tag canonical link
        match_alt = re.search(r'\"canonical\" href=\"https://www.youtube.com/watch\?v=([a-zA-Z0-9_-]{11})\"', html)
        if match_alt:
            return match_alt.group(1)
    except Exception as e:
        print(f"[!] Gagal mengecek status channel: {e}")
    return None

def fetch_chat():
    is_live = False
    current_video_id = None
    chat = None
    last_live_check = 0.0

    while True:
        now = time.time()
        should_check_live = (not is_live) or ((now - last_live_check) >= LIVE_RECHECK_INTERVAL)
        latest_video_id = current_video_id

        if should_check_live:
            latest_video_id = get_live_video_id(CHANNEL_HANDLE)
            last_live_check = now

        if not is_live:
            print(f"[*] Mencari siaran langsung aktif untuk {CHANNEL_HANDLE}...")

            if not latest_video_id:
                print(f"[!] Belum ada live stream aktif yang terdeteksi. Mencoba lagi dalam {STATUS_CHECK_INTERVAL} detik...")
                time.sleep(STATUS_CHECK_INTERVAL)
                continue

            try:
                chat = pytchat.create(video_id=latest_video_id, interruptable=False)
                if not chat.is_alive():
                    raise RuntimeError("Live chat tidak aktif")

                print(f"[*] Live stream dimulai! Video ID: {latest_video_id}")
                socketio.emit('stream_status', {
                    "status": "started",
                    "video_id": latest_video_id,
                    "channel": CHANNEL_HANDLE,
                    "time": time.strftime('%Y-%m-%d %H:%M:%S')
                })

                current_video_id = latest_video_id
                is_live = True
            except Exception as e:
                print(f"[!] Gagal membuka live chat: {e}. Dianggap belum live, coba lagi...")
                time.sleep(STATUS_CHECK_INTERVAL)
            continue

        if latest_video_id != current_video_id:
            print("[!] Live stream berhenti atau berpindah video. Kembali memantau...")
            socketio.emit('stream_status', {
                "status": "stopped",
                "video_id": current_video_id,
                "channel": CHANNEL_HANDLE,
                "time": time.strftime('%Y-%m-%d %H:%M:%S')
            })

            is_live = False
            current_video_id = None
            chat = None
            time.sleep(STATUS_CHECK_INTERVAL)
            continue

        try:
            if not chat or not chat.is_alive():
                raise RuntimeError("Live chat tidak aktif")

            for c in chat.get().sync_items():
                formatted_message = ""
                for part in c.messageEx:
                    if isinstance(part, str):
                        formatted_message += part
                    elif isinstance(part, dict) and 'url' in part:
                        formatted_message += f'<img class="chat-emote" src="{part["url"]}" alt="emote" />'

                is_owner = getattr(c.author, 'isChatOwner', False)
                is_mod = getattr(c.author, 'isChatModerator', False)
                is_member = getattr(c.author, 'isChatSponsor', False) or bool(c.author.badgeUrl)

                role_color = "default"
                if is_owner:
                    role_color = "owner"
                elif is_mod:
                    role_color = "moderator"
                elif is_member:
                    role_color = "sponsor"

                data = {
                    "author": c.author.name,
                    "role_color": role_color,
                    "is_mod": is_mod,
                    "is_owner": is_owner,
                    "badge_url": c.author.badgeUrl,
                    "message": formatted_message,
                    "avatar": c.author.imageUrl,
                    "time": c.datetime
                }
                socketio.emit('new_chat', data)

            time.sleep(CHAT_POLL_INTERVAL)

        except Exception as e:
            print(f"[!] Terjadi error saat membaca chat: {e}. Menandai stream berhenti dan memantau ulang...")
            socketio.emit('stream_status', {
                "status": "stopped",
                "video_id": current_video_id,
                "channel": CHANNEL_HANDLE,
                "time": time.strftime('%Y-%m-%d %H:%M:%S')
            })
            is_live = False
            current_video_id = None
            chat = None
            time.sleep(STATUS_CHECK_INTERVAL)

@app.route('/')
def index():
    return render_template('index.html')

# if __name__ == '__main__':
#     threading.Thread(target=fetch_chat, daemon=True).start()
#     socketio.run(app, host='127.0.0.1', port=5000)

if __name__ == '__main__':
    threading.Thread(target=fetch_chat, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)