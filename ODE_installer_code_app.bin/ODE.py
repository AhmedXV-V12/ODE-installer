import os

# نافذة SDL بملء الشاشة تُصغّر نفسها عندما تأخذ نافذة أخرى التركيز (مثل GParted)
# ولا يوجد شريط مهام في openbox لإرجاعها فتبقى الشاشة سوداء، لذلك يتم منع ذلك
# قبل تحميل pygame
os.environ.setdefault("SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS", "0")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import time
import pygame
from pygame import font
from datetime import datetime


class ODE:
    
    _instance = None
    _resource_manager = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # الألوان
        self.WHITE = (255, 255, 255)
        self.BLACK = (0, 0, 0)
        self.RED = (255, 0, 0)
        self.GREEN = (0, 255, 0)
        self.BLUE = (0, 0, 255)
        self.GRAY = (200, 200, 200)
        self.YELLOW = (255, 255, 0)
        self.ORANGE = (255, 165, 0)
        self.PURPLE = (128, 0, 128)
        self.CYAN = (0, 255, 255)
        self.PINK = (255, 192, 203)
        self.BROWN = (165, 42, 42)
        self.DARK_GREEN = (0, 100, 0)
        self.DARK_BLUE = (0, 0, 139)
        self.LIGHT_GRAY = (211, 211, 211)
        self.DARK_GRAY = (169, 169, 169)
        
        # أبعاد الشاشة
        self.SCREEN_WIDTH = 1920
        self.SCREEN_HEIGHT = 1080
        
        # إعداد المسارات
        self.DIR = os.path.dirname(__file__)
        # Liberation Sans (SIL Open Font License) has Arial's metrics, so the
        # pages keep their layout; it comes from the installer system's
        # fonts-liberation package. DejaVu Sans if it is missing.
        self.FONT_PATH = '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf'
        if not os.path.exists(self.FONT_PATH):
            self.FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        
        # المراجع
        self.dexpy = pygame
        self.ifelx = os
        
        # حالة التهيئة
        self._initialized = True
        self._pygame_initialized = False
        self._screen = None
        self._clock = None
        self._font_cache = {}
        self._image_cache = {}
        
        # تهيئة مدير الموارد
        if ODE._resource_manager is None:
            ODE._resource_manager = _ResourceManager(self)
    
    def get_resource_manager(self):
        """الحصول على مدير الموارد"""
        if ODE._resource_manager is None:
            ODE._resource_manager = _ResourceManager(self)
        return ODE._resource_manager


    def start(self):
        """تهيئة pygame مرة واحدة فقط"""
        if not self._pygame_initialized:
            self.dexpy.init()
            self.dexpy.font.init()
            self._pygame_initialized = True
        
    def screen(self):
        """الحصول على الشاشة (تُنشأ مرة واحدة فقط)"""
        if self._screen is None:
            if not self.dexpy.display.get_init():
                self.dexpy.display.init()
            info = self.dexpy.display.Info()
            self._screen = self.dexpy.display.set_mode(
                (info.current_w, info.current_h),
                self.dexpy.FULLSCREEN
            )
            self.dexpy.key.set_repeat(400, 40)
        return self._screen

    def release_screen(self):
        """إغلاق النافذة وتسليم الشاشة لبرنامج آخر (مثل GParted)"""
        if self._screen is not None:
            self.dexpy.display.quit()
            self._screen = None
            # الصور المحوّلة مرتبطة بالنافذة القديمة فيتم تحميلها من جديد
            self.get_resource_manager().clear_images()

    def restore_screen(self):
        """إعادة فتح النافذة بعد انتهاء البرنامج الآخر"""
        screen = self.screen()
        self.dexpy.event.clear()
        return screen

    def get_font(self, arabic=True):
        """إرجاع مسار الخط"""
        return self.FONT_PATH
        
    def clock(self):
        """الحصول على الساعة (تُنشأ مرة واحدة فقط)"""
        if self._clock is None:
            self._clock = self.dexpy.time.Clock()
        return self._clock


