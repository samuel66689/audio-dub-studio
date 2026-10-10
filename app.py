#!/usr/bin/env python3
"""Audio Dub Studio — ဗီဒီယိုထဲက စာသားပြောအပိုင်းတွေကို မြန်မာအသံနဲ့ အစားထိုးပေးတဲ့ tool.

RecapKit ရဲ့ Audio Dub feature ကို တစ်ယောက်စာသုံးဖို့ ပြန်ဆောက်ထားတာ။
Login မလို၊ ငွေမလို — ကိုယ့် Streamlit Cloud မှာ run တယ်။
API key တွေကို browser localStorage မှာ မှတ်ထားတယ် — တစ်ခါထည့်ရုံနဲ့
hard refresh ဆွဲလည်း မပျောက်ဘူး (server Secrets ရှိရင် အဲ့ဒါက အဓိက)။

Pipeline:
  1. MP4 တင် → ffmpeg နဲ့ audio ထုတ် (mp3 16k mono, 32k — Groq 25MB ကန့်သတ်ချက်နဲ့ကိုက်အောင်)
  2. Groq Whisper API (whisper-large-v3) နဲ့ စာသားထုတ် (timestamp ပါ)
     ※ အရင်က local faster-whisper သုံးတာ — Streamlit Cloud ရဲ့ RAM (~1GB)
       ကန့်သတ်ချက်နဲ့ မကိုက်လို့ Groq API နဲ့ လဲထားတာ
     ※ Groq က 403 IP-block ထိရင် AssemblyAI နဲ့ အလိုအလျောက် fallback
       (sidebar toggle + ကိုယ့် AssemblyAI key)
  2b. (optional) အပိုင်းသေးလေးတွေ အလိုအလျောက်ပေါင်း — Whisper ရဲ့ 0.2s လို
      အကွက်သေးတွေကြောင့် အသံအရမ်းမြန်ရတာကို ကာကွယ်ဖို့
  3. Gemini နဲ့ သဘာဝကျတဲ့ ပြောစကားမြန်မာလို ဘာသာပြန်
  4. ပြန်စစ်ပြီး ပြင်လို့ရ (တစ်ကြောင်းချင်း)
  5. edge-tts (my-MM-ThihaNeural) နဲ့ အသံထုတ် → အချိန်ကွက်အတိုင်း ချုံ့/ဖြန့်
  5b. (optional) အချိန်ကွက်ထဲ မဝင်တဲ့လိုင်း → Gemini နဲ့ အလိုအလျောက်တိုအောင်ပြင်
      → အသံပြန်ထုတ် (တစ်ကြိမ်သာ)
  6. ဗီဒီယိုအသစ်နဲ့ ပေါင်း → MP4 download + SRT download

🎬 Recap Studio (sidebar toggle):
  3b. Recap စတိုင်ဘာသာပြန် — စာကြောင်းတိုင်းဘာသာပြန်တာအစား movie recap
      narrator ပြောသလို သဘာဝကျတဲ့ ပြောစကားမြန်မာလို ပြန်ရေး
  6b. Recap render — အသံကို slot ထဲ အတင်းမထည့်ဘဲ သဘာဝအတိုင်းထား,
      video အပိုင်းတစ်ခုချင်းစီကို narration အရှည်နဲ့ကိုက်အောင် setpts နဲ့
      အမြန်/အနှေးချိန် (slow-mo/fast-mo) → dub audio နဲ့ mux

🎙️ Narrator mode (ဗီဒီယိုမုဒ်သာ):
  3'. ffmpeg scene detection → scene တစ်ခုချင်း frame ထုတ် →
     Gemini vision က scene ဖော်ပြချက် → Gemini က third-person မြန်မာ
     narrator script ရေး (scene အလိုက်, အချိန်နဲ့ကိုက်အောင်) →
     S.translations ထဲ ထည့် → အဆင့် ၄/၅/၆ အဟောင်းအတိုင်း ဆက်

Run:  streamlit run app.py
"""
import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_TTS = os.path.join(APP_DIR, "cache_tts")
WORK_DIR = os.path.join(APP_DIR, "work")
os.makedirs(CACHE_TTS, exist_ok=True)
os.makedirs(WORK_DIR, exist_ok=True)

# ---------------------------------------------------------- 🕷️ Spider-Man theme
_SPIDEY_CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Bangers&display=swap');

/* --- နောက်ခံ: ညမှောင် + spider web --- */
.stApp {
    background-color: #0A0A14;
    background-image:
        url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='260' height='260' viewBox='0 0 260 260'%3E%3Cg fill='none' stroke='%23E62429' stroke-opacity='0.06'%3E%3Ccircle cx='260' cy='0' r='55'/%3E%3Ccircle cx='260' cy='0' r='105'/%3E%3Ccircle cx='260' cy='0' r='155'/%3E%3Ccircle cx='260' cy='0' r='205'/%3E%3Cpath d='M260 0 L0 260 M260 0 L90 260 M260 0 L175 260 M260 0 L260 260 M260 0 L0 175 M260 0 L0 90'/%3E%3C/g%3E%3C/svg%3E"),
        radial-gradient(1000px 480px at 88% -5%, rgba(230,36,41,.12), transparent 60%),
        radial-gradient(820px 520px at 4% 108%, rgba(43,92,230,.12), transparent 60%);
    background-repeat: no-repeat;
    background-position: top right;
}

