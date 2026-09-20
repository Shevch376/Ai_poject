import calendar
import json
import logging
import os
import re
import threading
import webbrowser
from datetime import datetime, date, timedelta
from urllib.parse import urlencode
import requests
import websocket
from kivymd.app import MDApp
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.lang import Builder
from kivy.core.window import Window
from kivy.core.clipboard import Clipboard
from kivy.animation import Animation
from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import NumericProperty, StringProperty, ListProperty, BooleanProperty, DictProperty, ObjectProperty
from kivy.utils import platform
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.relativelayout import MDRelativeLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.button import Button
from kivy.uix.image import AsyncImage

for logger_name in ("urllib3", "urllib3.connectionpool", "requests", "websocket"):
    logging.getLogger(logger_name).setLevel(logging.WARNING)
    logging.getLogger(logger_name).propagate = False

if platform not in ("android", "ios"):
    Window.size = (375, 812)


API_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "api_config.json")


def resolve_api_base_url():
    env_url = os.environ.get("XOLIDAY_API_BASE_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as config_file:
            config = json.load(config_file)
        config_url = str(config.get("api_base_url") or "").strip()
        if config_url:
            return config_url.rstrip("/")
    except (OSError, ValueError, TypeError):
        pass
    return "http://10.0.2.2:8000" if platform == "android" else "http://127.0.0.1:8000"


API_BASE_URL = resolve_api_base_url()
GOOGLE_MOBILE_CLIENT_ID = "725770696366-9cabppf5iepcdbcoi30tl44qkqu7prcr.apps.googleusercontent.com"
GOOGLE_SIGN_IN_REQUEST_CODE = 9107
THEME_SETTINGS_PATH = os.path.join(os.path.dirname(__file__), ".theme_settings.json")
DEFAULT_LOCATION = {
    "latitude": 56.4846,
    "longitude": 84.9482,
}
DEFAULT_CHAT_MESSAGE_LIMIT = 100
CHAT_RENDER_WINDOW_SIZE = 8
CHAT_RENDER_WINDOW_STEP = 4


def resolve_chat_message_limit():
    candidate_paths = [
        os.path.join(os.path.dirname(__file__), "openapi_new.json"),
        os.path.join(os.path.expanduser("~"), "Downloads", "openapi_new.json"),
    ]
    for path in candidate_paths:
        try:
            with open(path, "r", encoding="utf-8") as openapi_file:
                openapi = json.load(openapi_file)
            params = (
                openapi.get("paths", {})
                .get("/api/v1/chats/{chat_id}/messages", {})
                .get("get", {})
                .get("parameters", [])
            )
            for param in params:
                schema = param.get("schema") or {}
                if param.get("name") == "limit" and schema.get("maximum"):
                    return int(schema.get("maximum"))
        except (OSError, ValueError, TypeError):
            continue
    return DEFAULT_CHAT_MESSAGE_LIMIT


CHAT_MESSAGE_LIMIT = resolve_chat_message_limit()

class FilterChip(ButtonBehavior, MDRelativeLayout):
    text = StringProperty("")
    selected = BooleanProperty(False)


class DayTile(ButtonBehavior, MDRelativeLayout):
    day_num = StringProperty("")
    day_name = StringProperty("")
    is_selected = BooleanProperty(False)
    is_today = BooleanProperty(False)
    in_current_month = BooleanProperty(True)


class PrivacyItem(MDBoxLayout):
    text = StringProperty("")
    secondary_text = StringProperty("")
    icon = StringProperty("")
    active = BooleanProperty(False)


class FeatureItem(MDBoxLayout):
    text = StringProperty("")
    icon = StringProperty("")


class ChatBubble(MDBoxLayout):
    message_id = NumericProperty(0)
    text = StringProperty("")
    display_text = StringProperty("")
    sender = StringProperty("user")
    bubble_type = StringProperty("text")
    meta_text = StringProperty("")
    cards = ListProperty([])
    reaction_type = StringProperty("")
    is_pending = BooleanProperty(False)
    bubble_width = NumericProperty(dp(180))
    cards_area_height = NumericProperty(0)
    row_opacity = NumericProperty(1)
    row_y_offset = NumericProperty(0)

    def on_text(self, *_args):
        self.display_text = self.format_display_text(self.text)

    def on_sender(self, *_args):
        self.display_text = self.format_display_text(self.text)

    def format_display_text(self, value):
        if self.sender != "ai":
            return self.escape_markup(value or "")
        return self.markdown_to_kivy_markup(self.clean_ai_text(value or ""))

    @staticmethod
    def escape_markup(value):
        return str(value).replace("&", "&amp;").replace("[", "&bl;").replace("]", "&br;")

    @staticmethod
    def clean_ai_text(value):
        text = str(value).replace("\ufe0f", "")
        # Kivy's bundled fonts often render emoji as tofu boxes.
        text = re.sub(r"[\U0001F000-\U0001FAFF]", "", text)
        text = re.sub(r"[\u2300-\u2BFF]", "", text)
        text = re.sub(r"\s+([:,.!?])", r"\1", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        return text.strip()

    def markdown_to_kivy_markup(self, value):
        formatted_lines = []
        previous_was_empty = False
        for raw_line in str(value).splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                if formatted_lines and not previous_was_empty:
                    formatted_lines.append("")
                previous_was_empty = True
                continue
            previous_was_empty = False
            if stripped.startswith(("- ", "* ")):
                item = stripped[2:].strip()
                formatted_lines.append(self.format_structured_line(item))
                continue
            if stripped.startswith("### "):
                formatted_lines.append(f"[b]{self.escape_markup(stripped[4:].strip())}[/b]")
                continue
            if stripped.startswith("## "):
                formatted_lines.append(f"[b]{self.escape_markup(stripped[3:].strip())}[/b]")
                continue
            if stripped.startswith("# "):
                formatted_lines.append(f"[b]{self.escape_markup(stripped[2:].strip())}[/b]")
                continue
            formatted_lines.append(self.format_structured_line(line))
        return "\n".join(formatted_lines)

    def format_structured_line(self, value):
        value = str(value).strip()
        value = re.sub(r"^\*\*([^*]+):\*\*\s*(.*)$", r"\1: \2", value)
        value = re.sub(r"^\*\*([^*]+)\*\*:\s*(.*)$", r"\1: \2", value)
        match = re.match(r"^([A-Za-z][A-Za-z /&-]{1,34}):\s*(.*)$", value)
        if match:
            label = self.escape_markup(match.group(1).strip())
            content = self.format_inline_markdown(match.group(2).strip())
            return f"[b]{label}:[/b] {content}".rstrip()
        return self.format_inline_markdown(value)

    def format_inline_markdown(self, value):
        link_pattern = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
        result = []
        last_end = 0
        for match in link_pattern.finditer(value):
            result.append(self.format_bold_markdown(value[last_end:match.start()]))
            label = self.escape_markup(match.group(1))
            result.append(f"[b]{label}[/b]")
            last_end = match.end()
        result.append(self.format_bold_markdown(value[last_end:]))
        return "".join(result)

    def format_bold_markdown(self, value):
        parts = re.split(r"(\*\*[^*]+\*\*)", value)
        formatted = []
        for part in parts:
            if part.startswith("**") and part.endswith("**") and len(part) > 4:
                formatted.append(f"[b]{self.escape_markup(part[2:-2])}[/b]")
            else:
                formatted.append(self.escape_markup(part))
        return "".join(formatted)

    def open_link(self, url):
        if url:
            webbrowser.open(url)

    def copy_text(self):
        if self.text:
            Clipboard.copy(self.text)
            app = MDApp.get_running_app()
            if app.sm.has_screen("chat"):
                app.sm.get_screen("chat").show_toast("Copied")

    def refresh_chat(self):
        app = MDApp.get_running_app()
        if app.sm.has_screen("chat"):
            app.sm.get_screen("chat").refresh_current_chat()

    def set_reaction(self, reaction_type):
        if not self.message_id:
            return
        threading.Thread(target=self._send_reaction_request, args=(reaction_type,), daemon=True).start()

    def _send_reaction_request(self, reaction_type):
        app = MDApp.get_running_app()
        try:
            if self.reaction_type == reaction_type:
                app.delete_message_reaction(self.message_id)
                Clock.schedule_once(lambda dt: setattr(self, "reaction_type", ""), 0)
            else:
                if self.reaction_type:
                    app.delete_message_reaction(self.message_id)
                app.add_message_reaction(self.message_id, reaction_type)
                Clock.schedule_once(lambda dt: setattr(self, "reaction_type", reaction_type), 0)
        except Exception:
            return

    def stop_generation(self):
        app = MDApp.get_running_app()
        if self.is_pending and app.sm.has_screen("chat"):
            app.sm.get_screen("chat").cancel_generation()
            return
        if not self.message_id:
            return
        threading.Thread(target=lambda: app.stop_message_generation(self.message_id), daemon=True).start()


class ChatActionButton(ButtonBehavior, MDRelativeLayout):
    icon = StringProperty("")
    selected = BooleanProperty(False)


class ChatCardsCanvas(Widget):
    cards = ListProperty([])
    card_height = NumericProperty(dp(94))
    card_spacing = NumericProperty(dp(10))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._card_hitboxes = []
        self.bind(pos=self.schedule_redraw, size=self.schedule_redraw, cards=self.schedule_redraw)
        Clock.schedule_once(lambda dt: self.redraw(), 0)

    def schedule_redraw(self, *_args):
        Clock.schedule_once(lambda dt: self.redraw(), 0)

    def redraw(self):
        self.canvas.clear()
        self._card_hitboxes = []
        if not self.cards or self.width <= 0:
            return
        app = MDApp.get_running_app()
        with self.canvas:
            for index, card in enumerate(self.cards):
                y = self.top - ((index + 1) * self.card_height) - (index * self.card_spacing)
                self._draw_card(app, card, self.x, y, self.width, self.card_height, index)

    def _draw_card(self, app, card, x, y, width, height, index):
        radius = dp(16)
        Color(*app.card_bg_color)
        RoundedRectangle(pos=(x, y), size=(width, height), radius=[radius])
        Color(*app.card_border_color)
        Line(rounded_rectangle=[x, y, width, height, radius], width=1)
        pad_x = dp(12)
        title_y = y + height - dp(27)
        text_width = max(1, width - dp(58))
        self._draw_text(card.get("title", ""), x + pad_x, title_y, text_width, app.primary_text_color, sp(15), bold=True)
        bookmark_color = app.card_accent_text_color if card.get("is_favorite") else app.muted_text_color
        bookmark_rect = (x + width - dp(34), y + height - dp(31), dp(24), dp(24))
        self._draw_bookmark(bookmark_rect, bookmark_color, bool(card.get("is_favorite")))
        detail_lines = [
            self._ellipsize(card.get("subtitle", ""), max(4, int((width - dp(24)) / sp(5.8)))),
            self._ellipsize(card.get("description", ""), max(4, int((width - dp(24)) / sp(5.6)))),
            self._ellipsize(
                "  ".join(part for part in (str(card.get("meta_left") or ""), str(card.get("meta_right") or "")) if part),
                max(4, int((width - dp(24)) / sp(5.4))),
            ),
        ]
        self._draw_text("\n".join(line for line in detail_lines if line), x + pad_x, y + dp(28), width - dp(24), app.card_subtitle_color, sp(11))
        self._draw_text(card.get("accent_text", ""), x + pad_x, y + dp(8), width - dp(24), app.card_accent_text_color, sp(10.5))
        self._card_hitboxes.append(
            {
                "index": index,
                "card": card,
                "rect": (x, y, width, height),
                "bookmark": bookmark_rect,
            }
        )

    def _draw_text(self, value, x, y, width, color, font_size, bold=False):
        text = self._ellipsize(str(value or ""), max(4, int(width / max(1, font_size * 0.48))))
        if not text:
            return
        label = CoreLabel(text=text, font_size=font_size, bold=bold, color=color)
        label.refresh()
        Color(1, 1, 1, 1)
        Rectangle(texture=label.texture, pos=(x, y), size=label.texture.size)

    def _draw_bookmark(self, rect, color, filled):
        x, y, width, height = rect
        icon_x = x + dp(8)
        icon_y = y + dp(5)
        icon_w = dp(8)
        icon_h = dp(14)
        Color(*color)
        if filled:
            Rectangle(pos=(icon_x, icon_y), size=(icon_w, icon_h))
            Color(*MDApp.get_running_app().card_bg_color)
            Line(points=[icon_x, icon_y, icon_x + icon_w / 2, icon_y + dp(4), icon_x + icon_w, icon_y], width=1.2)
        else:
            Line(rectangle=[icon_x, icon_y, icon_w, icon_h], width=1.2)

    @staticmethod
    def _ellipsize(value, limit):
        value = " ".join(str(value or "").split())
        if len(value) <= limit:
            return value
        return value[: max(1, limit - 3)].rstrip() + "..."

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        for hitbox in self._card_hitboxes:
            bx, by, bw, bh = hitbox["bookmark"]
            if bx <= touch.x <= bx + bw and by <= touch.y <= by + bh:
                self.toggle_card_favorite(hitbox["card"])
                return True
            x, y, width, height = hitbox["rect"]
            if x <= touch.x <= x + width and y <= touch.y <= y + height:
                self.open_card_details(hitbox["card"])
                return True
        return False

    def toggle_card_favorite(self, card):
        card_id = card.get("base_card_id") or 0
        if not card_id:
            return
        threading.Thread(target=self._toggle_favorite_request, args=(card,), daemon=True).start()

    def _toggle_favorite_request(self, card):
        app = MDApp.get_running_app()
        try:
            if card.get("is_favorite"):
                app.remove_favorite_card(card.get("base_card_id"))
                new_value = False
            else:
                app.add_favorite_card(card.get("base_card_id"))
                new_value = True
            Clock.schedule_once(lambda dt: self._apply_favorite_state(card, new_value), 0)
        except Exception:
            return

    def _apply_favorite_state(self, card, value):
        card["is_favorite"] = value
        self.cards = list(self.cards)
        self.redraw()

    def open_card_details(self, card):
        app = MDApp.get_running_app()
        card_id = card.get("base_card_id") or 0
        if not card_id:
            return
        detail_screen = app.sm.get_screen("saved_detail")
        detail_screen.source_screen = "chat"
        detail_screen.open_card(card_id, card.get("card_type") or "place")
        app.switch_screen("saved_detail", "left")


class ChatMiniCard(ButtonBehavior, BoxLayout):
    base_card_id = NumericProperty(0)
    card_type = StringProperty("place")
    title = StringProperty("")
    subtitle = StringProperty("")
    description = StringProperty("")
    meta_left = StringProperty("")
    meta_right = StringProperty("")
    accent_text = StringProperty("")
    image_url = StringProperty("")
    has_image = BooleanProperty(False)
    is_favorite = BooleanProperty(False)

    def toggle_favorite(self):
        app = MDApp.get_running_app()
        if not self.base_card_id:
            return
        threading.Thread(target=self._toggle_favorite_request, daemon=True).start()

    def _toggle_favorite_request(self):
        app = MDApp.get_running_app()
        try:
            if self.is_favorite:
                app.remove_favorite_card(self.base_card_id)
                Clock.schedule_once(lambda dt: setattr(self, "is_favorite", False), 0)
            else:
                app.add_favorite_card(self.base_card_id)
                Clock.schedule_once(lambda dt: setattr(self, "is_favorite", True), 0)
        except Exception:
            return

    def open_details(self):
        app = MDApp.get_running_app()
        if not self.base_card_id:
            return
        detail_screen = app.sm.get_screen("saved_detail")
        detail_screen.source_screen = "chat"
        detail_screen.open_card(self.base_card_id, self.card_type)
        app.switch_screen("saved_detail", "left")

    def on_release(self):
        self.open_details()


class FavoriteCardRow(ButtonBehavior, MDBoxLayout):
    base_card_id = NumericProperty(0)
    card_type = StringProperty("place")
    title = StringProperty("")
    subtitle = StringProperty("")
    description = StringProperty("")
    meta_left = StringProperty("")
    meta_right = StringProperty("")
    image_url = StringProperty("")
    has_image = BooleanProperty(False)
    source_screen = StringProperty("saved_screen")

    def on_release(self):
        app = MDApp.get_running_app()
        detail_screen = app.sm.get_screen("saved_detail")
        detail_screen.source_screen = self.source_screen or "saved_screen"
        detail_screen.open_card(self.base_card_id, self.card_type)
        app.switch_screen("saved_detail", "left")


class VoiceComposerMixin:
    voice_mode = StringProperty("idle")
    voice_elapsed = NumericProperty(0)
    voice_cancel_progress = NumericProperty(0)
    voice_draft = DictProperty({})
    voice_cancel_ready = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._voice_touch_active = False
        self._voice_touch_start_x = 0
        self._voice_drag_limit = dp(170)
        self._voice_btn_base_x = None
        self._voice_drag_started = False
        self._voice_ignore_next_release = False

    def on_record_drag(self, progress):
        self.voice_cancel_progress = max(0, min(1, progress))
        self.voice_cancel_ready = self.voice_cancel_progress >= 0.92
        self.update_record_button_position()

    def start_recording(self):
        if self.voice_mode == "recording":
            return
        self.voice_mode = "recording"
        self.voice_elapsed = 0
        self.voice_cancel_progress = 0
        self.voice_cancel_ready = False
        self.voice_draft = {"type": "audio", "waveform": [], "duration": 0}
        Clock.unschedule(self._tick_recording)
        Clock.schedule_interval(self._tick_recording, 1)

    def _tick_recording(self, dt):
        self.voice_elapsed += 1
        self.voice_draft["duration"] = self.voice_elapsed

    def cancel_recording(self):
        Clock.unschedule(self._tick_recording)
        self.voice_mode = "idle"
        self.voice_elapsed = 0
        self.voice_cancel_progress = 0
        self.voice_cancel_ready = False
        self.voice_draft = {}
        self.update_record_button_position(reset=True)

    def format_voice_duration(self, total_seconds):
        minutes = int(total_seconds) // 60
        seconds = int(total_seconds) % 60
        return f"{minutes:02d}:{seconds:02d}"

    def voice_touch_down(self, touch):
        if self.voice_mode != "recording" or "record_btn" not in self.ids:
            return False
        if self.ids.record_btn.collide_point(*touch.pos):
            self._voice_touch_active = True
            self._voice_touch_start_x = touch.x
            self._voice_drag_started = False
        return False

    def voice_touch_move(self, touch):
        if not self._voice_touch_active or self.voice_mode != "recording":
            return False
        delta = min(0, touch.x - self._voice_touch_start_x)
        progress = abs(delta) / float(self._voice_drag_limit or 1)
        if abs(delta) > dp(8):
            self._voice_drag_started = True
        self.on_record_drag(progress)
        return True

    def voice_touch_up(self, touch):
        if not self._voice_touch_active:
            return False
        self._voice_touch_active = False
        if self.voice_cancel_ready:
            self.cancel_recording()
            self._voice_ignore_next_release = True
            return True
        if self._voice_drag_started:
            self.on_record_drag(0)
            self._voice_ignore_next_release = True
            self._voice_drag_started = False
            return True
        self.on_record_drag(0)
        return False

    def should_ignore_voice_release(self):
        if self._voice_ignore_next_release:
            self._voice_ignore_next_release = False
            return True
        return False

    def update_record_button_position(self, reset=False):
        if "record_btn_wrap" not in self.ids:
            return
        btn_wrap = self.ids.record_btn_wrap
        if self._voice_btn_base_x is None:
            self._voice_btn_base_x = btn_wrap.x
        if reset or self.voice_mode == "idle":
            btn_wrap.x = self._voice_btn_base_x
            return
        btn_wrap.x = self._voice_btn_base_x - (self._voice_drag_limit * self.voice_cancel_progress)


class WelcomeScreen(Screen):
    login_card_pos = NumericProperty(-dp(500))
    opacity_bg = NumericProperty(0)

    def on_enter(self, *args):
        MDApp.get_running_app().animate_progress(0)

    def open_menu(self):
        Animation(login_card_pos=0, opacity_bg=0.8, duration=0.2, t="out_cubic").start(self)

    def close_menu(self):
        Animation(login_card_pos=-dp(500), opacity_bg=0, duration=0.2, t="in_cubic").start(self)

    def open_email_login(self):
        self.close_menu()
        Clock.schedule_once(lambda dt: MDApp.get_running_app().switch_screen("login_screen", "left", skipped=True), 0.22)

    def start_google_login(self):
        self.close_menu()
        Clock.schedule_once(lambda dt: MDApp.get_running_app().start_google_auth(), 0.22)

    def start_apple_login(self):
        self.close_menu()
        Clock.schedule_once(lambda dt: MDApp.get_running_app().show_social_auth_unavailable("Apple"), 0.22)


class GenderScreen(Screen):
    selected_gender = StringProperty("")

    def on_pre_leave(self, *args):
        if self.selected_gender:
            MDApp.get_running_app().onboarding_state["gender"] = self.selected_gender.lower()

    def on_enter(self, *args):
        MDApp.get_running_app().animate_progress(1)


class AgeScreen(Screen):
    selected_age = StringProperty("")

    def select_age(self, age):
        self.selected_age = age
        MDApp.get_running_app().switch_screen("budget_screen")

    def on_pre_leave(self, *args):
        if self.selected_age:
            MDApp.get_running_app().onboarding_state["age_range"] = self.selected_age

    def on_enter(self, *args):
        MDApp.get_running_app().animate_progress(2)


class BudgetScreen(Screen):
    selected_budget = StringProperty("")

    def select_budget(self, budget):
        self.selected_budget = budget
        MDApp.get_running_app().switch_screen("focus_screen")

    def on_pre_leave(self, *args):
        if self.selected_budget:
            MDApp.get_running_app().onboarding_state["budget"] = self.selected_budget

    def on_enter(self, *args):
        MDApp.get_running_app().animate_progress(3)


class FocusScreen(Screen):
    selected_focus = StringProperty("")

    def select_focus(self, focus):
        self.selected_focus = focus
        MDApp.get_running_app().switch_screen("hobbies_screen")

    def on_pre_leave(self, *args):
        focus_map = {
            "people": "Meet new people",
            "experience": "Discover experiences",
            "rest": "Rest & recharge",
            "growth": "Personal growth",
        }
        if self.selected_focus:
            MDApp.get_running_app().onboarding_state["focus"] = [focus_map.get(self.selected_focus, self.selected_focus)]

    def on_enter(self, *args):
        MDApp.get_running_app().animate_progress(4)


class HobbiesScreen(Screen):
    selected_hobbies = ListProperty([])
    selected_hobby = BooleanProperty(False)

    def toggle_hobby(self, hobby):
        if hobby in self.selected_hobbies:
            self.selected_hobbies.remove(hobby)
        else:
            self.selected_hobbies.append(hobby)
        self.selected_hobby = len(self.selected_hobbies) > 0

    def next_step(self):
        if self.selected_hobbies:
            MDApp.get_running_app().switch_screen("activity_screen")

    def on_pre_leave(self, *args):
        if self.selected_hobbies:
            MDApp.get_running_app().onboarding_state["lifestyle"] = list(self.selected_hobbies)

    def on_enter(self, *args):
        MDApp.get_running_app().animate_progress(5)


class ActivityScreen(Screen):
    selected_activity = StringProperty("")

    def select_activity(self, activity):
        self.selected_activity = activity
        MDApp.get_running_app().switch_screen("location_screen")

    def on_pre_leave(self, *args):
        if self.selected_activity:
            MDApp.get_running_app().onboarding_state["activity_type"] = [self.selected_activity]

    def on_enter(self, *args):
        MDApp.get_running_app().animate_progress(6)


class LocationScreen(Screen):
    search_text = StringProperty("")
    display_text = StringProperty("")
    filtered_cities = ListProperty([])
    all_cities = ListProperty([])
    is_city_valid = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.load_cities()

    def load_cities(self):
        try:
            with open("cities.txt", "r", encoding="utf-8") as f:
                self.all_cities = [line.strip() for line in f if line.strip()]
        except Exception:
            self.all_cities = ["Moscow", "Saint Petersburg", "Tomsk", "Novosibirsk"]

    def on_search_text(self, instance, value):
        val = value.replace(", Russia", "").strip()
        search_val = val.lower()
        if search_val and val not in self.all_cities:
            matches = [c for c in self.all_cities if c.lower().startswith(search_val)]
            self.filtered_cities = matches[:5]
        else:
            self.filtered_cities = []
        self.is_city_valid = val in self.all_cities
        self.display_text = value

    def on_filtered_cities(self, instance, value):
        if "cities_list" in self.ids:
            self.ids.cities_list.clear_widgets()
            for city in value:
                btn = Button(
                    text=city,
                    size_hint_y=None,
                    height=dp(50),
                    background_color=(0, 0, 0, 0),
                    color=(1, 1, 1, 1),
                    font_size=sp(16),
                    halign="left",
                    valign="middle",
                )
                btn.bind(size=lambda inst, size: setattr(inst, "text_size", (size[0] - dp(58), size[1])))
                btn.padding = [dp(58), 0, 0, 0]
                btn.on_release = lambda c=city: self.select_city(c)
                self.ids.cities_list.add_widget(btn)

    def select_city(self, city_name):
        self.is_city_valid = True
        self.filtered_cities = []
        self.display_text = f"{city_name}, Russia"
        if "city_input" in self.ids:
            self.ids.city_input.text = self.display_text

    def get_my_location(self):
        self.select_city("Tomsk")

    def next_step(self):
        if self.is_city_valid:
            city_text = self.display_text.replace(", Russia", "").strip()
            if city_text:
                MDApp.get_running_app().onboarding_state["city"] = city_text
            MDApp.get_running_app().switch_screen("auth_screen")

    def on_enter(self, *args):
        MDApp.get_running_app().animate_progress(7)


class AuthScreen(Screen):
    show_back_btn = BooleanProperty(True)
    is_valid = BooleanProperty(False)
    auth_status = StringProperty("")
    auth_loading = BooleanProperty(False)

    def on_pre_enter(self, *args):
        self.show_back_btn = not MDApp.get_running_app().onboarding_skipped

    def on_enter(self, *args):
        MDApp.get_running_app().animate_progress(8)
        self.auth_status = ""
        Clock.schedule_interval(self.check_form, 0.2)

    def on_leave(self, *args):
        Clock.unschedule(self.check_form)

    def check_form(self, dt):
        email = self.ids.email_field.text.strip()
        p1 = self.ids.pass_field.text.strip()
        p2 = self.ids.confirm_field.text.strip()
        is_email_valid = ("@" in email and "." in email.split("@")[-1]) if email else False
        self.is_valid = bool(is_email_valid and len(p1) >= 6 and p1 == p2)

    def submit_auth(self):
        if self.auth_loading or not self.is_valid:
            return
        self.auth_loading = True
        self.auth_status = ""
        email = self.ids.email_field.text.strip()
        password = self.ids.pass_field.text.strip()
        verify_password = self.ids.confirm_field.text.strip()
        threading.Thread(
            target=self._run_auth_flow,
            args=(email, password, verify_password),
            daemon=True,
        ).start()

    def start_google_login(self):
        self.auth_status = "Opening Google sign-in..."
        MDApp.get_running_app().start_google_auth()

    def start_apple_login(self):
        self.auth_status = MDApp.get_running_app().social_auth_unavailable_message("Apple")

    def _run_auth_flow(self, email, password, verify_password):
        app = MDApp.get_running_app()
        try:
            # API binding: registration screen -> create account -> login -> open chat.
            app.register_and_login_user(email, password, verify_password)
            app.sync_onboarding_to_backend()
            Clock.schedule_once(lambda dt: self._finish_auth_success(), 0)
        except Exception as exc:
            Clock.schedule_once(lambda dt, message=str(exc): self._finish_auth_error(message), 0)

    def _finish_auth_success(self):
        self.auth_loading = False
        self.auth_status = ""
        MDApp.get_running_app().current_user_email = self.ids.email_field.text.strip()
        MDApp.get_running_app().switch_screen("chat", "left")

    def _finish_auth_error(self, message):
        self.auth_loading = False
        self.auth_status = message


class LoginScreen(Screen):
    is_valid = BooleanProperty(False)
    login_status = StringProperty("")
    login_loading = BooleanProperty(False)

    def on_enter(self, *args):
        self.login_status = ""

    def check_form(self, dt):
        email = self.ids.email_field.text.strip()
        password = self.ids.pass_field.text.strip()
        is_email_valid = ("@" in email and "." in email.split("@")[-1]) if email else False
        self.is_valid = bool(is_email_valid and len(password) >= 6)

    def submit_login(self):
        if self.login_loading or not self.is_valid:
            return
        self.login_loading = True
        self.login_status = ""
        email = self.ids.email_field.text.strip()
        password = self.ids.pass_field.text.strip()
        threading.Thread(target=self._run_login_flow, args=(email, password), daemon=True).start()

    def start_google_login(self):
        self.login_status = "Opening Google sign-in..."
        MDApp.get_running_app().start_google_auth()

    def start_apple_login(self):
        self.login_status = MDApp.get_running_app().social_auth_unavailable_message("Apple")

    def _run_login_flow(self, email, password):
        app = MDApp.get_running_app()
        try:
            # Keep network I/O off the UI thread, then apply Kivy state on the UI thread.
            response = app.api_request(
                "/api/v1/auth/login/mobile",
                method="POST",
                auth=False,
                data={
                    "email": email,
                    "password": password,
                },
            )
            Clock.schedule_once(lambda dt, payload=response: self._finish_login_success(payload, email), 0)
        except Exception as exc:
            Clock.schedule_once(lambda dt, message=str(exc): self._finish_login_error(message), 0)

    def _finish_login_success(self, response, email):
        app = MDApp.get_running_app()
        try:
            app.apply_token_pair(response)
            app.current_user_email = email
        except Exception as exc:
            self._finish_login_error(str(exc))
            return
        self.login_loading = False
        self.login_status = ""
        app.switch_screen("chat", "left", skipped=True)
        app.refresh_after_login_async()

    def _finish_login_error(self, message):
        self.login_loading = False
        self.login_status = message


class ProfileScreen(Screen):
    user_data = DictProperty({"name": "David Jerome", "location": "London, UK", "personalization": 85, "status": "Basic"})
    profile_name = StringProperty("User")
    profile_location = StringProperty("Unknown city")
    profile_personalization = NumericProperty(85)
    profile_status = StringProperty("Basic")

    def on_pre_enter(self, *args):
        threading.Thread(target=self._load_profile, daemon=True).start()

    def _load_profile(self):
        app = MDApp.get_running_app()
        try:
            # API binding: profile screen -> fetch current user profile.
            payload = app.fetch_current_user()
            Clock.schedule_once(lambda dt, data=payload: self._apply_profile(data), 0)
        except Exception:
            Clock.schedule_once(lambda dt: self._apply_profile({}), 0)

    def _apply_profile(self, payload):
        app = MDApp.get_running_app()
        merged = app.merge_profile_with_fallback(payload or {})
        app.user_profile = merged
        preferences = (merged or {}).get("preferences", {}) or {}
        email = (merged or {}).get("email", "")
        city = (merged or {}).get("city") or "Unknown city"
        focus = preferences.get("focus", []) or []
        activity = preferences.get("activity_type", []) or []
        lifestyle = preferences.get("lifestyle", []) or []
        filled_groups = sum(
            1 for value in [city, preferences.get("gender"), preferences.get("age_range")] if value and value != "Unknown city"
        ) + sum(1 for group in [focus, activity, lifestyle] if group)
        personalization = min(100, 25 + filled_groups * 10)
        self.profile_name = self._display_name(email)
        self.profile_location = city
        self.profile_personalization = personalization
        self.profile_status = app.format_subscription_status(merged)
        self.user_data = {
            "name": self.profile_name,
            "location": self.profile_location,
            "personalization": self.profile_personalization,
            "status": self.profile_status,
        }

    @staticmethod
    def _display_name(email):
        return "User"

    def go_back(self):
        MDApp.get_running_app().switch_screen("chat", "right")

    def go_edit(self):
        MDApp.get_running_app().switch_screen("edit_profile", "left")


class SavedScreen(Screen):
    selected_tab = StringProperty("all")
    search_text = StringProperty("")
    tab_indicator_x = NumericProperty(0)
    tab_indicator_w = NumericProperty(0)
    saved_items = ListProperty([])
    saved_status = StringProperty("")
    _load_request_id = 0
    _render_event = None
    _row_render_event = None
    _last_render_signature = ""

    def on_pre_enter(self, *args):
        self._load_request_id += 1
        request_id = self._load_request_id
        Clock.schedule_once(lambda dt: self.update_tab_indicator(), 0)
        threading.Thread(target=self._load_saved_items, args=(request_id,), daemon=True).start()

    def go_back(self):
        MDApp.get_running_app().switch_screen("chat", "right")

    def select_tab(self, tab_name):
        self.selected_tab = tab_name
        Clock.schedule_once(lambda dt: self.update_tab_indicator(), 0)
        self.schedule_render_saved_items(0)

    def on_search_text(self, instance, value):
        self.schedule_render_saved_items(0.18)

    def _load_saved_items(self, request_id):
        app = MDApp.get_running_app()
        try:
            payload = app.fetch_favorite_cards(offset=0, limit=100)
            Clock.schedule_once(lambda dt, data=payload, rid=request_id: self._apply_saved_items(data, rid), 0)
        except Exception as exc:
            Clock.schedule_once(lambda dt, msg=str(exc), rid=request_id: self._apply_saved_error(msg, rid), 0)

    def _apply_saved_error(self, message, request_id):
        if request_id != self._load_request_id:
            return
        self.saved_status = message

    def _apply_saved_items(self, payload, request_id):
        if request_id != self._load_request_id:
            return
        self.saved_status = ""
        items = []
        app = MDApp.get_running_app()
        for item in (payload or {}).get("items", []) or []:
            card = item.get("card_info") or {}
            card_type = card.get("card_type") or ("movie" if card.get("title") else "place")
            if card_type == "movie":
                card_view = app.build_movie_card_view_model(card, include_image=True, compact=True)
            else:
                card_view = app.build_place_card_view_model(card, include_image=False, compact=False)
            card_view["base_card_id"] = item.get("base_card_id") or card_view.get("base_card_id") or 0
            items.append(card_view)
        self.saved_items = items
        self._last_render_signature = ""
        self.schedule_render_saved_items(0)

    def schedule_render_saved_items(self, delay=0):
        if self._render_event is not None:
            self._render_event.cancel()
            self._render_event = None
        self._render_event = Clock.schedule_once(self._render_saved_items_scheduled, delay)

    def _render_saved_items_scheduled(self, dt):
        self._render_event = None
        self.render_saved_items()

    def render_saved_items(self):
        items_box = self.ids.get("saved_items_box")
        empty_state = self.ids.get("saved_empty_state")
        if items_box is None or empty_state is None:
            return
        filtered = []
        query = (self.search_text or "").strip().lower()
        for item in self.saved_items:
            if self.selected_tab == "places" and item.get("card_type") != "place":
                continue
            if self.selected_tab == "content" and item.get("card_type") != "movie":
                continue
            if self.selected_tab == "events":
                continue
            haystack = " ".join(
                [
                    item.get("title", ""),
                    item.get("subtitle", ""),
                    item.get("description", ""),
                ]
            ).lower()
            if query and query not in haystack:
                continue
            filtered.append(item)
        empty_state.opacity = 0 if filtered else 1
        empty_state.height = 0 if filtered else dp(240)
        signature = self.saved_render_signature(filtered)
        if signature == self._last_render_signature:
            return
        self._last_render_signature = signature
        rows = [self.saved_row_data(item, "saved_screen") for item in filtered]
        self.replace_rows_batched(items_box, rows)

    def saved_row_data(self, item, source_screen):
        return {
            "base_card_id": item.get("base_card_id") or 0,
            "card_type": item.get("card_type") or "",
            "title": item.get("title") or "",
            "subtitle": item.get("subtitle") or "",
            "description": item.get("description") or "",
            "meta_left": item.get("meta_left") or "",
            "meta_right": item.get("meta_right") or "",
            "image_url": item.get("image_url") or "",
            "has_image": bool(item.get("has_image")),
            "source_screen": source_screen,
        }

    def cancel_row_render(self):
        if self._row_render_event is not None:
            self._row_render_event.cancel()
            self._row_render_event = None

    def replace_rows_batched(self, items_box, rows, batch_size=1, immediate_threshold=4):
        self.cancel_row_render()
        if len(rows) <= immediate_threshold and len(items_box.children) <= immediate_threshold:
            items_box.clear_widgets()
            for row_data in rows:
                items_box.add_widget(FavoriteCardRow(**row_data))
            return

        pending_rows = list(rows)
        clearing = {"active": bool(items_box.children)}

        def process(dt):
            if clearing["active"]:
                remove_count = min(batch_size, len(items_box.children))
                for _ in range(remove_count):
                    items_box.remove_widget(items_box.children[-1])
                if items_box.children:
                    return True
                clearing["active"] = False
            add_count = min(batch_size, len(pending_rows))
            for _ in range(add_count):
                items_box.add_widget(FavoriteCardRow(**pending_rows.pop(0)))
            if not pending_rows:
                self._row_render_event = None
                return False
            return True

        self._row_render_event = Clock.schedule_interval(process, 0)

    def saved_render_signature(self, items):
        return ";".join(
            "|".join(
                (
                    str(item.get("base_card_id") or 0),
                    str(item.get("card_type") or ""),
                    str(item.get("title") or ""),
                    str(item.get("subtitle") or ""),
                    str(item.get("meta_left") or ""),
                    str(item.get("meta_right") or ""),
                )
            )
            for item in items
        )

    def update_tab_indicator(self):
        tab_map = {
            "all": "tab_all",
            "places": "tab_places",
            "events": "tab_events",
            "content": "tab_content",
        }
        tab_id = tab_map.get(self.selected_tab)
        if not tab_id or tab_id not in self.ids:
            return
        tab = self.ids[tab_id]
        if self.tab_indicator_w == 0:
            self.tab_indicator_x = tab.x
            self.tab_indicator_w = tab.width
            return
        Animation.cancel_all(self, "tab_indicator_x", "tab_indicator_w")
        Animation(
            tab_indicator_x=tab.x,
            tab_indicator_w=tab.width,
            duration=0.18,
            t="out_cubic",
        ).start(self)


class FavoriteDetailScreen(Screen):
    title_text = StringProperty("")
    subtitle_text = StringProperty("")
    body_text = StringProperty("")
    meta_left = StringProperty("")
    meta_right = StringProperty("")
    accent_text = StringProperty("")
    image_url = StringProperty("")
    has_image = BooleanProperty(False)
    current_card_id = NumericProperty(0)
    current_card_type = StringProperty("")
    load_status = StringProperty("")
    source_screen = StringProperty("saved_screen")
    related_items = ListProperty([])
    related_status = StringProperty("")
    _related_render_event = None

    def go_back(self):
        target = self.source_screen or "saved_screen"
        MDApp.get_running_app().switch_screen(target, "right")

    def open_card(self, base_card_id, card_type=""):
        self.current_card_id = base_card_id
        self.current_card_type = card_type
        self.load_status = ""
        self.related_status = ""
        self.related_items = []
        Clock.schedule_once(lambda dt: self.render_related_movies(), 0)
        threading.Thread(target=self._load_card, daemon=True).start()

    def _load_card(self):
        app = MDApp.get_running_app()
        try:
            payload = app.fetch_favorite_card(self.current_card_id)
            Clock.schedule_once(lambda dt, data=payload: self._apply_card(data), 0)
        except Exception as exc:
            Clock.schedule_once(lambda dt, msg=str(exc): setattr(self, "load_status", msg), 0)

    def _apply_card(self, payload):
        app = MDApp.get_running_app()
        card = (payload or {}).get("card_info") or {}
        card_type = card.get("card_type") or self.current_card_type or "place"
        self.current_card_type = card_type
        if card_type == "movie":
            poster_path = card.get("poster_path")
            self.image_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""
            self.has_image = bool(self.image_url)
            self.title_text = card.get("title") or "Movie"
            self.subtitle_text = card.get("original_title") or ""
            self.body_text = card.get("overview") or ""
            release_date = card.get("release_date") or ""
            self.meta_left = release_date[:4] if release_date else ""
            vote_average = card.get("vote_average")
            self.meta_right = f"TMDb {vote_average:.1f}" if isinstance(vote_average, (int, float)) else ""
            genre_names = app.movie_genres_for_card(card)
            self.accent_text = app.movie_genre_summary(card, limit=3)
            threading.Thread(
                target=self._load_related_movies,
                args=(card.get("id") or 0, genre_names[:2]),
                daemon=True,
            ).start()
        else:
            self.image_url = ""
            self.has_image = False
            self.title_text = card.get("name") or "Place"
            self.subtitle_text = card.get("formatted_address") or ""
            self.body_text = card.get("description") or ""
            rating = card.get("rating")
            self.meta_left = f"Rating {rating:.1f}" if isinstance(rating, (int, float)) else ""
            self.meta_right = card.get("price_level") or ""
            self.accent_text = card.get("hours_summary") or ("Open now" if card.get("open_now") is True else ("Closed" if card.get("open_now") is False else ""))
            self.related_items = []
            self.related_status = ""
            Clock.schedule_once(lambda dt: self.render_related_movies(), 0)

    def _load_related_movies(self, current_movie_id, genre_names):
        app = MDApp.get_running_app()
        try:
            payload = app.discover_movies(with_genres=genre_names or None)
            items = []
            for movie in (payload or {}).get("results", []) or []:
                if (movie.get("id") or 0) == current_movie_id:
                    continue
                card_view = app.build_movie_card_view_model(movie, include_image=False, compact=True)
                items.append(card_view)
                if len(items) >= 3:
                    break
            Clock.schedule_once(lambda dt, data=items: self._apply_related_movies(data), 0)
        except Exception as exc:
            Clock.schedule_once(lambda dt, msg=str(exc): setattr(self, "related_status", msg), 0)

    def _apply_related_movies(self, items):
        self.related_status = ""
        self.related_items = items
        Clock.schedule_once(lambda dt: self.render_related_movies(), 0)

    def render_related_movies(self):
        items_box = self.ids.get("related_items_box")
        if items_box is None:
            return
        rows = [
            {
                "base_card_id": item.get("base_card_id") or 0,
                "card_type": item.get("card_type") or "movie",
                "title": item.get("title") or "",
                "subtitle": item.get("subtitle") or "",
                "description": item.get("description") or "",
                "meta_left": item.get("meta_left") or "",
                "meta_right": item.get("meta_right") or "",
                "image_url": item.get("image_url") or "",
                "has_image": bool(item.get("has_image")),
                "source_screen": "saved_detail",
            }
            for item in self.related_items
        ]
        self.replace_related_rows_batched(items_box, rows)

    def cancel_related_render(self):
        if self._related_render_event is not None:
            self._related_render_event.cancel()
            self._related_render_event = None

    def replace_related_rows_batched(self, items_box, rows, batch_size=1, immediate_threshold=4):
        self.cancel_related_render()
        if len(rows) <= immediate_threshold and len(items_box.children) <= immediate_threshold:
            items_box.clear_widgets()
            for row_data in rows:
                items_box.add_widget(FavoriteCardRow(**row_data))
            return

        pending_rows = list(rows)
        clearing = {"active": bool(items_box.children)}

        def process(dt):
            if clearing["active"]:
                remove_count = min(batch_size, len(items_box.children))
                for _ in range(remove_count):
                    items_box.remove_widget(items_box.children[-1])
                if items_box.children:
                    return True
                clearing["active"] = False
            add_count = min(batch_size, len(pending_rows))
            for _ in range(add_count):
                items_box.add_widget(FavoriteCardRow(**pending_rows.pop(0)))
            if not pending_rows:
                self._related_render_event = None
                return False
            return True

        self._related_render_event = Clock.schedule_interval(process, 0)


class EditProfileScreen(Screen):
    sheet_pos = NumericProperty(-dp(400))
    opacity_bg = NumericProperty(0)
    save_status = StringProperty("")
    save_loading = BooleanProperty(False)

    def on_pre_enter(self, *args):
        self.save_status = ""
        threading.Thread(target=self._load_profile, daemon=True).start()

    def go_back(self):
        MDApp.get_running_app().switch_screen("profile", "right")

    def open_gender_menu(self, *args):
        self.ids.main_scroll.do_scroll_y = False
        Animation(sheet_pos=0, opacity_bg=0.6, duration=0.3, t="out_cubic").start(self)

    def close_gender_menu(self):
        self.ids.main_scroll.do_scroll_y = True
        Animation(sheet_pos=-dp(400), opacity_bg=0, duration=0.2, t="in_cubic").start(self)

    def set_gender(self, gender_text):
        self.ids.gender_field.text = gender_text
        self.close_gender_menu()

    def _load_profile(self):
        app = MDApp.get_running_app()
        try:
            # API binding: edit profile screen -> fetch current user profile for form fields.
            payload = app.fetch_current_user()
            Clock.schedule_once(lambda dt, data=payload: self._apply_profile(data), 0)
        except Exception as exc:
            Clock.schedule_once(lambda dt: self._apply_profile({}), 0)
            Clock.schedule_once(lambda dt, message=str(exc): setattr(self, "save_status", message), 0)

    def _apply_profile(self, payload):
        app = MDApp.get_running_app()
        merged = app.merge_profile_with_fallback(payload or {})
        app.user_profile = merged
        preferences = (merged or {}).get("preferences", {}) or {}
        self.ids.name_field.value_text = ProfileScreen._display_name((merged or {}).get("email", ""))
        self.ids.gender_field.text = self._title_or_empty(preferences.get("gender"))
        self.ids.city_field.value_text = (merged or {}).get("city") or "Unknown city"
        self.ids.language_field.value_text = self._language_label((merged or {}).get("language_code"))
        self.ids.email_field_box.value_text = (merged or {}).get("email") or ""
        self.ids.age_field.value_text = preferences.get("age_range") or ""
        self._set_chip_group(self.ids.focus_chips, preferences.get("focus", []))
        self._set_chip_group(self.ids.activity_chips, preferences.get("activity_type", []))
        self._set_chip_group(self.ids.lifestyle_chips, preferences.get("lifestyle", []))

    def save_profile(self):
        if self.save_loading:
            return
        self.save_loading = True
        self.save_status = ""
        payload = {
            "language_code": self._language_code(self.ids.language_field.value_text),
            "city": self.ids.city_field.value_text.strip() or None,
            "preferences": {
                "gender": self._gender_value(self.ids.gender_field.text),
                "age_range": self.ids.age_field.value_text.strip() or None,
                "focus": self._selected_chip_texts(self.ids.focus_chips),
                "activity_type": self._selected_chip_texts(self.ids.activity_chips),
                "lifestyle": self._selected_chip_texts(self.ids.lifestyle_chips),
            },
        }
        threading.Thread(target=self._run_save_profile, args=(payload,), daemon=True).start()

    def _run_save_profile(self, payload):
        app = MDApp.get_running_app()
        try:
            # API binding: edit profile form -> PATCH /me -> refresh profile snapshot.
            app.update_current_user(payload)
            refreshed = app.fetch_current_user()
            Clock.schedule_once(lambda dt, data=refreshed: self._finish_save_success(data), 0)
        except Exception as exc:
            Clock.schedule_once(lambda dt, message=str(exc): self._finish_save_error(message), 0)

    def _finish_save_success(self, payload):
        self.save_loading = False
        self.save_status = ""
        MDApp.get_running_app().user_profile = payload or {}
        MDApp.get_running_app().switch_screen("profile", "right")

    def _finish_save_error(self, message):
        self.save_loading = False
        self.save_status = message

    @staticmethod
    def _set_chip_group(container, selected_values):
        selected_set = {str(value).strip().lower() for value in (selected_values or [])}
        for child in container.children:
            if hasattr(child, "text") and hasattr(child, "selected"):
                child.selected = child.text.strip().lower() in selected_set

    @staticmethod
    def _selected_chip_texts(container):
        selected = []
        for child in reversed(container.children):
            if getattr(child, "selected", False):
                selected.append(child.text)
        return selected

    @staticmethod
    def _title_or_empty(value):
        return str(value).replace("_", " ").title() if value else ""

    @staticmethod
    def _gender_value(value):
        return value.strip().lower() if value else None

    @staticmethod
    def _language_label(code):
        mapping = {
            "en": "English",
            "ru": "Russian",
            "es": "Spanish",
            "pt": "Portuguese",
            "fr": "French",
            "de": "German",
            "it": "Italian",
            "hi": "Hindi",
        }
        return mapping.get(code or "en", "English")

    @staticmethod
    def _language_code(label):
        reverse_mapping = {
            "English": "en",
            "Russian": "ru",
            "Spanish": "es",
            "Portuguese": "pt",
            "French": "fr",
            "German": "de",
            "Italian": "it",
            "Hindi": "hi",
        }
        return reverse_mapping.get(label or "English", "en")


class ChatInterface(Screen, VoiceComposerMixin):
    options_card_pos = NumericProperty(-dp(600))
    opacity_bg = NumericProperty(0)
    current_chat_id = NumericProperty(0)
    chat_loading = BooleanProperty(False)
    chat_error = StringProperty("")
    last_messages_signature = StringProperty("")
    poll_idle_cycles = NumericProperty(0)
    ws_connected = BooleanProperty(False)
    keyboard_offset = NumericProperty(0)
    generation_pending = BooleanProperty(False)
    generation_status_text = StringProperty("")
    toast_text = StringProperty("")
    toast_opacity = NumericProperty(0)
    chat_content_opacity = NumericProperty(1)
    pending_after_message_id = NumericProperty(0)
    pending_generation_message_id = NumericProperty(0)
    chat_history_loaded = BooleanProperty(False)
    can_use_chat = BooleanProperty(True)
    subscription_block_text = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._ws_app = None
        self._ws_thread = None
        self._pending_animation_event = None
        self._generation_poll_event = None
        self._generation_poll_count = 0
        self._generation_request_id = 0
        self._suppress_next_ws_refresh = False
        self._pending_dot_count = 0
        self._pending_user_bubble = None
        self._toast_event = None
        self._message_bubbles = {}
        self._visible_message_ids = set()
        self._scroll_event = None
        self._chat_render_event = None
        self._chat_card_events = {}
        self._all_chat_items = []
        self._all_message_ids = set()
        self._visible_start_index = 0
        self._visible_end_index = 0
        self._is_loading_older_messages = False
        self._suppress_scroll_window_check = False
        Window.bind(keyboard_height=self._on_keyboard_height)

    def open_nav(self):
        self.ids.nav_drawer.set_state("open")

    def go_to_profile(self):
        self.ids.nav_drawer.set_state("close")
        MDApp.get_running_app().switch_screen("profile", "left")

    def go_to_calendar(self):
        MDApp.get_running_app().switch_screen("calendar_screen", "left")

    def go_to_saved(self):
        MDApp.get_running_app().switch_screen("saved_screen", "left")

    def open_options(self):
        Animation(options_card_pos=dp(100), opacity_bg=1, duration=0.3, t="out_cubic").start(self)

    def close_options(self):
        Animation(options_card_pos=-dp(600), opacity_bg=0, duration=0.2, t="in_cubic").start(self)

    def show_toast(self, text):
        self.toast_text = text
        if self._toast_event is not None:
            self._toast_event.cancel()
            self._toast_event = None
        Animation.cancel_all(self, "toast_opacity")
        self.toast_opacity = 0
        Animation(toast_opacity=1, duration=0.12, t="out_cubic").start(self)
        self._toast_event = Clock.schedule_once(lambda dt: self.hide_toast(), 1.25)

    def hide_toast(self):
        self._toast_event = None
        Animation.cancel_all(self, "toast_opacity")
        Animation(toast_opacity=0, duration=0.18, t="out_cubic").start(self)

    def delete_current_chat(self):
        if self.chat_loading or not self.current_chat_id:
            return
        self.chat_loading = True
        self.chat_error = ""
        chat_id = self.current_chat_id
        self.close_options()
        threading.Thread(target=self._delete_current_chat_request, args=(chat_id,), daemon=True).start()

    def _delete_current_chat_request(self, chat_id):
        app = MDApp.get_running_app()
        try:
            app.delete_chat(chat_id)
            created_chat = app.create_chat()
            new_chat_id = created_chat["id"]
            messages_response = app.fetch_chat_messages(new_chat_id, offset=0, limit=CHAT_MESSAGE_LIMIT)
            Clock.schedule_once(
                lambda dt, cid=new_chat_id, payload=messages_response: self._finish_chat_bootstrap(cid, payload),
                0,
            )
        except Exception as exc:
            Clock.schedule_once(lambda dt, message=str(exc): self._finish_chat_error(message), 0)

    def on_enter(self, *args):
        self.refresh_subscription_access()
        if not self.chat_loading:
            self.prepare_chat_visual_update()
        self.ensure_chat_ready()
        self.connect_websocket()

    def on_leave(self, *args):
        self.disconnect_websocket()

    def _on_keyboard_height(self, window, height):
        self.keyboard_offset = max(0, height)
        if "chat_scroll" in self.ids:
            self.schedule_scroll_to_bottom(0.05)

    def ensure_chat_ready(self):
        if self.chat_loading:
            self.finish_chat_visual_update()
            return
        self.chat_loading = True
        self.chat_error = ""
        self.chat_history_loaded = False
        self.hide_empty_chat_view()
        threading.Thread(target=self._bootstrap_chat, daemon=True).start()

    def refresh_subscription_access(self):
        app = MDApp.get_running_app()
        if app.user_profile:
            self.apply_subscription_access(app.user_profile)
        else:
            self.subscription_block_text = ""
        threading.Thread(target=self._refresh_subscription_access_request, daemon=True).start()

    def _refresh_subscription_access_request(self):
        app = MDApp.get_running_app()
        try:
            profile = app.fetch_current_user()
            Clock.schedule_once(lambda dt, data=profile: self.apply_subscription_access(data), 0)
        except Exception:
            return

    def apply_subscription_access(self, profile):
        app = MDApp.get_running_app()
        if profile:
            app.user_profile = profile or {}
        self.can_use_chat = app.has_active_subscription(app.user_profile)
        self.subscription_block_text = "" if self.can_use_chat else (
            "AI chat is available with an active subscription. Open Subscription / Payment to activate access."
        )

    def _bootstrap_chat(self):
        app = MDApp.get_running_app()
        try:
            app.refresh_current_user_snapshot()
            # API binding: chat screen -> fetch user's chats -> create one if missing -> load history.
            chats_response = app.fetch_user_chats(offset=0, limit=20)
            items = (chats_response or {}).get("items", [])
            if items:
                chat_id = items[0]["id"]
            else:
                created_chat = app.create_chat()
                chat_id = created_chat["id"]
            messages_response = app.fetch_chat_messages(chat_id, offset=0, limit=CHAT_MESSAGE_LIMIT)
            Clock.schedule_once(
                lambda dt, cid=chat_id, payload=messages_response: self._finish_chat_bootstrap(
                    cid, payload
                ),
                0,
            )
        except Exception as exc:
            Clock.schedule_once(lambda dt, message=str(exc): self._finish_chat_error(message), 0)

    def _finish_chat_bootstrap(self, chat_id, payload):
        self.current_chat_id = chat_id
        self.chat_loading = False
        self.chat_error = ""
        self.last_messages_signature = ""
        self.poll_idle_cycles = 0
        self.pending_after_message_id = 0
        self.pending_generation_message_id = 0
        self.chat_history_loaded = False
        self.render_messages(payload, reset=True, autoscroll=True)

    def _finish_chat_error(self, message):
        self.chat_loading = False
        self.generation_pending = False
        self.pending_after_message_id = 0
        self.pending_generation_message_id = 0
        self.remove_generation_indicator()
        self.chat_error = message
        self.finish_chat_visual_update()

    def render_messages(self, payload, reset=False, autoscroll=False):
        items = self.normalize_chat_items((payload or {}).get("items", []))
        empty_view = self.ids.get("empty_chat_view")
        has_new_ai = self.has_new_ai_message(items)
        keep_pending = self.generation_pending and not has_new_ai
        existing_message_ids = self.visible_message_ids()
        signature = self.chat_items_signature(items)
        if not reset and signature == self.last_messages_signature:
            return
        if self.generation_pending and not items and self.has_visible_chat_bubbles():
            return
        self.last_messages_signature = signature
        if reset:
            self._all_chat_items = items
            self._all_message_ids = {
                int(message.get("id") or 0)
                for message in items
                if message.get("id")
            }
            self._visible_start_index = max(0, len(items) - CHAT_RENDER_WINDOW_SIZE)
            self._visible_end_index = len(items)
            self.render_chat_window(autoscroll=autoscroll)
            return
        self.merge_chat_items(items)
        existing_message_ids = self.visible_message_ids()
        if not items:
            if keep_pending:
                self.hide_empty_chat_view()
            else:
                self.show_empty_chat_view()
            self.chat_history_loaded = True
            return
        self.hide_empty_chat_view()
        added_new = False
        for message in items:
            message_id = message.get("id") or 0
            if message_id and message_id in existing_message_ids:
                self.update_existing_bubble(message)
                continue
            sender = self.resolve_message_sender(message)
            message_type = message.get("type", "text")
            bubble_type = "audio" if message_type == "voice" else "text"
            meta_text = self.format_message_time(message.get("created_at"))
            if bubble_type == "audio":
                meta_text = meta_text or "voice"
            cards = self.build_message_cards(message.get("cards") or {})
            self.add_bubble(
                message.get("content", ""),
                sender,
                message_id=message_id,
                bubble_type=bubble_type,
                meta_text=meta_text,
                cards=cards,
                reaction_type=self.extract_current_reaction(message.get("reactions") or []),
                animate=(not reset) and sender == "ai",
            )
            added_new = True
        if has_new_ai:
            self.generation_pending = False
            self.chat_loading = False
            self.pending_generation_message_id = 0
            self.remove_generation_indicator()
        if keep_pending:
            self.capture_pending_generation_message_id(items)
        self.chat_history_loaded = True
        if autoscroll or added_new:
            self.schedule_scroll_to_bottom(0.05)

    def merge_chat_items(self, items):
        if not items:
            return
        by_id = {
            int(message.get("id") or 0): message
            for message in self._all_chat_items
            if message.get("id")
        }
        anonymous = [message for message in self._all_chat_items if not message.get("id")]
        for message in items:
            message_id = int(message.get("id") or 0)
            if message_id:
                by_id[message_id] = message
            else:
                anonymous.append(message)
        self._all_chat_items = self.normalize_chat_items([*anonymous, *by_id.values()])
        self._all_message_ids = {
            int(message.get("id") or 0)
            for message in self._all_chat_items
            if message.get("id")
        }

    def clear_visible_chat_widgets(self):
        empty_view = self.ids.get("empty_chat_view")
        self.cancel_chunked_chat_render()
        self.cancel_chat_card_renders()
        for child in list(self.ids.chat_list.children):
            if empty_view is not None and child == empty_view:
                continue
            self.ids.chat_list.remove_widget(child)
        self._message_bubbles.clear()
        self._visible_message_ids.clear()

    def render_chat_window(self, autoscroll=False, on_complete=None):
        items = self._all_chat_items or []
        hide_until_ready = bool(autoscroll)
        if hide_until_ready:
            self.prepare_chat_visual_update()
        self.clear_visible_chat_widgets()
        if not items:
            self.show_empty_chat_view()
            self.chat_history_loaded = True
            if hide_until_ready:
                self.finish_chat_visual_update()
            return
        self.hide_empty_chat_view()
        if not self._visible_end_index or self._visible_end_index > len(items):
            self._visible_end_index = len(items)
        visible_items = items[self._visible_start_index:self._visible_end_index]
        final_callback = self.combine_chat_render_callbacks(
            on_complete,
            self.finish_chat_visual_update if hide_until_ready else None,
        )
        if len(visible_items) > 4 and not self.generation_pending and not hide_until_ready:
            self.start_chunked_chat_render(visible_items, autoscroll=autoscroll, on_complete=final_callback)
            return
        for message in visible_items:
            self.add_message_bubble_from_payload(message, animate=False)
        self.chat_history_loaded = True
        if autoscroll:
            self.schedule_scroll_to_bottom(0.05)
        if final_callback:
            final_callback()

    def combine_chat_render_callbacks(self, *callbacks):
        callbacks = [callback for callback in callbacks if callback]
        if not callbacks:
            return None

        def combined():
            for callback in callbacks:
                callback()

        return combined

    def prepare_chat_visual_update(self):
        self.chat_content_opacity = 0

    def finish_chat_visual_update(self):
        def reveal(dt):
            self.schedule_scroll_to_bottom(0)
            self.chat_content_opacity = 1

        Clock.schedule_once(reveal, 0)

    def on_chat_scroll_y(self, scroll_y):
        if self._suppress_scroll_window_check or self._is_loading_older_messages:
            return
        if self._chat_render_event is not None or self.generation_pending:
            return
        if scroll_y >= 0.96 and self._visible_start_index > 0:
            self.load_older_visible_messages()
            return
        if scroll_y <= 0.04 and self._visible_end_index < len(self._all_chat_items):
            self.load_newer_visible_messages()

    def load_older_visible_messages(self):
        old_start = self._visible_start_index
        new_start = max(0, old_start - CHAT_RENDER_WINDOW_STEP)
        if new_start == old_start:
            return
        self._is_loading_older_messages = True
        self._visible_start_index = new_start
        self._visible_end_index = min(len(self._all_chat_items), new_start + CHAT_RENDER_WINDOW_SIZE)
        self.render_chat_window(autoscroll=False, on_complete=lambda: self.finish_loading_older_messages())

    def load_newer_visible_messages(self):
        old_end = self._visible_end_index
        new_end = min(len(self._all_chat_items), old_end + CHAT_RENDER_WINDOW_STEP)
        if new_end == old_end:
            return
        self._is_loading_older_messages = True
        self._visible_end_index = new_end
        self._visible_start_index = max(0, new_end - CHAT_RENDER_WINDOW_SIZE)
        self.render_chat_window(autoscroll=False, on_complete=lambda: self.finish_loading_older_messages())

    def finish_loading_older_messages(self):
        self._is_loading_older_messages = False
        self._suppress_scroll_window_check = True
        Clock.schedule_once(lambda dt: setattr(self, "_suppress_scroll_window_check", False), 0.25)

    def cancel_chunked_chat_render(self):
        if self._chat_render_event is not None:
            self._chat_render_event.cancel()
            self._chat_render_event = None

    def cancel_chat_card_renders(self):
        for event in list(self._chat_card_events.values()):
            event.cancel()
        self._chat_card_events.clear()

    def start_chunked_chat_render(self, items, autoscroll=False, prepend=False, on_complete=None):
        self.cancel_chunked_chat_render()
        self.chat_history_loaded = False
        self._chunked_chat_items = list(items or [])
        self._chunked_chat_index = 0
        self._chunked_chat_autoscroll = autoscroll
        self._chunked_chat_prepend = prepend
        self._chunked_chat_on_complete = on_complete
        self._chat_render_event = Clock.schedule_interval(self._render_chat_chunk, 0)

    def _render_chat_chunk(self, dt):
        batch_size = 1
        items = getattr(self, "_chunked_chat_items", [])
        start_index = getattr(self, "_chunked_chat_index", 0)
        end_index = min(len(items), start_index + batch_size)
        for message in items[start_index:end_index]:
            self.add_message_bubble_from_payload(
                message,
                animate=False,
                prepend=getattr(self, "_chunked_chat_prepend", False),
            )
        self._chunked_chat_index = end_index
        if end_index >= len(items):
            on_complete = getattr(self, "_chunked_chat_on_complete", None)
            self.cancel_chunked_chat_render()
            self.chat_history_loaded = True
            if getattr(self, "_chunked_chat_autoscroll", False):
                self.schedule_scroll_to_bottom(0.05)
            if on_complete:
                on_complete()
            return False
        return True

    def add_message_bubble_from_payload(self, message, animate=False, prepend=False):
        sender = self.resolve_message_sender(message)
        message_type = message.get("type", "text")
        bubble_type = "audio" if message_type == "voice" else "text"
        meta_text = self.format_message_time(message.get("created_at"))
        if bubble_type == "audio":
            meta_text = meta_text or "voice"
        cards = self.build_message_cards(message.get("cards") or {})
        return self.add_bubble(
            message.get("content", ""),
            sender,
            message_id=message.get("id") or 0,
            bubble_type=bubble_type,
            meta_text=meta_text,
            cards=cards,
            reaction_type=self.extract_current_reaction(message.get("reactions") or []),
            animate=animate,
            prepend=prepend,
        )

    def send_message(self):
        text = self.ids.user_input.text.strip()
        if not self.can_use_chat:
            self.chat_error = ""
            self.subscription_block_text = (
                "AI chat is available with an active subscription. Open Subscription / Payment to activate access."
            )
            return
        if not text or self.chat_loading:
            return
        if not self.current_chat_id:
            self.chat_error = "Chat is not ready yet."
            return
        self.chat_loading = True
        self.generation_pending = True
        self.pending_after_message_id = self.latest_message_id()
        self.pending_generation_message_id = 0
        self.chat_error = ""
        self.ids.user_input.text = ""
        self._generation_request_id += 1
        request_id = self._generation_request_id
        empty_view = self.ids.get("empty_chat_view")
        if empty_view is not None:
            empty_view.opacity = 0
            empty_view.height = 0
        self._pending_user_bubble = self.add_bubble(
            text,
            "user",
            meta_text=self.format_message_time(datetime.now().isoformat()),
            animate=False,
        )
        self.add_generation_indicator()
        self.start_generation_history_poll(request_id)
        self.schedule_scroll_to_bottom(0)
        Clock.schedule_once(
            lambda dt, message_text=text, rid=request_id: threading.Thread(
                target=self._send_text_message,
                args=(message_text, rid),
                daemon=True,
            ).start(),
            0.08,
        )

    def _send_text_message(self, text, request_id):
        app = MDApp.get_running_app()
        try:
            # API binding: chat composer -> send message -> refresh history for current chat.
            created_message = app.send_chat_message(self.current_chat_id, text)
            Clock.schedule_once(
                lambda dt, payload=created_message, rid=request_id: self.capture_sent_message_id(payload, rid),
                0,
            )
            messages_response = app.fetch_chat_messages(self.current_chat_id, offset=0, limit=CHAT_MESSAGE_LIMIT)
            Clock.schedule_once(
                lambda dt, payload=messages_response, rid=request_id: self._finish_send_message(payload, rid),
                0,
            )
        except Exception as exc:
            Clock.schedule_once(
                lambda dt, message=str(exc), rid=request_id: self._finish_send_error(message, rid),
                0,
            )

    def _finish_send_message(self, payload, request_id):
        if request_id != self._generation_request_id:
            return
        self.chat_error = ""
        self.poll_idle_cycles = 0
        self.render_messages(payload)
        self.connect_websocket()

    def _finish_send_error(self, message, request_id):
        if request_id != self._generation_request_id:
            return
        self.generation_pending = False
        self.chat_loading = False
        self.pending_generation_message_id = 0
        self.remove_generation_indicator()
        if "subscription" in message.lower():
            self.can_use_chat = False
            self.subscription_block_text = (
                "AI chat is available with an active subscription. Open Subscription / Payment to activate access."
            )
            return
        if "already" in message.lower() or "429" in message:
            self.chat_error = "Previous generation is still running on backend. Try again in a moment."
            return
        self._finish_chat_error(message)

    def capture_sent_message_id(self, payload, request_id):
        if request_id != self._generation_request_id or not self.generation_pending:
            return
        message_id = self.extract_message_id(payload)
        if message_id:
            self.pending_generation_message_id = message_id
            if self._pending_user_bubble is not None and not self._pending_user_bubble.message_id:
                self._pending_user_bubble.message_id = message_id

    def extract_message_id(self, payload):
        if not isinstance(payload, dict):
            return 0
        for key in ("id", "message_id"):
            if payload.get(key):
                return int(payload.get(key) or 0)
        message = payload.get("message")
        if isinstance(message, dict):
            for key in ("id", "message_id"):
                if message.get(key):
                    return int(message.get(key) or 0)
        return 0

    def connect_websocket(self):
        app = MDApp.get_running_app()
        if not app.access_token or self._ws_app is not None:
            return
        ws_base = app.api_base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_base}/ws/?token={app.access_token}"
        self._ws_app = websocket.WebSocketApp(
            ws_url,
            on_open=self._on_ws_open,
            on_message=self._on_ws_message,
            on_close=self._on_ws_close,
            on_error=self._on_ws_error,
        )
        self._ws_thread = threading.Thread(target=self._ws_app.run_forever, daemon=True)
        self._ws_thread.start()

    def disconnect_websocket(self):
        if self._ws_app is not None:
            try:
                self._ws_app.close()
            except Exception:
                pass
        self._ws_app = None
        self._ws_thread = None
        self.ws_connected = False

    def _on_ws_open(self, ws_app):
        Clock.schedule_once(lambda dt: setattr(self, "ws_connected", True), 0)

    def _on_ws_close(self, ws_app, status_code, message):
        def reset_state(dt):
            self.ws_connected = False
            self._ws_app = None
            self._ws_thread = None
        Clock.schedule_once(reset_state, 0)

    def _on_ws_error(self, ws_app, error):
        Clock.schedule_once(lambda dt: setattr(self, "ws_connected", False), 0)

    def _on_ws_message(self, ws_app, message):
        try:
            payload = json.loads(message)
        except ValueError:
            return
        Clock.schedule_once(lambda dt, data=payload: self._handle_ws_payload(data), 0)

    def _handle_ws_payload(self, payload):
        if self._suppress_next_ws_refresh:
            self._suppress_next_ws_refresh = False
            return
        if self.handle_generation_status_payload(payload):
            return
        if self.handle_message_payload(payload):
            return
        incoming_chat_id = payload.get("chat_id")
        if incoming_chat_id is not None and self.current_chat_id and incoming_chat_id != self.current_chat_id:
            return
        if self.generation_pending:
            return
        threading.Thread(target=self._fetch_messages_after_ws, daemon=True).start()

    def handle_generation_status_payload(self, payload):
        if not isinstance(payload, dict) or payload.get("event") != "message_response_status":
            return False
        incoming_chat_id = payload.get("chat_id")
        if incoming_chat_id is not None and self.current_chat_id and incoming_chat_id != self.current_chat_id:
            return True
        message_id = payload.get("message_id") or 0
        if message_id:
            self.pending_generation_message_id = int(message_id)
        status = payload.get("status") or ""
        labels = {
            "received": "Message received",
            "thinking": "Thinking",
            "searching": "Searching",
            "summarizing": "Summarizing",
        }
        if self.generation_pending:
            self.generation_status_text = labels.get(status, "Generating")
        return True

    def handle_message_payload(self, payload):
        if not isinstance(payload, dict) or not payload.get("id") or "content" not in payload:
            return False
        incoming_chat_id = payload.get("chat_id")
        if incoming_chat_id is not None and self.current_chat_id and incoming_chat_id != self.current_chat_id:
            return True
        self.append_message_payload(payload, autoscroll=True)
        return True

    def append_message_payload(self, message, autoscroll=False):
        self.merge_chat_items([message])
        message_id = message.get("id") or 0
        if message_id and message_id in self.visible_message_ids():
            self.update_existing_bubble(message)
        else:
            sender = self.resolve_message_sender(message)
            message_type = message.get("type", "text")
            bubble_type = "audio" if message_type == "voice" else "text"
            meta_text = self.format_message_time(message.get("created_at"))
            if bubble_type == "audio":
                meta_text = meta_text or "voice"
            cards = self.build_message_cards(message.get("cards") or {})
            empty_view = self.ids.get("empty_chat_view")
            self.hide_empty_chat_view()
            self.add_bubble(
                message.get("content", ""),
                sender,
                message_id=message_id,
                bubble_type=bubble_type,
                meta_text=meta_text,
                cards=cards,
                reaction_type=self.extract_current_reaction(message.get("reactions") or []),
                animate=sender == "ai",
            )
        if self.resolve_message_sender(message) == "ai":
            self.generation_pending = False
            self.chat_loading = False
            self.pending_generation_message_id = 0
            self.remove_generation_indicator()
        if autoscroll:
            self.schedule_scroll_to_bottom(0.05)

    def _fetch_messages_after_ws(self):
        app = MDApp.get_running_app()
        try:
            messages_response = app.fetch_chat_messages(self.current_chat_id, offset=0, limit=CHAT_MESSAGE_LIMIT)
            Clock.schedule_once(lambda dt, payload=messages_response: self.render_messages(payload), 0)
        except Exception:
            return

    def add_generation_indicator(self):
        self.start_pending_animation()

    def remove_generation_indicator(self):
        self.stop_pending_animation()
        self.stop_generation_history_poll()
        self.generation_status_text = ""

    def start_pending_animation(self):
        self.stop_pending_animation()
        self._pending_dot_count = 0
        self._pending_animation_event = Clock.schedule_interval(self._tick_pending_animation, 0.35)
        self._tick_pending_animation(0)

    def stop_pending_animation(self):
        if self._pending_animation_event is not None:
            self._pending_animation_event.cancel()
            self._pending_animation_event = None

    def start_generation_history_poll(self, request_id):
        self.stop_generation_history_poll()
        self._generation_poll_count = 0
        self._generation_poll_event = Clock.schedule_interval(
            lambda dt, rid=request_id: self._poll_generation_history(rid),
            1.0,
        )

    def stop_generation_history_poll(self):
        if self._generation_poll_event is not None:
            self._generation_poll_event.cancel()
            self._generation_poll_event = None
        self._generation_poll_count = 0

    def _poll_generation_history(self, request_id):
        if request_id != self._generation_request_id or not self.generation_pending:
            self.stop_generation_history_poll()
            return False
        self._generation_poll_count += 1
        if self._generation_poll_count > 25:
            self.stop_generation_history_poll()
            return False
        threading.Thread(
            target=self._fetch_generation_history_snapshot,
            args=(request_id,),
            daemon=True,
        ).start()
        return True

    def _fetch_generation_history_snapshot(self, request_id):
        app = MDApp.get_running_app()
        try:
            messages_response = app.fetch_chat_messages(self.current_chat_id, offset=0, limit=CHAT_MESSAGE_LIMIT)
            Clock.schedule_once(
                lambda dt, payload=messages_response, rid=request_id: self._apply_generation_history_snapshot(payload, rid),
                0,
            )
        except Exception:
            return

    def _apply_generation_history_snapshot(self, payload, request_id):
        if request_id != self._generation_request_id or not self.generation_pending:
            return
        self.render_messages(payload)

    def _tick_pending_animation(self, dt):
        if not self.generation_pending:
            self.stop_pending_animation()
            return False
        self._pending_dot_count = (self._pending_dot_count + 1) % 4
        self.generation_status_text = "Generating" + ("." * self._pending_dot_count)
        return True

    def cancel_generation(self):
        message_id = int(self.pending_generation_message_id or 0)
        self._generation_request_id += 1
        self.generation_pending = False
        self.chat_loading = False
        self.pending_after_message_id = 0
        self.pending_generation_message_id = 0
        self._suppress_next_ws_refresh = True
        self.remove_generation_indicator()
        if message_id:
            threading.Thread(target=self._stop_generation_request, args=(message_id,), daemon=True).start()

    def _stop_generation_request(self, message_id):
        app = MDApp.get_running_app()
        try:
            app.stop_message_generation(message_id)
        except Exception:
            return

    def visible_message_ids(self):
        return set(self._visible_message_ids)

    def chat_items_signature(self, items):
        parts = []
        for message in items or []:
            message_id = message.get("id") or 0
            cards = message.get("cards") or {}
            card_count = len(cards.get("place_cards") or []) + len(cards.get("movie_cards") or [])
            reactions = message.get("reactions") or []
            reaction_sig = ",".join(
                f"{reaction.get('user_id')}:{reaction.get('type')}" for reaction in reactions if isinstance(reaction, dict)
            )
            parts.append(
                "|".join(
                    (
                        str(message_id),
                        str(message.get("user_id") or ""),
                        str(message.get("status") or ""),
                        str(message.get("created_at") or ""),
                        str(message.get("content") or ""),
                        str(card_count),
                        reaction_sig,
                    )
                )
            )
        return ";".join(parts)

    def normalize_chat_items(self, items):
        def sort_key(message):
            message_id = message.get("id") or 0
            created_at = message.get("created_at") or ""
            return (str(created_at), int(message_id or 0))

        return sorted([item for item in items or [] if isinstance(item, dict)], key=sort_key)

    def hide_empty_chat_view(self):
        empty_view = self.ids.get("empty_chat_view")
        if empty_view is None:
            return
        empty_view.opacity = 0
        empty_view.height = 0
        empty_view.disabled = True

    def show_empty_chat_view(self):
        empty_view = self.ids.get("empty_chat_view")
        if empty_view is None:
            return
        empty_view.opacity = 1
        empty_view.disabled = False
        scroll = self.ids.get("chat_scroll")
        empty_view.height = (scroll.height - dp(20)) if scroll is not None and scroll.height > 0 else dp(500)

    def find_bubble_by_message_id(self, message_id):
        if not message_id:
            return None
        return self._message_bubbles.get(int(message_id or 0))

    def update_existing_bubble(self, message):
        bubble = self.find_bubble_by_message_id(message.get("id") or 0)
        if bubble is None:
            return
        bubble.reaction_type = self.extract_current_reaction(message.get("reactions") or [])
        meta_text = self.format_message_time(message.get("created_at"))
        if meta_text:
            bubble.meta_text = meta_text
        if not bubble.cards:
            cards = self.build_message_cards(message.get("cards") or {})
            if cards:
                bubble.cards = cards
                bubble.cards_area_height = self.calculate_cards_area_height(cards)
                bubble.bubble_width = self.calculate_bubble_width(bubble.text, bubble.sender, bubble.bubble_type, cards)
                cards_box = bubble.ids.get("cards_box")
                if cards_box is not None:
                    self.render_bubble_cards(bubble, cards)

    def has_visible_chat_bubbles(self):
        return bool(self._message_bubbles) or self._pending_user_bubble is not None

    def latest_message_id(self):
        return max(self._all_message_ids or self._visible_message_ids, default=0)

    def has_new_ai_message(self, items):
        if not self.generation_pending:
            return False
        for message in items or []:
            if (message.get("id") or 0) <= self.pending_after_message_id:
                continue
            if self.resolve_message_sender(message) == "ai":
                return True
        return False

    def capture_pending_generation_message_id(self, items):
        if self.pending_generation_message_id:
            return
        app = MDApp.get_running_app()
        candidates = []
        for message in items or []:
            message_id = message.get("id") or 0
            if message_id <= self.pending_after_message_id:
                continue
            try:
                is_current_user_message = int(message.get("user_id") or 0) == int(app.current_user_id or 0)
            except (TypeError, ValueError):
                is_current_user_message = False
            if not is_current_user_message:
                continue
            if message.get("status") in ("queued", "processing"):
                candidates.append(message_id)
        if candidates:
            self.pending_generation_message_id = max(candidates)

    def send_voice_message(self):
        if not self.can_use_chat:
            self.subscription_block_text = (
                "AI chat is available with an active subscription. Open Subscription / Payment to activate access."
            )
            return
        if self.should_ignore_voice_release():
            return
        if self.voice_mode != "recording":
            self.start_recording()
            return
        empty_view = self.ids.get("empty_chat_view")
        if empty_view is not None and empty_view.opacity > 0:
            empty_view.opacity = 0
            empty_view.height = 0
        duration = self.voice_elapsed or 1
        draft = dict(self.voice_draft) if self.voice_draft else {}
        draft["duration"] = duration
        self.add_bubble("", "user", bubble_type="audio", meta_text=self.format_voice_duration(duration))
        self.cancel_recording()
        self.handle_voice_api_stub(draft)

    def handle_voice_api_stub(self, payload):
        return payload

    def build_message_cards(self, cards_payload):
        cards = []
        app = MDApp.get_running_app()
        for place in cards_payload.get("place_cards", []) or []:
            card_view = app.build_place_card_view_model(place, include_image=False, compact=True)
            card_view["meta_right"] = ""
            if not card_view.get("accent_text"):
                card_view["accent_text"] = place.get("price_level") or ""
            cards.append(card_view)
        for movie in cards_payload.get("movie_cards", []) or []:
            cards.append(app.build_movie_card_view_model(movie, include_image=False, compact=True))
        return cards

    def extract_current_reaction(self, reactions):
        app = MDApp.get_running_app()
        for reaction in reactions or []:
            if reaction.get("user_id") == app.current_user_id:
                return reaction.get("type") or ""
        return ""

    def resolve_message_sender(self, message):
        app = MDApp.get_running_app()
        user_id = message.get("user_id")
        if user_id is not None:
            try:
                return "user" if int(user_id) == int(app.current_user_id or 0) else "ai"
            except (TypeError, ValueError):
                return "ai"
        return "ai"

    def format_message_time(self, raw_value):
        if not raw_value:
            return ""
        try:
            value = str(raw_value).replace("Z", "+00:00")
            dt = datetime.fromisoformat(value)
            return dt.strftime("%H:%M")
        except (TypeError, ValueError):
            return ""

    def refresh_current_chat(self):
        if not self.current_chat_id:
            return
        threading.Thread(target=self._fetch_messages_after_ws, daemon=True).start()

    def calculate_bubble_width(self, text, sender, bubble_type, cards):
        if bubble_type == "audio":
            return dp(220)
        if bubble_type == "pending":
            return dp(170)
        if cards:
            return dp(285)
        clean_text = str(text or "")
        longest_line = max((len(line) for line in clean_text.splitlines()), default=0)
        estimated = longest_line * sp(7.8) + dp(54)
        minimum = dp(124)
        maximum = dp(285) if sender == "ai" else dp(230)
        return max(minimum, min(maximum, estimated))

    def add_bubble(self, text, sender, message_id=0, bubble_type="text", meta_text="", cards=None, reaction_type="", is_pending=False, animate=True, prepend=False):
        cards = cards or []
        bubble_width = self.calculate_bubble_width(text, sender, bubble_type, cards or [])
        bubble = ChatBubble(
            message_id=message_id,
            text=text,
            sender=sender,
            bubble_type=bubble_type,
            meta_text=meta_text,
            cards=cards,
            cards_area_height=self.calculate_cards_area_height(cards),
            reaction_type=reaction_type or "",
            is_pending=is_pending,
            bubble_width=bubble_width,
        )
        cards_box = bubble.ids.get("cards_box")
        if cards_box is not None:
            self.render_bubble_cards(bubble, cards or [])
        bubble.row_opacity = 0 if animate else 1
        bubble.row_y_offset = 0
        # BoxLayout lays out reversed children; default insertion keeps new chat rows at the visual bottom.
        if prepend:
            self.ids.chat_list.add_widget(bubble, index=len(self.ids.chat_list.children))
        else:
            self.ids.chat_list.add_widget(bubble)
        if message_id:
            message_id = int(message_id or 0)
            self._message_bubbles[message_id] = bubble
            self._visible_message_ids.add(message_id)
        if animate:
            Animation(row_opacity=1, duration=0.18, t="out_cubic").start(bubble)
        return bubble

    def calculate_cards_area_height(self, cards):
        count = len(cards or [])
        if not count:
            return 0
        return count * dp(94) + max(0, count - 1) * dp(10)

    def render_bubble_cards(self, bubble, cards):
        cards_box = bubble.ids.get("cards_box")
        if cards_box is None:
            return
        event_key = id(bubble)
        old_event = self._chat_card_events.pop(event_key, None)
        if old_event is not None:
            old_event.cancel()
        cards_box.clear_widgets()
        cards = list(cards or [])
        cards_box.cards = cards

    def redraw_visible_card_canvases(self):
        for bubble in list(self._message_bubbles.values()):
            cards_box = bubble.ids.get("cards_box")
            if isinstance(cards_box, ChatCardsCanvas):
                cards_box.redraw()

    def schedule_scroll_to_bottom(self, delay=0.05):
        if self._scroll_event is not None:
            self._scroll_event.cancel()
            self._scroll_event = None
        self._scroll_event = Clock.schedule_once(self._perform_scroll_to_bottom, delay)

    def _perform_scroll_to_bottom(self, dt):
        self._scroll_event = None
        self.scroll_to_bottom()

    def scroll_to_bottom(self):
        if "chat_scroll" not in self.ids:
            return
        self.ids.chat_scroll.scroll_y = 0

    def on_touch_down(self, touch):
        self.voice_touch_down(touch)
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self.voice_touch_move(touch):
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self.voice_touch_up(touch):
            return True
        return super().on_touch_up(touch)


class FriendsScreen(Screen):
    pass


class TripsScreen(Screen, VoiceComposerMixin):
    def go_back(self):
        self.manager.current = "profile"
        self.manager.transition.direction = "right"

    def send_voice_message(self):
        if self.should_ignore_voice_release():
            return
        if self.voice_mode != "recording":
            self.start_recording()
            return
        payload = dict(self.voice_draft) if self.voice_draft else {}
        payload["duration"] = self.voice_elapsed or 1
        self.cancel_recording()
        self.handle_voice_api_stub(payload)

    def handle_voice_api_stub(self, payload):
        return payload

    def on_touch_down(self, touch):
        self.voice_touch_down(touch)
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self.voice_touch_move(touch):
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self.voice_touch_up(touch):
            return True
        return super().on_touch_up(touch)


class PrivacyScreen(Screen):
    pass


class SubscriptionScreen(Screen):
    faq_open = BooleanProperty(False)
    subscription_title = StringProperty("No active subscription")
    subscription_plan_text = StringProperty("Plan: Free")
    subscription_details_text = StringProperty("Status: inactive")
    subscription_is_active = BooleanProperty(False)

    def on_enter(self):
        self.apply_subscription_profile(MDApp.get_running_app().user_profile or {})
        threading.Thread(target=self._refresh_subscription_profile, daemon=True).start()

    def _refresh_subscription_profile(self):
        app = MDApp.get_running_app()
        try:
            payload = app.fetch_current_user()
            Clock.schedule_once(lambda dt, data=payload: self.apply_subscription_profile(data), 0)
        except Exception:
            return

    def apply_subscription_profile(self, profile):
        app = MDApp.get_running_app()
        if profile:
            app.user_profile = profile or {}
        subscription_type = (profile or {}).get("subscription_type")
        expires_at = (profile or {}).get("subscription_expires_at")
        expires_label = self.format_subscription_date(expires_at)
        is_active = bool(subscription_type and not self.is_subscription_expired(expires_at))
        self.subscription_is_active = is_active
        if is_active:
            plan_name = str(subscription_type).replace("_", " ").title()
            self.subscription_title = "Subscription active"
            self.subscription_plan_text = f"Plan: XolidayAI {plan_name}"
            self.subscription_details_text = (
                f"Valid until: {expires_label}\n"
                "Status: Active\n"
                "Access: AI recommendations enabled"
            )
        else:
            self.subscription_title = "No active subscription"
            self.subscription_plan_text = "Plan: Free"
            if expires_label:
                status = f"Expired: {expires_label}"
            else:
                status = "Status: inactive"
            self.subscription_details_text = (
                f"{status}\n"
                "Access: AI chat is locked\n"
                "Activate a subscription to use AI recommendations"
            )
        if app.sm.has_screen("profile"):
            app.sm.get_screen("profile")._apply_profile(app.user_profile or profile or {})

    def is_subscription_expired(self, raw_value):
        if not raw_value:
            return False
        try:
            value = str(raw_value).replace("Z", "+00:00")
            expires_at = datetime.fromisoformat(value)
            if expires_at.tzinfo is not None:
                return expires_at <= datetime.now(expires_at.tzinfo)
            return expires_at <= datetime.now()
        except (TypeError, ValueError):
            return False

    def format_subscription_date(self, raw_value):
        if not raw_value:
            return ""
        try:
            value = str(raw_value).replace("Z", "+00:00")
            expires_at = datetime.fromisoformat(value)
            return expires_at.strftime("%d %b %Y")
        except (TypeError, ValueError):
            return str(raw_value)


class CalendarScreen(Screen):
    year_open = BooleanProperty(False)
    selected_tab = StringProperty("all")
    search_text = StringProperty("")
    calendar_items = ListProperty([])
    visible_calendar_items = ListProperty([])
    calendar_status = StringProperty("")
    empty_title = StringProperty("No plans for this day")
    empty_subtitle = StringProperty("Pick another date or add ideas in chat.")
    calendar_loading = BooleanProperty(False)
    _render_event = None
    _row_render_event = None
    _last_items_signature = ""
    _last_week_strip_signature = ""

    def on_enter(self):
        self.months = [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ]
        now = datetime.now()
        if not hasattr(self, "cur_m"):
            self.cur_m, self.cur_y = now.month, now.year
        if not hasattr(self, "selected_date") or self.selected_date is None:
            self.selected_date = date(self.cur_y, self.cur_m, min(now.day, calendar.monthrange(self.cur_y, self.cur_m)[1]))
        if not self.calendar_items and not self.calendar_loading:
            self.calendar_loading = True
            threading.Thread(target=self._load_calendar_items, daemon=True).start()
        self.update_calendar_view()

    def _load_calendar_items(self):
        app = MDApp.get_running_app()
        try:
            chats_response = app.fetch_user_chats(offset=0, limit=20)
            items = []
            seen = set()
            for chat in (chats_response or {}).get("items", []) or []:
                chat_id = chat.get("id")
                if not chat_id:
                    continue
                messages_response = app.fetch_chat_messages(chat_id, offset=0, limit=CHAT_MESSAGE_LIMIT)
                for message in (messages_response or {}).get("items", []) or []:
                    if self.resolve_calendar_message_sender(message) != "ai":
                        continue
                    raw_date = message.get("created_at")
                    cards = message.get("cards") or {}
                    for place in cards.get("place_cards", []) or []:
                        card_id = place.get("id") or 0
                        key = ("place", chat_id, message.get("id"), card_id)
                        if key in seen:
                            continue
                        seen.add(key)
                        item = app.build_place_card_view_model(place, include_image=False, compact=False)
                        item["date"] = raw_date
                        item["type"] = "place"
                        items.append(item)
                    for movie in cards.get("movie_cards", []) or []:
                        card_id = movie.get("id") or 0
                        key = ("movie", chat_id, message.get("id"), card_id)
                        if key in seen:
                            continue
                        seen.add(key)
                        item = app.build_movie_card_view_model(movie, include_image=False, compact=False)
                        item["date"] = raw_date
                        item["type"] = "home"
                        items.append(item)
            Clock.schedule_once(lambda dt, data=items: self._apply_calendar_items(data), 0)
        except Exception as exc:
            Clock.schedule_once(lambda dt, msg=str(exc): self._apply_calendar_error(msg), 0)

    def resolve_calendar_message_sender(self, message):
        app = MDApp.get_running_app()
        user_id = message.get("user_id")
        if user_id is not None:
            try:
                return "user" if int(user_id) == int(app.current_user_id or 0) else "ai"
            except (TypeError, ValueError):
                return "ai"
        return "ai"

    def _apply_calendar_items(self, items):
        self.calendar_loading = False
        self.calendar_status = ""
        self.calendar_items = items
        self.refresh_visible_calendar_items()

    def _apply_calendar_error(self, message):
        self.calendar_loading = False
        self.calendar_status = message
        self.calendar_items = []
        self.refresh_visible_calendar_items()

    def update_calendar_view(self):
        self.ids.month_label.text = self.months[self.cur_m - 1]
        self.ids.year_label.text = str(self.cur_y)
        self.build_week_strip()
        self.refresh_visible_calendar_items()

    def build_week_strip(self):
        if "days_container" not in self.ids:
            return
        selected = self.selected_date or date(self.cur_y, self.cur_m, 1)
        signature = f"{self.cur_y}-{self.cur_m}-{selected.isoformat()}"
        if signature == self._last_week_strip_signature:
            return
        self._last_week_strip_signature = signature
        self.ids.days_container.clear_widgets()
        today = datetime.now().date()
        days_in_month = calendar.monthrange(self.cur_y, self.cur_m)[1]
        for day_num in range(1, days_in_month + 1):
            d = date(self.cur_y, self.cur_m, day_num)
            tile = DayTile(
                day_num=str(d.day),
                day_name=d.strftime("%a").upper(),
                is_today=d == today,
                is_selected=d == selected,
                in_current_month=(d.month == self.cur_m and d.year == self.cur_y),
                size_hint=(None, None),
                size=(dp(42), dp(58)),
            )
            tile.bind(on_release=lambda inst, day=d: self.select_day(day))
            self.ids.days_container.add_widget(tile)
        Clock.schedule_once(lambda dt: self.scroll_to_selected_day(), 0)

    def scroll_to_selected_day(self):
        if "days_container" not in self.ids:
            return
        selected_index = max(0, (self.selected_date.day if getattr(self, "selected_date", None) else 1) - 1)
        total_days = max(1, calendar.monthrange(self.cur_y, self.cur_m)[1] - 1)
        scroll_view = self.ids.days_container.parent
        scroll_view.scroll_x = min(1, max(0, selected_index / total_days))

    def select_day(self, selected_day):
        self.selected_date = selected_day
        self.cur_m = selected_day.month
        self.cur_y = selected_day.year
        self.update_calendar_view()

    def change_month(self, delta):
        self.cur_m += delta
        if self.cur_m > 12:
            self.cur_m = 1
            self.cur_y += 1
        elif self.cur_m < 1:
            self.cur_m = 12
            self.cur_y -= 1
        day = self.selected_date.day if getattr(self, "selected_date", None) else 1
        max_day = calendar.monthrange(self.cur_y, self.cur_m)[1]
        self.selected_date = date(self.cur_y, self.cur_m, min(day, max_day))
        self.update_calendar_view()

    def select_tab(self, tab_name):
        self.selected_tab = tab_name
        self.refresh_visible_calendar_items()

    def on_search_text(self, instance, value):
        self.schedule_refresh_visible_calendar_items(0.18)

    def schedule_refresh_visible_calendar_items(self, delay=0):
        if self._render_event is not None:
            self._render_event.cancel()
            self._render_event = None
        self._render_event = Clock.schedule_once(self._refresh_visible_calendar_items_scheduled, delay)

    def _refresh_visible_calendar_items_scheduled(self, dt):
        self._render_event = None
        self.refresh_visible_calendar_items()

    def refresh_visible_calendar_items(self):
        selected = getattr(self, "selected_date", None)
        query = (self.search_text or "").strip().lower()
        visible = []
        for item in self.calendar_items:
            if selected and not self.calendar_item_matches_date(item, selected):
                continue
            if self.selected_tab != "all" and not self.calendar_item_matches_tab(item):
                continue
            haystack = " ".join(
                str(item.get(key, ""))
                for key in ("title", "subtitle", "description", "location")
            ).lower()
            if query and query not in haystack:
                continue
            visible.append(item)
        self.visible_calendar_items = visible
        self.schedule_render_calendar_items(0)
        self.refresh_empty_state()

    def schedule_render_calendar_items(self, delay=0):
        if self._render_event is not None:
            self._render_event.cancel()
            self._render_event = None
        self._render_event = Clock.schedule_once(self._render_calendar_items_scheduled, delay)

    def _render_calendar_items_scheduled(self, dt):
        self._render_event = None
        self.render_calendar_items()

    def render_calendar_items(self):
        items_box = self.ids.get("calendar_items_box")
        if items_box is None:
            return
        signature = self.calendar_items_signature(self.visible_calendar_items)
        if signature == self._last_items_signature:
            return
        self._last_items_signature = signature
        rows = [self.calendar_row_data(item) for item in self.visible_calendar_items]
        self.replace_rows_batched(items_box, rows)

    def calendar_row_data(self, item):
        return {
            "base_card_id": item.get("base_card_id") or 0,
            "card_type": item.get("card_type") or "",
            "title": item.get("title") or "",
            "subtitle": item.get("subtitle") or "",
            "description": item.get("description") or "",
            "meta_left": item.get("meta_left") or "",
            "meta_right": item.get("meta_right") or "",
            "image_url": item.get("image_url") or "",
            "has_image": bool(item.get("has_image")),
            "source_screen": "calendar_screen",
        }

    def cancel_row_render(self):
        if self._row_render_event is not None:
            self._row_render_event.cancel()
            self._row_render_event = None

    def replace_rows_batched(self, items_box, rows, batch_size=1, immediate_threshold=4):
        self.cancel_row_render()
        if len(rows) <= immediate_threshold and len(items_box.children) <= immediate_threshold:
            items_box.clear_widgets()
            for row_data in rows:
                items_box.add_widget(FavoriteCardRow(**row_data))
            return

        pending_rows = list(rows)
        clearing = {"active": bool(items_box.children)}

        def process(dt):
            if clearing["active"]:
                remove_count = min(batch_size, len(items_box.children))
                for _ in range(remove_count):
                    items_box.remove_widget(items_box.children[-1])
                if items_box.children:
                    return True
                clearing["active"] = False
            add_count = min(batch_size, len(pending_rows))
            for _ in range(add_count):
                items_box.add_widget(FavoriteCardRow(**pending_rows.pop(0)))
            if not pending_rows:
                self._row_render_event = None
                return False
            return True

        self._row_render_event = Clock.schedule_interval(process, 0)

    def calendar_items_signature(self, items):
        return ";".join(
            "|".join(
                (
                    str(item.get("base_card_id") or 0),
                    str(item.get("card_type") or ""),
                    str(item.get("type") or ""),
                    str(item.get("title") or ""),
                    str(item.get("date") or item.get("start_date") or item.get("day") or ""),
                )
            )
            for item in items
        )

    def calendar_item_matches_tab(self, item):
        item_type = str(item.get("type") or item.get("card_type") or "").lower()
        tab_types = {
            "places": {"places", "place", "restaurant", "card_place"},
            "events": {"events", "event"},
            "home": {"home", "at_home", "at-home"},
        }
        return item_type in tab_types.get(self.selected_tab, set())

    def calendar_item_matches_date(self, item, selected):
        raw_date = item.get("date") or item.get("start_date") or item.get("day")
        if isinstance(raw_date, date):
            return raw_date == selected
        if isinstance(raw_date, str):
            try:
                return datetime.fromisoformat(raw_date.replace("Z", "+00:00")).date() == selected
            except ValueError:
                return raw_date[:10] == selected.isoformat()
        return False

    def refresh_empty_state(self):
        if self.visible_calendar_items:
            self.empty_title = ""
            self.empty_subtitle = ""
            return
        selected_label = self.selected_date.strftime("%d %b") if getattr(self, "selected_date", None) else "selected day"
        if self.search_text.strip():
            self.empty_title = "Nothing found"
            self.empty_subtitle = f"No plans match '{self.search_text.strip()}' for {selected_label}."
            return
        if self.calendar_status:
            self.empty_title = "Cannot load plans"
            self.empty_subtitle = self.calendar_status
            return
        tab_label = {
            "all": "plans",
            "places": "place plans",
            "events": "events",
            "home": "home ideas",
        }.get(self.selected_tab, "plans")
        self.empty_title = "No plans for this day"
        self.empty_subtitle = f"Add {tab_label} for {selected_label} from chat recommendations."


class MainApp(MDApp):
    progress_width = NumericProperty(0)
    onboarding_skipped = BooleanProperty(False)
    api_base_url = StringProperty(API_BASE_URL)
    is_light_mode = BooleanProperty(False)
    app_bg_color = ListProperty([0.05, 0.05, 0.05, 1])
    app_bar_bg_color = ListProperty([0.051, 0.051, 0.051, 1])
    primary_text_color = ListProperty([1, 1, 1, 1])
    secondary_text_color = ListProperty([1, 1, 1, 0.78])
    muted_text_color = ListProperty([0.62, 0.64, 0.68, 1])
    inverse_text_color = ListProperty([1, 1, 1, 1])
    divider_color = ListProperty([0.12, 0.12, 0.12, 1])
    surface_color = ListProperty([0.098, 0.1137, 0.1255, 1])
    surface_strong_color = ListProperty([0.095, 0.104, 0.12, 1])
    disabled_surface_color = ListProperty([0.1647, 0.1647, 0.1647, 1])
    user_bubble_color = ListProperty([0.125, 0.145, 0.170, 1])
    ai_bubble_color = ListProperty([0.164, 0.180, 0.192, 1])
    bubble_text_color = ListProperty([1, 1, 1, 1])
    chat_input_bg_color = ListProperty([0.098, 0.1137, 0.1255, 1])
    chat_send_icon_color = ListProperty([1, 1, 1, 1])
    voice_button_color = ListProperty([0.102, 0.114, 0.122, 1])
    card_bg_color = ListProperty([0.095, 0.104, 0.12, 1])
    card_border_color = ListProperty([1, 1, 1, 0.06])
    card_subtitle_color = ListProperty([0.78, 0.80, 0.84, 1])
    card_accent_text_color = ListProperty([0.62, 0.64, 0.68, 1])
    card_meta_text_color = ListProperty([0.74, 0.76, 0.80, 1])
    link_markup_color = StringProperty("FFFFFF")
    selected_chip_color = ListProperty([0.102, 0.451, 0.914, 1])
    selected_chip_text_color = ListProperty([1, 1, 1, 1])
    modal_scrim_color = ListProperty([0, 0, 0, 0.68])
    chip_bg_color = ListProperty([0.0627, 0.0706, 0.0667, 1])
    sheet_bg_color = ListProperty([0.0902, 0.0941, 0.102, 1])
    sheet_button_bg_color = ListProperty([0.098, 0.114, 0.125, 1])
    sheet_accent_button_bg_color = ListProperty([0.075, 0.16, 0.25, 1])
    sheet_text_color = ListProperty([1, 1, 1, 1])
    sheet_muted_text_color = ListProperty([0.58, 0.58, 0.58, 1])
    theme_toggle_icon = StringProperty("white-balance-sunny")
    access_token = StringProperty("")
    refresh_token = StringProperty("")
    user_profile = DictProperty({})
    onboarding_state = DictProperty({})
    current_user_id = NumericProperty(0)
    current_user_email = StringProperty("")
    favorite_card_ids = ListProperty([])
    movie_genre_map = DictProperty({})

    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.restore_theme_settings()
        self.apply_color_mode()
        self.http = requests.Session()
        self.http.trust_env = False
        self._after_login_loading = False
        self.sm = ScreenManager()
        kv_files = [
            "Welcome.kv",
            "Gender.kv",
            "Age.kv",
            "Budget.kv",
            "focus.kv",
            "hobbies.kv",
            "activity.kv",
            "location.kv",
            "auth.kv",
            "login.kv",
            "chat.kv",
            "saved.kv",
            "favorite_detail.kv",
            "profile.kv",
            "edit_profile.kv",
            "friends.kv",
            "trips.kv",
            "privacy.kv",
            "subscription.kv",
            "calendar_screen.kv",
        ]
        for f in kv_files:
            Builder.load_file(f)

        screens = [
            WelcomeScreen(name="welcome"),
            GenderScreen(name="gender"),
            AgeScreen(name="age_screen"),
            BudgetScreen(name="budget_screen"),
            FocusScreen(name="focus_screen"),
            HobbiesScreen(name="hobbies_screen"),
            ActivityScreen(name="activity_screen"),
            LocationScreen(name="location_screen"),
            AuthScreen(name="auth_screen"),
            LoginScreen(name="login_screen"),
            ChatInterface(name="chat"),
            SavedScreen(name="saved_screen"),
            FavoriteDetailScreen(name="saved_detail"),
            ProfileScreen(name="profile"),
            EditProfileScreen(name="edit_profile"),
            FriendsScreen(name="friends_screen"),
            TripsScreen(name="trips_screen"),
            PrivacyScreen(name="privacy_screen"),
            SubscriptionScreen(name="subscription_screen"),
            CalendarScreen(name="calendar_screen"),
        ]
        for s in screens:
            self.sm.add_widget(s)
        return self.sm

    def toggle_color_mode(self):
        chat_screen = self.sm.get_screen("chat") if hasattr(self, "sm") and self.sm.has_screen("chat") else None
        if chat_screen is not None and self.sm.current == "chat":
            chat_screen.prepare_chat_visual_update()
        self.is_light_mode = not self.is_light_mode
        self.apply_color_mode()
        self.persist_theme_settings()
        if chat_screen is not None and self.sm.current == "chat":
            chat_screen.redraw_visible_card_canvases()
            chat_screen.finish_chat_visual_update()

    def apply_color_mode(self):
        if self.is_light_mode:
            self.theme_cls.theme_style = "Light"
            self.app_bg_color = [1, 1, 1, 1]
            self.app_bar_bg_color = [1, 1, 1, 1]
            self.primary_text_color = [0.06, 0.07, 0.08, 1]
            self.secondary_text_color = [0.23, 0.25, 0.28, 0.78]
            self.muted_text_color = [0.45, 0.48, 0.52, 1]
            self.inverse_text_color = [1, 1, 1, 1]
            self.divider_color = [0.88, 0.89, 0.91, 1]
            self.surface_color = [0.90, 0.91, 0.93, 1]
            self.surface_strong_color = [0.94, 0.95, 0.97, 1]
            self.disabled_surface_color = [0.82, 0.84, 0.87, 1]
            self.user_bubble_color = [0.88, 0.93, 1.0, 1]
            self.ai_bubble_color = [0.94, 0.95, 0.97, 1]
            self.bubble_text_color = [0.06, 0.07, 0.08, 1]
            self.chat_input_bg_color = [0.90, 0.91, 0.93, 1]
            self.chat_send_icon_color = [0.18, 0.19, 0.19, 1]
            self.voice_button_color = [0.90, 0.91, 0.93, 1]
            self.card_bg_color = [1, 1, 1, 1]
            self.card_border_color = [0.78, 0.80, 0.84, 0.55]
            self.card_subtitle_color = [0.45, 0.48, 0.52, 1]
            self.card_accent_text_color = [0.45, 0.48, 0.52, 1]
            self.card_meta_text_color = [0.48, 0.50, 0.54, 1]
            self.link_markup_color = "111214"
            self.selected_chip_color = [0.102, 0.451, 0.914, 1]
            self.selected_chip_text_color = [1, 1, 1, 1]
            self.modal_scrim_color = [1, 1, 1, 0.22]
            self.chip_bg_color = [0.90, 0.91, 0.93, 1]
            self.sheet_bg_color = [0.94, 0.95, 0.97, 1]
            self.sheet_button_bg_color = [0.88, 0.90, 0.92, 1]
            self.sheet_accent_button_bg_color = [0.84, 0.89, 0.95, 1]
            self.sheet_text_color = [0.07, 0.08, 0.10, 1]
            self.sheet_muted_text_color = [0.38, 0.40, 0.44, 1]
            self.theme_toggle_icon = "moon-waning-crescent"
            return
        self.theme_cls.theme_style = "Dark"
        self.app_bg_color = [0.05, 0.05, 0.05, 1]
        self.app_bar_bg_color = [0.051, 0.051, 0.051, 1]
        self.primary_text_color = [1, 1, 1, 1]
        self.secondary_text_color = [1, 1, 1, 0.78]
        self.muted_text_color = [0.62, 0.64, 0.68, 1]
        self.inverse_text_color = [1, 1, 1, 1]
        self.divider_color = [0.12, 0.12, 0.12, 1]
        self.surface_color = [0.098, 0.1137, 0.1255, 1]
        self.surface_strong_color = [0.095, 0.104, 0.12, 1]
        self.disabled_surface_color = [0.1647, 0.1647, 0.1647, 1]
        self.user_bubble_color = [0.125, 0.145, 0.170, 1]
        self.ai_bubble_color = [0.145, 0.158, 0.166, 1]
        self.bubble_text_color = [1, 1, 1, 1]
        self.chat_input_bg_color = [0.098, 0.1137, 0.1255, 1]
        self.chat_send_icon_color = [1, 1, 1, 1]
        self.voice_button_color = [0.102, 0.114, 0.122, 1]
        self.card_bg_color = [0.095, 0.104, 0.12, 1]
        self.card_border_color = [1, 1, 1, 0.10]
        self.card_subtitle_color = [0.74, 0.78, 0.82, 1]
        self.card_accent_text_color = [0.62, 0.64, 0.68, 1]
        self.card_meta_text_color = [0.68, 0.71, 0.76, 1]
        self.link_markup_color = "FFFFFF"
        self.selected_chip_color = [0.102, 0.451, 0.914, 1]
        self.selected_chip_text_color = [1, 1, 1, 1]
        self.modal_scrim_color = [0, 0, 0, 0.68]
        self.chip_bg_color = [0.0627, 0.0706, 0.0667, 1]
        self.sheet_bg_color = [0.0902, 0.0941, 0.102, 1]
        self.sheet_button_bg_color = [0.098, 0.114, 0.125, 1]
        self.sheet_accent_button_bg_color = [0.075, 0.16, 0.25, 1]
        self.sheet_text_color = [1, 1, 1, 1]
        self.sheet_muted_text_color = [0.58, 0.58, 0.58, 1]
        self.theme_toggle_icon = "white-balance-sunny"

    def restore_theme_settings(self):
        try:
            with open(THEME_SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.is_light_mode = bool(data.get("is_light_mode", False))
        except (OSError, ValueError, TypeError):
            self.is_light_mode = False

    def persist_theme_settings(self):
        try:
            with open(THEME_SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump({"is_light_mode": bool(self.is_light_mode)}, f)
        except OSError:
            pass

    def switch_screen(self, screen_name, direction="left", skipped=False):
        if getattr(self, "_screen_switch_locked", False):
            return
        if self.sm.current == screen_name:
            return
        self._screen_switch_locked = True
        Clock.schedule_once(lambda dt: setattr(self, "_screen_switch_locked", False), 0.28)
        self.onboarding_skipped = skipped
        if self.sm.has_screen(screen_name):
            self.sm.transition.direction = direction
            self.sm.current = screen_name
        else:
            self._screen_switch_locked = False

    def animate_progress(self, step_num):
        screen_width = Window.width if hasattr(Window, "width") else dp(375)
        content_width = screen_width - dp(40)
        target_w = (content_width / 8) * step_num
        Animation(progress_width=target_w, duration=0.3).start(self)

    def start_google_auth(self):
        if platform == "android":
            self._start_android_google_sign_in()
            return
        self._set_auth_status("Google Sign-In can be tested only in Android APK/emulator.")

    def _start_android_google_sign_in(self):
        try:
            from android import activity
            from jnius import autoclass

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            GoogleSignIn = autoclass("com.google.android.gms.auth.api.signin.GoogleSignIn")
            GoogleSignInOptions = autoclass("com.google.android.gms.auth.api.signin.GoogleSignInOptions")

            gso = (
                GoogleSignInOptions.Builder(GoogleSignInOptions.DEFAULT_SIGN_IN)
                .requestIdToken(GOOGLE_MOBILE_CLIENT_ID)
                .requestEmail()
                .build()
            )
            self._google_activity = activity
            self._google_activity.unbind(on_activity_result=self._on_google_activity_result)
            self._google_activity.bind(on_activity_result=self._on_google_activity_result)
            self._google_client = GoogleSignIn.getClient(PythonActivity.mActivity, gso)
            sign_in_intent = self._google_client.getSignInIntent()
            PythonActivity.mActivity.startActivityForResult(sign_in_intent, GOOGLE_SIGN_IN_REQUEST_CODE)
        except Exception as exc:
            Clock.schedule_once(lambda dt, message=str(exc): self._set_auth_status(message), 0)

    def _on_google_activity_result(self, request_code, result_code, intent):
        if request_code != GOOGLE_SIGN_IN_REQUEST_CODE:
            return
        try:
            if getattr(self, "_google_activity", None):
                self._google_activity.unbind(on_activity_result=self._on_google_activity_result)
            from jnius import autoclass

            GoogleSignIn = autoclass("com.google.android.gms.auth.api.signin.GoogleSignIn")
            ApiException = autoclass("com.google.android.gms.common.api.ApiException")
            task = GoogleSignIn.getSignedInAccountFromIntent(intent)
            account = task.getResult(ApiException)
            id_token = account.getIdToken()
            if not id_token:
                raise ValueError("Google did not return id_token.")
            threading.Thread(target=self._login_google_with_id_token, args=(id_token,), daemon=True).start()
        except Exception as exc:
            Clock.schedule_once(lambda dt, message=str(exc): self._set_auth_status(message), 0)

    def _login_google_with_id_token(self, id_token):
        try:
            # API binding: native Google id_token -> backend mobile login.
            self.login_google_mobile(id_token)
            Clock.schedule_once(lambda dt: self._finish_social_login_success(), 0)
        except Exception as exc:
            Clock.schedule_once(lambda dt, message=str(exc): self._set_auth_status(message), 0)

    def _finish_social_login_success(self):
        self._set_auth_status("")
        self.switch_screen("chat", "left", skipped=True)

    def _set_auth_status(self, message):
        current = self.sm.current if getattr(self, "sm", None) else ""
        if current == "auth_screen" and self.sm.has_screen("auth_screen"):
            self.sm.get_screen("auth_screen").auth_status = message
        elif current == "login_screen" and self.sm.has_screen("login_screen"):
            self.sm.get_screen("login_screen").login_status = message
        elif self.sm.has_screen("login_screen"):
            self.sm.get_screen("login_screen").login_status = message

    def social_auth_unavailable_message(self, provider):
        return f"{provider} sign-in is not available in backend API yet."

    def show_social_auth_unavailable(self, provider):
        message = self.social_auth_unavailable_message(provider)
        if self.sm.has_screen("login_screen"):
            login_screen = self.sm.get_screen("login_screen")
            login_screen.login_status = message
        self.switch_screen("login_screen", "left", skipped=True)

    # Core HTTP client used by all API-bound screens.
    def api_request(self, path, method="GET", data=None, headers=None, auth=True, retry_on_unauthorized=True):
        url = f"{self.api_base_url}{path}"
        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)
        if auth and self.access_token:
            request_headers["Authorization"] = f"Bearer {self.access_token}"
        try:
            try:
                response = self.http.request(
                    method=method,
                    url=url,
                    json=data,
                    headers=request_headers,
                    timeout=30,
                )
            except requests.RequestException:
                response = self.http.request(
                    method=method,
                    url=url,
                    json=data,
                    headers=request_headers,
                    timeout=30,
                )
            response.raise_for_status()
            return response.json() if response.text else {}
        except requests.HTTPError as exc:
            if (
                auth
                and retry_on_unauthorized
                and exc.response is not None
                and exc.response.status_code == 401
                and self.refresh_token
            ):
                self.refresh_tokens_mobile()
                return self.api_request(
                    path,
                    method=method,
                    data=data,
                    headers=headers,
                    auth=auth,
                    retry_on_unauthorized=False,
                )
            payload = {}
            try:
                payload = exc.response.json() if exc.response is not None and exc.response.text else {}
            except ValueError:
                payload = {}
            detail = payload.get("detail")
            if isinstance(detail, list) and detail:
                first_error = detail[0]
                if isinstance(first_error, dict):
                    detail = first_error.get("msg")
            if not detail:
                detail = exc.response.text if exc.response is not None else str(exc)
            raise ValueError(str(detail))
        except requests.RequestException:
            raise ValueError("Cannot connect to backend. Check your internet connection and API URL.")

    # Auth API group.
    def register_user(self, email, password, verify_password):
        return self.api_request(
            "/api/v1/auth/register",
            method="POST",
            auth=False,
            data={
                "email": email,
                "password": password,
                "verify_password": verify_password,
            },
        )

    def login_user(self, email, password):
        response = self.api_request(
            "/api/v1/auth/login/mobile",
            method="POST",
            auth=False,
            data={
                "email": email,
                "password": password,
            },
        )
        self.apply_token_pair(response)
        self.current_user_email = email
        self.refresh_after_login_async()
        return response

    def login_google_mobile(self, id_token):
        response = self.api_request(
            "/api/v1/auth/google/login/mobile",
            method="POST",
            auth=False,
            data={"id_token": id_token},
        )
        self.apply_token_pair(response)
        self.refresh_after_login_async()
        return response

    def refresh_tokens_mobile(self):
        if not self.refresh_token:
            raise ValueError("Refresh token is missing.")
        response = self.api_request(
            "/api/v1/auth/refresh/mobile",
            method="POST",
            auth=False,
            retry_on_unauthorized=False,
            data={"refresh_token": self.refresh_token},
        )
        self.apply_token_pair(response)
        return response

    def apply_token_pair(self, response):
        access_token = (response or {}).get("access_token", "")
        if not access_token:
            raise ValueError("Backend did not return access token.")
        self.access_token = access_token
        self.refresh_token = (response or {}).get("refresh_token", self.refresh_token or "")

    def refresh_after_login_async(self):
        if getattr(self, "_after_login_loading", False):
            return
        self._after_login_loading = True
        threading.Thread(target=self._load_after_login_data, daemon=True).start()

    def _load_after_login_data(self):
        profile = None
        favorite_ids = []
        genre_map = None
        try:
            profile = self.fetch_current_user()
        except Exception:
            profile = None
        try:
            payload = self.fetch_favorite_cards(offset=0, limit=100)
            favorite_ids = [
                item.get("base_card_id")
                for item in (payload or {}).get("items", []) or []
                if item.get("base_card_id") is not None
            ]
        except Exception:
            favorite_ids = []
        try:
            payload = self.fetch_movie_genres()
            items = payload.get("genres", payload if isinstance(payload, list) else [])
            genre_map = {
                int(item.get("id")): item.get("name")
                for item in items
                if item.get("id") is not None and item.get("name")
            }
        except Exception:
            genre_map = None
        Clock.schedule_once(lambda dt: self._apply_after_login_data(profile, favorite_ids, genre_map), 0)

    def _apply_after_login_data(self, profile, favorite_ids, genre_map):
        self._after_login_loading = False
        if profile:
            self.current_user_id = int((profile or {}).get("id") or 0)
            self.current_user_email = (profile or {}).get("email") or self.current_user_email
            self.user_profile = profile or {}
        self.favorite_card_ids = favorite_ids or []
        if genre_map:
            self.movie_genre_map = genre_map

    def logout_user(self):
        try:
            if self.access_token:
                self.api_request("/api/v1/auth/logout", method="DELETE", retry_on_unauthorized=False)
        finally:
            self.access_token = ""
            self.refresh_token = ""
            self.current_user_id = 0
            self.current_user_email = ""
            self.favorite_card_ids = []
            self.movie_genre_map = {}

    def register_and_login_user(self, email, password, verify_password):
        self.register_user(email, password, verify_password)
        return self.login_user(email, password)

    # Profile API group.
    def fetch_current_user(self):
        return self.api_request("/api/v1/me")

    def update_current_user(self, payload):
        return self.api_request("/api/v1/me", method="PATCH", data=payload)

    # Films services API group.
    def fetch_movie_genres(self, language=None):
        query = urlencode({"language": language or self._preferred_language_code()})
        return self.api_request(f"/api/v1/services/films/genres?{query}")

    def discover_movies(self, language=None, with_genres=None, without_genres=None):
        params = [("language", language or self._preferred_language_code())]
        for genre_name in with_genres or []:
            params.append(("with_genres", genre_name))
        for genre_name in without_genres or []:
            params.append(("without_genres", genre_name))
        return self.api_request(f"/api/v1/services/films/discover?{urlencode(params)}")

    def ensure_movie_genres_loaded(self):
        if self.movie_genre_map:
            return self.movie_genre_map
        try:
            payload = self.fetch_movie_genres()
            items = payload.get("genres", payload if isinstance(payload, list) else [])
            self.movie_genre_map = {
                int(item.get("id")): item.get("name")
                for item in items
                if item.get("id") is not None and item.get("name")
            }
        except Exception:
            self.movie_genre_map = self.movie_genre_map or {}
        return self.movie_genre_map

    def movie_genres_for_card(self, card):
        genres = card.get("genres") if isinstance(card, dict) else None
        if genres:
            return [str(item) for item in genres if item]
        return self.movie_genre_names((card or {}).get("genre_ids") or [])

    def movie_genre_names(self, genre_ids):
        genre_map = self.movie_genre_map or self.ensure_movie_genres_loaded()
        names = []
        for genre_id in genre_ids or []:
            try:
                name = genre_map.get(int(genre_id))
            except (TypeError, ValueError):
                name = None
            if name:
                names.append(name)
        return names

    def movie_genre_summary(self, card_or_genre_ids, limit=2):
        if isinstance(card_or_genre_ids, dict):
            names = self.movie_genres_for_card(card_or_genre_ids)
            genre_ids = card_or_genre_ids.get("genre_ids") or []
        else:
            genre_ids = card_or_genre_ids or []
            names = self.movie_genre_names(genre_ids)
        if names:
            return " / ".join(names[:limit])
        if genre_ids:
            return f"{len(genre_ids)} genres"
        return ""

    def build_place_card_view_model(self, card, include_image=False, favorite_lookup=True, compact=True):
        formatted_address = card.get("formatted_address") or ""
        address = formatted_address
        if compact and len(address) > 42:
            address = f"{address[:42]}..."
        types = [item.replace("_", " ").title() for item in (card.get("types") or [])[:2]]
        rating = card.get("rating")
        open_now = card.get("open_now")
        status = ""
        if open_now is True:
            status = "Open now"
        elif open_now is False:
            status = "Closed"
        return {
            "base_card_id": card.get("id") or 0,
            "card_type": "place",
            "title": card.get("name") or "Place",
            "subtitle": address,
            "description": " / ".join(types),
            "meta_left": f"Rating {rating:.1f}" if isinstance(rating, (int, float)) else "",
            "meta_right": card.get("price_level") or "",
            "accent_text": status,
            "image_url": "",
            "has_image": False if not include_image else False,
            "is_favorite": (card.get("id") or 0) in self.favorite_card_ids if favorite_lookup else False,
        }

    def build_movie_card_view_model(self, card, include_image=False, favorite_lookup=True, compact=True):
        title = card.get("title") or "Movie"
        original_title = card.get("original_title") or ""
        release_date = card.get("release_date") or ""
        release_year = release_date[:4] if release_date else ""
        vote_average = card.get("vote_average")
        poster_path = card.get("poster_path")
        image_url = f"https://image.tmdb.org/t/p/w342{poster_path}" if include_image and poster_path else ""
        description = card.get("overview") or ""
        if compact and len(description) > 56:
            description = f"{description[:56]}..."
        return {
            "base_card_id": card.get("id") or 0,
            "card_type": "movie",
            "title": title,
            "subtitle": original_title if original_title != title else "",
            "description": description,
            "meta_left": release_year,
            "meta_right": f"TMDb {vote_average:.1f}" if isinstance(vote_average, (int, float)) else "",
            "accent_text": self.movie_genre_summary(card),
            "image_url": image_url,
            "has_image": bool(image_url),
            "is_favorite": (card.get("id") or 0) in self.favorite_card_ids if favorite_lookup else False,
        }

    def refresh_current_user_snapshot(self):
        try:
            payload = self.fetch_current_user()
            self.current_user_id = int((payload or {}).get("id") or 0)
            self.current_user_email = (payload or {}).get("email") or self.current_user_email
            self.user_profile = payload or {}
        except Exception:
            return

    # Message actions API group.
    def add_message_reaction(self, message_id, reaction_type):
        return self.api_request(
            f"/api/v1/messages/{message_id}/reactions",
            method="POST",
            data={"type": reaction_type},
        )

    def delete_message_reaction(self, message_id):
        return self.api_request(f"/api/v1/messages/{message_id}/reactions", method="DELETE")

    def stop_message_generation(self, message_id):
        return self.api_request(f"/api/v1/messages/{message_id}/stop", method="DELETE")

    # Favorites API group.
    def fetch_favorite_cards(self, offset=0, limit=100):
        return self.api_request(f"/api/v1/favorites/cards?offset={offset}&limit={limit}")

    def fetch_favorite_card(self, base_card_id):
        return self.api_request(f"/api/v1/favorites/cards/{base_card_id}")

    def add_favorite_card(self, base_card_id):
        response = self.api_request(f"/api/v1/favorites/cards/{base_card_id}", method="POST")
        if base_card_id not in self.favorite_card_ids:
            self.favorite_card_ids = [*self.favorite_card_ids, base_card_id]
        return response

    def remove_favorite_card(self, base_card_id):
        response = self.api_request(f"/api/v1/favorites/cards/{base_card_id}", method="DELETE")
        self.favorite_card_ids = [item for item in self.favorite_card_ids if item != base_card_id]
        return response

    def refresh_favorite_ids(self):
        if not self.access_token:
            self.favorite_card_ids = []
            return
        try:
            payload = self.fetch_favorite_cards(offset=0, limit=100)
            self.favorite_card_ids = [
                item.get("base_card_id")
                for item in (payload or {}).get("items", []) or []
                if item.get("base_card_id") is not None
            ]
        except Exception:
            self.favorite_card_ids = []

    def build_onboarding_payload(self):
        state = self.onboarding_state or {}
        budget_map = {
            "low": "low",
            "mid": "medium",
            "high": "plus",
        }
        payload = {
            "language_code": state.get("language_code") or "en",
            "city": state.get("city"),
            "preferences": {
                "gender": state.get("gender"),
                "age_range": state.get("age_range"),
                "focus": state.get("focus") or [],
                "activity_type": state.get("activity_type") or [],
                "lifestyle": state.get("lifestyle") or [],
            },
        }
        budget_value = budget_map.get(state.get("budget"))
        if budget_value:
            payload["preferences"]["budget"] = budget_value
        return payload

    def sync_onboarding_to_backend(self):
        if not self.access_token or not self.onboarding_state:
            return
        payload = self.build_onboarding_payload()
        return self.update_current_user(payload)

    # Chat API group.
    def fetch_user_chats(self, offset=0, limit=20):
        return self.api_request(f"/api/v1/chats?offset={offset}&limit={limit}")

    def create_chat(self):
        return self.api_request("/api/v1/chats", method="POST")

    def fetch_chat_messages(self, chat_id, offset=0, limit=100):
        return self.api_request(f"/api/v1/chats/{chat_id}/messages?offset={offset}&limit={limit}")

    def delete_chat(self, chat_id):
        return self.api_request(f"/api/v1/chats/{chat_id}", method="DELETE")

    def send_chat_message(self, chat_id, text, location=None):
        return self.api_request(
            f"/api/v1/chats/{chat_id}/messages",
            method="POST",
            data={
                "content": text,
                "type": "text",
                "location": dict(location or DEFAULT_LOCATION),
            },
        )

    def _preferred_language_code(self):
        profile_lang = (self.user_profile or {}).get("language_code")
        onboarding_lang = (self.onboarding_state or {}).get("language_code")
        return profile_lang or onboarding_lang or "en"

    def merge_profile_with_fallback(self, payload):
        merged = dict(payload or {})
        preferences = dict((merged.get("preferences") or {}))
        fallback = self.onboarding_state or {}
        merged["email"] = merged.get("email") or self.current_user_email
        merged["city"] = merged.get("city") or fallback.get("city")
        merged["language_code"] = merged.get("language_code") or fallback.get("language_code") or "en"
        preferences["gender"] = preferences.get("gender") or fallback.get("gender")
        preferences["age_range"] = preferences.get("age_range") or fallback.get("age_range")
        preferences["focus"] = preferences.get("focus") or fallback.get("focus") or []
        preferences["activity_type"] = preferences.get("activity_type") or fallback.get("activity_type") or []
        preferences["lifestyle"] = preferences.get("lifestyle") or fallback.get("lifestyle") or []
        merged["preferences"] = preferences
        return merged

    def format_subscription_status(self, profile):
        subscription_type = (profile or {}).get("subscription_type")
        expires_at = (profile or {}).get("subscription_expires_at")
        if not subscription_type:
            return "Free"
        if self.is_subscription_expired(expires_at):
            return "Expired"
        return str(subscription_type).replace("_", " ").title()

    def has_active_subscription(self, profile):
        subscription_type = (profile or {}).get("subscription_type")
        expires_at = (profile or {}).get("subscription_expires_at")
        return bool(subscription_type and not self.is_subscription_expired(expires_at))

    def is_subscription_expired(self, raw_value):
        if not raw_value:
            return False
        try:
            value = str(raw_value).replace("Z", "+00:00")
            expires_at = datetime.fromisoformat(value)
            if expires_at.tzinfo is not None:
                return expires_at <= datetime.now(expires_at.tzinfo)
            return expires_at <= datetime.now()
        except (TypeError, ValueError):
            return False


if __name__ == "__main__":
    MainApp().run()
