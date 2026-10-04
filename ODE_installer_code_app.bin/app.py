import ODE
import json
import subprocess
import threading

_ode = ODE.ODE()
_ode.start()
_shapes = ODE.shapes()

# the backend that checks the disk and installs; see fix_src/ode-install
INSTALLER = "/usr/sbin/ode-install"
MEDIUM = "/run/ode/medium"
MEDIUM_DEV = "/run/ode/medium.dev"
FIND_MEDIUM = "/usr/sbin/ode-find-medium"
INSTALL_LOG = "/var/log/ode-install.log"
GPARTED_LOG = "/var/log/ode-gparted.log"

ESP_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
BIOS_BOOT_GUID = "21686148-6449-6e6f-744e-656564454649"
HOST_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
ACCOUNT_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789_-"
# names the system already uses for itself
RESERVED_ACCOUNTS = {
    "root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail", "news", "uucp",
    "proxy", "www-data", "backup", "list", "irc", "gnats", "nobody", "messagebus", "sshd",
    "polkitd", "avahi", "colord", "pulse", "rtkit", "tss", "usbmux", "dnsmasq", "user",
}

ORANGE = (255, 170, 60)
RED = (255, 90, 90)
GREEN = (90, 210, 120)
DIM = (120, 120, 120)


def human_size(num_bytes):
    # binary units, as GParted and the backend's messages use
    value = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return ("%.0f %s" if unit in ("B", "KiB") else "%.1f %s") % (value, unit)
        value /= 1024.0


def margin(w):
    return 80 if w >= 1100 else 40


class ConfigManager:
    def __init__(self):
        self.ifelx = _ode.ifelx
        self.path = self.ifelx.path.join(_ode.DIR, "config.json")
        self.data = self._load()

    def _load(self):
        if self.ifelx.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"pages": {}, "system": {}}

    def get_logo_path(self):
        return self.data.get("logo_path")

    def get_logos_dir(self):
        return self.data.get("logos_dir")

    def get_text(self, page_key, field, default=""):
        return self.data.get("pages", {}).get(page_key, {}).get(field, default)

    def get_system(self, field, default=None):
        return self.data.get("system", {}).get(field, default)


class AppState:
    def __init__(self):
        self.current_page = 1
        self.total_pages = 8
        self.accepted_terms = False
        self.disks = []
        self.selected_disk = None
        self.mode = None                 # "erase" or "manual"
        self.partitions = []
        self.selected_partition = None
        self.check_ok = False
        self.check_lines = []            # [("WARN" | "FAIL", message)]
        self.hostname = ""
        self.account = ""
        self.password = ""
        self.finish_action = None        # "reboot" or "poweroff"

    def disk(self):
        for d in self.disks:
            if d["name"] == self.selected_disk:
                return d
        return None

    def partition(self):
        for p in self.partitions:
            if p["name"] == self.selected_partition:
                return p
        return None


