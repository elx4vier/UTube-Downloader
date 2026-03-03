import logging
import requests
import json
import os
import io
import re
import subprocess
import locale
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from PIL import Image, ImageOps, ImageDraw

from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction
from ulauncher.api.shared.action.SetUserQueryAction import SetUserQueryAction
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction

logger = logging.getLogger(__name__)

# =========================
# UTILIDADES XDG
# =========================
def get_xdg_dir(name):
    try:
        path = subprocess.getoutput(f"xdg-user-dir {name}")
        if os.path.exists(path):
            return path
    except:
        pass
    return os.path.expanduser("~")

# =========================
# EXTENSÃO
# =========================
class UTubeDownloader(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(ItemEnterEvent, ItemEnterEventListener())

        self.cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "ulauncher-utube-downloader")
        os.makedirs(self.cache_dir, exist_ok=True)

        self.executor = ThreadPoolExecutor(max_workers=4)
        self.session = requests.Session()
        self.search_cache = OrderedDict()

        self.yt_regex = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+")

        self.translations = self.load_translations()

        try:
            subprocess.check_output(["yt-dlp", "--version"])
            self.ytdlp_ok = True
        except Exception:
            self.ytdlp_ok = False

    def load_translations(self):
        lang = "en"
        try:
            default_lang = locale.getdefaultlocale()[0]
            if default_lang:
                lang = default_lang
        except:
            pass
            
        lang_short = lang.split("_")[0]
        base_path = os.path.join(os.path.dirname(__file__), "translations")

        def load_file(code):
            try:
                path = os.path.join(base_path, f"{code}.json")
                if os.path.exists(path):
                    with open(path, encoding="utf-8") as f:
                        return json.load(f)
            except:
                pass
            return {}

        fallback = load_file("en")
        data = load_file(lang)
        if not data:
            data = load_file(lang_short)

        fallback.update(data)
        return fallback

    def t(self, key, **kwargs):
        text = self.translations.get(key, key)
        return text.format(**kwargs)

    def format_time_ago(self, text):
        if not text:
            return ""
        try:
            parts = text.split()
            num = int(parts[0])
            unit = parts[1].lower()
            plural = num > 1

            mapping = {
                "minute": "minutes" if plural else "minute",
                "hour": "hours" if plural else "hour",
                "day": "days" if plural else "day",
                "week": "weeks" if plural else "week",
                "month": "months" if plural else "month",
                "year": "years" if plural else "year"
            }

            unit_key = mapping.get(unit.rstrip("s"), unit)
            word = self.t(unit_key)
            ago = self.t("ago")

            prefix_languages = ["há", "hace", "il y a", "vor"]
            if ago.lower() in prefix_languages:
                return f"{ago} {num} {word}"
            else:
                return f"{num} {word} {ago}"
        except:
            return text

    def get_prefs(self):
        p = self.preferences
        return {
            "download_mode": p.get("download_mode", "separate"),
            "max_results": int(p.get("max_results", 6)),
            "show_thumbs": p.get("show_thumbs", "yes") == "yes",
            "open_folder": p.get("open_folder", "yes") == "yes"
        }

    def process_thumbnail(self, v_id, url):
        path = os.path.join(self.cache_dir, f"{v_id}.png")
        if os.path.exists(path):
            return path
        try:
            r = self.session.get(url, timeout=(1, 2), stream=True)
            if r.status_code != 200:
                return None

            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            img = ImageOps.fit(img, (100, 100), Image.LANCZOS)

            mask = Image.new("L", (100, 100), 0)
            draw = ImageDraw.Draw(mask)
            draw.rounded_rectangle((0, 0, 100, 100), radius=15, fill=255)

            img.putalpha(mask)
            img.save(path, "PNG")
            return path
        except:
            return None