/* --- hero --- */
.spidey-hero { text-align: center; padding: 20px 0 4px; }
.spidey-kicker { color: #8A93B8; font-size: .78rem; letter-spacing: 3px; font-weight: 700; }
.spidey-title {
    font-family: 'Bangers', 'Arial Black', sans-serif;
    font-size: 3.2rem; letter-spacing: 3px; color: #F03A3A;
    -webkit-text-stroke: 1.5px #5d0a0d;
    text-shadow: 3px 3px 0 #1D4ED8, 7px 7px 0 rgba(0,0,0,.55), 0 0 34px rgba(230,36,41,.55);
    transform: rotate(-1.5deg); margin: 2px 0;
}
.spidey-sub { color: #B9C4E8; font-size: 1rem; margin-top: 8px; }
@media (max-width: 640px){ .spidey-title{ font-size: 2.2rem; } }

/* --- အဆင့်ခြေရာ (step tracker) --- */
.spidey-steps { display: flex; gap: 8px; margin: 16px 0 6px; flex-wrap: wrap; }
.spidey-step { flex: 1 1 0; min-width: 96px; text-align: center; padding: 9px 4px;
    border-radius: 14px; font-size: .8rem; font-weight: 700;
    background: rgba(255,255,255,.045); border: 1px solid rgba(255,255,255,.13); color: #9AA0BC; }
.spidey-step .n { display: block; font-size: 1.1rem; margin-bottom: 2px; }
.spidey-step.done { background: rgba(230,36,41,.16); border-color: rgba(230,36,41,.7); color: #FFB4B6; }
.spidey-step.current { background: linear-gradient(135deg,#E62429,#9E1116); color: #fff;
    border-color: #FF7A7A; box-shadow: 0 0 18px rgba(230,36,41,.65); }
.spidey-step.skip { opacity: .4; }

/* --- ကတ် (st.container(border=True) အစစ် — အထဲမှာ content တကယ်ရှိတယ်) --- */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: rgba(18,18,36,.78);
    border: 1px solid rgba(230,36,41,.30) !important;
    border-radius: 18px;
    box-shadow: 0 8px 28px rgba(0,0,0,.5);
}
.spidey-stephead {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 16px; margin-bottom: 6px;
    background: linear-gradient(90deg, rgba(230,36,41,.25), rgba(43,92,230,.14));
    border: 1px solid rgba(230,36,41,.28);
    border-radius: 12px;
    font-size: 1.12rem; font-weight: 800; color: #fff;
}
.spidey-num { width: 34px; height: 34px; border-radius: 50%; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    background: linear-gradient(135deg,#F03A3A,#8f1013); color: #fff;
    font-weight: 800; font-size: 1.05rem; box-shadow: 0 0 14px rgba(230,36,41,.8); }

/* --- ခလုတ် --- */
div[data-testid*="stBaseButton-primary"] > button, .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #F03A3A, #A50F14) !important;
    color: #fff !important; border: none !important; border-radius: 12px !important;
    font-weight: 800 !important; letter-spacing: .3px;
    box-shadow: 0 4px 20px rgba(230,36,41,.5) !important;
}
div[data-testid*="stBaseButton-primary"] > button:hover, .stButton > button[kind="primary"]:hover {
    box-shadow: 0 6px 28px rgba(230,36,41,.85) !important;
    transform: translateY(-1px); color: #fff !important;
}
.stButton > button[kind="secondary"], div[data-testid*="stBaseButton-secondary"] > button {
    border: 1px solid rgba(80,120,255,.55) !important; border-radius: 12px !important;
    background: rgba(43,92,230,.10) !important; color: #C9D6FF !important; font-weight: 700 !important;
}
.stButton > button[kind="secondary"]:hover, div[data-testid*="stBaseButton-secondary"] > button:hover {
    background: rgba(43,92,230,.22) !important; color: #fff !important;
    box-shadow: 0 0 16px rgba(43,92,230,.45) !important; border-color: #7FA2FF !important;
}

/* --- sidebar --- */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #160709 0%, #0A0A14 70%) !important;
    border-right: 1px solid rgba(230,36,41,.32);
}
section[data-testid="stSidebar"] h3 { border-left: 4px solid #E62429; padding-left: 10px !important; }
section[data-testid="stSidebar"] h4 { color: #FF8A8D !important; }

/* --- တခြား --- */
div[data-testid="stExpander"] { border: 1px solid rgba(230,36,41,.32); border-radius: 14px;
    background: rgba(230,36,41,.05); }
div[data-testid="stFileUploader"] { border: 1.5px dashed rgba(230,36,41,.55); border-radius: 16px;
    background: rgba(230,36,41,.05); padding: 10px; }
div[data-testid="stTextInput"] input:focus, div[data-testid="stTextArea"] textarea:focus {
    border-color: #E62429 !important;
    box-shadow: 0 0 0 1px #E62429, 0 0 14px rgba(230,36,41,.4) !important; }
div[data-testid="stProgress"] > div > div { box-shadow: 0 0 12px rgba(230,36,41,.8); }
.spidey-dl-label { font-weight: 800; color: #FFB4B6; margin: 6px 0 10px; font-size: 1rem; }
.spidey-foot { text-align: center; color: #5A6080; font-size: .8rem; padding: 20px 0 8px; }
</style>"""


_card_ctx_stack = []


def _spidey_card_open(n, title):
    import streamlit as st
    # open/close ကို function နှစ်ခုနဲ့ ခွဲထားလို့ container ရဲ့
    # __enter__/__exit__ ကို ကိုယ်တိုင် မောင်းတာ — `with st.container():` နဲ့ အတူတူပဲ။
    # (ကြားထဲမှာ st.rerun/st.stop ဖြစ်ရင် run ပြတ်သွားမယ် — run အသစ်မှာ
    #  Streamlit က context_dg_stack ကို အစက ပြန် reset လုပ်ပြီးသားမို့
    #  ဒီမှာ ကျန်နေတဲ့ အဟောင်း ctx ကို လွှတ်ပစ်လိုက်ရုံပဲ)
    if _card_ctx_stack:
        _card_ctx_stack.clear()
    ctx = st.container(border=True)
    ctx.__enter__()
    _card_ctx_stack.append(ctx)
    st.markdown(
        f'<div class="spidey-stephead"><span class="spidey-num">{n}</span>'
        f"<span>{title}</span></div>",
        unsafe_allow_html=True,
    )


def _spidey_card_close():
    ctx = _card_ctx_stack.pop()
    ctx.__exit__(None, None, None)


def _spidey_steps(S, is_video, narr=False):
    """Wizard nav — horizontal stepper (number + status icon), နှိပ်ပြီး ကူးလို့ရ."""
    import streamlit as st
    # ဖုန်း narrow screen မှာ Streamlit က columns တွေကို vertical ပြိုချပစ်တယ် —
    # ၆ ကောလံ stepper ကို တစ်တန်းတည်း ဘေးတိုက်ထိန်းဖို့ CSS
    st.markdown(
        """<style>
div[data-testid="stHorizontalBlock"]:has(> :nth-child(6):last-child) {
    flex-wrap: nowrap !important;
    gap: 0.25rem !important;
}
div[data-testid="stHorizontalBlock"]:has(> :nth-child(6):last-child) > div {
    min-width: 0 !important;
}
div[data-testid="stHorizontalBlock"]:has(> :nth-child(6):last-child) button {
    padding-left: 0.2rem !important;
    padding-right: 0.2rem !important;
}
/* wizard bottom nav: ခလုတ် ၂ ခု ဘေးချင်းကပ် (marker က ပထမကော်လံထဲ) */
.wiz-bnav-col { display: none; }
/* marker ရဲ့ ကိုယ်ပိုင်အခွံ (stElementContainer) ကိုပဲ layout ကနေ ဖယ် —
   element container တွေက nest မဖြစ်လို့ ဒီ rule က nav row ကို လုံးဝ မထိဘူး */
div[data-testid="stElementContainer"]:has(.wiz-bnav-col) { display: none; }
div[data-testid="stHorizontalBlock"]:has(.wiz-bnav-col) {
    flex-wrap: nowrap !important;
    gap: 0.5rem !important;
}
div[data-testid="stHorizontalBlock"]:has(.wiz-bnav-col) > div {
    min-width: 0 !important;
}
</style>""",
        unsafe_allow_html=True,
    )
    has_out = bool(
        (S.out_mp4 and os.path.isfile(S.out_mp4))
        or (S.out_mp3 and os.path.isfile(S.out_mp3))
    )
    done = [
        bool(S.video_path) if is_video else bool(S.src_segments),
        bool(S.src_segments),
        bool(S.translations),
        bool(S.final_segments),
        bool(S.fitted),
        has_out,
    ]
    cur = max(1, min(6, int(S.get("wizard_step", 1))))
    S["wizard_step"] = cur  # clamp
    cols = st.columns(6)
    for i, col in enumerate(cols):
        icon = ("✅" if done[i] else
                "⏭️" if i == 1 and not is_video else
                "🔴" if i + 1 == cur else "⭕")
        with col:
            if st.button(f"{i + 1}{icon}", key=f"wiz_nav_{i}",
                         type="primary" if i + 1 == cur else "secondary",
                         use_container_width=True,
                         disabled=(i + 1 == cur)):
                S["wizard_step"] = i + 1
                st.rerun()

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3"  # turbo က CJK hallucination (Korean မှားရေး + စာသားထပ်) များလို့ full model ပြောင်း — sub-translator နည်းတူ (2026-10-08)
# Whisper က ဘာသာစကား auto-detect မှားတတ်လို့ (ဥပမာ English ကို Tamil လို့ ထင်တာ)
# သုံးသူ တိတိကျကျ ရွေးနိုင်အောင် — (ပြသမယ့်အမည်, Whisper code)
_SRC_LANGS = [
    ("🤖 Auto (အလိုအလျောက်)", None),
    ("🇬🇧 English", "en"),
    ("🇰🇷 Korean", "ko"),
    ("🇯🇵 Japanese", "ja"),
    ("🇨🇳 Chinese", "zh"),
    ("🇹🇭 Thai", "th"),
    ("🇻🇳 Vietnamese", "vi"),
    ("🇮🇩 Indonesian", "id"),
    ("🇪🇸 Spanish", "es"),
    ("🇫🇷 French", "fr"),
    ("🇩🇪 German", "de"),
    ("🇷🇺 Russian", "ru"),
    ("🇮🇳 Hindi", "hi"),
]
GEMINI_MODEL_DEFAULT = "gemini-3.5-flash-lite"   # Script-writer / sub-translator မှာ အလုပ်ဖြစ်နေတဲ့ model
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
VOICE_MALE = "my-MM-ThihaNeural"
VOICE_FEMALE = "my-MM-NilarNeural"


# ------------------------------------------------------------------ helpers
def run(cmd):
    """ffmpeg/ffprobe စတာတွေ run ဖို့ (stderr ဖွက်)."""
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def dur(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def fmt_ts(sec):
    total_ms = max(0, int(round(sec * 1000)))
    h, rem = divmod(total_ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_ts(s):
    s = s.strip().replace(",", ".")
    parts = s.split(":")
    if len(parts) == 3:
        h, m, sec = parts
        return int(h) * 3600 + int(m) * 60 + float(sec)
    m, sec = parts
    return int(m) * 60 + float(sec)


def silence(path, seconds, sr=24000):
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "anullsrc=r=24000:cl=mono", "-t", f"{seconds:.3f}",
         "-ar", str(sr), path])


# ------------------------------------------------------- step 2: transcribe
def transcribe_audio(audio_path, api_key, language=None, on_chunk=None):
    """Groq Whisper API နဲ့ transcribe လုပ် → {'language':..., 'segments':[{'start','end','text'}]}.

    language: Whisper ISO code (ဥပမာ "en") — ပေးရင် auto-detect မလုပ်ဘဲ
    အဲ့ဘာသာစကားအတိုင်း နားထောင်မယ်။ None ဆို auto-detect (အရင်အတိုင်း)။

    sub-translator မှာ အလုပ်ဖြစ်နေတဲ့ request ပုံစံအတိုင်း
    (whisper-large-v3, verbose_json) — Streamlit Cloud RAM ကန့်သတ်ချက်ကြောင့်
    local faster-whisper အစား ဒီ API ကို သုံးထားတာ။

    အသံ 20MB ကျော်ရင် (အပိုင်းရှည်) အပိုင်းခွဲနားထောင်ပြီး ပြန်ဆက်တယ် —
    on_chunk(i, n) ကို အပိုင်းတိုင်းပြီးတိုင်း ခေါ်တယ်။
    """
    import requests  # local import
    size = os.path.getsize(audio_path)
    if size > 20 * 1024 * 1024:
        return _transcribe_chunked(audio_path, api_key, language, on_chunk)
    return _transcribe_single(audio_path, api_key, language)


def _transcribe_single(audio_path, api_key, language=None):
    """ဖိုင်တစ်ခုတည်း Groq ကို ပို့ (20MB အောက်)."""
    import requests  # local import
    with open(audio_path, "rb") as f:
        data = f.read()
    files = {"file": (os.path.basename(audio_path), data, "audio/mpeg")}
    form = {"model": GROQ_MODEL, "response_format": "verbose_json"}
    if language:
        form["language"] = language
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        r = requests.post(GROQ_URL, headers=headers, files=files,
                          data=form, timeout=300)
    except Exception:
        raise RuntimeError("Groq transcription timed out — network စစ်ပြီး ပြန်ကြိုးစားပါ")
    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message") or f"Groq Error ({r.status_code})"
        except Exception:
            msg = f"Groq Error ({r.status_code})"
        # 403 = Groq firewall က IP block (key မစစ်ခင်) — key ပြဿနာမဟုတ်
        raise RuntimeError(f"စာသားထုတ်တာ ပျက်သွားတယ် (Groq HTTP {r.status_code}): {msg}")
    body = r.json()
    segs = []
    for s in (body.get("segments") or []):
        if not isinstance(s, dict):
            continue
        text = (s.get("text") or "").strip()
        if not text:
            continue
        segs.append({"start": float(s.get("start") or 0),
                     "end": float(s.get("end") or 0), "text": text})
    return {"language": body.get("language", ""), "segments": segs}


def _transcribe_chunked(audio_path, api_key, language=None, on_chunk=None):
    """အသံရှည် (>20MB) ကို ~12MB အပိုင်းတွေ ခွဲ → တစ်ခုချင်း Groq → timestamp ပြန်ဆက်.

    sub-translator ရဲ့ _transcribe_chunked ပုံစံ (port) + အပိုင်းဆက်နေရာ
    (+1s overlap) မှာ စာသားထပ်နေတာ ဖယ်တယ်။
    """
    total = dur(audio_path) or 0
    CHUNK_SEC = 3000.0  # 32kbps mono → ~12MB/ခု (Groq 25MB အောက် safe)
    n = max(2, int(total // CHUNK_SEC) + 1)
    step = total / n
    tmpdir = os.path.dirname(audio_path)
    all_segs, lang = [], ""
    for i in range(n):
        start = i * step
        chunk = os.path.join(tmpdir, f"_tchunk{i}.mp3")
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}",
             "-t", f"{step + 1:.2f}", "-i", audio_path, "-c", "copy", chunk])
        try:
            data = _transcribe_single(chunk, api_key, language)
        finally:
            if os.path.isfile(chunk):
                os.remove(chunk)
        if i == 0:
            lang = data.get("language", "")
        if on_chunk:
            on_chunk(i + 1, n)
        for s in data.get("segments", []):
            s = dict(s)
            s["start"] = float(s.get("start") or 0) + start
            s["end"] = float(s.get("end") or 0) + start
            all_segs.append(s)
    all_segs.sort(key=lambda s: s["start"])
    # overlap ကြောင့် အပိုင်းဆက်မှာ စာသားအတူတူ ထပ်ပါတာ ဖယ်
    deduped = []
    for s in all_segs:
        if (deduped and abs(s["start"] - deduped[-1]["start"]) < 0.5
                and s["text"] == deduped[-1]["text"]):
            continue
        deduped.append(s)
    return {"language": lang, "segments": deduped}


# ------------------------------------------------- step 2b: AssemblyAI fallback
# Groq (whisper-large-v3) က 403 IP-block ထိတဲ့အခါ သုံးတဲ့ fallback.
# အဆင့်တွေ: file upload → transcript request → poll → words → segments.
_AAI_BASE = "https://api.assemblyai.com/v2"


def _aai_words_to_segments(words, max_gap=0.7, max_dur=8.0, max_words=25):
    """AssemblyAI words (ms timestamps) → [{'start','end','text'}] စာပိုဒ်တွေ.

    စည်း: စကားရပ်တဲ့နေရာ (gap ကြီး) / စာကြောင်းရှည်လွန်း / စကားစုပြီးတဲ့နေရာ
    (.!?) မှာ ဖြတ် — Whisper segment တွေနဲ့ ပုံစံတူအောင်.
    """
    segs, cur, cur_start = [], [], None
    for w in words:
        text = (w.get("text") or "").strip()
        if not text:
            continue
        s, e = w.get("start", 0) / 1000.0, w.get("end", 0) / 1000.0
        if cur and cur_start is not None:
            gap = s - cur[-1][1]
            dur = e - cur_start
            if gap > max_gap or dur > max_dur or len(cur) >= max_words \
                    or cur[-1][2][-1:] in ".!?":
                segs.append({"start": cur_start, "end": cur[-1][1],
                             "text": " ".join(t for _, _, t in cur)})
                cur, cur_start = [], None
        if cur_start is None:
            cur_start = s
        cur.append((s, e, text))
    if cur:
        segs.append({"start": cur_start, "end": cur[-1][1],
                     "text": " ".join(t for _, _, t in cur)})
    return [sg for sg in segs if sg["end"] > sg["start"] and sg["text"]]


def transcribe_assemblyai(audio_path, api_key, language=None, progress_cb=None,
                          poll_interval=3.0, timeout=900):
    """AssemblyAI နဲ့ transcribe → {'language':..., 'segments':[...]}.

    language: ISO code (ဥပမာ "en") — None ဆို auto-detect.
    """
    import requests  # local import
    import time

    def _h(json_ct=False):
        h = {"authorization": api_key}
        if json_ct:
            h["content-type"] = "application/json"
        return h

    # 1. file upload
    try:
        with open(audio_path, "rb") as f:
            r = requests.post(f"{_AAI_BASE}/upload", headers=_h(), data=f,
                              timeout=300)
    except Exception:
        raise RuntimeError("AssemblyAI: ဖိုင်တင်တာ ပျက်သွားတယ် — network စစ်ပြီး ပြန်ကြိုးစားပါ")
    if r.status_code != 200:
        raise RuntimeError(f"AssemblyAI upload ပျက်သွားတယ် (HTTP {r.status_code})")
    upload_url = r.json().get("upload_url")
    if not upload_url:
        raise RuntimeError("AssemblyAI upload: upload_url ပြန်မရဘူး")
    # 2. transcript request
    # (2026-10: speech_model (singular) deprecated → speech_models list သုံး)
    payload = {"audio_url": upload_url, "speech_models": ["universal-2"]}
    if language:
        payload["language_code"] = language
    else:
        payload["language_detection"] = True
    try:
        r = requests.post(f"{_AAI_BASE}/transcript", headers=_h(True),
                          json=payload, timeout=60)
    except Exception:
        raise RuntimeError("AssemblyAI: transcript တောင်းတာ ပျက်သွားတယ် — network စစ်ပါ")
    if r.status_code != 200:
        try:
            msg = r.json().get("error") or f"HTTP {r.status_code}"
        except Exception:
            msg = f"HTTP {r.status_code}"
        raise RuntimeError(f"AssemblyAI transcript ပျက်သွားတယ်: {msg}")
    tid = r.json().get("id")
    if not tid:
        raise RuntimeError("AssemblyAI: transcript id ပြန်မရဘူး")
    # 3. poll (ဗီဒီယိုရှည်ရင် မိနစ်ပိုင်းကြာနိုင်တယ်)
    waited = 0.0
    while True:
        try:
            r = requests.get(f"{_AAI_BASE}/transcript/{tid}", headers=_h(),
                             timeout=30)
        except Exception:
            raise RuntimeError("AssemblyAI: အခြေအနေမေးတာ ပျက်သွားတယ် — network စစ်ပါ")
        if r.status_code != 200:
            raise RuntimeError(f"AssemblyAI status ပျက်သွားတယ် (HTTP {r.status_code})")
        body = r.json()
        status = body.get("status")
        if status == "completed":
            segs = _aai_words_to_segments(body.get("words") or [])
            return {"language": body.get("language_code", ""), "segments": segs}
        if status == "error":
            raise RuntimeError(
                f"AssemblyAI transcribe ပျက်သွားတယ်: {body.get('error') or 'unknown'}")
        if waited >= timeout:
            raise RuntimeError("AssemblyAI: အချိန်ကုန်သွားတယ် — ပြန်ကြိုးစားပါ")
        time.sleep(poll_interval)
        waited += poll_interval
        if progress_cb:
            progress_cb(waited)


def transcribe_with_fallback(audio_path, groq_key=None, assembly_key=None,
                             language=None, on_note=None, on_chunk=None):
    """Groq အရင်ကြိုး → ပျက်ရင် AssemblyAI (key ရှိရင်).

    Returns: (data, provider) — provider: "groq" | "assemblyai".
    နှစ်ခုလုံးမရရင် နောက်ဆုံး error ကို raise လုပ်တယ်.
    on_chunk(i, n): အသံရှည်လို့ အပိုင်းခွဲနားထောင်တဲ့အခါ progress.
    """
    last_err = None
    if groq_key:
        try:
            return transcribe_audio(audio_path, groq_key, language, on_chunk), "groq"
        except Exception as e:
            last_err = e
            if on_note:
                on_note(f"Groq မရဘူး — AssemblyAI နဲ့ ဆက်လုပ်မယ်…")
    if assembly_key:
        def _cb(w):
            if on_note:
                on_note(f"AssemblyAI နားထောင်နေတယ်… ({w:.0f} စက္ကန့်)")
        data = transcribe_assemblyai(audio_path, assembly_key, language,
                                     progress_cb=_cb)
        return data, "assemblyai"
    if last_err is not None:
        raise last_err
    raise RuntimeError("Groq / AssemblyAI key တစ်ခုခု ထည့်မှ စာသားထုတ်လို့ရမယ် (ဘယ်ဘက် sidebar)။")


# ------------------------------------------------------- step 3: translate
# Gemini က တခါတလေ Tamil/Devanagari လို တခြား script တွေ ညှပ်ထုတ်တတ်လို့ —
# စာထုတ် prompt တိုင်းမှာ မြန်မာ Unicode သက်သက် သုံးဖို့ အတိအကျမှာထားတယ်
_MYANMAR_ONLY = (
    " Write every 'text' value ONLY in Myanmar (Burmese) Unicode script — "
    "never mix in Tamil, Devanagari/Hindi, Thai, Chinese, Korean, Japanese, "
    "or any other non-Myanmar script, not even for names."
)

# လူ့လက်ရာနဲ့တူအောင်: AI ပြန်မှန်းသိသာစေတဲ့ အချက်တွေ ဖြေရှင်း
_HUMAN_STYLE = (
    " Write like a veteran human subtitler, NOT a translation machine. "
    "Translate MEANING, never mirror the source sentence structure \u2014 rebuild each line "
    "the way a Burmese person would actually say it out loud. One idea per line, short "
    "and speakable; cut filler the viewer can already see on screen. "
    "Match the register to each character's relationship and keep it consistent for the "
    "whole video: close friends / lovers / family \u2192 casual (ငါ/နင်); strangers, elders, "
    "bosses \u2192 polite (ကျွန်တော်/ခင်ဗျား). "
    "BANNED stiff formal connectors: ထို့ကြောင့်, သို့သော်လည်း, ထို့နောက်, ထို့အပြင် \u2014 "
    "use conversational ones instead (ဒါကြောင့်, ဒါပေမဲ့, ပြီးတော့). "
    "Localize idioms, jokes and slang into natural Burmese equivalents \u2014 never translate "
    "them literally. No em-dashes, no explanatory padding. "
    "FINAL CHECK: read each line aloud in your head \u2014 if no real Burmese speaker would say "
    "it like that, rewrite it until it sounds human. "
    "TTS READABILITY: write every number as spoken Burmese words (TTS misreads bare digits); "
    "strip [Music], (laughs) and all sound-effect / stage-direction tags \u2014 never read them aloud; "
    "use ကျွန်တော် for a male speaker and ကျွန်မ for a female speaker; "
    "keep each character's honorifics (ဦး/ဒေါ်/ကို/မ) consistent through the whole video."
)

_TRANSLATE_SYS = (
    "You translate video subtitle lines for Myanmar voiceover dubbing. "
    "Translate each line into natural SPOKEN Burmese (Myanmar) — the way a narrator "
    "would say it out loud, not formal written style. Keep the meaning, keep it "
    "concise (it must fit the original speaking time). Do not add explanations. "
    "Return ONLY a JSON array of objects with keys 'id' and 'text'."
    + _MYANMAR_ONLY + _HUMAN_STYLE
)

# 🎬 Recap Studio: စာကြောင်းတိုင်းဘာသာပြန်တာအစား recap narrator ပြောသလို ပြန်ရေး
_RECAP_SYS = (
    "You rewrite video subtitle lines as a Myanmar movie-recap narrator would SAY them. "
    "For each line, RETELL it in natural SPOKEN Burmese (Myanmar) in third-person "
    "movie-recap narration style — like those gripping recap channels: SHORT punchy "
    "sentences, one story beat per sentence, plain and dramatic, never a literal "
    "word-for-word translation. Refer to characters by role ('the delivery man', "
    "'the woman', 'the old man') instead of bare pronouns. Keep the original meaning "
    "of each line, keep every line self-contained, and keep it concise enough to be "
    "spoken aloud. Do not add explanations. "
    "Return ONLY a JSON array of objects with keys 'id' and 'text'."
    + _MYANMAR_ONLY + _HUMAN_STYLE
)


def _gemini_call(api_key, model_id, system_text, payload_text):
    import requests  # local import: requests မရှိရင် ဒီ step မှပဲ error တက်
    url = f"{GEMINI_BASE}{model_id}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": [{"text": payload_text}]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "temperature": 0.3, "maxOutputTokens": 8192},
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    last_err, retry_after = None, 0.0
    for attempt in range(3):  # 429/5xx → exponential backoff နဲ့ ၃ ကြိမ်အထိ
        try:
            r = requests.post(url, headers=headers, json=body, timeout=120)
        except Exception as e:
            last_err = RuntimeError(f"Gemini request failed: {e}")
            retry_after = 0.0
        else:
            if r.status_code == 200:
                break
            if r.status_code in (429, 500, 502, 503):
                last_err = RuntimeError(f"Gemini error {r.status_code}: {r.text[:300]}")
                try:
                    retry_after = float(r.headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    retry_after = 0.0
            else:
                raise RuntimeError(f"Gemini error {r.status_code}: {r.text[:300]}")
        if attempt < 2:
            time.sleep(max(4.0 * (2 ** attempt), retry_after))
    else:
        raise last_err
    data = r.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        txt = "".join(p.get("text", "") for p in parts
                      if isinstance(p, dict) and isinstance(p.get("text"), str))
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Gemini က မျှော်လင့်မထားတဲ့ response ပြန်တယ်")
    if not txt.strip():
        raise RuntimeError("Gemini က မျှော်လင့်မထားတဲ့ response ပြန်တယ်")
    txt = txt.strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(?:json)?\s*", "", txt)
        txt = re.sub(r"\s*```$", "", txt)
    return json.loads(txt.strip())


def parse_glossary(raw):
    """sidebar glossary box → [(foreign, burmese), ...].

    ပုံစံ: တစ်ကြောင်းတစ်ခု၊ `John=ဂျွန်` — `=` မပါတာ/လွတ်နေတာတွေ ကျော်။
    """
    pairs = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        a, b = line.split("=", 1)
        a, b = a.strip(), b.strip()
        if a and b:
            pairs.append((a, b))
    return pairs


def _glossary_prompt(pairs):
    if not pairs:
        return ""
    lines = "\n".join(f"- {a} → {b}" for a, b in pairs)
    return ("\nGlossary — ALWAYS use these exact Burmese forms for the "
            f"names/terms below, do not transliterate them differently:\n{lines}\n")


def gemini_translate(api_key, segments, model_id, progress_cb=None, glossary=None,
                   recap=False, story_memory=None):
    """segments: [{'start','end','text'}] → [{'start','end','src','text'}].

    ပြန်မရတဲ့ အပိုင်းတွေက မူရင်းစာသားအတိုင်း ကျန်ပြီး failed_ids မှာ မှတ်ထားတယ်။
    recap=True ဆို စာကြောင်းတိုင်းဘာသာပြန်တာအစား recap narrator စတိုင်နဲ့ ပြန်ရေးတယ်။
    story_memory: build_story_memory/update_story_memory ရဲ့ dict — ဇာတ်ကောင်
    နာမည်တွေ အပိုင်းတိုင်း တသမတ်တည်း ဖြစ်အောင်.
    """
    items = [{"id": i, "text": s["text"]} for i, s in enumerate(segments)]
    out = {}
    failed = []
    _sys = ((_RECAP_SYS if recap else _TRANSLATE_SYS)
            + _story_memory_block(story_memory) + _glossary_prompt(glossary))
    BATCH = 25
    batches = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]
    for b, batch in enumerate(batches):
        try:
            res = _gemini_call(api_key, model_id, _sys,
                               json.dumps(batch, ensure_ascii=False))
            for row in res:
                if isinstance(row, dict) and "id" in row and "text" in row:
                    out[int(row["id"])] = str(row["text"]).strip()
            missing = [x["id"] for x in batch if x["id"] not in out]
            failed.extend(missing)
        except Exception:
            failed.extend([x["id"] for x in batch])
        if progress_cb:
            progress_cb((b + 1) / len(batches))
    # ပြန်မရတာတွေ တစ်ကြိမ်ထပ်ကြိုးစား
    if failed:
        retry = [x for x in items if x["id"] in failed]
        still = []
        for b, batch in enumerate([retry[i:i + BATCH] for i in range(0, len(retry), BATCH)]):
            try:
                res = _gemini_call(api_key, model_id, _sys,
                                   json.dumps(batch, ensure_ascii=False))
                for row in res:
                    if isinstance(row, dict) and "id" in row and "text" in row:
                        out[int(row["id"])] = str(row["text"]).strip()
                        if int(row["id"]) in failed:
                            failed.remove(int(row["id"]))
            except Exception:
                still.extend([x["id"] for x in batch])
    result = []
    for i, s in enumerate(segments):
        result.append({"start": s["start"], "end": s["end"],
                       "src": s["text"], "text": out.get(i, s["text"])})
    return result, failed


def merge_tiny_segments(segments, max_gap=0.5, min_slot=1.5, max_merged=8.0):
    """Whisper (verbose_json) က တခါတလေ စက္ကန့်ပိုင်းအကွက်သေးသေးလေးတွေ
    (ဥပမာ 0.2s) ပေးတတ်တယ် — အဲ့ဒါတွေကို ကပ်နေတဲ့နောက်အပိုင်းနဲ့ ပေါင်းလိုက်.

    စည်း: အကွက်က min_slot ထက် သေးနေသေးရင် + နောက်အပိုင်းနဲ့ကြားက gap က
    max_gap ထက်နည်းရင် ပေါင်း; ပေါင်းပြီးသားအကွက် max_merged ထက် မကျော်စေနဲ့.
    စကားပြောရပ်တဲ့နေရာ (gap ကြီး) တွေတော့ မပေါင်းဘူး — sync မပျက်စေဖို့.
    """
    if not segments:
        return segments
    merged = []
    i, n = 0, len(segments)
    while i < n:
        cur = dict(segments[i])
        while (i + 1 < n
               and cur["end"] - cur["start"] < min_slot
               and segments[i + 1]["start"] - cur["end"] < max_gap
               and cur["end"] - cur["start"] < max_merged):
            nxt = segments[i + 1]
            cur["end"] = float(nxt["end"])
            cur["text"] = (cur["text"] + " " + nxt["text"]).strip()
            if "src" in cur or "src" in nxt:
                cur["src"] = ((cur.get("src") or "") + " "
                              + (nxt.get("src") or "")).strip()
            i += 1
        merged.append(cur)
        i += 1
    return merged


_SHORTEN_SYS = (
    "You rewrite subtitle lines SHORTER for voiceover dubbing. Each line will be "
    "spoken by TTS inside a tight time slot, so compress aggressively: cut filler "
    "words, drop repeated ideas, keep only the core meaning. Keep natural SPOKEN "
    "Burmese (Myanmar). Each item has 'max_chars' — stay under it if possible. "
    "Return ONLY a JSON array of objects with keys 'id' and 'text'."
    + _MYANMAR_ONLY + _HUMAN_STYLE
)


def gemini_shorten(api_key, model_id, items, glossary=None):
    """items: [{'id': seg_idx, 'text':..., 'target_chars':...}]
    → {seg_idx: တိုထားတဲ့စာသား}. ပျက်ရင်/ပြန်မရရင် အဲ့အပိုင်း ပါမလာဘူး
    (မူရင်းအတိုင်း ကျန်မယ်)."""
    payload = [{"id": x["id"], "text": x["text"],
                "max_chars": x["target_chars"]} for x in items]
    try:
        res = _gemini_call(api_key, model_id,
                           _SHORTEN_SYS + _glossary_prompt(glossary),
                           json.dumps(payload, ensure_ascii=False))
    except Exception:
        return {}
    out = {}
    for row in res:
        if isinstance(row, dict) and "id" in row and "text" in row:
            t = str(row["text"]).strip()
            if t:
                out[int(row["id"])] = t
    return out


# ------------------------------------------------- 🎙️ narrator mode
# စာကြောင်းချင်း ဘာသာပြန်တာအစား: scene ခွဲ → AI က scene ကြည့် →
# third-person မြန်မာ narrator script ရေး → ကျန်တဲ့ pipeline (TTS/fit/mix)
# ဒီအတိုင်း ပြန်သုံး.
NARR_MAX_SCENES = 40      # vision token ကုန်သက်သာအောင် scene အများဆုံး
NARR_MAX_SCENE_LEN = 30.0  # ဒီထက်ရှည်တဲ့ scene ကို ထပ်ခွဲ
NARR_VISION_BATCH = 6     # vision API တစ်ခေါက်မှာ scene ဘယ်နှခုထည့်မလဲ
NARR_CPS = 12.0           # narrator script အရှည်ချိန်ဖို့ (သဘာဝနှုန်း, conservative)

_VISION_SYS = (
    "You are analyzing video frames for a Myanmar recap narrator. "
    "For each scene you get 3 frames in order (near-start/middle/near-end). "
    "Describe the scene in 2-3 concise English sentences: who is visible, "
    "the key action, and the mood. CRITICAL: compare the frames for STATE CHANGES "
    "(something empty becoming full, appearing, transforming, a surprising event). "
    "If a change happens across the frames, describe the CHANGE as the main beat "
    "(e.g. 'the girl touches the jar and rice magically fills it'), not just the "
    "final state. Magical or surprising transformations are the most important "
    "story information — never omit them. Also read any burned-in text overlays; "
    "they often label the key event. "
    "Return ONLY a JSON array of objects with keys 'id' and 'desc'."
)

_NARRATE_SYS = (
    "You write Myanmar voiceover narration for video recap dubbing, in "
    "THIRD-PERSON narrator style — like those gripping movie-recap channels that "
    "hook viewers: SHORT punchy sentences, one story beat per sentence, plain "
    "dramatic storytelling. Refer to characters by role ('the delivery man', "
    "'the little girl', 'the wealthy old man') instead of bare pronouns. Use "
    "natural SPOKEN Burmese (Myanmar), not formal written style — the way a "
    "narrator speaks out loud. "
    "For each scene, write narration that fits within max_chars (it must be "
    "speakable within the scene's duration at natural speed). "
    "Ground every line in the provided visual description and dialogue — "
    "do NOT invent events, characters, or dialogue not supported by them. "
    "Return ONLY a JSON array of objects with keys 'id' and 'text'."
    + _MYANMAR_ONLY + _HUMAN_STYLE
)


def detect_scenes(video_path, threshold=0.30, max_scenes=NARR_MAX_SCENES,
                  max_len=NARR_MAX_SCENE_LEN):
    """ffmpeg scene detection → [{'start','end'}].

    - ရှည်လွန်းတဲ့ scene (>max_len) ကို ထပ်ခွဲ
    - သေးလွန်းတဲ့ အပိုင်းတွေကို ကပ်ရက်နဲ့ ပေါင်း (max_scenes ထိ)
    """
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", video_path, "-vf",
         f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True)
    cuts = [0.0]
    for line in r.stderr.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
            if t - cuts[-1] > 0.5:
                cuts.append(t)
    total = dur(video_path) or (cuts[-1] + 1.0)
    cuts.append(total)
    scenes = [{"start": cuts[i], "end": cuts[i + 1]}
              for i in range(len(cuts) - 1) if cuts[i + 1] - cuts[i] > 0.3]
    # ရှည်လွန်းတာ ခွဲ (ceil: 30s ကျော်ရင် အပိုင်းခွဲရမယ် — AI video လို
    # cut မသိသာတာတွေမှာ scene နည်းနည်း တွေ့တဲ့ ပြဿနာ ကာကွယ်ဖို့)
    split = []
    for s in scenes:
        L = s["end"] - s["start"]
        n = max(1, math.ceil(L / max_len))
        for k in range(n):
            split.append({"start": s["start"] + L * k / n,
                          "end": s["start"] + L * (k + 1) / n})
    # အများဆုံး max_scenes ထိ — အတိုဆုံး ကပ်ရက်နှစ်ခုကို ပေါင်း
    while len(split) > max_scenes:
        i = min(range(len(split) - 1),
                key=lambda k: (split[k]["end"] - split[k]["start"]) +
                              (split[k + 1]["end"] - split[k + 1]["start"]))
        split[i]["end"] = split[i + 1]["end"]
        del split[i + 1]
    return split


def extract_scene_frames(video_path, scenes, out_dir):
    """scene တစ်ခုချင်း frame ၃ ပုံ (5%/50%/95%, 320px jpg). → [[path|None]]."""
    os.makedirs(out_dir, exist_ok=True)
    all_paths = []
    for i, s in enumerate(scenes):
        L = s["end"] - s["start"]
        paths = []
        for k, frac in enumerate((0.05, 0.5, 0.95)):
            t = s["start"] + L * frac
            p = os.path.join(out_dir, f"scene_{i:03d}_{k}.jpg")
            try:
                run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}",
                     "-i", video_path, "-frames:v", "1",
                     "-vf", "scale=320:-1", "-q:v", "4", p])
            except Exception:
                pass
            paths.append(p if os.path.isfile(p) else None)
        all_paths.append(paths)
    return all_paths


def _gemini_vision_call(api_key, model_id, system_text, items):
    """items: [{'id', 'image_paths':[path|None], 'label'}] → {id: desc}.

    Vision ပျက်တဲ့ batch / scene ကို ကျော်မယ် (ပြန်မရတာ transcript-only
    နဲ့ ဆက်လို့ရအောင်).
    """
    import requests  # local import
    import base64
    out = {}
    for b in range(0, len(items), NARR_VISION_BATCH):
        batch = items[b:b + NARR_VISION_BATCH]
        parts = [{"text": system_text},
                 {"text": "Frames:\n" + "\n".join(
                     f"[{x['id']}] {x['label']}" for x in batch)}]
        for x in batch:
            for _fi, _ip in enumerate(x.get("image_paths") or []):
                if _ip and os.path.isfile(_ip):
                    with open(_ip, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("ascii")
                    parts.append({"text": f"Frame [{x['id']}]#{_fi + 1}:"})
                    parts.append({"inline_data": {"mime_type": "image/jpeg",
                                                  "data": b64}})
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json",
                                 "temperature": 0.2, "maxOutputTokens": 4096},
        }
        try:
            r = requests.post(
                f"{GEMINI_BASE}{model_id}:generateContent",
                headers={"Content-Type": "application/json",
                         "x-goog-api-key": api_key},
                json=body, timeout=180)
            if r.status_code != 200:
                continue
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            txt = txt.strip()
            if txt.startswith("```"):
                txt = re.sub(r"^```(?:json)?\s*", "", txt)
                txt = re.sub(r"\s*```$", "", txt)
            for row in json.loads(txt):
                if isinstance(row, dict) and "id" in row and "desc" in row:
                    out[int(row["id"])] = str(row["desc"]).strip()
        except Exception:
            continue
    return out


def describe_scenes(api_key, model_id, video_path, scenes, work_dir,
                    progress_cb=None):
    """scene တွေကို frame ထုတ် → Gemini vision → [{'start','end','desc'}]."""
    frames = extract_scene_frames(
        video_path, scenes, os.path.join(work_dir, "frames"))
    items = [{"id": i, "image_paths": p,
              "label": f"scene {fmt_ts(s['start'])}-{fmt_ts(s['end'])}"}
             for i, (s, p) in enumerate(zip(scenes, frames))]
    got = {}
    total_batches = max(1, (len(items) + NARR_VISION_BATCH - 1) //
                        NARR_VISION_BATCH)
    for b in range(0, len(items), NARR_VISION_BATCH):
        got.update(_gemini_vision_call(
            api_key, model_id, _VISION_SYS, items[b:b + NARR_VISION_BATCH]))
        if progress_cb:
            progress_cb((b // NARR_VISION_BATCH + 1) / total_batches)
    return [{"start": s["start"], "end": s["end"],
             "desc": got.get(i, "")} for i, s in enumerate(scenes)]


_STORY_BIBLE_SYS = (
    "You are the story editor for a Myanmar video-recap dubbing project. "
    "You receive scene-by-scene visual descriptions (and any dialogue) of a video. "
    "Build a compact STORY BIBLE as a JSON object with keys: "
    "'characters' (list of at most 8, most important first, each "
    "{'label': 'the delivery man', 'desc': '...'}), "
    "'arc' (2-3 sentence overall story arc: setup, central conflict/turning point, stakes), "
    "'premise' (the core setup revealed in the OPENING scenes, stated plainly in "
    "one or two sentences — e.g. a hidden power, a secret identity, the inciting "
    "incident; this is the most important part of the bible), "
    "'setting' (one line). "
    "Rules: give every recurring person ONE stable role-label in plain English "
    "('the delivery man', 'the little girl', 'the wealthy old man') — the narrator "
    "will reuse these exact labels in every scene; merge duplicates (the same person "
    "described differently across scenes gets a single label). "
    "Pay special attention to the opening scenes: the premise must be captured "
    "completely and accurately — the narrator will establish it before anything else. "
    "Return ONLY the JSON object."
)

_NARRATE_CONT = (
    "CONTINUITY: You also receive STORY (characters with stable role-labels and the "
    "overall story arc) and STORY SO FAR (narration already written for earlier "
    "scenes). Use both: keep every character's role-label EXACTLY as in STORY; "
    "connect each scene to what came before instead of re-introducing people or "
    "events; compress uneventful transitional scenes into a brief bridge line and "
    "give dramatic scenes their full weight (never exceed max_chars). "
    "Keep narration substantial — a story-rich scene should use most of its "
    "max_chars; only truly empty transitional moments may be brief. "
    "The opening scene(s) MUST establish the premise from STORY clearly "
    "(who the characters are, any hidden powers or secrets) — never skip the setup."
)


def build_story_bible(api_key, model_id, scenes_with_desc, src_segments,
                      glossary=None):
    """Scene အားလုံးကနေ story bible (characters + arc). ပျက်ရင် None → fallback."""
    try:
        beats = []
        for i, sc in enumerate(scenes_with_desc):
            dlg = " ".join(x["text"] for x in src_segments
                           if x["start"] < sc["end"] and x["end"] > sc["start"])
            beats.append({"id": i,
                          "visual": (sc["desc"] or "")[:250],
                          "dialogue": dlg[:400]})
        res = _gemini_call(api_key, model_id,
                           _STORY_BIBLE_SYS + _glossary_prompt(glossary),
                           json.dumps(beats, ensure_ascii=False))
        if isinstance(res, dict) and res.get("characters"):
            return res
        return None
    except Exception:
        return None


def gemini_narrate(api_key, model_id, scenes_with_desc, src_segments,
                   glossary=None, progress_cb=None):
    """scene တစ်ခုချင်းအတွက် third-person မြန်မာ narrator script.

    → [{'start','end','text','src'}] — 'src' ထဲမှာ scene ဖော်ပြချက်
    (အဆင့် ၄ review မှာ ကြည့်လို့ရအောင်). text လွတ်လာတဲ့ scene လည်း
    ပါတယ် (အဆင့် ၄ မှာ ကိုယ်တိုင်ဖြည့် / problem finder က ထောက်မယ်).

    Continuity: အရင် story bible (characters + arc) တစ်ခေါက်တည်း တည်ဆောက် →
    batch တွေကို အစဉ်လိုက် ရေးရင်း အရင် batch တွေရဲ့ narration ကို
    STORY SO FAR အဖြစ် နောက် batch တွေမှာ ထည့်ပေးတယ်။
    """
    items = []
    for i, s in enumerate(scenes_with_desc):
        L = s["end"] - s["start"]
        dlg = " ".join(x["text"] for x in src_segments
                       if x["start"] < s["end"] and x["end"] > s["start"])
        items.append({"id": i, "duration": round(L, 1),
                      "max_chars": max(8, int(L * NARR_CPS)),
                      "visual": (s["desc"] or "")[:300],
                      "dialogue": dlg[:600]})
    out = {}
    _sys_base = _NARRATE_SYS + _glossary_prompt(glossary)
    # story bible: တစ်ဗီဒီယိုလုံး တစ်ခေါက်တည်း (ပျက်ရင် None → old behavior)
    _bible = build_story_bible(api_key, model_id, scenes_with_desc,
                               src_segments, glossary)
    _bible_txt = ""
    if _bible:
        _chars = "; ".join(
            f"{c.get('label', '')} ({c.get('desc', '')})"
            for c in _bible.get("characters", [])[:8])
        _bible_txt = (f"STORY — characters: {_chars}. "
                      f"Premise: {_bible.get('premise', '')} "
                      f"Arc: {_bible.get('arc', '')} "
                      f"Setting: {_bible.get('setting', '')}").strip()
    BATCH = 10
    batches = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]
    _so_far = []  # အရင် batch တွေရဲ့ narration, scene အစဉ်လိုက်
    for b, batch in enumerate(batches):
        _sys_b = _sys_base
        _ctx = ""
        if _bible_txt:
            _ctx += "\n" + _bible_txt
        _so_far_txt = " ".join(_so_far)[-3000:]
        if _so_far_txt:
            _ctx += "\nSTORY SO FAR: " + _so_far_txt
        if _ctx:
            _sys_b += "\n" + _NARRATE_CONT + _ctx
        try:
            res = _gemini_call(api_key, model_id, _sys_b,
                               json.dumps(batch, ensure_ascii=False))
            for row in res:
                if isinstance(row, dict) and "id" in row and "text" in row:
                    out[int(row["id"])] = str(row["text"]).strip()
        except Exception:
            pass
        for _it in batch:  # နောက် batch အတွက် စုထား
            _t = out.get(_it["id"], "")
            if _t:
                _so_far.append(_t)
        if progress_cb:
            progress_cb((b + 1) / len(batches))
    return [{"start": s["start"], "end": s["end"],
             "text": out.get(i, ""), "src": s["desc"]}
            for i, s in enumerate(scenes_with_desc)]


# ----------------------------- browser localStorage (key မပျောက်ဖို့)
_LS_GEMINI = "audiodub_gemini_key"
_LS_GROQ = "audiodub_groq_key"
_LS_ASSEMBLYAI = "audiodub_assemblyai_key"
_LS_GLOSSARY = "audiodub_glossary"


def _local_storage(st):
    """browser localStorage component — package မရှိရင်/ပျက်ရင် None."""
    try:
        from streamlit_local_storage import LocalStorage
        return LocalStorage(key="audiodub_ls")
    except Exception:
        return None


def _ls_get(localS, k):
    try:
        return (localS.getItem(k) or "").strip() if localS else ""
    except Exception:
        return ""


def _ls_set(localS, k, v, ckey):
    try:
        if localS and v:
            localS.setItem(k, v, key=ckey)
    except Exception:
        pass


def _ls_del(localS, k, ckey):
    # eraseItem = browser localStorage ကနေ တကယ်ဖျက် (deleteItem က value ပဲ reset);
    # memory ထဲက storedItems ကိုပါ ထုတ်
    try:
        if localS:
            localS.eraseItem(k, key=ckey)
            try:
                localS.storedItems.pop(k, None)
            except Exception:
                pass
    except Exception:
        pass


# ------------------------------------------------- step 5: TTS + slot fit
def _valid_audio(path):
    return os.path.isfile(path) and os.path.getsize(path) > 1000


async def _edge_save(text, voice, path):
    import edge_tts
    await edge_tts.Communicate(text, voice).save(path)


def _tts_cache_path(text, voice_primary):
    """edge-tts cache file path — key = voice + text."""
    key = hashlib.sha1(f"edge:{voice_primary}:{text}".encode("utf-8")).hexdigest()[:16]
    return os.path.join(CACHE_TTS, f"{key}.mp3")


def tts_segment(text, voice_primary=VOICE_MALE, voice_fallback=VOICE_FEMALE):
    """စာတစ်ကြောင်းကို TTS mp3 ထုတ် (cache ပါ). မရရင် None.

    မှတ်ချက်: ဒီစက်ရဲ့ network က Microsoft TTS ကို ပိတ်ထားလို့ ဒီမှာစမ်းရင်
    ပျက်မယ် — အဲ့တာ bug မဟုတ်ဘူး၊ user စက်မှာ အလုပ်လုပ်တယ်။
    """
    out = _tts_cache_path(text, voice_primary)
    if _valid_audio(out):
        return out
    for voice in (voice_primary, voice_fallback):
        try:
            asyncio.run(_edge_save(text, voice, out))
            if _valid_audio(out):
                return out
        except Exception:
            continue
    return None


def fit_segment(src_mp3, slot, gap_after, max_speed, out_path):
    """TTS clip ကို အချိန်ကွက် (slot) ထဲ ထည့်.

    - သဘာဝအတိုင်း ဆန့်ရင် အတိုင်းထား (ကျန်တာ silence ဖြည့်)
    - နည်းနည်းရှည်ရင် max_speed (default 1.3x) အထိ မြန်ပေး
    - အဲ့မှာမှ မဆန့်ရင် max_speed နဲ့ နောက်က silence ငှားသုံး၊
      နောက်အပိုင်းနဲ့တော့ ဘယ်တော့မှ မထပ်စေနဲ့
    Returns: (played_duration, note, ratio)
    """
    d = dur(src_mp3)
    ratio = d / slot if slot > 0 else 1.0
    filters = []
    if ratio <= 1.0:
        # သဘာဝအတိုင်း ဆန့်တယ်: slot အပြည့် silence နဲ့ဖြည့် (timeline မရွေ့စေဖို့)
        filters.append(f"apad=whole_dur={slot:.3f}")
        filters.append(f"atrim=duration={slot:.3f}")
        target, note = slot, "natural"
    elif ratio <= max_speed:
        filters.append(f"atempo={ratio:.4f}")
        target, note = slot, f"x{ratio:.2f}"
    else:
        filters.append(f"atempo={max_speed:.4f}")
        target = min(d / max_speed, slot + gap_after)
        note = "overflow"
    filters.append(f"atrim=duration={target:.3f}")
    run(["ffmpeg", "-y", "-v", "error", "-i", src_mp3,
         "-af", ",".join(filters), "-ar", "24000", "-ac", "1", out_path])
    return target, note, ratio


def tts_and_fit(segments, voice, max_speed, work_segs, progress_cb=None, tts_fn=None):
    """segments: [{'start','end','text'}] → fitted mp3 တွေ.

    Returns: (fitted=[(start, seg_path, played)], report={natural, sped,
             overflow:[...], tts_failed:[...]})
    """
    tts_fn = tts_fn or tts_segment
    os.makedirs(work_segs, exist_ok=True)
    fitted, report = [], {"natural": 0, "sped": 0, "overflow": [], "tts_failed": []}
    n = len(segments)
    for i, s in enumerate(segments):
        start, end, text = s["start"], s["end"], s["text"].strip()
        slot = end - start
        next_start = segments[i + 1]["start"] if i + 1 < n else end
        gap_after = max(0.0, next_start - end)
        src = tts_fn(text, voice, VOICE_FEMALE) if tts_fn is tts_segment else tts_fn(text)
        if src is None:
            report["tts_failed"].append((i, start, text[:60]))
        else:
            seg_path = os.path.join(work_segs, f"s{i:04d}.mp3")
            played, note, ratio = fit_segment(src, slot, gap_after, max_speed, seg_path)
            fitted.append((start, seg_path, played))
            if note == "natural":
                report["natural"] += 1
            elif note == "overflow":
                report["overflow"].append((i, start, end, text, ratio))
            else:
                report["sped"] += 1
        if progress_cb:
            progress_cb((i + 1) / n, i, text[:50])
    return fitted, report


# ------------------------------------------------- step 6: assemble + mux
def assemble_dubbed(fitted, total_duration, work_asm, out_mp3):
    """fitted clip တွေကို timeline အတိုင်း ဆက် → total_duration အတိအကျ mp3."""
    os.makedirs(work_asm, exist_ok=True)
    lst = os.path.join(work_asm, "concat.txt")
    gap_cache = {}

    def gap_file(gap):
        key = round(gap, 2)
        if key not in gap_cache:
            gf = os.path.join(work_asm, f"_gap{key}.mp3")
            if not os.path.exists(gf):
                silence(gf, key)
            gap_cache[key] = gf
        return gap_cache[key]

    with open(lst, "w") as fh:
        # ပထမအပိုင်းမစခင် ဦးဆောင်တိတ်ဆိတ်မှု (timeline မရွေ့စေဖို့)
        if fitted and fitted[0][0] > 0.02:
            fh.write(f"file '{gap_file(fitted[0][0])}'\n")
        for j, (start, seg, played) in enumerate(fitted):
            fh.write(f"file '{seg}'\n")
            next_s = fitted[j + 1][0] if j + 1 < len(fitted) else total_duration
            gap = next_s - (start + played)
            if gap > 0.02:
                fh.write(f"file '{gap_file(gap)}'\n")
    # re-encode (MP3 frame padding က timeline မပျက်စေဖို့)
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", lst, "-c:a", "libmp3lame", "-b:a", "96k",
         "-ar", "24000", "-ac", "1", out_mp3])
    return out_mp3


def mux_video(video_path, dubbed_mp3, out_mp4):
    """မူရင်းဗီဒီယို (ပုံအတိုင်း) + အသံသစ် → MP4."""
    run(["ffmpeg", "-y", "-v", "error", "-i", video_path, "-i", dubbed_mp3,
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
         "-shortest", out_mp4])
    return out_mp4


# ------------------------------------------------- 🎬 Recap Studio render engine
# အလုပ်လုပ်ပုံ: narration (TTS) ကို အချိန်ကွက်ထဲ အတင်းမထည့်ဘဲ သဘာဝအတိုင်းထား →
# video အပိုင်းတစ်ခုချင်းစီကို သူ့ narration အရှည်နဲ့ကိုက်အောင် setpts နဲ့
# အမြန်/အနှေးချိန် (slow-mo / fast-mo) → dub audio နဲ့ mux → MP4.
# မူရင်းအသံမပါဘူး (dub-voice-only — အရင်အတိုင်း).
def tts_natural(segments, voice, work_segs, progress_cb=None):
    """segments → [{'start','end','text','mp3','dur'}].

    fit_segment လို slot ထဲ အတင်းမထည့်ဘူး — TTS သဘာဝအရှည်အတိုင်း.
    Recap render အတွက် narration အရှည်တိုင်းဖို့ သုံးတယ်.
    Cache လွတ်တဲ့အပိုင်းတွေကို asyncio.gather + Semaphore(6) နဲ့ ပြိုင်တူထုတ်တယ်.
    """
    os.makedirs(work_segs, exist_ok=True)
    out, failed = [], []
    n = len(segments)
    if n == 0:
        return out, failed
    texts = [(s.get("text") or "").strip() for s in segments]
    mp3 = [None] * n
    todo = []  # (i, text, path)
    alias = {}  # စာသားထပ်နေတဲ့ index → ပထမဆုံး index (cache path တူ)
    seen_path = {}
    for i, text in enumerate(texts):
        if not text:
            continue
        p = _tts_cache_path(text, voice)
        if _valid_audio(p):
            mp3[i] = p  # cache hit
        elif p in seen_path:
            alias[i] = seen_path[p]  # တစ်ပြိုင်နက် ဖိုင်တူရေးမိမှာစိုးလို့ alias ထား
        else:
            seen_path[p] = i
            todo.append((i, text, p))

    _done = [0]

    def _tick(i):
        _done[0] += 1
        if progress_cb:
            progress_cb(_done[0] / n, i, texts[i][:50])

    for i in range(n):  # cache-hit / စာလွတ် / စာသားထပ် တွေကို ချက်ချင်း တိုး
        if mp3[i] is not None or not texts[i] or i in alias:
            _tick(i)

    async def _fetch(jobs, report):
        sem = asyncio.Semaphore(6)

        async def _one(i, text, v, path):
            async with sem:
                try:
                    await _edge_save(text, v, path)
                    ok = _valid_audio(path)
                except Exception:
                    ok = False
                return i, ok

        tasks = [asyncio.ensure_future(_one(i, t, v, p)) for i, t, v, p in jobs]
        results = []
        for fut in asyncio.as_completed(tasks):
            i, ok = await fut
            results.append((i, ok))
            if report:
                _tick(i)
        return results

    if todo:
        by_i = {i: (text, path) for i, text, path in todo}
        res1 = asyncio.run(_fetch(
            [(i, t, voice, p) for i, (t, p) in by_i.items()], True))
        need_retry = []
        for i, ok in res1:
            if ok:
                mp3[i] = by_i[i][1]
            else:
                need_retry.append(i)
        if need_retry:
            # fallback voice နဲ့ တစ်ကြိမ်ထပ်ကြိုး (cache path က primary key အတိုင်း)
            res2 = asyncio.run(_fetch(
                [(i, by_i[i][0], VOICE_FEMALE, by_i[i][1]) for i in need_retry],
                False))
            for i, ok in res2:
                if ok:
                    mp3[i] = by_i[i][1]

    for i, s in enumerate(segments):
        if i in alias:  # စာသားထပ်နေတာ → ပထမအပိုင်းရဲ့ mp3 ကို ပြန်သုံး
            mp3[i] = mp3[alias[i]]
        if mp3[i] is None:
            failed.append((i, s.get("start", 0.0), texts[i][:60]))
        else:
            out.append({"start": float(s.get("start", 0.0)),
                        "end": float(s.get("end", 0.0)),
                        "text": texts[i], "mp3": mp3[i], "dur": dur(mp3[i])})
    return out, failed


def _video_fps(path):
    """မူရင်း video ရဲ့ fps (recap render က concat ပြီးနောက် CFR ပြန်လုပ်ဖို့)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=15)
        num, den = r.stdout.strip().split("/")
        f = float(num) / float(den)
        if 1.0 < f < 120.0:
            return f
    except Exception:
        pass
    return 30.0


def render_recap_video(video_path, natural, total_duration, work_dir, out_mp4):
    """Recap render: video piece တစ်ခုချင်းစီကို narration အရှည်နဲ့ကိုက်အောင် ချိန်.

    natural: tts_natural() ကရတာ [{'start','end','text','mp3','dur'}].
    Piece ပိုင်းခြားပုံ: [start_i, boundary_i] (boundary_i = နောက် segment ရဲ့ start,
    နောက်ဆုံးအပိုင်းဆို video အဆုံး) — piece တစ်ခုလုံးရဲ့ အရှည် P_i ကို
    (dur_i + gap_i) အဖြစ် setpts နဲ့ ချိန်တယ်. Gap (အသံတိတ်) အပိုင်းတွေက
    သူ့အတိုင်းကျန်မယ်. Leading silence (ပထမအပိုင်းမစခင်) လည်း 1x အတိုင်း.

    Returns: (out_mp4, timeline=[{'start','end','text'}],
              report=[(seg_idx, factor, note)])
    """
    if not natural:
        raise ValueError("recap render: narration အပိုင်း မရှိဘူး")
    os.makedirs(work_dir, exist_ok=True)
    n = len(natural)

    def _boundary(i):
        b = natural[i + 1]["start"] if i + 1 < n else total_duration
        return max(b, natural[i]["end"])

    # video pieces: (v_start, v_end, target_dur)
    pieces = []
    if natural[0]["start"] > 0.05:
        pieces.append((0.0, natural[0]["start"], natural[0]["start"]))
    for i, sg in enumerate(natural):
        b = _boundary(i)
        p_dur = b - sg["start"]
        gap = max(0.0, b - sg["end"])
        pieces.append((sg["start"], b, sg["dur"] + gap))

    fparts, vlabels = [], []
    for j, (a, b, target) in enumerate(pieces):
        p_dur = b - a
        factor = target / p_dur if p_dur > 0.05 else 1.0
        factor = min(max(factor, 0.05), 20.0)  # setpts အရမ်းလွန်ကဲတာ ကာကွယ်
        fparts.append(
            f"[0:v]trim=start={a:.3f}:end={b:.3f},"
            # (PTS-STARTPTS): piece အစကို 0 ကနေစပြီး အချိုးချတာ —
            # PTS သက်သက်ဆို absolute timestamp ကို မြှောက်မိပြီး piece တွေ ထပ်ကုန်မယ်
            f"settb=AVTB,setpts=(PTS-STARTPTS)*{factor:.4f}[v{j}]")
        vlabels.append(f"[v{j}]")
    fcomplex = (";".join(fparts) + ";" + "".join(vlabels) +
                f"concat=n={len(pieces)}:v=1:a=0,"
                # setpts ကြောင့် VFR ဖြစ်သွားတဲ့ timestamp တွေကို source fps
                # အတိုင်း CFR ပြန်လုပ် (slow-mo အပိုင်းမှာ frame ပွား, fast-mo မှာ ချုံ့)
                f"fps={_video_fps(video_path):.2f}[vout]")

    # audio: tts + gap silence တွေ timeline အတိုင်း ဆက်
    lst = os.path.join(work_dir, "recap_audio.txt")
    gap_cache = {}

    def gap_file(g):
        key = round(g, 2)
        if key not in gap_cache:
            gf = os.path.join(work_dir, f"_rgap{key}.mp3")
            if not os.path.exists(gf):
                silence(gf, key)
            gap_cache[key] = os.path.abspath(gf)
        return gap_cache[key]

    with open(lst, "w") as fh:
        # concat demuxer က list ထဲက relative path တွေကို list file ရဲ့ dir နဲ့
        # ပေါင်းဖြေရှင်းလို့ — absolute path ပဲ ရေးမယ်
        if natural[0]["start"] > 0.05:
            fh.write(f"file '{gap_file(natural[0]['start'])}'\n")
        for i, sg in enumerate(natural):
            fh.write(f"file '{os.path.abspath(sg['mp3'])}'\n")
            gap = max(0.0, _boundary(i) - sg["end"])
            if gap > 0.02:
                fh.write(f"file '{gap_file(gap)}'\n")

    run(["ffmpeg", "-y", "-v", "error", "-i", video_path,
         "-f", "concat", "-safe", "0", "-i", lst,
         "-filter_complex", fcomplex,
         "-map", "[vout]", "-map", "1:a:0",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart", "-shortest", out_mp4])

    # subtitle အတွက် timeline အသစ်
    timeline, report, cum = [], [], 0.0
    if natural[0]["start"] > 0.05:
        cum = natural[0]["start"]
    for i, sg in enumerate(natural):
        b = _boundary(i)
        p_dur = b - sg["start"]
        target = sg["dur"] + max(0.0, b - sg["end"])
        factor = target / p_dur if p_dur > 0.05 else 1.0
        note = ""
        if factor < 0.5:
            note = "အရမ်းနှေး (slow-mo)"
        elif factor > 2.0:
            note = "အရမ်းမြန်"
        report.append((i, factor, note))
        timeline.append({"start": cum, "end": cum + sg["dur"], "text": sg["text"]})
        cum += target
    return out_mp4, timeline, report


def speedup_video(video_in, factor, out_mp4):
    """Render ပြီးသား video ကို factor အတိုင်း အမြန်ပေး (video+audio အတူ, sync မပျက်).

    factor=1.0 ဆို မူရင်းအတိုင်း copy. atempa က 0.5–2.0 အတွင်းမို့
    slider ကို 1.0–1.5 ပဲ ပေးထားတယ်.
    """
    if abs(factor - 1.0) < 1e-6:
        shutil.copyfile(video_in, out_mp4)
        return out_mp4
    run(["ffmpeg", "-y", "-v", "error", "-i", video_in,
         "-vf", f"setpts=PTS/{factor:.4f}",
         "-af", f"atempo={factor:.4f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart", out_mp4])
    return out_mp4


def segments_to_srt(segments):
    lines = []
    for i, s in enumerate(segments, 1):
        lines.append(f"{i}\n{fmt_ts(s['start'])} --> {fmt_ts(s['end'])}\n{s['text']}\n")
    return "\n".join(lines)


_SRT_TS_LINE = re.compile(
    r"(\d+:[\d:.,]+)\s*-->\s*(\d+:[\d:.,]+)")


def _decode_text_upload(raw):
    """Uploaded file bytes → str (utf-8-sig / utf-16 / cp1252 အစဉ်လိုက် စမ်း)."""
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return bytes(raw).decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return ""


def parse_srt(text):
    """SRT ဖိုင်စာသား → [{start, end, text}]. စာသားအပိုဒ်များရင် space နဲ့ဆက်."""
    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    segs = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.strip().split("\n") if l.strip()]
        if not lines:
            continue
        ts_idx = 0
        if "-->" not in lines[0] and len(lines) > 1:
            ts_idx = 1  # ပထမလိုင်းက နံပါတ်စဉ်
        m = _SRT_TS_LINE.search(lines[ts_idx]) if ts_idx < len(lines) else None
        if not m:
            continue
        try:
            start, end = parse_ts(m.group(1)), parse_ts(m.group(2))
        except (ValueError, IndexError):
            continue
        txt = " ".join(l.strip() for l in lines[ts_idx + 1:] if l.strip())
        if end > start and txt:
            segs.append({"start": start, "end": end, "text": txt})
    segs.sort(key=lambda x: x["start"])
    return segs


_REVIEW_LINE = re.compile(
    r"(\d+:\d+:[\d.,]+)\s*-->\s*(\d+:[\d:.,]+)\s*\|\s*(.*)")


def segments_to_review_text(segments):
    return "\n".join(f"{fmt_ts(s['start'])} --> {fmt_ts(s['end'])} | {s['text']}"
                     for s in segments)


def parse_review_text(raw):
    """ပြင်ပြီးသား text → segments. မှားနေတဲ့လိုင်း ရှိရင် error တက်."""
    segs = []
    for ln, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        m = _REVIEW_LINE.match(line)
        if not m:
            raise ValueError(f"လိုင်း {ln} ပုံစံမှားနေတယ်: {line[:60]}")
        start, end, text = parse_ts(m.group(1)), parse_ts(m.group(2)), m.group(3).strip()
        if end <= start or not text:
            raise ValueError(f"လိုင်း {ln} အချိန်/စာသား မှားနေတယ်")
        segs.append({"start": start, "end": end, "text": text})
    segs.sort(key=lambda x: x["start"])
    if not segs:
        raise ValueError("စာသားတစ်ကြောင်းမှ မကျန်ဘူး")
    return segs


# မြန်မာစာမဟုတ်တဲ့ script တွေ (Tamil/Devanagari/Thai/Korean/CJK စသဖြင့်) —
# ဘာသာပြန်အမှား/အကြွင်းအကျန်တွေ ဖမ်းဖို့
_FOREIGN_SCRIPT_RE = re.compile(
    r"[\u0B80-\u0BFF\u0900-\u097F\u0E00-\u0E7F\u3040-\u30FF\uAC00-\uD7AF\u4E00-\u9FFF]")
_FOREIGN_SCRIPT_NAMES = (
    (0x0B80, 0x0BFF, "Tamil"),
    (0x0900, 0x097F, "Devanagari"),
    (0x0E00, 0x0E7F, "Thai"),
    (0x3040, 0x30FF, "Japanese"),
    (0xAC00, 0xD7AF, "Korean"),
    (0x4E00, 0x9FFF, "Chinese"),
)


def _foreign_script_name(text):
    """တခြား script ပါနေရင် နာမည်ပြန် (flag message အတွက်)."""
    for ch in text:
        o = ord(ch)
        for lo, hi, name in _FOREIGN_SCRIPT_NAMES:
            if lo <= o <= hi:
                return name
    return "တခြား"
# my-MM TTS ခန့်မှန်းအမြန်နှုန်း (စာလုံး/စက္ကန့်) — ပြဿနာလိုင်းရှာဖို့ ခန့်မှန်းချက်သက်သက်
_EST_CPS = 12.0  # NARR_CPS (12.0) နဲ့ တစ်သမတ်တည်းဖြစ်အောင် unified


def find_problem_lines(segments, max_speed):
    """အဆင့် ၄ အတွက် ပြဿနာရှိနိုင်တဲ့လိုင်းတွေ ရှာပေး.

    → [(idx, "အကြောင်းရင်း"), ...]. TTS အစစ်မထုတ်ဘဲ ခန့်မှန်းချက်နဲ့ပဲ
    စစ်တာ (အတိအကျမဟုတ် — သတိပေးတဲ့သဘော).
    """
    flags = []
    for i, s in enumerate(segments):
        slot = s["end"] - s["start"]
        text = (s["text"] or "").strip()
        reasons = []
        if not text:
            reasons.append("စာသားလွတ်နေတယ်")
        else:
            if slot > 0 and len(text) > slot * _EST_CPS * max_speed:
                reasons.append("ရှည်လွန်းတယ် (အသံထွက်ရင် အချိန်မလောက်နိုင်ဘူး)")
            if _FOREIGN_SCRIPT_RE.search(text):
                reasons.append(
                    f"{_foreign_script_name(text)} စာလုံး ပါနေတယ်")
            src = (s.get("src") or "").strip()
            if src and text == src and re.search(r"[A-Za-z]{3,}", text):
                reasons.append("ဘာသာမပြန်ရသေးဘူး (မူရင်းအတိုင်း ကျန်နေတယ်)")
        if reasons:
            flags.append((i, " + ".join(reasons)))
    return flags



def _qc_bad_reason(text):
    """ဘာသာပြန်လိုင်း အရည်အသွေးစစ် → ပျက်ရင် အကြောင်း, ကောင်းရင် None."""
    t = (text or "").strip()
    if not t:
        return "စာသားလွတ်နေတယ်"
    if _FOREIGN_SCRIPT_RE.search(t):
        return f"{_foreign_script_name(t)} စာလုံး ပါနေတယ်"
    if re.search(r"[\u1000-\u109F]", t) and re.search(r"[A-Za-z]", t):
        return "မြန်မာနဲ့ အင်္ဂလိပ် ရောနေတယ်"
    if not re.search(r"[\u1000-\u109F]", t) and re.search(r"[A-Za-z]{3,}", t):
        return "ဘာသာမပြန်ရသေးဘူး (မူရင်းအတိုင်း ကျန်နေတယ်)"
    return None


def _qc_retranslate_sys(glossary=None, story_memory=None):
    return (
        "You translate ONE video subtitle line into natural SPOKEN Burmese (Myanmar). "
        "Output ONLY Myanmar (Burmese) Unicode script — never mix in Tamil, "
        "Devanagari/Hindi, Thai, Chinese, Korean, Japanese, Latin, or any other "
        "non-Myanmar script, not even for names. Keep the meaning, keep it concise. "
        "Return ONLY a JSON object with key 'text'."
        + _HUMAN_STYLE + _story_memory_block(story_memory)
        + _glossary_prompt(glossary)
    )


def qc_retranslate(api_key, model_id, translations, glossary=None,
                   progress_cb=None, max_retries=2, story_memory=None):
    """ဘာသာပြန်ပြီးသားလိုင်းတွေ အရည်အသွေးစစ် → ပျက်တာတွေ တစ်ကြောင်းချင်း ပြန်ပြန်.

    → (translations, report). report: {"checked", "bad_initial", "bad_ratio",
    "retried", "fixed", "still_bad": [(idx, reason, src)]}.
    စာသားလွတ်နေတဲ့လိုင်းတွေက ပြန်ပြန်လို့မရလို့ still_bad ထဲ တန်းဝင်မယ်.
    """
    n = len(translations)
    bad = {}
    for i, sg in enumerate(translations):
        r = _qc_bad_reason(sg.get("text", ""))
        if r:
            bad[i] = r
    report = {"checked": n, "bad_initial": len(bad),
              "bad_ratio": (len(bad) / n) if n else 0.0,
              "retried": [], "fixed": [], "still_bad": []}
    if not bad:
        return translations, report
    sys = _qc_retranslate_sys(glossary, story_memory)
    total = len(bad)
    for k, (i, reason) in enumerate(bad.items()):
        src = translations[i].get("src", "") or translations[i].get("text", "")
        if not src.strip():
            # ပြန်စရာမူရင်းစာသားတောင် မရှိဘူး
            report["still_bad"].append((i, reason, ""))
            if progress_cb:
                progress_cb((k + 1) / total)
            continue
        ok = False
        for _ in range(max_retries):
            try:
                res = _gemini_call(api_key, model_id, sys,
                                   json.dumps([{"id": 0, "text": src}],
                                              ensure_ascii=False))
                if res and isinstance(res[0], dict) and res[0].get("text"):
                    new_text = str(res[0]["text"]).strip()
                    if not _qc_bad_reason(new_text):
                        translations[i]["text"] = new_text
                        ok = True
                        break
            except Exception:
                pass
        report["retried"].append(i)
        if ok:
            report["fixed"].append(i)
        else:
            report["still_bad"].append(
                (i, _qc_bad_reason(translations[i].get("text", "")) or reason,
                 src[:80]))
        if progress_cb:
            progress_cb((k + 1) / total)
    return translations, report


def _reset_review_keys(S):
    """ဘာသာပြန် အသစ်ရတိုင်း review textarea + quick-fix key တွေ ရှင်း
    (အဟောင်း widget state က စာအသစ်ကို မဖုံးစေဖို့)."""
    if "review_text" in S:
        del S["review_text"]
    for k in [k for k in S.keys() if k.startswith("fixline_")]:
        del S[k]


# ------------------------------------------------- ⚡ Auto mode (တစ်ချက်နှိပ် အပြီးအစီး)
_AUTO_SPEEDUP = 1.3
_AUTO_QC_BREAK_RATIO = 0.30


# ---------------- checkpoint / resume ----------------
# Auto အဆင့်တိုင်း disk မှာ သိမ်း → tab ပိတ် / error တက်ရင် ခလုတ်ပြန်နှိပ်ရုံနဲ့
# ရပ်တဲ့နေရာက ဆက် (ပြီးသားအဆင့် ကျော်).

def _ckpt_path(run_id, name):
    return os.path.join(WORK_DIR, run_id, "ckpt", name + ".json")


def _ckpt_save(run_id, name, data):
    d = os.path.dirname(_ckpt_path(run_id, name))
    os.makedirs(d, exist_ok=True)
    tmp = _ckpt_path(run_id, name) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, _ckpt_path(run_id, name))


def _ckpt_load(run_id, name):
    p = _ckpt_path(run_id, name)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _ckpt_matches(ckpt, want):
    """checkpoint က လက်ရှိ setting တွေနဲ့ ကိုက်လား (setting ပြောင်းရင် အသစ်စ)."""
    if not isinstance(ckpt, dict):
        return False
    return all(ckpt.get(k) == v for k, v in want.items())


def _video_fingerprint(video_path):
    try:
        return f"{os.path.basename(video_path)}::{os.path.getsize(video_path)}"
    except Exception:
        return ""


def _find_prior_run(fingerprint):
    """fingerprint တူတဲ့ မပြီးသေးတဲ့ run ရှာ → run_id (မရှိရင် None).

    ပြီးသားဆိုရင် အသစ်စ (setting ပြောင်းပြီး ပြန်လုပ်ချင်လို့နေမယ်).
    """
    if not fingerprint or not os.path.isdir(WORK_DIR):
        return None
    for rid in sorted(os.listdir(WORK_DIR)):
        rd = os.path.join(WORK_DIR, rid)
        if not os.path.isdir(rd):
            continue
        meta = _ckpt_load(rid, "meta")
        if meta and meta.get("fingerprint") == fingerprint:
            if not os.path.isfile(os.path.join(rd, "dubbed_video.mp4")):
                return rid
    return None


def _auto_adopt_run(S, run_id):
    """အရင် run ရဲ့ ckpt တွေ S ထဲ ပြန်ထည့် (session အသစ် / tab ပြန်ဖွင့်)."""
    meta = _ckpt_load(run_id, "meta") or {}
    S.update(run_id=run_id,
             video_path=meta.get("video_path"),
             audio_path=meta.get("audio_path"),
             duration=meta.get("duration", 0.0),
             dl_base=meta.get("dl_base", ""),
             _auto_up_name=meta.get("up_name", ""),
             src_segments=None, translations=None, final_segments=None,
             out_mp4=None, out_subs=None, auto_mp3=None,
             auto_done=False, auto_report=None)
    s2 = _ckpt_load(run_id, "s2_translate")
    if s2 and s2.get("drama_name"):
        S["drama_name"] = s2["drama_name"]


def _qc_report_json(qc):
    """qc report ကို JSON-serializable ဖြစ် (still_bad tuple → list)."""
    qc = dict(qc or {})
    qc["still_bad"] = [list(x) for x in (qc.get("still_bad") or [])]
    return qc


# ---------------- story memory (ဇာတ်ကောင်နာမည် တသမတ်တည်း) ----------------
# ဇာတ်လမ်းရှည်ကို အပိုင်းခွဲလုပ်ရင် အပိုင်းတိုင်း နာမည်တစ်မျိုးတည်း ဖြစ်အောင်
# drama တစ်ခုစာအတွက် ဇာတ်ကောင်/နေရာ မှတ်ဉာဏ် တစ်ခု share သုံး.
MEM_DIR = os.path.join(WORK_DIR, "memories")


def _mem_path(name):
    safe = re.sub(r"[^\w\- ]", "", (name or "")).strip()[:60] or "drama"
    return os.path.join(MEM_DIR, safe + ".json")


def load_story_memory(name):
    if not name:
        return None
    p = _mem_path(name)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_story_memory(name, mem):
    if not name:
        return
    os.makedirs(MEM_DIR, exist_ok=True)
    mem = dict(mem or {})
    mem["drama"] = name
    tmp = _mem_path(name) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _mem_path(name))


def delete_story_memory(name):
    try:
        os.remove(_mem_path(name))
    except Exception:
        pass


def _mem_fingerprint(mem):
    if not mem:
        return ""
    try:
        return hashlib.md5(json.dumps(mem.get("characters"), ensure_ascii=False,
                                     sort_keys=True).encode()).hexdigest()[:12]
    except Exception:
        return ""


def _story_memory_block(mem):
    """translate / QC prompt ထဲ ထည့်မယ့် နာမည်စာရင်း."""
    if not mem:
        return ""
    out = []
    chars = [c for c in (mem.get("characters") or [])
             if isinstance(c, dict) and c.get("src") and c.get("mm")]
    if chars:
        out.append("CHARACTER NAME MEMORY — use these EXACT Myanmar names every "
                   "time these characters appear (do not re-transliterate them "
                   "differently; if the manual Glossary below lists the same name, "
                   "the Glossary wins):")
        for c in chars:
            out.append(f"- {c['src']} → {c['mm']}"
                       + (f" ({c['role']})" if c.get("role") else ""))
    for key, label in (("places", "PLACES"), ("terms", "TERMS")):
        items = [e for e in (mem.get(key) or [])
                 if isinstance(e, dict) and e.get("src") and e.get("mm")]
        if items:
            out.append(f"{label} — use these exact Myanmar forms:")
            out += [f"- {e['src']} → {e['mm']}" for e in items]
    return ("\n" + "\n".join(out) + "\n") if out else ""


def build_story_memory(api_key, model_id, segments):
    """transcript ဖတ် → {characters, places, terms} (source နာမည်တွေ).

    မရရင် အလွတ်ပြန် (memory မပါဘဲ ဆက်လုပ်) — ဘယ်တော့မှ error မထုတ်.
    """
    full = "\n".join(s.get("text", "") for s in segments)
    CH = 24000
    chunks = [full[i:i + CH] for i in range(0, len(full), CH)] or [""]
    mem = {"characters": [], "places": [], "terms": []}
    sys = ("You read a video transcript and build a CAST/TERM MEMORY as JSON. "
           "Return ONLY a JSON object with keys 'characters', 'places', 'terms'. "
           "characters: [{\"src\": name exactly as in transcript, \"role\": short role}]. "
           "places: [{\"src\": place name}]. terms: [{\"src\": recurring special term}]. "
           "Include EVERY named character and place, even minor ones. "
           "Source names only — no translation yet.")
    for ci, ch in enumerate(chunks):
        try:
            payload = (f"CHUNK {ci + 1}/{len(chunks)}:\n{ch}\n\n"
                       f"EXISTING MEMORY (merge into it, do not duplicate names):\n"
                       f"{json.dumps(mem, ensure_ascii=False)}")
            res = _gemini_call(api_key, model_id, sys, payload)
        except Exception:
            continue
        if not isinstance(res, dict):
            continue
        for k in ("characters", "places", "terms"):
            for e in (res.get(k) or []):
                if (isinstance(e, dict) and e.get("src")
                        and not any(x.get("src") == e["src"] for x in mem[k])):
                    mem[k].append({"src": e["src"], "role": e.get("role", ""),
                                   "mm": ""})
    return mem


def update_story_memory(api_key, model_id, mem, translations):
    """ဘာသာပြန်ပြီးသား → ဇာတ်ကောင်တစ်ယောက်ချင်းရဲ့ မြန်မာနာမည် မှတ်.

    မရရင် အဟောင်းအတိုင်း ပြန် — ဘယ်တော့မှ error မထုတ်.
    """
    mem = dict(mem or {"characters": [], "places": [], "terms": []})
    pairs = "\n".join(
        f"[{i}] SRC: {(t.get('src') or '')[:200]}\n"
        f"    MM : {(t.get('text') or '')[:200]}"
        for i, t in enumerate(translations))
    CH = 24000
    chunks = [pairs[i:i + CH] for i in range(0, len(pairs), CH)] or [""]
    sys = ("You get source lines and their Myanmar translations. For each entry in "
           "the NAME LIST below, find the Myanmar name actually used in the "
           "translations. Return ONLY a JSON object with keys 'characters', "
           "'places', 'terms' — each a list of {\"src\", \"mm\"}. Keep every input "
           "entry (mm=\"\" if not found). Also ADD newly appeared named characters, "
           "places or recurring terms with their Myanmar names.")
    for ci, ch in enumerate(chunks):
        try:
            payload = (f"PART {ci + 1}/{len(chunks)}:\n{ch}\n\n"
                       f"NAME LIST:\n{json.dumps(mem, ensure_ascii=False)}")
            res = _gemini_call(api_key, model_id, sys, payload)
        except Exception:
            continue
        if not isinstance(res, dict):
            continue
        for k in ("characters", "places", "terms"):
            for e in (res.get(k) or []):
                if not (isinstance(e, dict) and e.get("src")):
                    continue
                hit = next((x for x in mem.get(k, [])
                            if x.get("src") == e["src"]), None)
                if hit:
                    if e.get("mm"):
                        hit["mm"] = e["mm"]
                else:
                    mem.setdefault(k, []).append(
                        {"src": e["src"], "role": e.get("role", ""),
                         "mm": e.get("mm", "")})
    return mem


def _auto_ui(S, api_key, groq_key, assembly_key, model_id, voice,
             use_fallback, glossary, auto_merge):
    """⚡ Auto mode: ဗီဒီယိုတင် → ခလုတ်တစ်ချက် → အပြီးအစီး."""
    import streamlit as st
    _spidey_card_open("⚡", "Auto — တစ်ချက်နှိပ်ပြီး အပြီးလုပ်")
    # --- ဖိုင်တင် (ရွေးတာနဲ့ အသံထုတ်ထား)
    up = st.file_uploader("MP4 / MOV / WEBM ဖိုင်ရွေးပါ",
                          type=["mp4", "mov", "webm"], key="auto_up")
    if S.video_path:
        st.info(f"📁 {os.path.basename(S.video_path)} — {S.duration:.1f} စက္ကန့်")
    if up is not None and S.get("_auto_up_name") != up.name:
        run_id = uuid.uuid4().hex[:8]
        rd = os.path.join(WORK_DIR, run_id)
        os.makedirs(rd, exist_ok=True)
        vpath = os.path.join(rd, up.name)
        with open(vpath, "wb") as f:
            f.write(up.getbuffer())
        # အရင်လုပ်လက်စ run ရှိလား (tab ပိတ် / session အသစ်) → ပြန်ဆက်
        fp = _video_fingerprint(vpath)
        prior = _find_prior_run(fp)
        if prior:
            shutil.rmtree(rd, ignore_errors=True)
            _auto_adopt_run(S, prior)
            st.toast("♻️ အရင်လုပ်လက်စ တွေ့လို့ ရပ်တဲ့နေရာက ပြန်ဆက်မယ် — "
                     "ခလုတ်နှိပ်လိုက်ပါ")
            st.rerun()
        wpath = os.path.join(rd, "audio.mp3")
        with st.spinner("ffmpeg နဲ့ အသံထုတ်နေတယ်..."):
            run(["ffmpeg", "-y", "-v", "error", "-i", vpath,
                 "-ar", "16000", "-ac", "1", "-b:a", "32k", wpath])
            d = dur(vpath)
        S.update(run_id=run_id, video_path=vpath, audio_path=wpath, duration=d,
                 src_segments=None, translations=None, final_segments=None,
                 fitted=None, fit_report=None, out_mp4=None, out_mp3=None,
                 auto_mp3=None, auto_done=False, auto_report=None,
                 dl_base=os.path.splitext(up.name)[0], _auto_up_name=up.name)
        _ckpt_save(run_id, "meta", {"fingerprint": fp, "video_path": vpath,
                   "audio_path": wpath, "duration": d,
                   "dl_base": os.path.splitext(up.name)[0], "up_name": up.name})
        st.toast(f"✅ အသံထုတ်ပြီးပြီ — ဗီဒီယို {d:.1f} စက္ကန့်")
        st.rerun()
    # --- မူရင်းဘာသာစကား
    _lang_label = st.pills(
        "🎙️ မူရင်းဘာသာစကား",
        [lbl for lbl, _ in _SRC_LANGS],
        selection_mode="single",
        default=[lbl for lbl, _ in _SRC_LANGS][0],
        key="auto_src_lang",
        help="Whisper က ဘာသာစကား မှားသိတတ်တယ် — ဗီဒီယိုက ဘာဘာသာစကားလဲ "
             "သိရင် ဒီမှာ ရွေးလိုက်။ မသိရင် Auto ထားခဲ့။")
    _lang_code = dict(_SRC_LANGS)[_lang_label]
    # --- ဇာတ်လမ်း မှတ်ဉာဏ် (အပိုင်းခွဲ နာမည်တူအောင် — မထည့်လည်းရ) ---
    drama_name = st.text_input(
        "🎭 ဇာတ်လမ်း အမည်",
        key="drama_name",
        placeholder="ဥပမာ: 颠倒世界 (အပိုင်းခွဲလုပ်မှ ထည့်)",
        help="ဇာတ်လမ်းရှည်ကို အပိုင်းခွဲလုပ်ရင် ဒီနာမည်တူတူ ထည့်ထား — "
             "ဇာတ်ကောင်နာမည်တွေ အပိုင်းတိုင်း တစ်မျိုးတည်းဖြစ်အောင် "
             "မှတ်ဉာဏ် share သုံးမယ်")
    drama_name = (drama_name or "").strip()
    _mem = load_story_memory(drama_name) if drama_name else None
    if _mem:
        _nch = len(_mem.get("characters") or [])
        st.caption(f"📖 မှတ်ဉာဏ်ရှိနေတယ် — ဇာတ်ကောင် {_nch} ယောက် မှတ်ထားပြီး")
        with st.expander("👀 မှတ်ဉာဏ်ကြည့် / ဖျက်"):
            for c in (_mem.get("characters") or []):
                if isinstance(c, dict) and c.get("src"):
                    st.write(f"• {c['src']} → {c.get('mm') or '(မသိမ်းရသေး)'}"
                             + (f" — {c['role']}" if c.get("role") else ""))
            if st.button("🗑️ ဒီမှတ်ဉာဏ်ဖျက်", key="mem_del_btn"):
                delete_story_memory(drama_name)
                st.toast("🗑️ မှတ်ဉာဏ်ဖျက်ပြီးပြီ")
                st.rerun()
    # --- ခလုတ်
    _has_keys = bool((groq_key or assembly_key) and api_key)
    if not (groq_key or assembly_key):
        st.warning("⚠️ Groq / AssemblyAI API Key တစ်ခုခု ထည့်မှ စာသားထုတ်လို့ရမယ် "
                   "(ဘယ်ဘက် sidebar)။")
    if not api_key:
        st.warning("⚠️ Gemini API key ထည့်မှ ဘာသာပြန်လို့ရမယ် (ဘယ်ဘက် sidebar)။")
    _go = st.button("⚡ တစ်ချက်နှိပ်ပြီး အပြီးလုပ်", type="primary",
                    use_container_width=True,
                    disabled=not (S.video_path and _has_keys))
    if _go:
        _auto_run(S, api_key, groq_key, assembly_key, model_id, voice,
                  use_fallback, glossary, auto_merge, _lang_code, drama_name)
    _spidey_card_close()
    # --- ရလဒ်
    if S.get("auto_done") and S.out_mp4 and os.path.isfile(S.out_mp4):
        _auto_results(S)


def _auto_run(S, api_key, groq_key, assembly_key, model_id, voice,
              use_fallback, glossary, auto_merge, lang_code, drama_name=""):
    """Auto pipeline အစအဆုံး (progress နဲ့). ပျက်ရင် ဘယ်အဆင့်လဲ ပြပြီး ရပ်.

    အဆင့်တိုင်း checkpoint သိမ်း → ခလုတ်ပြန်နှိပ်ရင် ပြီးသားအဆင့်တွေ ကျော်ပြီး
    ရပ်တဲ့နေရာက ဆက်. drama_name ပေးထားရင် story memory share သုံး
    (အပိုင်းခွဲ နာမည်တူအောင်).
    """
    import streamlit as st
    prog = st.progress(0.0)
    msg = st.empty()

    def setp(f, t):
        prog.progress(max(0.0, min(1.0, f)))
        msg.text(t)

    rid = S.run_id
    _mid = model_id.strip() or GEMINI_MODEL_DEFAULT
    _gloss_hash = hashlib.md5(str(glossary or "").encode()).hexdigest()[:12]
    try:
        # ---- 1/6 transcribe (အသံရှည်ရင် အပိုင်းခွဲနားထောင်) ----
        s1 = _ckpt_load(rid, "s1_transcribe")
        if _ckpt_matches(s1, {"lang_code": lang_code or ""}):
            segs, _slang = s1["segments"], s1.get("lang", "")
            setp(0.06, f"⏭️ 1/6 — စာသားထုတ်ပြီးသား ({len(segs)} ပိုင်း) ကျော်မယ်")
        else:
            setp(0.03, "🎤 1/6 — အသံမှ စာသားထုတ်နေတယ်...")
            data, _provider = transcribe_with_fallback(
                S.audio_path, groq_key or None,
                assembly_key if use_fallback else None, language=lang_code,
                on_chunk=lambda i, n: setp(
                    0.03 + 0.10 * i / n,
                    f"🎤 1/6 — အသံအပိုင်း {i}/{n} နားထောင်နေတယ်..."))
            segs = [{"start": x["start"], "end": x["end"], "text": x["text"]}
                    for x in data.get("segments", [])]
            if auto_merge and segs:
                segs = merge_tiny_segments(segs)
            if not segs:
                raise ValueError("စာသားမတွေ့ဘူး — ဗီဒီယိုမှာ စကားပြောအသံ ရှိမရှိ စစ်ပါ")
            _slang = data.get("language", "")
            _ckpt_save(rid, "s1_transcribe",
                       {"segments": segs, "lang": _slang,
                        "lang_code": lang_code or ""})
        S.src_segments, S.lang = segs, _slang
        src_hash = hashlib.md5(
            "".join(x["text"] for x in segs).encode()).hexdigest()[:12]

        # ---- story memory (drama_name ရှိမှ) ----
        mem = load_story_memory(drama_name) if drama_name else None
        mem_fp = _mem_fingerprint(mem)

        # ---- 2/6 translate ----
        s2 = _ckpt_load(rid, "s2_translate")
        if _ckpt_matches(s2, {"src_hash": src_hash, "model": _mid,
                              "gloss": _gloss_hash, "mem_fp": mem_fp}):
            result = s2["translations"]
            setp(0.24, f"⏭️ 2/6 — ဘာသာပြန်ပြီးသား ({len(result)} ပိုင်း) ကျော်မယ်")
        else:
            if drama_name and not mem:
                setp(0.20, "🧠 2/6 — ဇာတ်ကောင်မှတ်ဉာဏ် တည်နေတယ်...")
                mem = build_story_memory(api_key, _mid, segs)
                save_story_memory(drama_name, mem)
                mem_fp = _mem_fingerprint(mem)
            setp(0.22, f"🌐 2/6 — ဘာသာပြန်နေတယ် ({len(segs)} ပိုင်း)...")
            result, _failed = gemini_translate(
                api_key, segs, _mid,
                progress_cb=lambda f: setp(0.22 + 0.20 * f,
                                           "🌐 2/6 — ဘာသာပြန်နေတယ်..."),
                glossary=glossary, recap=False, story_memory=mem)
            _ckpt_save(rid, "s2_translate",
                       {"translations": result, "src_hash": src_hash,
                        "model": _mid, "gloss": _gloss_hash, "mem_fp": mem_fp,
                        "drama_name": drama_name or ""})

        # ---- 3/6 quality check + ပြန်ပြင် ----
        s3 = _ckpt_load(rid, "s3_qc")
        if _ckpt_matches(s3, {"src_hash": src_hash, "model": _mid,
                              "gloss": _gloss_hash, "mem_fp": mem_fp}):
            result, qc = s3["translations"], s3["report"]
            setp(0.46, "⏭️ 3/6 — အရည်အသွေးစစ်ပြီးသား ကျော်မယ်")
        else:
            setp(0.44, "🔍 3/6 — အရည်အသွေးစစ်နေတယ်...")
            result, qc = qc_retranslate(
                api_key, _mid, result, glossary=glossary, story_memory=mem,
                progress_cb=lambda f: setp(
                    0.44 + 0.08 * f, "🔍 3/6 — ပျက်တဲ့လိုင်းတွေ ပြန်ပြန်နေတယ်..."))
            if qc["bad_ratio"] > _AUTO_QC_BREAK_RATIO:
                raise ValueError(
                    f"စာကြောင်း {qc['bad_initial']}/{qc['checked']} ခု ပျက်နေတယ် — "
                    "မူရင်းဘာသာစကား ရွေးတာ မှားနေနိုင်တယ်။ "
                    "Manual mode အဆင့် ၂ မှာ စစ်ကြည့်ပါ။")
            if drama_name:
                setp(0.52, "🧠 3/6 — မှတ်ဉာဏ်မှာ မြန်မာနာမည်တွေ သိမ်းနေတယ်...")
                mem = update_story_memory(
                    api_key, _mid,
                    mem or {"characters": [], "places": [], "terms": []},
                    result)
                save_story_memory(drama_name, mem)
            _ckpt_save(rid, "s3_qc",
                       {"translations": result, "report": _qc_report_json(qc),
                        "src_hash": src_hash, "model": _mid,
                        "gloss": _gloss_hash, "mem_fp": mem_fp})
        S.translations = result
        S.final_segments = [dict(x) for x in result]
        S.auto_report = qc
        _reset_review_keys(S)

        # ---- 4/6 TTS (သဘာဝအရှည် — render က video ချိန်ပေးမယ်) ----
        s4 = _ckpt_load(rid, "s4_tts")
        work_nat = os.path.join(WORK_DIR, rid, "natural")
        natural = None
        if _ckpt_matches(s4, {"n": len(S.final_segments), "voice": voice}):
            cand = s4.get("natural") or []
            if cand and all(os.path.isfile((x or {}).get("mp3", ""))
                           for x in cand):
                natural = cand
                setp(0.56,
                     f"⏭️ 4/6 — အသံထုတ်ပြီးသား ({len(natural)} ပိုင်း) ကျော်မယ်")
        if natural is None:
            setp(0.54, "🔊 4/6 — မြန်မာအသံထုတ်နေတယ်...")
            natural, failed_n = tts_natural(
                S.final_segments, voice, work_nat,
                progress_cb=lambda f, i, t: setp(
                    0.54 + 0.20 * f,
                    f"🔊 4/6 — အပိုင်း {i + 1}/{len(S.final_segments)}"))
            if not natural:
                raise ValueError("အသံထုတ်မရဘူး — network / VPN စစ်ပါ")
            if failed_n:
                msg.text(f"🔇 အသံထုတ်မရတဲ့အပိုင်း {len(failed_n)} ခု ကျော်သွားမယ်")
            _ckpt_save(rid, "s4_tts",
                       {"natural": natural, "failed": failed_n,
                        "n": len(S.final_segments), "voice": voice})

        # ---- 5-6/6 recap render + speedup ----
        s5 = _ckpt_load(rid, "s5_final")
        if (s5 and os.path.isfile(s5.get("out_mp4", ""))
                and os.path.isfile(s5.get("amp3", ""))):
            out, amp3, subs = s5["out_mp4"], s5["amp3"], s5["subs"]
            setp(0.96, "⏭️ 5-6/6 — video ပြီးသား ကျော်မယ်")
        else:
            setp(0.76, "🎞️ 5/6 — video ကို narration အရှည်နဲ့ကိုက်အောင် ချိန်နေတယ်...")
            work_rc = os.path.join(WORK_DIR, rid, "recap")
            tmp_out = os.path.join(work_rc, "recap_video.mp4")
            _, timeline, _ = render_recap_video(
                S.video_path, natural, S.duration, work_rc, tmp_out)
            setp(0.94, f"⚡ 6/6 — {_AUTO_SPEEDUP}x တင်ပြီး အပြီးသတ်နေတယ်...")
            out = os.path.join(WORK_DIR, rid, "dubbed_video.mp4")
            sped = os.path.join(WORK_DIR, rid, "spedup.mp4")
            speedup_video(tmp_out, _AUTO_SPEEDUP, sped)
            shutil.copyfile(sped, out)
            subs = [{"start": x["start"] / _AUTO_SPEEDUP,
                     "end": x["end"] / _AUTO_SPEEDUP,
                     "text": x["text"]} for x in timeline]
            amp3 = os.path.join(WORK_DIR, rid, "dubbed_voiceover.mp3")
            run(["ffmpeg", "-y", "-v", "error", "-i", out, "-vn",
                 "-c:a", "libmp3lame", "-b:a", "128k", amp3])
            _ckpt_save(rid, "s5_final",
                       {"out_mp4": out, "amp3": amp3, "subs": subs})
        S.out_mp4, S.out_subs, S.auto_mp3 = out, subs, amp3
        S.auto_done = True
        setp(1.0, "✅ ပြီးပြီ!")
    except Exception as e:
        prog.empty()
        msg.empty()
        st.error(f"⛔ Auto ရပ်သွားတယ်: {e}")
        st.info("💡 ခလုတ်ပြန်နှိပ်ရင် ပြီးသားအဆင့်တွေ ကျော်ပြီး ရပ်တဲ့နေရာက "
                "ဆက်လုပ်မယ် (ဒီဗီဒီယိုနဲ့ပဲ)")
        st.stop()
    prog.empty()
    msg.empty()
    st.toast("✅ Auto ပြီးပြီ!")
    st.rerun()



def _auto_results(S):
    """Auto ရလဒ်: quality report + MP4 ခလုတ်အကြီး + MP3/SRT အသေး."""
    import streamlit as st
    st.success("✅ Auto ပြီးပြီ! အောက်မှာ download ချလို့ရပြီ")
    st.video(S.out_mp4)  # ⬇️ မဒေါင်းခင် preview အရင်ကြည့်
    qc = S.get("auto_report") or {}
    if qc.get("checked"):
        _bits = [f"စာကြောင်း {qc['checked']} ခု စစ်ပြီး"]
        if qc.get("fixed"):
            _bits.append(f"{len(qc['fixed'])} လိုင်း ပြန်ပြင်ခဲ့တယ် ✅")
        if qc.get("still_bad"):
            _bits.append(f"⚠️ {len(qc['still_bad'])} လိုင်း ကျန်နေတယ်")
        with st.expander("🔍 အရည်အသွေးစစ်ချက် ကြည့်",
                         expanded=bool(qc.get("still_bad"))):
            st.caption(" · ".join(_bits))
            for (i, reason, src) in qc.get("still_bad", []):
                st.write(f"#{i + 1} — {reason}")
                if src:
                    st.caption(f"မူရင်း: {src[:80]}")
            if qc.get("still_bad"):
                st.caption("ကျန်တဲ့လိုင်းတွေ Manual mode အဆင့် ၄ မှာ ပြင်လို့ရတယ်")
    if S.get("_dl_for") != S.run_id:
        _base = (S.get("dl_base") or "audio").strip() or "audio"
        S["dl_name"] = f"{_base}_dubbed"
        S["_dl_for"] = S.run_id
    st.text_input("📝 ဖိုင်နာမည်", key="dl_name",
                  help="download ချမယ့်အမည် — .mp4/.mp3/.srt ကို သူ့အလိုလို ထည့်ပေးမယ်")
    _dl = re.sub(r'[\\/:*?"<>|]', "_", (S.get("dl_name") or "").strip()) or "dubbed"
    with open(S.out_mp4, "rb") as f:
        st.download_button(f"⬇️ Dubbed MP4 ({_AUTO_SPEEDUP}x)", f,
                           file_name=f"{_dl}.mp4", mime="video/mp4",
                           type="primary", use_container_width=True)
    _c1, _c2 = st.columns(2)
    if S.get("auto_mp3") and os.path.isfile(S.auto_mp3):
        with _c1, open(S.auto_mp3, "rb") as f:
            st.download_button("⬇️ MP3 (အသံသက်သက်)", f,
                               file_name=f"{_dl}.mp3", mime="audio/mpeg",
                               use_container_width=True)
    with _c2:
        st.download_button("⬇️ SRT", segments_to_srt(S.out_subs or []),
                           file_name=f"{_dl}.srt", mime="text/plain",
                           use_container_width=True)


# ------------------------------------------------------------------ UI
def _init_state(st):
    defaults = {
        "run_id": None, "video_path": None, "audio_path": None, "duration": 0.0,
        "src_segments": None, "translations": None, "final_segments": None,
        "fitted": None, "fit_report": None, "out_mp4": None, "out_mp3": None,
        "lang": "", "auto_shortened": False,
        "srt_name": "", "srt_is_my": False, "dl_base": "",
        "scenes": None, "scene_descs": None,
        "recap_timeline": None, "recap_report": None,
        "out_subs": None,
        "wizard_step": 1,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def main():
    import streamlit as st
    st.set_page_config(page_title="Audio Dub Studio", page_icon="🕷️", layout="wide")
    st.markdown(_SPIDEY_CSS, unsafe_allow_html=True)
    _init_state(st)
    S = st.session_state

    # ---------------------------------------------------------- sidebar
    with st.sidebar:
        st.markdown("### 🕷️ Spidey Control")
        st.radio("🎛️ Mode",
                 ["🔧 Manual (တစ်ဆင့်ချင်း)", "⚡ Auto (တစ်ချက်နှိပ်)"],
                 key="app_mode",
                 help="Manual = တစ်ဆင့်ချင်းကိုယ်တိုင်စစ်ပြီးလုပ်; "
                      "Auto = ဗီဒီယိုတင်ပြီး ခလုတ်တစ်ချက်နဲ့ အပြီးအစီး")
        st.divider()
        st.caption("Key တွေ၊ အသံနဲ့ ရွေးချယ်စရာတွေ ဒီမှာပြင်")
        st.markdown("#### 🔑 API Keys")
        localS = _local_storage(st)
        # key ဖျက်တာ — widget တွေ မပေါ်ခင် (run အစ) မှာ လုပ်
        if S.get("_clear_keys"):
            _ls_del(localS, _LS_GEMINI, "ls_del_gemini")
            _ls_del(localS, _LS_GROQ, "ls_del_groq")
            _ls_del(localS, _LS_ASSEMBLYAI, "ls_del_aai")
            for _k in ("gemini_key", "groq_key", "assemblyai_key"):
                if _k in S:
                    del S[_k]
            del S["_clear_keys"]
        # --- Gemini key: server secret > ရိုက်ထည့်ထား > browser သိမ်းထား ---
        env_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not env_key and "gemini_key" not in S:
            _sg = _ls_get(localS, _LS_GEMINI)
            if _sg:
                S["gemini_key"] = _sg
        key_input = st.text_input("Gemini API Key", type="password", key="gemini_key",
                                  placeholder="AIzaSy...",
                                  help="စာသားဘာသာပြန်ဖို့သုံး — တစ်ခါထည့်ထားရင် browser မှာ "
                                       "မှတ်ထားမယ်၊ hard refresh ဆွဲလည်း မပျောက်ဘူး")
        typed_gemini = key_input.strip()
        if typed_gemini and typed_gemini != _ls_get(localS, _LS_GEMINI):
            _ls_set(localS, _LS_GEMINI, typed_gemini, "ls_set_gemini")
        api_key = typed_gemini or env_key
        st.markdown("🔑 key အလကားယူရန်: "
                    "[aistudio.google.com/apikey](https://aistudio.google.com/apikey)")
        if api_key:
            st.success("✅ Gemini key ရှိတယ်")
        else:
            st.warning("⚠️ Gemini key မရှိသေးဘူး (အဆင့် ၃ အတွက်လိုတယ်)")
        # --- Groq key: server secret > ရိုက်ထည့်ထား > browser သိမ်းထား ---
        env_groq = os.environ.get("GROQ_API_KEY", "").strip()
        if not env_groq and "groq_key" not in S:
            _sq = _ls_get(localS, _LS_GROQ)
            if _sq:
                S["groq_key"] = _sq
        groq_input = st.text_input("Groq API Key", type="password", key="groq_key",
                                   placeholder="gsk_...",
                                   help="အသံမှ စာသားထုတ်ဖို့သုံး — console.groq.com မှာ အလကားယူလို့ရ။ "
                                        "တစ်ခါထည့်ထားရင် browser မှာ မှတ်ထားမယ်")
        typed_groq = groq_input.strip()
        if typed_groq and typed_groq != _ls_get(localS, _LS_GROQ):
            _ls_set(localS, _LS_GROQ, typed_groq, "ls_set_groq")
        groq_key = typed_groq or env_groq
        st.markdown("🔑 key အလကားယူရန်: "
                    "[console.groq.com/keys](https://console.groq.com/keys)")
        if groq_key:
            st.success("✅ Groq key ရှိတယ်")
        else:
            st.warning("⚠️ Groq key မရှိသေးဘူး (အဆင့် ၂ အတွက်လိုတယ်)")
        # --- AssemblyAI key: Groq 403 IP-block ထိတဲ့အခါ fallback ---
        env_aai = os.environ.get("ASSEMBLYAI_API_KEY", "").strip()
        if not env_aai and "assemblyai_key" not in S:
            _sa = _ls_get(localS, _LS_ASSEMBLYAI)
            if _sa:
                S["assemblyai_key"] = _sa
        aai_input = st.text_input("AssemblyAI API Key", type="password",
                                  key="assemblyai_key", placeholder="...",
                                  help="Groq က 403 IP-block ထိတဲ့အခါ အလိုအလျောက်သုံးမယ့် "
                                       "fallback — assemblyai.com မှာ ကတ်မလိုဘဲ $50 free "
                                       "credit ရတယ်။ တစ်ခါထည့်ထားရင် browser မှာ မှတ်ထားမယ်")
        typed_aai = aai_input.strip()
        if typed_aai and typed_aai != _ls_get(localS, _LS_ASSEMBLYAI):
            _ls_set(localS, _LS_ASSEMBLYAI, typed_aai, "ls_set_aai")
        assembly_key = typed_aai or env_aai
        st.markdown("🔑 key ယူရန် ($50 free, ကတ်မလို): "
                    "[assemblyai.com](https://www.assemblyai.com/dashboard/signup)")
        if assembly_key:
            st.success("✅ AssemblyAI key ရှိတယ် (Groq fallback)")
        else:
            st.caption("💡 AssemblyAI key မရှိသေးဘူး — Groq ပျက်ရင် fallback မရဘူး")
        # glossary: browser သိမ်းထားတာ ရှိရင် ပြန် load
        if "glossary" not in S:
            _gg = _ls_get(localS, _LS_GLOSSARY)
            if _gg:
                S["glossary"] = _gg
        if st.button("🔑 သိမ်းထားတဲ့ key တွေ ဖျက်",
                     help="browser မှာ မှတ်ထားတဲ့ key တွေကို ဖျက်မယ် "
                          "(ဥပမာ သူများဖုန်း/ကွန်ပျူတာနဲ့ သုံးပြီးရင်)"):
            S["_clear_keys"] = True
            st.rerun()
        st.divider()
        st.markdown("#### 🎚️ အသံ ဆက်တင်")
        model_id = st.text_input("Gemini model", value=GEMINI_MODEL_DEFAULT)
        # 🎚️ အသံချုံ့ slider ဝှက်ထားတယ် — render mode မှာ အလုပ်မလုပ်လို့; 1.3x အသေ
        max_speed = 1.3
        voice = st.selectbox("အသံ", [VOICE_MALE, VOICE_FEMALE],
                             format_func=lambda v: "🗣️ ကျား (Thiha)" if v == VOICE_MALE else "🗣️ မ (Nilar)")
        if st.button("🔊 အသံ စမ်းနားထောင်ရန်", use_container_width=True,
                     help="ရွေးထားတဲ့အသံနဲ့ နမူနာစာတစ်ကြောင်း ဖတ်ပြမယ် — "
                          "အဆင့် ၅ မလုပ်ခင် အသံကြိုက်မကြိုက် စစ်လို့ရတယ်"):
            _sample = "မင်္ဂလာပါ။ ဒီအသံနဲ့ ဇာတ်လမ်းကို ပြောပြမယ်။"
            with st.spinner("အသံထုတ်နေတယ်..."):
                _tp = tts_segment(_sample, voice, VOICE_FEMALE)
            if _tp:
                S["_voice_test"] = _tp
            else:
                st.error("အသံထုတ်မရဘူး — network / VPN စစ်ပါ")
        if S.get("_voice_test") and os.path.isfile(S["_voice_test"]):
            st.audio(S["_voice_test"])
        st.divider()
        st.markdown("#### ⚙️ ရွေးချယ်စရာ")
        # 🔗/✂️ UI ဝှက်ထားတယ် (code ကျန်တယ်) — render အမြဲသုံးတော့ မလိုတော့ဘူး
        auto_merge = False
        auto_shorten = False
        # 🔄 fallback checkbox ဖြုတ်လိုက်တယ် — Groq ပျက်ရင် အမြဲ AssemblyAI နဲ့ဆက်မယ်
        use_fallback = True
        st.markdown("##### 🎬 Recap Studio")
        # 🎬 recap-style UI ဝှက်ထားတယ် (code ကျန်တယ်) — အခု စာကြောင်းချင်းပြန်ပဲ
        recap_style = False
        recap_render = st.checkbox(
            "🎞️ Recap render — video ကို narration အရှည်နဲ့ကိုက်အောင် ချိန်",
            value=True,
            help="အသံကို အချိန်ကွက်ထဲ အတင်းမထည့်ဘဲ သဘာဝအတိုင်းထားပြီး၊ "
                 "video အပိုင်းတစ်ခုချင်းစီကို သူ့ narration အရှည်နဲ့ကိုက်အောင် "
                 "အမြန်/အနှေးချိန်မယ် (slow-mo / fast-mo)။ ဗီဒီယိုမုဒ်မှာသာ "
                 "အလုပ်လုပ်တယ်။ ပိတ်ထားရင် အရင်အတိုင်း")
        speedup = st.slider("⚡ Render ပြီးရင် speed တင်", 1.0, 1.5, 1.0, 0.05,
                            help="Download မချခင် video ကို အမြန်ပေးမယ် "
                                 "(video+audio အတူ, sync မပျက်) — 1.0 = မူရင်းအတိုင်း, "
                                 "1.2 = 20% မြန်။ Recap render နှေးနေရင် ဒီမှာ တင်လို့ရတယ်")
        st.markdown("##### 📖 နာမည်စာရင်း (Glossary)")
        glossary_raw = st.text_area(
            "ဇာတ်ကောင်နာမည်တွေ — တစ်ကြောင်းတစ်ခု",
            key="glossary", height=90, placeholder="John=ဂျွန်\nSarah=ဆာရာ",
            help="ဘာသာပြန်တိုင်း ဒီနာမည်တွေကို ဒီမြန်မာလိုအတိုင်း သုံးမယ် — "
                 "Gemini က တစ်မျိုးတစ်မျိုး ပြောင်းပြန်မှာ စိုးလို့။ browser မှာ မှတ်ထားမယ်")
        _g_stored = _ls_get(localS, _LS_GLOSSARY)
        if glossary_raw.strip() != _g_stored:
            if glossary_raw.strip():
                _ls_set(localS, _LS_GLOSSARY, glossary_raw.strip(), "ls_set_glossary")
            else:
                _ls_del(localS, _LS_GLOSSARY, "ls_del_glossary")
        glossary = parse_glossary(glossary_raw)
        if glossary:
            st.caption(f"✅ {len(glossary)} ခု မှတ်ထားပြီးပြီ")
        st.divider()
        st.markdown("#### 🗑️ အသစ်")
        if st.button("အစက ပြန်စ", use_container_width=True):
            for k in list(S.keys()):
                del S[k]
            st.rerun()

    # ---------------------------------------------------------- main
    st.markdown(
        '<div class="spidey-hero">'
        '<div class="spidey-kicker">🕸️ FRIENDLY NEIGHBORHOOD DUBBING 🕸️</div>'
        '<div class="spidey-title">Audio Dub Studio</div>'
        '<div class="spidey-sub">ဗီဒီယို / SRT → မြန်မာအသံ — မူရင်းအချိန်အတိုင်း 🕷️</div>'
        "</div>",
        unsafe_allow_html=True,
    )

    # ⚡ Auto mode: ဗီဒီယိုတင် → တစ်ချက်နှိပ် အပြီးအစီး (manual wizard ကို ကျော်)
    if str(S.get("app_mode", "🔧 Manual (တစ်ဆင့်ချင်း)")).startswith("⚡"):
        _auto_ui(S, api_key, groq_key, assembly_key,
                 model_id, voice, use_fallback, glossary, auto_merge)
        st.markdown(
            '<div class="spidey-foot">🕷️ Audio Dub Studio — '
            "your friendly neighborhood dubbing tool 🕸️</div>",
            unsafe_allow_html=True)
        return

    mode = st.radio("အရင်းအမြစ်", ["🎬 ဗီဒီယို", "📄 SRT ဖိုင်"], horizontal=True,
                    key="src_mode",
                    help="ဗီဒီယိုတင်ပြီး အစအဆုံးလုပ်မလား၊ "
                         "SRT ဖိုင်အဆင်သင့်ရှိလို့ အဲ့ဒါကနေပဲ ဆက်လုပ်မလား")
    if S.get("_mode") is not None and S["_mode"] != mode:
        for k in ("run_id", "video_path", "audio_path", "duration",
                  "src_segments", "translations", "final_segments",
                  "fitted", "fit_report", "out_mp4", "out_mp3", "lang",
                  "auto_shortened", "srt_name", "srt_is_my", "dl_base",
                  "dl_name", "_dl_for", "scenes", "scene_descs"):
            if k in S:
                del S[k]
        _reset_review_keys(S)
        S["_mode"] = mode
        st.rerun()
    S["_mode"] = mode
    is_video = (mode == "🎬 ဗီဒီယို")

    # 🎙️ narrator UI ဝှက်ထားတယ် (code ကျန်တယ်) — အခု စာကြောင်းချင်းပြန်ပဲ
    narr = False
    if str(S.get("_narr_mode", "")).startswith("🎙️"):
        for k in ("scenes", "scene_descs", "translations",
                  "final_segments", "fitted", "fit_report",
                  "out_mp4", "out_mp3"):
            if k in S:
                del S[k]
        _reset_review_keys(S)
    S["_narr_mode"] = "📝 စာကြောင်းချင်းပြန်"
    _spidey_steps(S, is_video, narr)

    if S["wizard_step"] == 1:
        # ---- အဆင့် ၁: upload (ဗီဒီယို / SRT)
        _spidey_card_open(1, "ဗီဒီယိုတင်ပါ" if is_video else "SRT ဖိုင်တင်ပါ")
        if is_video:
            up = st.file_uploader("MP4 / MOV / WEBM ဖိုင်ရွေးပါ", type=["mp4", "mov", "webm"])
            if S.video_path:
                st.info(f"📁 {os.path.basename(S.video_path)} — {S.duration:.1f} စက္ကန့်")
            _bc1, _ = st.columns([1, 2])
            with _bc1:
                _go1 = (st.button("▶️ အသံထုတ်ယူရန်", type="primary",
                                  use_container_width=True)
                        if up is not None else False)
            if _go1:
                run_id = uuid.uuid4().hex[:8]
                rd = os.path.join(WORK_DIR, run_id)
                os.makedirs(rd, exist_ok=True)
                vpath = os.path.join(rd, up.name)
                with open(vpath, "wb") as f:
                    f.write(up.getbuffer())
                wpath = os.path.join(rd, "audio.mp3")
                with st.status("ffmpeg နဲ့ အသံထုတ်နေတယ်...", expanded=False):
                    run(["ffmpeg", "-y", "-v", "error", "-i", vpath,
                         "-ar", "16000", "-ac", "1", "-b:a", "32k", wpath])
                    d = dur(vpath)
                S.update(run_id=run_id, video_path=vpath, audio_path=wpath, duration=d,
                         src_segments=None, translations=None, final_segments=None,
                         fitted=None, fit_report=None, out_mp4=None, out_mp3=None,
                         dl_base=os.path.splitext(up.name)[0])
                st.toast(f"✅ အသံထုတ်ပြီးပြီ — ဗီဒီယို {d:.1f} စက္ကန့်")
                S["wizard_step"] = 2
                st.rerun()
            if S.video_path:
                # 📄 ဗီဒီယိုမုဒ်မှာ SRT အဆင်သင့်ရှိရင် — transcribe (အဆင့် ၂) ကျော်နိုင်
                with st.expander("📄 SRT အဆင်သင့်ရှိလား? (အဆင့် ၂ ကျော်မယ်)"):
                    st.caption("ဒီဗီဒီယိုနဲ့ အချိန်ကိုက်တဲ့ SRT ရှိရင် တင်လိုက်ပါ — "
                               "အသံနားထောင်ပြီး စာသားထုတ်စရာမလိုတော့ဘူး။")
                    vsrt_up = st.file_uploader("SRT ဖိုင်ရွေးပါ", type=["srt"],
                                               key="srt_up_video")
                    vsrt_lang = st.radio(
                        "SRT က ဘယ်ဘာသာစကားလဲ",
                        ["🌐 ဘာသာခြား (ဘာသာပြန်မယ်)",
                         "✅ မြန်မာလို အဆင်သင့် (တိုက်ရိုက်အသံထုတ်မယ်)"],
                        horizontal=True, key="srt_lang_radio_video")
                    v_is_my = vsrt_lang.startswith("✅")
                    _bc1v, _ = st.columns([1, 2])
                    with _bc1v:
                        _gov = (st.button("▶️ SRT ထည့်ရန်", type="primary",
                                          use_container_width=True)
                                if vsrt_up is not None else False)
                    if _gov:
                        v_segs = parse_srt(_decode_text_upload(vsrt_up.getbuffer()))
                        if not v_segs:
                            st.error("SRT ထဲမှာ စာသားမတွေ့ဘူး — ဖိုင်စစ်ကြည့်ပါ")
                            st.stop()
                        S.update(src_segments=v_segs, lang="",
                                 translations=None, final_segments=None,
                                 fitted=None, fit_report=None,
                                 out_mp4=None, out_mp3=None,
                                 srt_name=vsrt_up.name, srt_is_my=v_is_my)
                        if v_is_my:
                            # မြန်မာလို အဆင်သင့်မို့ ဘာသာပြန်စရာမလို — အဆင့် ၄ တန်းသွား
                            S.translations = [
                                {"start": s["start"], "end": s["end"],
                                 "text": s["text"], "src": ""} for s in v_segs]
                        _reset_review_keys(S)
                        st.toast(f"✅ SRT ထည့်ပြီးပြီ — အပိုင်း {len(v_segs)} ခု")
                        S["wizard_step"] = 4 if v_is_my else 3
                        st.rerun()
        else:
            srt_up = st.file_uploader("SRT ဖိုင်ရွေးပါ", type=["srt"], key="srt_up")
            srt_lang_choice = st.radio(
                "SRT က ဘယ်ဘာသာစကားလဲ",
                ["🌐 ဘာသာခြား (ဘာသာပြန်မယ်)", "✅ မြန်မာလို အဆင်သင့် (တိုက်ရိုက်အသံထုတ်မယ်)"],
                horizontal=True, key="srt_lang_radio")
            is_my = srt_lang_choice.startswith("✅")
            if S.src_segments:
                st.info(f"📄 {S.srt_name} — အပိုင်း {len(S.src_segments)} ခု")
            _bc1s, _ = st.columns([1, 2])
            with _bc1s:
                _gos = (st.button("▶️ SRT ဖတ်ရန်", type="primary",
                                  use_container_width=True)
                        if srt_up is not None else False)
            if _gos:
                raw = srt_up.getbuffer()
                text = None
                for enc in ("utf-8-sig", "utf-16", "cp1252"):
                    try:
                        text = bytes(raw).decode(enc)
                        break
                    except (UnicodeDecodeError, ValueError):
                        continue
                segs = parse_srt(text or "")
                if not segs:
                    st.error("SRT ထဲမှာ စာသားမတွေ့ဘူး — ဖိုင်စစ်ကြည့်ပါ")
                    st.stop()
                run_id = uuid.uuid4().hex[:8]
                rd = os.path.join(WORK_DIR, run_id)
                os.makedirs(rd, exist_ok=True)
                S.update(run_id=run_id, video_path=None, audio_path=None,
                         duration=segs[-1]["end"],
                         src_segments=segs, lang="",
                         translations=None, final_segments=None,
                         fitted=None, fit_report=None, out_mp4=None, out_mp3=None,
                         srt_name=srt_up.name, srt_is_my=is_my,
                         dl_base=os.path.splitext(srt_up.name)[0])
                if is_my:
                    # မြန်မာလို အဆင်သင့်မို့ ဘာသာပြန်စရာမလို — အဆင့် ၄ တန်းသွား
                    S.translations = [{"start": s["start"], "end": s["end"],
                                       "text": s["text"], "src": ""} for s in segs]
                _reset_review_keys(S)
                st.toast(f"✅ SRT ဖတ်ပြီးပြီ — အပိုင်း {len(segs)} ခု")
                S["wizard_step"] = 4 if is_my else 3
                st.rerun()
        _spidey_card_close()

    if S["wizard_step"] == 2:
        # ---- အဆင့် ၂: transcribe (ဗီဒီယိုမုဒ်သာ)
        _spidey_card_open(2, "အသံမှ စာသားထုတ်")
        if not is_video:
            st.info("📄 SRT ဖိုင်ကနေ တိုက်ရိုက်ရပြီးမို့ ဒီအဆင့်မလိုဘူး — အဆင့် ၃ ကို ဆက်သွားပါ။")
        elif not S.audio_path:
            st.caption("အရင်ဆုံး အဆင့် ၁ မှာ ဗီဒီယိုတင်ပါ။")
        elif not (groq_key or assembly_key):
            st.warning("⚠️ Groq / AssemblyAI API Key တစ်ခုခု ထည့်မှ စာသားထုတ်လို့ရမယ် "
                       "(ဘယ်ဘက် sidebar)။")
        else:
            _lang_label = st.pills(
                "🎙️ မူရင်းဘာသာစကား",
                [lbl for lbl, _ in _SRC_LANGS],
                selection_mode="single",
                default=[lbl for lbl, _ in _SRC_LANGS][0],
                key="src_lang_pills",
                help="Whisper က ဘာသာစကား မှားသိတတ်တယ် (ဥပမာ English အသံကို "
                     "Tamil စာနဲ့ ရေးချတာ) — ဗီဒီယိုက ဘာဘာသာစကားလဲ သိရင် "
                     "ဒီမှာ တိတိကျကျ ရွေးလိုက်။ မသိရင် Auto ထားခဲ့။ "
                     "(နှိပ်ရွေးရုံ — စာရိုက်စရာမလို)")
            _lang_code = dict(_SRC_LANGS)[_lang_label]
            _bc2, _ = st.columns([1, 2])
            with _bc2:
                _go2 = st.button("🎤 နားထောင်ပြီး စာသားထုတ်ရန်", type="primary",
                                 use_container_width=True)
            if _go2:
                _init_label = ("Groq Whisper API နဲ့ နားထောင်နေတယ်..."
                               if groq_key else "AssemblyAI နဲ့ နားထောင်နေတယ်...")
                with st.status(_init_label, expanded=True) as stt:
                    try:
                        def _note(msg):
                            stt.update(label=msg)
                        data, _provider = transcribe_with_fallback(
                            S.audio_path, groq_key or None,
                            assembly_key if use_fallback else None,
                            language=_lang_code, on_note=_note)
                    except Exception as e:
                        stt.update(state="error")
                        st.error(str(e))
                        st.stop()
                segs = [{"start": x["start"], "end": x["end"], "text": x["text"]}
                        for x in data.get("segments", [])]
                merge_note = ""
                if auto_merge:
                    before = len(segs)
                    segs = merge_tiny_segments(segs)
                    if len(segs) < before:
                        merge_note = f" (အပိုင်းသေး {before - len(segs)} ခု ပေါင်းပြီးပြီ)"
                S.src_segments, S.lang = segs, data.get("language", "")
                S.translations, S.final_segments, S.fitted = None, None, None
                stt.update(state="complete")
                _via = "Groq" if _provider == "groq" else "AssemblyAI"
                st.toast(f"✅ အပိုင်း {len(segs)} ခု တွေ့တယ် ({_via}){merge_note}"
                         + (f" (ဘာသာစကား: {S.lang})" if S.lang else ""))
                S["wizard_step"] = 3
                st.rerun()
            if S.src_segments:
                with st.expander(f"တွေ့တဲ့အပိုင်း {len(S.src_segments)} ခု ကြည့်"):
                    for s in S.src_segments[:50]:
                        st.write(f"`{fmt_ts(s['start'])} → {fmt_ts(s['end'])}` {s['text']}")
                    if len(S.src_segments) > 50:
                        st.caption(f"...နောက် {len(S.src_segments) - 50} ခု ကျန်သေးတယ်")

        _spidey_card_close()

    if S["wizard_step"] == 3:
        # ---- အဆင့် ၃: translate / narrator script
        _spidey_card_open(3, "🎙️ Narrator script ရေး" if narr else "မြန်မာလို ဘာသာပြန်")
        if narr:
            # 🎙️ narrator mode: scene ခွဲ → AI ကြည့် → script ရေး →
            # ရလာတဲ့ script က S.translations ထဲ {start,end,text,src} ပုံစံနဲ့ ဝင်မယ် —
            # အဆင့် ၄/၅/၆ က အဟောင်းအတိုင်း ဒီအတိုင်း ဆက်သုံးလို့ရတယ်
            if not S.video_path:
                st.caption("အရင်ဆုံး အဆင့် ၁ မှာ ဗီဒီယိုတင်ပါ။")
            elif not S.src_segments:
                st.caption("အရင်ဆုံး အဆင့် ၂ မှာ အသံမှ စာသားထုတ်ပါ "
                           "(dialogue context အတွက် လိုတယ်)။")
            elif not api_key:
                st.warning("⚠️ Gemini API key ထည့်မှ narrator script ရေးလို့ရမယ် "
                           "(ဘယ်ဘက် sidebar)။")
            else:
                _mid = model_id.strip() or GEMINI_MODEL_DEFAULT
                st.caption("Scene ခွဲ → AI က scene တွေကြည့် → "
                           "third-person မြန်မာ narrator script ရေး")
                _bc3a, _ = st.columns([1, 2])
                with _bc3a:
                    _go3a = st.button("🎬 ① Scene ခွဲရန်", type="primary",
                                     use_container_width=True)
                if _go3a:
                    with st.spinner("Scene ဖြတ်တဲ့နေရာတွေ ရှာနေတယ်..."):
                        S.scenes = detect_scenes(S.video_path)
                    S.scene_descs, S.translations = None, None
                    S.final_segments, S.fitted = None, None
                    _reset_review_keys(S)
                    st.success(f"✅ Scene {len(S.scenes)} ခု တွေ့တယ်")
                    st.rerun()
                if S.scenes:
                    _longest = max(s["end"] - s["start"] for s in S.scenes)
                    st.caption(f"🎬 Scene {len(S.scenes)} ခု — "
                               f"အရှည်ဆုံး {_longest:.1f} စက္ကန့်")
                    _bc3b, _ = st.columns([1, 2])
                    with _bc3b:
                        _go3b = st.button("👁️ ② AI က scene တွေကြည့်ရန်",
                                         type="primary", use_container_width=True)
                    if _go3b:
                        prog = st.progress(0.0, "AI က scene တွေကို ကြည့်နေတယ်...")
                        try:
                            S.scene_descs = describe_scenes(
                                api_key, _mid, S.video_path, S.scenes,
                                os.path.join(WORK_DIR, S.run_id, "narr"),
                                progress_cb=lambda f: prog.progress(f))
                        except Exception as e:
                            prog.empty()
                            st.error(f"Vision ပျက်သွားတယ်: {e}")
                            st.stop()
                        prog.empty()
                        _nd = sum(1 for d in S.scene_descs if d["desc"])
                        if _nd == 0:
                            st.warning("⚠️ AI က scene တွေ မမြင်ရဘူး — "
                                       "transcript-only နဲ့ ဆက်မယ်")
                        else:
                            st.success(f"✅ {_nd}/{len(S.scene_descs)} scene "
                                       "မြင်ပြီးပြီ")
                        st.rerun()
                if S.scene_descs:
                    with st.expander(
                            f"👁️ Scene ဖော်ပြချက် {len(S.scene_descs)} ခု ကြည့်"):
                        for d in S.scene_descs[:20]:
                            st.write(f"`{fmt_ts(d['start'])} → {fmt_ts(d['end'])}` "
                                     f"{d['desc'] or '—'}")
                        if len(S.scene_descs) > 20:
                            st.caption(f"...နောက် {len(S.scene_descs) - 20} ခု "
                                       "ကျန်သေးတယ်")
                    _bc3c, _ = st.columns([1, 2])
                    with _bc3c:
                        _go3c = st.button("🎙️ ③ Narrator script ရေးရန်",
                                         type="primary", use_container_width=True)
                    if _go3c:
                        prog = st.progress(0.0, "Narrator script ရေးနေတယ်...")
                        try:
                            S.translations = gemini_narrate(
                                api_key, _mid, S.scene_descs, S.src_segments,
                                glossary=glossary,
                                progress_cb=lambda f: prog.progress(f))
                        except Exception as e:
                            prog.empty()
                            st.error(f"Script ရေးတာ ပျက်သွားတယ်: {e}")
                            st.stop()
                        S.final_segments, S.fitted = None, None
                        _reset_review_keys(S)
                        prog.empty()
                        st.toast(f"✅ {len(S.translations)} scene အတွက် script ရပြီးပြီ")
                        S["wizard_step"] = 4
                        st.rerun()
                if S.translations:
                    with st.expander("🎙️ Narrator script ကြည့်"):
                        for s in S.translations[:20]:
                            st.write(f"`{fmt_ts(s['start'])}` {s['text']}")
                        if len(S.translations) > 20:
                            st.caption(f"...နောက် {len(S.translations) - 20} ခု "
                                       "ကျန်သေးတယ်")
            _spidey_card_close()
        else:
            if not S.src_segments:
                st.caption("အရင်ဆုံး အဆင့် ၁ မှာ " +
                           ("ဗီဒီယိုတင်" if is_video else "SRT ဖိုင်တင်") + "ပါ။")
            elif S.get("srt_is_my"):
                st.info("✅ SRT က မြန်မာလိုအဆင်သင့်မို့ ဘာသာပြန်စရာမလိုဘူး — "
                        "အဆင့် ၄ ကို ဆက်သွားပါ။")
                if S.translations:
                    with st.expander("SRT စာသား ကြည့်"):
                        for s in S.translations[:30]:
                            st.write(f"`{fmt_ts(s['start'])}` {s['text']}")
            elif not api_key:
                st.warning("⚠️ Gemini API key ထည့်မှ ဘာသာပြန်လို့ရမယ် (ဘယ်ဘက် sidebar)။")
            else:
                _drama_name_m = st.text_input(
                    "🎭 ဇာတ်လမ်း အမည်",
                    key="drama_name",
                    placeholder="ဥပမာ: 颠倒世界 (အပိုင်းခွဲလုပ်မှ ထည့်)",
                    help="ဇာတ်လမ်းရှည်ကို အပိုင်းခွဲလုပ်ရင် ဒီနာမည်တူတူ ထည့်ထား — "
                         "ဇာတ်ကောင်နာမည်တွေ အပိုင်းတိုင်း တစ်မျိုးတည်းဖြစ်အောင် "
                         "မှတ်ဉာဏ် share သုံးမယ်")
                _drama_name_m = (_drama_name_m or "").strip()
                _bc3, _ = st.columns([1, 2])
                with _bc3:
                    _go3 = st.button("🌐 သဘာဝကျတဲ့ ပြောစကားမြန်မာလို ပြန်ရန်",
                                     type="primary", use_container_width=True)
                if _go3:
                    prog = st.progress(0.0, "Gemini နဲ့ ဘာသာပြန်နေတယ်...")
                    try:
                        _mid3 = model_id.strip() or GEMINI_MODEL_DEFAULT
                        _mem3 = (load_story_memory(_drama_name_m)
                                 if _drama_name_m else None)
                        if _drama_name_m and not _mem3:
                            prog.progress(0.05, "🧠 ဇာတ်ကောင်မှတ်ဉာဏ် တည်နေတယ်...")
                            _mem3 = build_story_memory(api_key, _mid3,
                                                       S.src_segments)
                            save_story_memory(_drama_name_m, _mem3)
                        result, failed = gemini_translate(
                            api_key, S.src_segments, _mid3,
                            progress_cb=lambda f: prog.progress(f),
                            glossary=glossary, recap=recap_style,
                            story_memory=_mem3)
                    except Exception as e:
                        st.error(f"ဘာသာပြန်တာ ပျက်သွားတယ်: {e}")
                        st.stop()
                    S.translations, S.final_segments, S.fitted = result, None, None
                    _reset_review_keys(S)
                    prog.empty()
                    if failed:
                        st.warning(f"⚠️ {len(failed)} ပိုင်း ပြန်မရလို့ မူရင်းစာသားအတိုင်း ထားထားတယ်")
                    st.toast(f"✅ {len(result)} ပိုင်း ဘာသာပြန်ပြီးပြီ")
                    S["wizard_step"] = 4
                    st.rerun()
                if S.translations:
                    with st.expander("ဘာသာပြန်ချက် ကြည့်"):
                        for s in S.translations[:30]:
                            st.write(f"`{fmt_ts(s['start'])}` {s['text']}")
                            st.caption(f"မူရင်း: {s['src'][:80]}")

            _spidey_card_close()

    if S["wizard_step"] == 4:
        # ---- အဆင့် ၄: review / edit
        _spidey_card_open(4, "စာသားစစ် / ပြင်")
        if not S.translations:
            st.caption("အရင်ဆုံး အဆင့် ၃ မှာ ဘာသာပြန်ပါ။")
        else:
            # 🔍 ပြဿနာလိုင်းရှာသူ — textarea မပေါ်ခင် အရင်စစ်တာ:
            # ဒီအစဉ်လိုက်ထားမှ quick-fix က textarea�ဲ ဒီတစ်ပတ်တည်း တိုက်ရိုက်ရေးလို့ရမယ်
            # (widget ပေါ်ပြီးမှ session_state ပြင်ရင် Streamlit က error ထုတ်လို့)
            _cur_raw = S.get("review_text")
            if _cur_raw is None:
                _cur_raw = segments_to_review_text(S.translations)
            try:
                _work = parse_review_text(_cur_raw)
                _parse_ok = True
            except ValueError:
                _work = S.translations
                _parse_ok = False
            _flags = find_problem_lines(_work, max_speed)
            # ရှည်တဲ့စာတွေ မပြ — တခြားဘာသာစကား/script ညှပ်ပါလာတာပဲ ပြ
            _flags = [(i, r) for (i, r) in _flags if "စာလုံး ပါနေတယ်" in r]
            if _flags:
                with st.expander(
                        f"🔍 တခြားဘာသာစကား ပါနေတဲ့လိုင်းများ ({len(_flags)})",
                        expanded=False):
                    st.caption("တစ်ခုချင်းနှိပ်ပြင်ရုံနဲ့ အောက်ကစာထဲ သူ့အလိုလို ဝင်သွားမယ်")
                    if not _parse_ok:
                        st.warning("အောက်ကစာမှာ ပုံစံမှားနေလို့ ဒီမှာ တိုက်ရိုက်ပြင်မရဘူး — "
                                   "အရင်ပြင်လိုက်ပါ")
                    for (i, _reason) in _flags:
                        _s = _work[i]
                        _fk = f"fixline_{S.run_id}_{i}"
                        _new = st.text_input(
                            f"#{i + 1} `{fmt_ts(_s['start'])} → {fmt_ts(_s['end'])}` — {_reason}",
                            value=_s["text"], key=_fk, disabled=not _parse_ok)
                        if _parse_ok and _new != _s["text"]:
                            _work[i]["text"] = _new
                            S["review_text"] = segments_to_review_text(_work)
                            st.rerun()  # flag စာရင်း ပြန်တွက်ဖို့
            raw = st.text_area(
                "တစ်ကြောင်းချင်း ပြင်လို့ရတယ် — အစဉ်မပြောင်းနဲ့၊ ပုံစံမဖျက်နဲ့",
                value=segments_to_review_text(S.translations), height=300,
                key="review_text")
            _bc4, _ = st.columns([1, 2])
            with _bc4:
                _go4 = st.button("✔️ စစ်ပြီး ဆက်ရန်", type="primary",
                                 use_container_width=True)
            if _go4:
                try:
                    S.final_segments = parse_review_text(raw)
                    S.fitted, S.out_mp4, S.out_mp3 = None, None, None
                    S.recap_timeline, S.recap_report, S.out_subs = None, None, None
                    # 🎭 drama memory: ကိုယ်တိုင်ပြင်ထားတဲ့ မြန်မာနာမည်တွေ မှတ်
                    _drama_name_m4 = (S.get("drama_name") or "").strip()
                    if _drama_name_m4 and api_key:
                        with st.spinner("🧠 မှတ်ဉာဏ်မှာ နာမည်တွေ သိမ်းနေတယ်..."):
                            _src_by_start = {
                                round(t.get("start", 0), 2): t.get("src", "")
                                for t in (S.translations or [])}
                            _pairs = [{
                                "start": fs["start"], "end": fs["end"],
                                "src": _src_by_start.get(round(fs["start"], 2),
                                                        ""),
                                "text": fs["text"]}
                                for fs in S.final_segments]
                            _mem4 = (load_story_memory(_drama_name_m4) or
                                     {"characters": [], "places": [],
                                      "terms": []})
                            _mem4 = update_story_memory(
                                api_key,
                                model_id.strip() or GEMINI_MODEL_DEFAULT,
                                _mem4, _pairs)
                            save_story_memory(_drama_name_m4, _mem4)
                    st.toast(f"✅ {len(S.final_segments)} ပိုင်း အတည်ပြုပြီးပြီ")
                    S["wizard_step"] = 5
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

        _spidey_card_close()

    if S["wizard_step"] == 5:
        # ---- အဆင့် ၅: TTS + fit
        _spidey_card_open(5, "မြန်မာအသံထုတ် + အချိန်ချိန်")
        if not S.final_segments:
            st.caption("အရင်ဆုံး အဆင့် ၄ မှာ စာသားအတည်ပြုပါ။")
        else:
            st.caption("အသံတစ်ကြောင်းချင်းကို သူ့အချိန်ကွက်ထဲ အတိအကျထည့်မယ် — "
                       f"ရှည်ရင် {max_speed}x အထိ မြန်ပေးမယ်၊ နောက်အပိုင်းနဲ့ ဘယ်တော့မှ မထပ်စေဘူး။")
            _bc5, _ = st.columns([1, 2])
            with _bc5:
                _go5 = st.button("🔊 အသံထုတ်ရန်", type="primary",
                                 use_container_width=True)
            if _go5:
                work_segs = os.path.join(WORK_DIR, S.run_id, "segs")
                prog = st.progress(0.0)
                curlbl = st.empty()
                def cb(f, i, t):
                    prog.progress(f)
                    curlbl.text(f"အပိုင်း {i + 1}/{len(S.final_segments)}: {t}")
                S.auto_shortened = False
                fitted, report = tts_and_fit(S.final_segments, voice, max_speed,
                                             work_segs, progress_cb=cb)
                # စာရှည်လို့ အချိန်ကွက်ထဲ မဝင်တဲ့လိုင်းတွေ → Gemini နဲ့ အလိုအလျောက်တိုပေး
                if auto_shorten and report["overflow"] and api_key:
                    items = [{"id": i, "text": t,
                              "target_chars": max(4, int(len(t) / ratio * 1.15))}
                             for (i, _s, _e, t, ratio) in report["overflow"]]
                    with st.status("✂️ Gemini နဲ့ စာရှည်တဲ့လိုင်းတွေ တိုအောင်ပြင်နေတယ်...",
                                   expanded=False):
                        short = gemini_shorten(api_key,
                                               model_id.strip() or GEMINI_MODEL_DEFAULT,
                                               items, glossary=glossary)
                    applied = 0
                    for (i, _s, _e, t, _r) in report["overflow"]:
                        if i in short and short[i] != t:
                            S.final_segments[i]["text"] = short[i]
                            applied += 1
                    if applied:
                        # တိုထားတဲ့စာသားနဲ့ အသံပြန်ထုတ် (တစ်ကြိမ်သာ — cache ကြောင့်
                        # မပြောင်းတဲ့လိုင်းတွေ အသံပြန်ထုတ်စရာ မလိုဘူး)
                        fitted, report = tts_and_fit(S.final_segments, voice, max_speed,
                                                     work_segs, progress_cb=cb)
                        S.auto_shortened = True
                        st.info(f"✂️ Gemini က {applied} လိုင်း တိုအောင်ပြင်ပြီးပြီ — "
                                "အသံပြန်ထုတ်ထားတယ်")
                S.fitted, S.fit_report, S.out_mp4, S.out_mp3 = fitted, report, None, None
                S.recap_timeline, S.recap_report, S.out_subs = None, None, None
                prog.empty(); curlbl.empty()
                st.toast(f"✅ အပိုင်း {len(fitted)} ပိုင်း အသံထွက်ပြီးပြီ")
                S["wizard_step"] = 6
                st.rerun()
        _spidey_card_close()

    if S["wizard_step"] == 6:
        # ---- အဆင့် ၆: assemble + download
        _spidey_card_open(6, "ဗီဒီယိုနဲ့ပေါင်း + Download"
                          if is_video else "အသံဖိုင် Download")
        # recap render မုဒ်ဆို အဆင့် ၅ (fit) မလိုဘူး — သဘာဝအသံကနေ တိုက်ရိုက်တွက်မယ်
        _can_render = bool(S.fitted) or (recap_render and bool(S.final_segments))
        if not _can_render:
            st.caption("အရင်ဆုံး အဆင့် ၅ မှာ အသံထုတ်ပါ။")
        else:
            if is_video:
                _bc6, _ = st.columns([1, 2])
                with _bc6:
                    _go6 = st.button(
                        "🎞️ Recap render (video ချိန် + ပေါင်း)" if recap_render
                        else "🎬 မူရင်းဗီဒီယိုနဲ့ ပေါင်းရန်",
                        type="primary", use_container_width=True)
                if _go6:
                    work_asm = os.path.join(WORK_DIR, S.run_id, "asm")
                    dubbed = os.path.join(WORK_DIR, S.run_id, "dubbed_audio.mp3")
                    out = os.path.join(WORK_DIR, S.run_id, "dubbed_video.mp4")
                    with st.status("အသံဆက် + ဗီဒီယိုနဲ့ပေါင်းနေတယ်...", expanded=False):
                        if recap_render and S.final_segments and S.video_path:
                            # 🎞️ recap render: သဘာဝအသံထုတ် → video ချိန် → mux
                            work_nat = os.path.join(WORK_DIR, S.run_id, "natural")
                            _pn = st.progress(0.0, "Recap အသံ သဘာဝအတိုင်းထုတ်နေတယ်...")
                            natural, _failed_n = tts_natural(
                                S.final_segments, voice, work_nat,
                                progress_cb=lambda f, i, t: _pn.progress(f))
                            _pn.empty()
                            if _failed_n:
                                st.warning(f"🔇 အသံထုတ်မရတဲ့အပိုင်း {len(_failed_n)} ခု "
                                           "ကျော်သွားမယ်")
                            work_rc = os.path.join(WORK_DIR, S.run_id, "recap")
                            _tmp_out = os.path.join(work_rc, "recap_video.mp4")
                            _, S.recap_timeline, S.recap_report = render_recap_video(
                                S.video_path, natural, S.duration, work_rc, _tmp_out)
                            _stage = _tmp_out
                            _subs = [dict(s) for s in S.recap_timeline]
                            _extreme = [(i, f) for (i, f, _n) in (S.recap_report or [])
                                        if f < 0.5 or f > 2.0]
                            if _extreme:
                                st.info("🎞️ Video အမြန်/အနှေးချိန်ထားတာ: " +
                                        ", ".join(f"#{i + 1} x{f:.2f}"
                                                  for i, f in _extreme[:10]) +
                                        ("…" if len(_extreme) > 10 else ""))
                        else:
                            assemble_dubbed(S.fitted, S.duration, work_asm, dubbed)
                            _final_audio = dubbed
                            mux_video(S.video_path, _final_audio, out)
                            S.recap_timeline, S.recap_report, S.out_subs = None, None, None
                            _stage = out
                            _subs = [dict(s) for s in S.final_segments]
                        # ⚡ speed-up (download မချခင် — video+audio အတူ, sync မပျက်)
                        if speedup > 1.0:
                            _spd = os.path.join(WORK_DIR, S.run_id, "spedup.mp4")
                            speedup_video(_stage, speedup, _spd)
                            _stage = _spd
                            _subs = [{"start": s["start"] / speedup,
                                      "end": s["end"] / speedup,
                                      "text": s["text"]} for s in _subs]
                        if _stage != out:
                            shutil.copyfile(_stage, out)
                        S.out_subs = _subs
                    S.out_mp4 = out
                    st.success("✅ ပြီးပြီ! အောက်မှာ download ချလို့ရပြီ")
            else:
                _bc6s, _ = st.columns([1, 2])
                with _bc6s:
                    _go6s = st.button("🎧 အသံဖိုင်ထုတ်ရန်", type="primary",
                                      use_container_width=True)
                if _go6s:
                    work_asm = os.path.join(WORK_DIR, S.run_id, "asm")
                    out = os.path.join(WORK_DIR, S.run_id, "dubbed_voiceover.mp3")
                    with st.status("အသံဆက်နေတယ်...", expanded=False):
                        assemble_dubbed(S.fitted, S.duration, work_asm, out)
                    S.out_mp3 = out
                    st.success("✅ ပြီးပြီ! အောက်မှာ download ချလို့ရပြီ")
            _has_out = ((S.out_mp4 and os.path.isfile(S.out_mp4)) or
                        (S.out_mp3 and os.path.isfile(S.out_mp3)))
            if _has_out or S.final_segments:
                # 👀 မဒေါင်းခင် preview အရင်ကြည့်
                if S.out_mp4 and os.path.isfile(S.out_mp4):
                    st.video(S.out_mp4)
                elif S.out_mp3 and os.path.isfile(S.out_mp3):
                    st.audio(S.out_mp3)
                # ဖိုင်အသစ်တင်တိုင်း အမည်အကြံကို refresh (ရိုက်ထားတာကို မဖျက်)
                if S.get("_dl_for") != S.run_id:
                    _base = (S.get("dl_base") or "audio").strip() or "audio"
                    S["dl_name"] = f"{_base}_dubbed"
                    S["_dl_for"] = S.run_id
                st.text_input("📝 ဖိုင်နာမည်", key="dl_name",
                              help="download ချမယ့်အမည် — .mp4/.mp3/.srt ကို သူ့အလိုလို ထည့်ပေးမယ်")
                _dl = re.sub(r'[\\/:*?"<>|]', "_", (S.get("dl_name") or "").strip())
                if not _dl:
                    _dl = "dubbed"
            st.markdown('<div class="spidey-dl-label">📥 ရလာဒ်များ</div>',
                        unsafe_allow_html=True)
            _dc = st.columns(3)
            _di = 0
            if S.out_mp4 and os.path.isfile(S.out_mp4):
                with _dc[_di], open(S.out_mp4, "rb") as f:
                    st.download_button("⬇️ Dubbed MP4", f, file_name=f"{_dl}.mp4",
                                       mime="video/mp4", type="primary",
                                       use_container_width=True)
                _di += 1
            if S.out_mp3 and os.path.isfile(S.out_mp3):
                with _dc[_di], open(S.out_mp3, "rb") as f:
                    st.download_button("⬇️ Dubbed MP3", f, file_name=f"{_dl}.mp3",
                                       mime="audio/mpeg", type="primary",
                                       use_container_width=True)
                _di += 1
            if S.final_segments:
                with _dc[_di]:
                    # render မှာ သုံးတဲ့ timeline အတိုင်း (speedup ပါရင် ချိန်ပြီးသား)
                    _srt_segs = S.out_subs or S.recap_timeline or S.final_segments
                    st.download_button("⬇️ SRT", segments_to_srt(_srt_segs),
                                       file_name=f"{_dl}.srt", mime="text/plain",
                                       use_container_width=True)
        _spidey_card_close()
    # ---- wizard အောက် nav: စာအပေါ်, ခလုတ် ၂ ခု ဘေးချင်းကပ်
    _cur = max(1, min(6, int(S.get("wizard_step", 1))))
    st.caption(f"အဆင့် {_cur} / 6")
    _show_back = _cur > 1
    _show_next = _cur < 6
    if _show_back and _show_next:
        _b1, _b2 = st.columns(2)
        with _b1:
            st.markdown('<div class="wiz-bnav-col"></div>',
                        unsafe_allow_html=True)
            if st.button("◀️ ပြန်သွား", key="wiz_back",
                         use_container_width=True):
                S["wizard_step"] = _cur - 1
                st.rerun()
        with _b2:
            if st.button("ဆက်သွား ▶️", key="wiz_next", type="primary",
                         use_container_width=True):
                S["wizard_step"] = _cur + 1
                st.rerun()
    elif _show_back:
        if st.button("◀️ ပြန်သွား", key="wiz_back", use_container_width=True):
            S["wizard_step"] = _cur - 1
            st.rerun()
    elif _show_next:
        if st.button("ဆက်သွား ▶️", key="wiz_next", type="primary",
                     use_container_width=True):
            S["wizard_step"] = _cur + 1
            st.rerun()
    st.markdown(
        '<div class="spidey-foot">🕷️ Audio Dub Studio — '
        "your friendly neighborhood dubbing tool 🕸️</div>",
        unsafe_allow_html=True)


if __name__ == "__main__":
    main()