class DiskManager:
    def __init__(self, ode, config):
        self.ifelx = ode.ifelx
        self.ode = ode
        self.config = config
        self.searching = False

    def _read(self, path, default=""):
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except OSError:
            return default

    def image_path(self):
        return self.config.get_system("image", MEDIUM + "/ifelxos/filesystem.squashfs")

    def image_present(self):
        return self.ifelx.path.isfile(self.image_path())

    def min_root_mib(self):
        return int(self.config.get_system("min_root_mib", 6144))

    def medium_disk(self):
        """the disk the installer started from: never offered as a target"""
        # ode-find-medium writes the device down; when the medium is an ISO
        # file, the mount itself is only a loop device
        dev = self._read(MEDIUM_DEV)
        if not dev:
            try:
                with open("/proc/mounts", "r") as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 2 and parts[1] == MEDIUM:
                            dev = parts[0]
                            break
            except OSError:
                pass
        if not dev:
            return None
        name = dev.rsplit("/", 1)[-1]
        sys_path = "/sys/class/block/" + name
        if self.ifelx.path.exists(sys_path + "/partition"):
            name = self.ifelx.path.basename(self.ifelx.path.dirname(self.ifelx.path.realpath(sys_path)))
        return name

    def search_medium(self):
        """looks for the installation medium again, in the background"""
        if self.searching:
            return
        self.searching = True

        def run():
            try:
                subprocess.run([FIND_MEDIUM, "10"], capture_output=True, timeout=120)
            except (OSError, subprocess.SubprocessError):
                pass
            self.searching = False

        threading.Thread(target=run, daemon=True).start()

    def list_disks(self):
        # read from sysfs, which is always there
        result = []
        medium = self.medium_disk()
        try:
            names = sorted(self.ifelx.listdir("/sys/block"))
        except OSError:
            return result
        for name in names:
            if name.startswith(("loop", "ram", "zram", "sr", "dm-", "md", "fd")):
                continue
            base = "/sys/block/" + name
            try:
                sectors = int(self._read(base + "/size", "0") or 0)
            except ValueError:
                continue
            if sectors < 2048 * 64:
                continue
            vendor = self._read(base + "/device/vendor")
            model = self._read(base + "/device/model")
            if vendor.startswith("0x"):          # virtio and others give a PCI id, not a name
                vendor = ""
            result.append({
                "name": name,
                "bytes": sectors * 512,
                "size": human_size(sectors * 512),
                "model": " ".join(x for x in (vendor, model) if x),
                "medium": name == medium,
            })
        return result

    def _probe(self, dev):
        # blkid's low-level probe reads the device itself, so it works without udev
        try:
            out = subprocess.run(["blkid", "-p", "-o", "export", dev],
                                 capture_output=True, text=True, timeout=15).stdout
        except (OSError, subprocess.SubprocessError):
            return {}
        info = {}
        for line in out.splitlines():
            key, sep, value = line.partition("=")
            if sep:
                info[key] = value
        return info

    def list_partitions(self, disk_name):
        result = []
        if not disk_name:
            return result
        base = "/sys/block/" + disk_name
        try:
            entries = self.ifelx.listdir(base)
        except OSError:
            return result
        for name in entries:
            if not self.ifelx.path.exists(base + "/" + name + "/partition"):
                continue
            try:
                number = int(self._read(base + "/" + name + "/partition", "0"))
                sectors = int(self._read(base + "/" + name + "/size", "0"))
            except ValueError:
                continue
            info = self._probe("/dev/" + name)
            ptype = info.get("PART_ENTRY_TYPE", "").lower()
            if ptype in ("0x5", "0xf", "0x85"):
                kind = "extended"
            elif ptype in (ESP_GUID, "0xef"):
                kind = "EFI"
            elif ptype == BIOS_BOOT_GUID:
                kind = "BIOS boot"
            else:
                kind = ""
            result.append({
                "name": name,
                "number": number,
                "bytes": sectors * 512,
                "size": human_size(sectors * 512),
                "fstype": info.get("TYPE", ""),
                "label": info.get("LABEL", "") or info.get("PART_ENTRY_NAME", ""),
                "kind": kind,
            })
        result.sort(key=lambda p: p["number"])
        return result

    def check(self, mode, disk_name, part_name=None):
        """asks the backend whether the installation can go ahead; changes nothing"""
        argv = [INSTALLER, "check", mode, "/dev/" + disk_name]
        if part_name:
            argv.append("/dev/" + part_name)
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            return False, [("FAIL", "the installer backend could not run: %s" % e)]
        lines = []
        for line in r.stdout.splitlines():
            kind, _, msg = line.partition(" ")
            if kind in ("FAIL", "WARN"):
                lines.append((kind, msg))
        ok = r.returncode == 0 and "OK" in r.stdout.splitlines()
        if not ok and not any(k == "FAIL" for k, _ in lines):
            lines.append(("FAIL", "the disk could not be checked"))
        return ok, lines

    def open_gparted(self, disk_name=None):
        """Runs GParted on a screen of its own and waits for it to close.

        The installer's window is closed first and opened again afterwards: a
        full-screen window that stays open hides GParted (or minimizes itself
        with no panel to bring it back), which looked like a frozen system.
        Returns GParted's exit status."""
        argv = ["gparted"]
        if disk_name:
            argv.append("/dev/" + disk_name)
        self.ode.release_screen()
        try:
            with open(GPARTED_LOG, "a") as log:
                rc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT).returncode
        except OSError:
            rc = 127
        finally:
            self.ode.restore_screen()
        return rc