class _ResourceManager:
    """مدير الموارد - يقوم بـ caching الخطوط والصور"""
    
    def __init__(self, ode):
        self.ode = ode
        self._font_cache = {}
        self._image_cache = {}
    
    def get_font(self, font_size, font_path=None):
        """الحصول على خط مع caching"""
        if font_path is None:
            font_path = self.ode.get_font()
        
        cache_key = (font_path, font_size)
        
        if cache_key not in self._font_cache:
            self._font_cache[cache_key] = self.ode.dexpy.font.Font(font_path, font_size)
        
        return self._font_cache[cache_key]
    
    def get_image(self, image_path, scale_to=None):
        """الحصول على صورة مع caching"""
        cache_key = (image_path, scale_to)
        
        if cache_key not in self._image_cache:
            image = self.ode.dexpy.image.load(image_path).convert_alpha()
            if scale_to:
                image = self.ode.dexpy.transform.scale(image, scale_to)
            self._image_cache[cache_key] = image
        
        return self._image_cache[cache_key]
    
    def clear_cache(self):
        """تنظيف ذاكرة التخزين المؤقت"""
        self._font_cache.clear()
        self._image_cache.clear()

    def clear_images(self):
        """تنظيف الصور فقط (الخطوط تبقى صالحة بعد إغلاق النافذة)"""
        self._image_cache.clear()

    
class shapes:    
    def __init__(self):
        self.ode = ODE()
        self.ode.start()
        self.resource_manager = self.ode.get_resource_manager()

#______________________________________________________________________
#|______________shapes______________________________2025/2026_________|      
    def text(self, surface, text, font_size, color, x, y, align=0):
        # استخدام cached font بدلاً من إعادة إنشاء
        font_obj = self.resource_manager.get_font(font_size)
        text_surf = font_obj.render(text, True, color)
        surface.blit(text_surf, (x, y))
        return text_surf
    
    def block_with_border_radius(self, surface, color, rect, border_radius=0):
        return self.ode.dexpy.draw.rect(surface, color, rect, border_radius=border_radius)

    def block(self, surface, color, rect, width=0):
        return self.ode.dexpy.draw.rect(surface, color, rect, width)
    
    def circle(self, surface, color, center, radius):
        return self.ode.dexpy.draw.circle(surface, color, center, radius)
    
    def rectangle(self, surface, color, rect):
        return self.ode.dexpy.draw.rect(surface, color, rect)
    
    def button(self, surface, x, y, width, height, color, text="", font_size=24, text_color=(0,0,0), border_radius=8):

        rect = pygame.Rect(x, y, width, height)
        # رسم الزر
        self.block_with_border_radius(surface, color, rect, border_radius)

        if text:
            # استخدام cached font بدلاً من إعادة إنشاء
            font_obj = self.resource_manager.get_font(font_size)
            text_surf = font_obj.render(text, True, text_color)
            # محاذاة النص في منتصف الزر
            text_rect = text_surf.get_rect(center=rect.center)
            surface.blit(text_surf, text_rect)

        return rect

    def is_button_clicked(self, rect, event):

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if rect.collidepoint(event.pos):
                return True
        return False

    def wrap(self, text, font_size, width):
        """تقسيم النص إلى أسطر لا يتجاوز كل منها العرض المحدد"""
        font_obj = self.resource_manager.get_font(font_size)
        lines = []
        for paragraph in str(text).split("\n"):
            line = ""
            for word in paragraph.split(" "):
                candidate = word if not line else line + " " + word
                if font_obj.size(candidate)[0] <= width or not line:
                    line = candidate
                else:
                    lines.append(line)
                    line = word
            lines.append(line)
        return lines

    def text_wrapped(self, surface, text, font_size, color, x, y, width, line_gap=6):
        """رسم نص يلتف داخل العرض المحدد، ويرجع الارتفاع المستخدم"""
        font_obj = self.resource_manager.get_font(font_size)
        line_h = font_obj.get_linesize() + line_gap
        lines = self.wrap(text, font_size, width)
        for i, line in enumerate(lines):
            surface.blit(font_obj.render(line, True, color), (x, y + i * line_h))
        return len(lines) * line_h

    def text_fit(self, surface, text, font_size, color, x, y, width):
        """رسم سطر واحد يُقص بثلاث نقاط إذا كان أطول من العرض"""
        font_obj = self.resource_manager.get_font(font_size)
        text = str(text)
        if font_obj.size(text)[0] > width:
            while text and font_obj.size(text + "...")[0] > width:
                text = text[:-1]
            text += "..."
        surface.blit(font_obj.render(text, True, color), (x, y))