# =========================
# 🔍 SEARCH
# =========================
class KeywordQueryEventListener(EventListener):
    def on_event(self, event, extension):
        prefs = extension.get_prefs()
        t = extension.t

        query = (event.get_argument() or "").strip()
        keyword = event.get_keyword()

        if extension.yt_regex.match(query):
            return RenderResultListAction([
                ExtensionResultItem(
                    icon="images/video.png",
                    name=t("quality_max"),
                    description=t("quality_max_desc"),
                    on_enter=ExtensionCustomAction({
                        "url": query, "mode": "video", "quality": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best", "action": "download"
                    })
                ),
                ExtensionResultItem(
                    icon="images/video.png",
                    name=t("quality_med"),
                    description=t("quality_med_desc"),
                    on_enter=ExtensionCustomAction({
                        "url": query, "mode": "video", "quality": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best", "action": "download"
                    })
                ),
                ExtensionResultItem(
                    icon="images/video.png",
                    name=t("quality_low"),
                    description=t("quality_low_desc"),
                    on_enter=ExtensionCustomAction({
                        "url": query, "mode": "video", "quality": "bestvideo[height<=320][ext=mp4]+bestaudio[ext=m4a]/best[height<=320][ext=mp4]/best", "action": "download"
                    })
                ),
                ExtensionResultItem(
                    icon="images/audio.png",
                    name=t("audio_lossless"),
                    description=t("audio_lossless_desc"),
                    on_enter=ExtensionCustomAction({
                        "url": query, "mode": "audio", "format": "flac", "quality": "0", "action": "download"
                    })
                ),
                ExtensionResultItem(
                    icon="images/audio.png",
                    name=t("audio_standard"),
                    description=t("audio_standard_desc"),
                    on_enter=ExtensionCustomAction({
                        "url": query, "mode": "audio", "format": "mp3", "quality": "128", "action": "download"
                    })
                ),
                ExtensionResultItem(
                    icon="images/audio.png",
                    name=t("audio_light"),
                    description=t("audio_light_desc"),
                    on_enter=ExtensionCustomAction({
                        "url": query, "mode": "audio", "format": "mp3", "quality": "96", "action": "download"
                    })
                ),
            ])

        if query.startswith("http"):
            return RenderResultListAction([
                ExtensionResultItem(
                    icon="images/icon.png",
                    name=t("invalid_link"),
                    description=t("invalid_link_desc"),
                    on_enter=DoNothingAction()
                )
            ])

        if len(query) < 3:
            return RenderResultListAction([
                ExtensionResultItem(
                    icon="images/icon.png",
                    name=t("app_name"),
                    description=t("search_prompt"),
                    on_enter=DoNothingAction()
                )
            ])

        try:
            r = extension.session.get(
                f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}",
                timeout=3
            )

            text = r.text
            json_str = text.split("var ytInitialData = ")[1].split(";</script>")[0].rstrip(";")
            data = json.loads(json_str)

            results = data["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"][
                "sectionListRenderer"]["contents"][0]["itemSectionRenderer"]["contents"]

            items = []
            for res in results:
                v = res.get("videoRenderer")
                if v and len(items) < prefs["max_results"]:

                    thumb = "images/icon.png"
                    if prefs["show_thumbs"]:
                        thumb = extension.process_thumbnail(
                            v["videoId"],
                            v["thumbnail"]["thumbnails"][-1]["url"]
                        ) or thumb

                    year = v.get("publishedTimeText", {}).get("simpleText", "")
                    year = extension.format_time_ago(year)

                    base_desc = f"{v.get('lengthText', {}).get('simpleText', '--:--')} · {v['longBylineText']['runs'][0]['text']}"
                    full_description = f"{base_desc} · {year}" if year.strip() else base_desc

                    items.append(
                        ExtensionResultItem(
                            icon=thumb,
                            name=v["title"]["runs"][0]["text"],
                            description=full_description,
                            on_enter=SetUserQueryAction(f"{keyword} https://www.youtube.com/watch?v={v['videoId']}")
                        )
                    )

            if not items:
                msg = t("no_results")
            else:
                return RenderResultListAction(items)

        except:
            msg = t("search_failed")

        return RenderResultListAction([
            ExtensionResultItem(
                icon="images/icon.png",
                name=msg,
                on_enter=DoNothingAction()
            )
        ])

# =========================
# ⬇️ DOWNLOAD
# =========================
class ItemEnterEventListener(EventListener):
    def on_event(self, event, extension):
        prefs = extension.get_prefs()
        t = extension.t
        data = event.get_data()

        if data.get("action") != "download":
            return

        if not extension.ytdlp_ok:
            subprocess.Popen(["notify-send", "-a", "Ulauncher", "-i", "dialog-error", t("app_name"), t("ytdlp_missing")])
            return

        if prefs["download_mode"] == "separate":
            folder_base = get_xdg_dir("MUSIC") if data.get("mode") == "audio" else get_xdg_dir("VIDEOS")
        else:
            folder_base = get_xdg_dir("DOWNLOAD")

        # ABRIR PASTA IMEDIATAMENTE (Assim que o download é solicitado)
        if prefs["open_folder"]:
            subprocess.Popen(["xdg-open", folder_base])

        def run():
            try:
                cmd = [
                    "yt-dlp",
                    "--no-part",
                    "--restrict-filenames",
                    "--windows-filenames",
                    "--print", "after_move:filepath",
                    "-o", f"{folder_base}/%(title)s.%(ext)s"
                ]

                if data.get("mode") == "audio":
                    fmt = data.get("format", "mp3")
                    cmd.extend(["-f", "bestaudio", "-x", "--audio-format", fmt])
                    if fmt == "mp3":
                        cmd.extend(["--audio-quality", data["quality"]])
                else:
                    cmd.extend(["-f", data["quality"], "--merge-output-format", "mp4"])

                cmd.append(data["url"])
                
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                full_path = result.stdout.strip().split('\n')[-1]
                final_filename = os.path.basename(full_path)

                subprocess.Popen([
                    "notify-send",
                    "-a", "Ulauncher",
                    "-i", "folder-download",
                    "-t", "5000",
                    t("app_name"),
                    t("download_complete", name=final_filename, folder=os.path.basename(folder_base))
                ])
            except:
                subprocess.Popen(["notify-send", "-a", "Ulauncher", "-i", "error", t("app_name"), t("download_failed")])

        extension.executor.submit(run)


if __name__ == "__main__":
    UTubeDownloader().run()