class Installer:
    """Runs ode-install in a thread and follows its output, so the window keeps
    drawing (and answering) during the whole installation."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.running = False
        self.started = False
        self.done = False
        self.error = None
        self.progress = 0
        self.step = ""
        self.log = []
        self.warnings = []

    def start(self, argv, password):
        self.reset()
        self.running = True
        self.started = True
        threading.Thread(target=self._run, args=(argv, password), daemon=True).start()

    def _line(self, line, logfile):
        logfile.write(line + "\n")
        logfile.flush()
        kind, _, rest = line.partition(" ")
        with self.lock:
            if kind == "STEP":
                name, _, pct = rest.partition(" ")
                self.step = name
                self.progress = max(self.progress, self._pct(pct))
            elif kind == "PROGRESS":
                self.progress = max(self.progress, self._pct(rest))
            elif kind == "WARN":
                self.warnings.append(rest)
                self.log.append("warning: " + rest)
            elif kind == "ERROR":
                self.error = rest
                self.log.append("error: " + rest)
            elif kind == "DONE":
                self.done = True
                self.progress = 100
            elif line.strip():
                self.log.append(line)
            self.log = self.log[-200:]

    @staticmethod
    def _pct(text):
        try:
            return max(0, min(100, int(text.strip())))
        except ValueError:
            return 0

    def _run(self, argv, password):
        try:
            with open(INSTALL_LOG, "a") as logfile:
                logfile.write("---- " + " ".join(argv) + "\n")
                proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1)
                # the password goes through a pipe, never on the command line
                proc.stdin.write(password + "\n")
                proc.stdin.close()
                for line in proc.stdout:
                    self._line(line.rstrip("\n"), logfile)
                rc = proc.wait()
        except OSError as e:
            rc = -1
            with self.lock:
                self.error = "the installer backend could not run: %s" % e
        with self.lock:
            if not self.done and not self.error:
                self.error = "the installation stopped unexpectedly (status %d)" % rc
            self.running = False


class LogoManager:
    def __init__(self, ode, config):
        self.ifelx = ode.ifelx
        self.ode = ode
        self.config = config

    def resolve(self):
        fixed = self.config.get_logo_path()
        if fixed:
            return [fixed], True
        logos_dir = self.config.get_logos_dir() or self.ode.DIR
        found = []
        if self.ifelx.path.isdir(logos_dir):
            for f in sorted(self.ifelx.listdir(logos_dir)):
                if f.lower().endswith((".png", ".jpg", ".jpeg")):
                    found.append(self.ifelx.path.join(logos_dir, f))
        return found, False


class NavBar:
    def __init__(self, ode, shapes, logo_path=None):
        self.ode = ode
        self.shapes = shapes
        self.logo_path = logo_path
        self.resource_manager = self.ode.get_resource_manager()

    def set_logo(self, logo_path):
        self.logo_path = logo_path

    def render(self, screen, page_num, total_pages):
        w, h = screen.get_size()
        bar_h = 6
        step = w / total_pages
        self.shapes.rectangle(screen, self.ode.GRAY, self.ode.dexpy.Rect(0, 0, w, bar_h))
        self.shapes.rectangle(
            screen,
            self.ode.DARK_BLUE,
            self.ode.dexpy.Rect(0, 0, int(step * page_num), bar_h),
        )
        self.shapes.text(
            screen,
            str(page_num) + " / " + str(total_pages),
            18,
            self.ode.GRAY,
            w - 90,
            16,
        )
        if self.logo_path:
            image = self.resource_manager.get_image(self.logo_path, scale_to=(36, 36))
            screen.blit(image, (16, 14))


def bottom_buttons(page, screen, back=True, next_label="Next", next_enabled=True):
    """Back on the left, Next on the right, the same place on every page"""
    w, h = screen.get_size()
    m = margin(w)
    page.back_btn = None
    page.next_btn = None
    if back:
        page.back_btn = _shapes.button(
            screen, m, h - 110, 180, 60, page.ode.GRAY, "Back", 22, page.ode.BLACK, 38
        )
    if next_label:
        color = page.ode.DARK_BLUE if next_enabled else (60, 60, 70)
        text_color = page.ode.WHITE if next_enabled else DIM
        rect = _shapes.button(
            screen, w - m - 220, h - 110, 220, 60, color, next_label, 22, text_color, 38
        )
        page.next_btn = rect if next_enabled else None


def draw_messages(screen, lines, x, y, width, size=19):
    for kind, msg in lines:
        color = RED if kind == "FAIL" else ORANGE
        y += _shapes.text_wrapped(screen, ("!  " if kind == "FAIL" else "-  ") + msg,
                                  size, color, x, y, width, 4)
        y += 6
    return y


class PageWelcome:
    key = "welcome"

    def __init__(self, ode, shapes, state, config, logo_manager):
        self.ode = ode
        self.shapes = shapes
        self.state = state
        self.config = config
        self.logo_manager = logo_manager
        self.resource_manager = self.ode.get_resource_manager()
        self.next_btn = None
        self._logo_loaded = False
        self.logo_path = None

    def render(self, screen):
        screen.fill(self.ode.BLACK)
        w, h = screen.get_size()

        if not self._logo_loaded:
            logos, locked = self.logo_manager.resolve()
            if logos:
                self.logo_path = logos[0]
            self._logo_loaded = True

        title = self.config.get_text(self.key, "title", "ODE Installer")
        subtitle = self.config.get_text(self.key, "subtitle", "IFelx")
        system = self.config.get_system("name", "IFelxOS2")

        if self.logo_path:
            image = self.resource_manager.get_image(self.logo_path, scale_to=(120, 120))
            screen.blit(image, (w // 2 - 60, h // 2 - 280))

        self.shapes.text(screen, title, 72, self.ode.WHITE, w // 2 - 260, h // 2 - 160)
        self.shapes.text(screen, subtitle, 26, self.ode.GRAY, w // 2 - 260, h // 2 - 80)
        self.shapes.text(screen, "Installs " + system + " on this computer", 22, DIM,
                         w // 2 - 260, h // 2 - 36)
        self.next_btn = self.shapes.button(
            screen, w // 2 - 110, h - 160, 220, 64, self.ode.DARK_BLUE,
            "Start", 26, self.ode.WHITE, 38,
        )

    def handle_event(self, event):
        if self.next_btn and self.shapes.is_button_clicked(self.next_btn, event):
            self.state.current_page = 2


class PageTerms:
    key = "terms"

    def __init__(self, ode, shapes, state, config):
        self.ode = ode
        self.shapes = shapes
        self.state = state
        self.config = config
        self.accept_btn = None
        self.back_btn = None
        self.next_btn = None

    def render(self, screen):
        screen.fill(self.ode.BLACK)
        w, h = screen.get_size()
        m = margin(w)
        self.shapes.text(screen, "Terms and Conditions", 42, self.ode.WHITE, m, 80)
        body = self.config.get_text(
            self.key, "body",
            "AGPL-3.0 licensed. By continuing you accept all listed terms."
        )
        box = self.ode.dexpy.Rect(m, 160, w - 2 * m, h - 380)
        self.shapes.block_with_border_radius(screen, self.ode.GRAY, box, 32)
        # the text wraps inside the box instead of running past its edge
        self.shapes.text_wrapped(screen, body, 22, self.ode.BLACK, box.x + 32, box.y + 30,
                                 box.width - 64, 8)

        color = self.ode.DARK_BLUE if self.state.accepted_terms else self.ode.GRAY
        label = "Accepted" if self.state.accepted_terms else "Accept Terms"
        text_color = self.ode.WHITE if self.state.accepted_terms else self.ode.BLACK
        self.accept_btn = self.shapes.button(
            screen, m, h - 200, 260, 60, color, label, 22, text_color, 38
        )
        bottom_buttons(self, screen, next_enabled=self.state.accepted_terms)

    def handle_event(self, event):
        if self.accept_btn and self.shapes.is_button_clicked(self.accept_btn, event):
            self.state.accepted_terms = not self.state.accepted_terms
        if self.back_btn and self.shapes.is_button_clicked(self.back_btn, event):
            self.state.current_page = 1
        if self.next_btn and self.shapes.is_button_clicked(self.next_btn, event):
            self.state.current_page = 3


class PageSelectDisk:
    key = "select_disk"

    def __init__(self, ode, shapes, state, disk_manager):
        self.ode = ode
        self.shapes = shapes
        self.state = state
        self.disk_manager = disk_manager
        self.disk_buttons = []
        self.back_btn = None
        self.next_btn = None
        self.refresh_btn = None
        self._loaded = False
        self._searching = False

    def refresh(self):
        self.state.disks = self.disk_manager.list_disks()
        if not self.state.disk():
            self.state.selected_disk = None

    def usable(self, disk):
        if disk["medium"]:
            return False, "installation medium"
        if disk["bytes"] < (self.disk_manager.min_root_mib() + 260) * 1024 * 1024:
            return False, "too small"
        return True, ""

    def render(self, screen):
        if not self._loaded:
            self.refresh()
            self._loaded = True
        if self._searching and not self.disk_manager.searching:
            self.refresh()                   # the medium may have been found
        self._searching = self.disk_manager.searching

        screen.fill(self.ode.BLACK)
        w, h = screen.get_size()
        m = margin(w)
        self.shapes.text(screen, "Select Storage Device", 42, self.ode.WHITE, m, 80)
        self.shapes.text(screen, "The disk " + self.ode_system() + " will be installed on", 20,
                         self.ode.GRAY, m, 136)

        self.disk_buttons = []
        y = 180
        for disk in self.state.disks:
            ok, why = self.usable(disk)
            selected = self.state.selected_disk == disk["name"]
            if not ok:
                color, text_color = (45, 45, 50), DIM
            elif selected:
                color, text_color = self.ode.DARK_BLUE, self.ode.WHITE
            else:
                color, text_color = self.ode.GRAY, self.ode.BLACK
            rect = self.shapes.button(screen, m, y, w - 2 * m, 70, color, "", 22, text_color, 24)
            label = "/dev/" + disk["name"] + "    " + disk["size"]
            self.shapes.text(screen, label, 24, text_color, m + 28, y + 10)
            detail = disk["model"] or "disk"
            if why:
                detail += "   (" + why + ")"
            self.shapes.text_fit(screen, detail, 18, text_color, m + 28, y + 42, w - 2 * m - 56)
            if ok:
                self.disk_buttons.append((rect, disk["name"]))
            y += 86
            if y > h - 220:
                break

        if not self.state.disks:
            self.shapes.text(screen, "No disks detected", 22, self.ode.GRAY, m, 200)
        if self.disk_manager.searching:
            self.shapes.text(screen, "Looking for the installation medium...", 20, ORANGE, m, h - 190)
        elif not self.disk_manager.image_present():
            self.shapes.text_wrapped(
                screen, "The " + self.ode_system() + " image (ifelxos/filesystem.squashfs) was not "
                "found on any disk. Plug in the USB stick or insert the disc it is on, then press "
                "Refresh.", 20, RED, m, h - 190, w - 2 * m)

        self.refresh_btn = self.shapes.button(
            screen, m + 200, h - 110, 180, 60, self.ode.GRAY, "Refresh", 22, self.ode.BLACK, 38
        )
        bottom_buttons(self, screen, next_enabled=bool(self.state.selected_disk)
                       and self.disk_manager.image_present())

    def ode_system(self):
        return self.disk_manager.config.get_system("name", "IFelxOS2")

    def handle_event(self, event):
        for btn, name in self.disk_buttons:
            if self.shapes.is_button_clicked(btn, event):
                if self.state.selected_disk != name:
                    self.state.selected_disk = name
                    self.state.mode = None
                    self.state.selected_partition = None
                    self.state.check_ok = False
                    self.state.check_lines = []
        if self.refresh_btn and self.shapes.is_button_clicked(self.refresh_btn, event):
            if not self.disk_manager.image_present():
                self.disk_manager.search_medium()
            self.refresh()
        if self.back_btn and self.shapes.is_button_clicked(self.back_btn, event):
            self.state.current_page = 2
        if self.next_btn and self.shapes.is_button_clicked(self.next_btn, event):
            self.state.current_page = 4


class PageInstallType:
    key = "install_type"

    def __init__(self, ode, shapes, state, disk_manager):
        self.ode = ode
        self.shapes = shapes
        self.state = state
        self.disk_manager = disk_manager
        self.erase_btn = None
        self.manual_btn = None
        self.part_buttons = []
        self.gparted_btn = None
        self.refresh_btn = None
        self.back_btn = None
        self.next_btn = None
        self.scroll = 0
        self.notice = ""
        self._loaded_for = None

    def reload_partitions(self):
        self.state.partitions = self.disk_manager.list_partitions(self.state.selected_disk)
        if not self.state.partition():
            self.state.selected_partition = None
        self.scroll = 0

    def run_check(self):
        if self.state.mode == "erase":
            ok, lines = self.disk_manager.check("erase", self.state.selected_disk)
        elif self.state.mode == "manual" and self.state.selected_partition:
            ok, lines = self.disk_manager.check("manual", self.state.selected_disk,
                                                self.state.selected_partition)
        else:
            ok, lines = False, []
        self.state.check_ok = ok
        self.state.check_lines = lines

    def option(self, screen, x, y, width, height, selected, title, text):
        color = self.ode.DARK_BLUE if selected else (40, 40, 48)
        rect = self.shapes.button(screen, x, y, width, height, color, "", 22, self.ode.WHITE, 22)
        if selected:
            self.ode.dexpy.draw.rect(screen, self.ode.WHITE, rect, 2, border_radius=22)
        self.shapes.text(screen, title, 23, self.ode.WHITE, x + 24, y + 14)
        self.shapes.text_wrapped(screen, text, 17, self.ode.GRAY if not selected else self.ode.LIGHT_GRAY,
                                 x + 24, y + 48, width - 48, 2)
        return rect

    def render(self, screen):
        if self._loaded_for != self.state.selected_disk:
            self.reload_partitions()
            self._loaded_for = self.state.selected_disk
            if self.state.mode:
                self.run_check()

        screen.fill(self.ode.BLACK)
        w, h = screen.get_size()
        m = margin(w)
        disk = self.state.disk() or {"name": str(self.state.selected_disk), "size": ""}
        self.shapes.text(screen, "Installation Type", 42, self.ode.WHITE, m, 80)
        self.shapes.text(screen, "/dev/" + disk["name"] + "   " + disk["size"], 20,
                         self.ode.GRAY, m, 136)

        half = (w - 2 * m - 20) // 2
        self.erase_btn = self.option(
            screen, m, 176, half, 110, self.state.mode == "erase",
            "Erase disk and install",
            "Deletes everything on the disk and creates the partitions automatically.")
        self.manual_btn = self.option(
            screen, m + half + 20, 176, half, 110, self.state.mode == "manual",
            "Choose a partition",
            "Installs on a partition you choose; the others are kept. "
            "GParted can create or resize partitions.")

        y = 306
        self.part_buttons = []
        self.gparted_btn = None
        self.refresh_btn = None
        msg_top = h - 240
        if self.state.mode == "manual":
            row_h = 46
            visible = max(1, (msg_top - y - 10) // (row_h + 6))
            parts = self.state.partitions
            self.scroll = max(0, min(self.scroll, max(0, len(parts) - visible)))
            if not parts:
                self.shapes.text(screen, "This disk has no partitions. Create one with GParted.",
                                 20, self.ode.GRAY, m, y + 8)
            for part in parts[self.scroll:self.scroll + visible]:
                selected = self.state.selected_partition == part["name"]
                pickable = part["kind"] not in ("extended", "EFI", "BIOS boot")
                if selected:
                    color, text_color = self.ode.DARK_BLUE, self.ode.WHITE
                elif pickable:
                    color, text_color = self.ode.GRAY, self.ode.BLACK
                else:
                    color, text_color = (45, 45, 50), DIM
                rect = self.shapes.button(screen, m, y, w - 2 * m, row_h, color, "", 20, text_color, 18)
                self.shapes.text(screen, "/dev/" + part["name"], 21, text_color, m + 22, y + 10)
                self.shapes.text(screen, part["size"], 21, text_color, m + 260, y + 10)
                fs = part["fstype"] or ("" if part["kind"] else "no filesystem")
                info = "   ".join(x for x in (part["kind"], fs, part["label"]) if x)
                self.shapes.text_fit(screen, info, 19, text_color, m + 420, y + 12, w - 2 * m - 440)
                if pickable:
                    self.part_buttons.append((rect, part["name"]))
                y += row_h + 6
            if len(parts) > visible:
                self.shapes.text(screen, "scroll for more (%d partitions)" % len(parts), 16, DIM,
                                 w - m - 260, msg_top - 26)
        elif self.state.mode == "erase":
            self.shapes.text_wrapped(
                screen, "Layout: an EFI system partition (256 MiB) and the system partition "
                "(the rest of the disk). The disk starts on UEFI and BIOS computers.",
                19, self.ode.GRAY, m, y + 4, w - 2 * m)

        if self.notice:
            self.shapes.text_wrapped(screen, self.notice, 19, ORANGE, m, msg_top, w - 2 * m)
            msg_top += 30
        if self.state.mode == "manual" and not self.state.selected_partition and self.state.partitions:
            self.shapes.text(screen, "Select the partition for the system.", 19, self.ode.GRAY, m, msg_top)
        draw_messages(screen, self.state.check_lines, m, msg_top, w - 2 * m)

        if self.state.mode == "manual":
            self.gparted_btn = self.shapes.button(
                screen, m + 200, h - 110, 220, 60, self.ode.DARK_BLUE, "Open GParted", 21,
                self.ode.WHITE, 38)
            self.refresh_btn = self.shapes.button(
                screen, m + 440, h - 110, 160, 60, self.ode.GRAY, "Refresh", 21, self.ode.BLACK, 38)
        bottom_buttons(self, screen, next_enabled=self.state.check_ok)

    def handle_event(self, event):
        if event.type == self.ode.dexpy.MOUSEWHEEL and self.state.mode == "manual":
            self.scroll = max(0, self.scroll - event.y)
            return
        if self.erase_btn and self.shapes.is_button_clicked(self.erase_btn, event):
            self.state.mode = "erase"
            self.notice = ""
            self.run_check()
        if self.manual_btn and self.shapes.is_button_clicked(self.manual_btn, event):
            if self.state.mode != "manual":
                self.state.mode = "manual"
                self.notice = ""
                self.reload_partitions()
                self.run_check()
        for btn, name in self.part_buttons:
            if self.shapes.is_button_clicked(btn, event):
                self.state.selected_partition = name
                self.run_check()
        if self.gparted_btn and self.shapes.is_button_clicked(self.gparted_btn, event):
            rc = self.disk_manager.open_gparted(self.state.selected_disk)
            if rc == 0:
                self.notice = ""
            elif rc == 127:
                self.notice = "GParted could not be started."
            elif rc < 0:
                self.notice = "GParted stopped unexpectedly (signal %d). See %s." % (-rc, GPARTED_LOG)
            else:
                self.notice = "GParted closed with status %d." % rc
            # the disks and partitions may have changed while it was open
            self.state.disks = self.disk_manager.list_disks()
            self.reload_partitions()
            self.run_check()
            return
        if self.refresh_btn and self.shapes.is_button_clicked(self.refresh_btn, event):
            self.reload_partitions()
            self.run_check()
        if self.back_btn and self.shapes.is_button_clicked(self.back_btn, event):
            self.state.current_page = 3
        if self.next_btn and self.shapes.is_button_clicked(self.next_btn, event):
            self.state.current_page = 5


class PageAccount:
    key = "account"

    def __init__(self, ode, shapes, state, config):
        self.ode = ode
        self.shapes = shapes
        self.state = state
        self.config = config
        self.fields = [
            ODE.text_field("Computer name", config.get_system("default_hostname", "ifelxos2"),
                           max_len=63, allowed=HOST_CHARS),
            ODE.text_field("Account name (a-z, 0-9, '-' and '_')", max_len=32,
                           allowed=ACCOUNT_CHARS, lower=True),
            ODE.text_field("Password", masked=True, max_len=128),
            ODE.text_field("Confirm password", masked=True, max_len=128),
        ]
        self.fields[1].focused = True
        self.back_btn = None
        self.next_btn = None

    def problem(self):
        host, account, pw, pw2 = (f.value for f in self.fields)
        if not host:
            return "Enter a name for this computer."
        if host.startswith("-") or host.endswith("-"):
            return "The computer name cannot start or end with '-'."
        if not account:
            return "Enter a name for your account."
        if not account[0].isalpha():
            return "The account name must start with a letter."
        if account in RESERVED_ACCOUNTS:
            return "The account name '%s' is used by the system; choose another." % account
        if len(pw) < 4:
            return "The password needs at least 4 characters."
        if pw != pw2:
            return "The two passwords are not the same."
        return ""

    def render(self, screen):
        screen.fill(self.ode.BLACK)
        w, h = screen.get_size()
        m = margin(w)
        self.shapes.text(screen, "Your Account", 42, self.ode.WHITE, m, 80)
        self.shapes.text(screen, "The account you will sign in with. It can administer the "
                         "computer with its password (sudo).", 19, self.ode.GRAY, m, 136)
        width = min(560, w - 2 * m)
        y = 186
        for field in self.fields:
            y = field.render(screen, m, y, width) + 18
        problem = self.problem()
        if problem and any(f.value for f in self.fields[1:]):
            self.shapes.text_wrapped(screen, problem, 19, ORANGE, m, y + 4, width)
        bottom_buttons(self, screen, next_enabled=not problem)

    def focus(self, index):
        for i, f in enumerate(self.fields):
            f.focused = i == index

    def handle_event(self, event):
        for i, field in enumerate(self.fields):
            result = field.handle_event(event)
            if result == "focus":
                self.focus(i)
            elif result == "next":
                self.focus((i + 1) % len(self.fields))
                break
            elif result == "submit":
                if i < len(self.fields) - 1:
                    self.focus(i + 1)
                elif not self.problem():
                    self.go_next()
                break
        if self.back_btn and self.shapes.is_button_clicked(self.back_btn, event):
            self.state.current_page = 4
        if self.next_btn and self.shapes.is_button_clicked(self.next_btn, event):
            self.go_next()

    def go_next(self):
        self.state.hostname, self.state.account, self.state.password, _ = (f.value for f in self.fields)
        self.state.current_page = 6


class PageSummary:
    key = "summary"

    def __init__(self, ode, shapes, state, config, installer):
        self.ode = ode
        self.shapes = shapes
        self.state = state
        self.config = config
        self.installer = installer
        self.back_btn = None
        self.next_btn = None

    def render(self, screen):
        screen.fill(self.ode.BLACK)
        w, h = screen.get_size()
        m = margin(w)
        system = self.config.get_system("name", "IFelxOS2")
        disk = self.state.disk() or {"name": str(self.state.selected_disk), "size": "", "model": ""}
        self.shapes.text(screen, "Final Confirmation", 42, self.ode.WHITE, m, 80)
        box = self.ode.dexpy.Rect(m, 160, w - 2 * m, h - 400)
        self.shapes.block_with_border_radius(screen, self.ode.GRAY, box, 32)
        lines = [
            "System:  " + system,
            "Disk:  /dev/" + disk["name"] + "   " + disk["size"] + "   " + disk.get("model", ""),
        ]
        if self.state.mode == "erase":
            lines.append("Partitions:  the whole disk is erased and partitioned again")
        else:
            lines.append("System partition:  /dev/" + str(self.state.selected_partition) + "  (formatted)")
        lines.append("Computer name:  " + self.state.hostname)
        lines.append("Account:  " + self.state.account)
        y = box.y + 28
        for line in lines:
            self.shapes.text_fit(screen, line, 22, self.ode.BLACK, box.x + 32, y, box.width - 64)
            y += 42
        if self.state.mode == "erase":
            warning = "Everything on /dev/" + disk["name"] + " will be deleted. This cannot be undone."
        else:
            warning = ("Everything on /dev/" + str(self.state.selected_partition) +
                       " will be deleted. The other partitions are kept.")
        self.shapes.text_wrapped(screen, warning, 21, (170, 0, 0), box.x + 32, y + 8, box.width - 64)
        draw_messages(screen, [l for l in self.state.check_lines if l[0] == "WARN"],
                      m, box.bottom + 16, w - 2 * m, 18)
        bottom_buttons(self, screen, next_label="Install")

    def handle_event(self, event):
        if self.back_btn and self.shapes.is_button_clicked(self.back_btn, event):
            self.state.current_page = 5
        if self.next_btn and self.shapes.is_button_clicked(self.next_btn, event):
            if self.state.mode == "erase":
                argv = [INSTALLER, "erase", "/dev/" + self.state.selected_disk,
                        self.state.hostname, self.state.account]
            else:
                argv = [INSTALLER, "manual", "/dev/" + self.state.selected_disk,
                        "/dev/" + self.state.selected_partition,
                        self.state.hostname, self.state.account]
            self.installer.start(argv, self.state.password)
            self.state.current_page = 7


class PageInstall:
    key = "install"

    STEPS = {
        "partition": "Preparing the disk",
        "format": "Creating the filesystems",
        "copy": "Copying the system",
        "configure": "Setting up the account and the system",
        "efi": "Setting up UEFI start",
        "bootloader": "Writing the boot loader",
        "finish": "Finishing",
    }

    def __init__(self, ode, shapes, state, config, installer):
        self.ode = ode
        self.shapes = shapes
        self.state = state
        self.config = config
        self.installer = installer
        self.back_btn = None
        self.next_btn = None

    def render(self, screen):
        screen.fill(self.ode.BLACK)
        w, h = screen.get_size()
        m = margin(w)
        inst = self.installer
        with inst.lock:
            progress, step, error, done = inst.progress, inst.step, inst.error, inst.done
            log = list(inst.log[-8:])
            warnings = list(inst.warnings)
        system = self.config.get_system("name", "IFelxOS2")

        title = "Installation failed" if error else ("Installed" if done else "Installing " + system)
        self.shapes.text(screen, title, 42, RED if error else self.ode.WHITE, m, 80)
        self.shapes.text(screen, self.STEPS.get(step, "Starting") if not done else "Done", 22,
                         self.ode.GRAY, m, 150)

        bar_w = w - 2 * m
        self.shapes.block_with_border_radius(screen, (50, 50, 55), self.ode.dexpy.Rect(m, 196, bar_w, 34), 17)
        filled = int(bar_w * progress / 100)
        if filled > 0:
            self.shapes.block_with_border_radius(
                screen, RED if error else self.ode.DARK_BLUE,
                self.ode.dexpy.Rect(m, 196, max(filled, 34), 34), 17)
        self.shapes.text(screen, str(progress) + "%", 22, self.ode.WHITE, m, 244)

        y = 296
        for line in log:
            self.shapes.text_fit(screen, line, 16, DIM, m, y, bar_w)
            y += 24
        if error:
            self.shapes.text_wrapped(screen, error, 21, RED, m, y + 14, bar_w)
            self.shapes.text(screen, "The full log is in " + INSTALL_LOG, 17, self.ode.GRAY, m, h - 150)
            bottom_buttons(self, screen, next_label=None)
        elif done:
            if warnings:
                draw_messages(screen, [("WARN", x) for x in warnings], m, y + 14, bar_w, 18)
            bottom_buttons(self, screen, back=False, next_label="Continue")
        else:
            self.shapes.text(screen, "Do not turn the computer off.", 18, self.ode.GRAY, m, h - 150)
            self.back_btn = None
            self.next_btn = None

    def handle_event(self, event):
        if self.installer.running:
            return
        if self.back_btn and self.shapes.is_button_clicked(self.back_btn, event):
            # back to the summary: nothing was kept, so the installation can be started again
            self.installer.reset()
            self.state.current_page = 6
        if self.next_btn and self.shapes.is_button_clicked(self.next_btn, event):
            self.state.password = ""
            self.state.current_page = 8


class PageFinish:
    key = "finish"

    def __init__(self, ode, shapes, state, config):
        self.ode = ode
        self.shapes = shapes
        self.state = state
        self.config = config
        self.reboot_btn = None
        self.poweroff_btn = None

    def render(self, screen):
        screen.fill(self.ode.BLACK)
        w, h = screen.get_size()
        title = self.config.get_text(self.key, "title", "Installation Complete")
        msg = self.config.get_text(self.key, "message", "You can now remove the installation media.")
        self.shapes.text(screen, title, 48, self.ode.WHITE, w // 2 - 280, h // 2 - 160)
        self.shapes.text_wrapped(screen, msg, 22, self.ode.GRAY, w // 2 - 280, h // 2 - 80, 600)
        self.reboot_btn = self.shapes.button(
            screen, w // 2 - 280, h // 2 + 40, 260, 60, self.ode.DARK_BLUE, "Restart", 22, self.ode.WHITE, 38
        )
        self.poweroff_btn = self.shapes.button(
            screen, w // 2, h // 2 + 40, 260, 60, self.ode.GRAY, "Shut Down", 22, self.ode.BLACK, 38
        )

    def handle_event(self, event):
        if self.reboot_btn and self.shapes.is_button_clicked(self.reboot_btn, event):
            self.state.finish_action = "reboot"
        if self.poweroff_btn and self.shapes.is_button_clicked(self.poweroff_btn, event):
            self.state.finish_action = "poweroff"


class App:
    def __init__(self):
        self.ode = _ode
        self.shapes = _shapes
        self.config = ConfigManager()
        self.state = AppState()
        self.disk_manager = DiskManager(self.ode, self.config)
        self.logo_manager = LogoManager(self.ode, self.config)
        self.installer = Installer()
        self.navbar = NavBar(self.ode, self.shapes)

        logos, _ = self.logo_manager.resolve()
        if logos:
            self.navbar.set_logo(logos[0])

        self.pages = {
            1: PageWelcome(self.ode, self.shapes, self.state, self.config, self.logo_manager),
            2: PageTerms(self.ode, self.shapes, self.state, self.config),
            3: PageSelectDisk(self.ode, self.shapes, self.state, self.disk_manager),
            4: PageInstallType(self.ode, self.shapes, self.state, self.disk_manager),
            5: PageAccount(self.ode, self.shapes, self.state, self.config),
            6: PageSummary(self.ode, self.shapes, self.state, self.config, self.installer),
            7: PageInstall(self.ode, self.shapes, self.state, self.config, self.installer),
            8: PageFinish(self.ode, self.shapes, self.state, self.config),
        }

    def run(self):
        screen = self.ode.screen()
        clock = self.ode.clock()
        running = True

        while running:
            for event in self.ode.dexpy.event.get():
                if event.type == self.ode.dexpy.QUIT:
                    # never in the middle of writing the disk
                    if not self.installer.running:
                        running = False
                    continue
                self.pages[self.state.current_page].handle_event(event)
                if self.state.finish_action:
                    running = False
                    break
                if self.ode.screen() is not screen:
                    # GParted had the screen: the events fetched before belong to the old window
                    break

            screen = self.ode.screen()
            self.pages[self.state.current_page].render(screen)
            self.navbar.render(screen, self.state.current_page, self.state.total_pages)
            self.ode.dexpy.display.flip()
            clock.tick(30)

        self.ode.dexpy.quit()
        if self.state.finish_action == "reboot":
            subprocess.run(["/usr/sbin/shutdown", "-r", "now"])
        elif self.state.finish_action == "poweroff":
            subprocess.run(["/usr/sbin/shutdown", "-h", "now"])


if __name__ == "__main__":
    App().run()