class text_field:
    """حقل إدخال نص بسطر واحد (اسم الجهاز، اسم الحساب، كلمة المرور)"""

    def __init__(self, label, value="", masked=False, max_len=63, allowed=None, lower=False):
        self.ode = ODE()
        self.resource_manager = self.ode.get_resource_manager()
        self.label = label
        self.value = value
        self.masked = masked
        self.max_len = max_len
        self.allowed = allowed          # الأحرف المسموحة، أو None لكل الأحرف المطبوعة
        self.lower = lower              # تحويل الأحرف الكبيرة إلى صغيرة أثناء الكتابة
        self.focused = False
        self.rect = None

    def render(self, surface, x, y, width, height=52, font_size=22):
        label_font = self.resource_manager.get_font(18)
        surface.blit(label_font.render(self.label, True, self.ode.GRAY), (x, y))
        self.rect = pygame.Rect(x, y + 26, width, height)
        border = self.ode.WHITE if self.focused else self.ode.DARK_GRAY
        pygame.draw.rect(surface, (30, 30, 30), self.rect, border_radius=10)
        pygame.draw.rect(surface, border, self.rect, 2, border_radius=10)
        shown = "*" * len(self.value) if self.masked else self.value
        font_obj = self.resource_manager.get_font(font_size)
        # يظهر آخر النص إذا كان أطول من الحقل
        while shown and font_obj.size(shown)[0] > width - 36:
            shown = shown[1:]
        text_surf = font_obj.render(shown, True, self.ode.WHITE)
        ty = self.rect.y + (height - text_surf.get_height()) // 2
        surface.blit(text_surf, (x + 14, ty))
        if self.focused and int(time.time() * 2) % 2 == 0:
            cx = x + 16 + text_surf.get_width()
            pygame.draw.line(surface, self.ode.WHITE, (cx, ty + 2), (cx, ty + text_surf.get_height() - 2), 2)
        return self.rect.bottom

    def handle_event(self, event):
        """يرجع 'focus' عند النقر عليه، 'next' عند Tab، 'submit' عند Enter"""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect and self.rect.collidepoint(event.pos):
                return "focus"
            return None
        if not self.focused:
            return None
        if event.type == pygame.TEXTINPUT:
            for ch in event.text:
                if len(self.value) >= self.max_len:
                    break
                if self.lower:
                    ch = ch.lower()
                if not ch.isprintable():
                    continue
                if self.allowed is not None and ch not in self.allowed:
                    continue
                self.value += ch
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                self.value = self.value[:-1]
            elif event.key == pygame.K_TAB:
                return "next"
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return "submit"
        return None

    
    
class apps_mODE:
    def __init__(self):
        self.ode = ODE()
        self.ode.start()
        

    def files_home(self):
        return self.ode.ifelx.listdir(self.ode.ifelx.path.expanduser("~"))
    

class mouse:
    def __init__(self):
        self.ode = ODE()
        self.resource_manager = self.ode.get_resource_manager()
        self._mouse_image_cached = None

    def mouse_obj(self, screen):

        mouse_path = self.ode.ifelx.path.join(self.ode.DIR, "mouse", "m.png")
        backup_path = self.ode.ifelx.path.join(self.ode.DIR, "mouse", "m.bk.png")

        # اختيار المسار الصحيح
        correct_path = mouse_path if self.ode.ifelx.path.exists(mouse_path) else backup_path
        
        # استخدام cached image بدلاً من إعادة تحميل
        image = self.resource_manager.get_image(correct_path)

        rect = image.get_rect()
        rect.topleft = self.ode.dexpy.mouse.get_pos()

        # إخفاء ماوس النظام
        self.ode.dexpy.mouse.set_visible(False)

        def handle_event(event):
            if event.type == self.ode.dexpy.MOUSEMOTION:
                rect.topleft = event.pos

        def get_pos():
            return rect.topleft

        def update(surface):
            surface.blit(image, rect)

        return {
            "handle_event": handle_event,
            "get_pos": get_pos,
            "rect": rect,
            "image": image,
            "update": update
        }

class Tools:
    def __init__(self):
        self.ode = ODE()
        self.shapes = shapes()
        import time
        self.time = time
        

    
    def get_current_time(self):
        """الحصول على الوقت الحالي"""
        return self.time.strftime("%H:%M:%S")
    

    def terminal(self, screen):
        # رسم واجهة الطرفية
        terminal_rect = self.shapes.button(screen, 100, 100, 400, 300, self.ode.GRAY, "Terminal", 24, self.ode.BLACK)
        return terminal_rect