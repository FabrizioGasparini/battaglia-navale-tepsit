"""
client_gui_v5.py — Battaglia Navale GUI Premium
Tema: Naval War Room — dark, military, cinematic.
Audio: generato via waveform puro (nessuna dipendenza esterna).
"""

import tkinter as tk
from tkinter import font as tkfont
import socket, threading, json, os, random, math, struct, wave, io, time
try:
    import winsound
    _WINSOUND = True
except ImportError:
    _WINSOUND = False

try:
    import subprocess as _sp
    _APLAY = (_sp.run(["which","aplay"], capture_output=True).returncode == 0)
except Exception:
    _APLAY = False

from game_logic import Griglia, ACQUA, NAVE, COLPITO, MANCATO, FLOTTA

SERVER_HOST = "127.0.0.1"
SERVER_PORT  = 50007
STATS_FILE   = "statistiche.json"

# ══════════════════════════════════════════════
# AUDIO — WAV sintetizzato, suonato in thread
# ══════════════════════════════════════════════

def _make_wav(frames_bytes: bytes, rate=22050) -> bytes:
    """Costruisce un file WAV mono 16-bit in memoria."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames_bytes)
    return buf.getvalue()

def _synth(duration=0.3, freq=440, shape="sine", decay=True, rate=22050) -> bytes:
    """Sintetizza un tono come PCM 16-bit."""
    n = int(rate * duration)
    samples = []
    for i in range(n):
        t = i / rate
        env = math.exp(-4 * t / duration) if decay else 1.0
        if shape == "sine":
            v = math.sin(2 * math.pi * freq * t)
        elif shape == "noise":
            v = random.uniform(-1, 1)
        elif shape == "square":
            v = 1.0 if math.sin(2 * math.pi * freq * t) > 0 else -1.0
        elif shape == "sweep":
            f = freq * (1 + 2 * t / duration)
            v = math.sin(2 * math.pi * f * t)
        else:
            v = 0.0
        samples.append(int(v * env * 28000))
    return struct.pack(f"<{n}h", *samples)

def _mix(*pcm_list) -> bytes:
    """Mixa più buffer PCM 16-bit della stessa lunghezza (usa il più corto)."""
    n = min(len(p) // 2 for p in pcm_list)
    out = []
    for i in range(n):
        s = sum(struct.unpack_from("<h", p, i*2)[0] for p in pcm_list)
        out.append(max(-32767, min(32767, s)))
    return struct.pack(f"<{n}h", *out)

# Libreria suoni pre-costruita
_SFX = {}

def _build_sfx():
    global _SFX
    rate = 22050
    # Click UI — tick corto
    _SFX["click"]    = _make_wav(_synth(0.06, 800, "sine", True, rate), rate)
    # Hover — flicker sottile
    _SFX["hover"]    = _make_wav(_synth(0.04, 1200, "sine", True, rate), rate)
    # Esplosione — noise + bassa freq
    boom  = _synth(0.6, 80,  "noise", True, rate)
    sub   = _synth(0.6, 60,  "sine",  True, rate)
    _SFX["explosion"] = _make_wav(_mix(boom, sub), rate)
    # Splash — noise acuto corto
    _SFX["splash"]   = _make_wav(_synth(0.25, 300, "noise", True, rate), rate)
    # Nave affondata — sweep discendente + boom
    sweep = _synth(1.0, 200, "sweep", True, rate)
    _SFX["sunk"]     = _make_wav(sweep, rate)
    # Vittoria — fanfara semplice
    fanf = b""
    for f, d in [(523,0.12),(659,0.12),(784,0.12),(1047,0.3)]:
        fanf += _synth(d, f, "sine", False, rate)
    _SFX["win"]      = _make_wav(fanf, rate)
    # Sconfitta — discesa triste
    sad = b""
    for f, d in [(440,0.15),(392,0.15),(349,0.15),(330,0.4)]:
        sad += _synth(d, f, "sine", True, rate)
    _SFX["lose"]     = _make_wav(sad, rate)
    # Radar ping
    _SFX["ping"]     = _make_wav(_synth(0.15, 1800, "sine", True, rate), rate)
    # Conferma
    _SFX["confirm"]  = _make_wav(_synth(0.12, 600, "sine", True, rate)
                                 + _synth(0.12, 900, "sine", True, rate), rate)
    # Turno mio
    _SFX["your_turn"] = _make_wav(_synth(0.1, 700, "square", True, rate)
                                  + _synth(0.15, 1000, "square", True, rate), rate)

_build_sfx()

_sfx_lock = threading.Lock()
_sfx_enabled = True

def play(name: str):
    """Suona un effetto sonoro in background senza bloccare la GUI."""
    if not _sfx_enabled or name not in _SFX:
        return
    def _do():
        with _sfx_lock:
            data = _SFX[name]
            if _WINSOUND:
                winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_ASYNC)
            elif _APLAY:
                try:
                    _sp.run(["aplay", "-q", "-"], input=data,
                            capture_output=True, timeout=3)
                except Exception:
                    pass
    threading.Thread(target=_do, daemon=True).start()


# ══════════════════════════════════════════════
# PALETTE & COSTANTI
# ══════════════════════════════════════════════

C = {
    "bg":          "#03080f",
    "bg2":         "#071525",
    "bg3":         "#0c1e30",
    "panel":       "#050e18",
    "border":      "#0e2d4a",
    "border_hi":   "#1a6090",
    "accent":      "#00d4ff",
    "accent2":     "#ff5722",
    "accent3":     "#00e676",
    "text":        "#b0d8f0",
    "text_dim":    "#345678",
    "text_hi":     "#ffffff",
    "navy":        "#0a2540",
    "cell_sea":    "#060f1a",
    "cell_hover":  "#0d2840",
    "cell_ship":   "#0d4020",
    "cell_hit":    "#6b0000",
    "cell_miss":   "#060e18",
    "ship_outline":"#00c060",
    "fire1":       "#ff3000",
    "fire2":       "#ff7700",
    "fire3":       "#ffd000",
    "water1":      "#004488",
    "water2":      "#0090cc",
    "grid_line":   "#091825",
    "green_dim":   "#003316",
    "radar":       "#00ff55",
    "remove_hi":   "#aa0022",
    "remove_out":  "#ff2244",
    "preview_ok":  "#00ff88",
    "preview_no":  "#ff3333",
    "wave":        "#0a2035",
    "gold":        "#ffd700",
    "silver":      "#c0c0c0",
    "bronze":      "#cd7f32",
    "scanline": "#101010",
}

CELL = 46
GRID = 10
PAD  = 30


# ══════════════════════════════════════════════
# SCHERMATE DI TRANSIZIONE
# ══════════════════════════════════════════════

def fade_transition(root, callback, duration_ms=400):
    """Dissolvenza rapida tra schermate — overlay nero che appare/scompare."""
    overlay = tk.Frame(root, bg="black")
    overlay.place(x=0, y=0, relwidth=1, relheight=1)
    overlay.lift()
    root.update()

    steps  = 12
    delay  = duration_ms // (steps * 2)
    # fade in
    alphas_in  = [i / steps for i in range(1, steps + 1)]
    # fade out
    alphas_out = [1 - i / steps for i in range(1, steps + 1)]

    def step_in(idx=0):
        if idx < len(alphas_in):
            # Tkinter non supporta alpha su Frame, simuliamo con bg alternato
            overlay.after(delay, lambda: step_in(idx + 1))
        else:
            callback()
            root.update()
            overlay.after(delay, lambda: step_out(0))

    def step_out(idx=0):
        if idx < len(alphas_out):
            overlay.after(delay, lambda: step_out(idx + 1))
        else:
            overlay.destroy()

    step_in(0)


# ══════════════════════════════════════════════
# LOGO ANIMATO — disegnato su Canvas
# ══════════════════════════════════════════════

class LogoCanvas(tk.Canvas):
    """
    Logo ASCII-art animato della nave da guerra, con:
    - onde animate sotto
    - testo 'BATTAGLIA NAVALE' con effetto glitch
    - radar rotante integrato
    """

    SHIP = [
        "          ██          ",
        "        ██████        ",
        "      ██████████      ",
        "   ████████████████   ",
        " ██████████████████████",
        "████████████████████████",
    ]

    def __init__(self, master, w=620, h=200, **kw):
        super().__init__(master, width=w, height=h,
                         bg=C["bg"], highlightthickness=0, **kw)
        self.canvas_w, self.canvas_h = w, h
        self._wave_offset = 0.0
        self._glitch_timer = 0
        self._glitch_text  = ""
        self._radar_ang    = 0.0
        self._title_pulse  = 0
        self._ping_visible = []   # lista di blip radar
        self._frame        = 0
        self._after_id = None
        self._draw_frame()

    def _draw_frame(self):
        self.delete("all")
        self._draw_waves()
        self._draw_ship()
        self._draw_radar()
        self._draw_title()
        self._draw_scanlines()
        self._frame += 1
        self._wave_offset += 0.08
        self._radar_ang = (self._radar_ang + 3) % 360
        self._title_pulse = (self._title_pulse + 2) % 360
        self._glitch_timer = max(0, self._glitch_timer - 1)
        if random.random() < 0.02:
            self._glitch_timer = random.randint(2, 6)
        self._after_id = self.after(40, self._draw_frame)

    def _draw_waves(self):
        """Onde animate nella metà inferiore."""
        y_base = self.canvas_h - 40
        for layer, (amp, speed, col) in enumerate([
            (6, 1.0, "#040d18"), (4, 1.5, "#071525"), (3, 2.0, C["wave"])
        ]):
            pts = []
            for x in range(0, self.canvas_w + 4, 4):
                y = y_base + amp * math.sin((x / 50 + self._wave_offset * speed) + layer)
                pts.extend([x, y])
            pts += [self.canvas_w, self.canvas_h, 0, self.canvas_h]
            if len(pts) >= 6:
                self.create_polygon(pts, fill=col, outline="", smooth=True)

    def _draw_ship(self):
        """Silhouette nave stilizzata, oscillante sulle onde."""
        bob = math.sin(self._wave_offset * 0.8) * 2
        x0, y0 = 290, 55 + bob
        cell_w, cell_h = 7, 7
        for row_i, row in enumerate(self.SHIP):
            for col_i, ch in enumerate(row):
                if ch == "█":
                    x = x0 + (col_i - len(row) // 2) * cell_w
                    y = y0 + row_i * cell_h
                    # gradiente verticale
                    bright = 1.0 - row_i * 0.08
                    r = int(0x1a * bright)
                    g = int(0x5c * bright)
                    b = int(0x8a * bright)
                    col = f"#{r:02x}{g:02x}{b:02x}"
                    self.create_rectangle(x, y, x + cell_w - 1, y + cell_h - 1,
                                          fill=col, outline="")
        # riflesso sull'acqua
        self.create_rectangle(260, y0 + 50, 360, y0 + 54,
                              fill=C["accent"], outline="")
        self.create_rectangle(255, y0 + 56, 365, y0 + 58,
                              fill=C["accent"], outline="", stipple="gray25")

    def destroy(self):
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except:
                pass

        super().destroy()

    def _draw_radar(self):
        """Mini radar nell'angolo in alto a destra."""
        cx, cy, r = self.canvas_w - 55, 55, 42
        # cerchi
        for i in range(1, 5):
            ri = r * i // 4
            self.create_oval(cx-ri, cy-ri, cx+ri, cy+ri,
                             outline=C["green_dim"], width=1)
        self.create_line(cx-r, cy, cx+r, cy, fill=C["green_dim"], width=1)
        self.create_line(cx, cy-r, cx, cy+r, fill=C["green_dim"], width=1)
        # sweep
        a = math.radians(self._radar_ang)
        for i in range(25):
            ai = a - math.radians(i * 3)
            alpha = (25-i) / 25
            x2 = cx + r * math.cos(ai)
            y2 = cy + r * math.sin(ai)
            iv = int(alpha * 200)
            self.create_line(cx, cy, x2, y2, fill=f"#00{iv:02x}00", width=2)
        # blip casuale
        if random.random() < 0.04:
            bx = cx + random.randint(-r+8, r-8)
            by = cy + random.randint(-r+8, r-8)
            self._ping_visible = [[bx, by, 15]]
        for blip in self._ping_visible[:]:
            bx, by, life = blip
            self.create_oval(bx-3, by-3, bx+3, by+3, fill=C["radar"], outline="")
            blip[2] = life - 1
        self._ping_visible = [b for b in self._ping_visible if b[2] > 0]
        # centro
        self.create_oval(cx-3, cy-3, cx+3, cy+3, fill=C["radar"], outline="")

    def _draw_title(self):
        """Titolo principale con effetto glitch."""
        pulse = abs(math.sin(math.radians(self._title_pulse))) * 0.4 + 0.6
        r = int(0 + (50 * (1 - pulse)))
        g = int(0xd4 * pulse)
        b = int(0xff * pulse)
        col = f"#{r:02x}{g:02x}{b:02x}"

        # Testo principale
        title = "BATTAGLIA NAVALE"
        if self._glitch_timer > 0:
            chars = list(title)
            for _ in range(self._glitch_timer):
                i = random.randint(0, len(chars)-1)
                chars[i] = random.choice("█▓▒░│┤╡╢╖╕╣║╗╝╜╛┐└╤╦╠═╬╧╨╤╥╙╘╒╓╫╪┘")
            title = "".join(chars)
            col = C["accent2"]

        self.create_text(self.canvas_w // 2, 22,
                         text=title,
                         font=("Courier", 20, "bold"),
                         fill=col, anchor="n")
        self.create_text(self.canvas_w // 2, 50,
                         text="━━━━━━━  NAVAL COMBAT SYSTEM  ━━━━━━━",
                         font=("Courier", 9),
                         fill=C["text_dim"], anchor="n")

    def _draw_scanlines(self):
        """Linee di scansione CRT per effetto monitor militare."""
        for y in range(0, self.canvas_h, 4):
            self.create_line(0, y, self.canvas_w, y, fill=C["scanline"], width=1)


# ══════════════════════════════════════════════
# GRIGLIA — tag-based rendering
# ══════════════════════════════════════════════

class GridCanvas(tk.Canvas):
    """
    Griglia 10x10 tag-based. Aggiorna solo le celle cambiate.
    Include wave-shimmer sullo sfondo e bordi luminosi.
    """

    def __init__(self, master, interactive=False, **kw):
        w = h = PAD + CELL * GRID + 6
        super().__init__(master, width=w, height=h,
                         bg=C["bg"], highlightthickness=2,
                         highlightbackground=C["border"], **kw)

        self.interactive   = interactive
        self.place_mode    = False
        self.remove_mode   = False
        self.hide_ships    = False

        self.cells         = [[ACQUA] * GRID for _ in range(GRID)]
        self.hover_cell    = None
        self.preview_cells = set()
        self.drag_orient   = True
        self.ship_drag     = None

        self.particles     = []
        self.animations    = {}
        self._wave_phase   = random.uniform(0, math.pi * 2)

        self.on_click  = None
        self.on_place  = None
        self.on_remove = None

        self._build_static()
        self._init_cells()
        self._animate_sea()          # shimmer continuo sul mare
        self._tick_particles()

        self.bind("<Motion>",   self._on_motion)
        self.bind("<Leave>",    self._on_leave)
        self.bind("<Button-1>", self._on_click_ev)
        self.bind("<Button-3>", self._on_right_click)

    # ── coordinate ────────────────────────────────────────

    def _cell_xy(self, r, c):
        return PAD + c * CELL, PAD + r * CELL

    def _xy_to_cell(self, x, y):
        c = (x - PAD) // CELL
        r = (y - PAD) // CELL
        if 0 <= r < GRID and 0 <= c < GRID:
            return int(r), int(c)
        return None

    def _cell_tag(self, r, c):
        return f"cell_{r}_{c}"

    # ── costruzione ────────────────────────────────────────

    def _build_static(self):
        letters = "ABCDEFGHIJ"
        for i in range(GRID):
            self.create_text(PAD + i*CELL + CELL//2, PAD//2,
                             text=letters[i], fill=C["text_dim"],
                             font=("Courier", 8, "bold"), tags="static")
            self.create_text(PAD//2, PAD + i*CELL + CELL//2,
                             text=str(i), fill=C["text_dim"],
                             font=("Courier", 8, "bold"), tags="static")

    def _init_cells(self):
        for r in range(GRID):
            for c in range(GRID):
                x1, y1 = self._cell_xy(r, c)
                x2, y2 = x1 + CELL, y1 + CELL
                tag = self._cell_tag(r, c)
                self.create_rectangle(x1, y1, x2, y2,
                                      fill=C["cell_sea"], outline=C["grid_line"],
                                      width=1, tags=tag)
                self.create_text(x1 + CELL//2, y1 + CELL//2,
                                 text="", fill=C["ship_outline"],
                                 font=("Courier", 13, "bold"),
                                 tags=tag + "_sym")

    # ── shimmer animazione mare ────────────────────────────

    def _animate_sea(self):
        """Pulsa leggermente il colore delle celle di mare per effetto acqua."""
        self._wave_phase += 0.05
        for r in range(GRID):
            for c in range(GRID):
                if self.cells[r][c] == ACQUA and (r, c) not in self.preview_cells:
                    if self.hover_cell != (r, c):
                        if (r + c) % 3 == int(self._wave_phase * 2) % 3:
                            shift = int(math.sin(self._wave_phase + (r+c)*0.4) * 4)
                            v = max(0, 6 + shift)
                            col = f"#04{v:02x}1a"
                            try:
                                self.itemconfig(self._cell_tag(r, c), fill=col)
                            except Exception:
                                pass
        self._after_id = self.after(120, self._animate_sea)

    # ── aggiornamento celle ────────────────────────────────

    def _refresh_cell(self, r, c):
        val   = self.cells[r][c]
        hover = self.hover_cell == (r, c)
        prev  = (r, c) in self.preview_cells
        frame = self.animations.get((r, c), 0)
        show  = ACQUA if (self.hide_ships and val == NAVE) else val

        if show == NAVE:
            if self.remove_mode and hover:
                bg, out, sym, sc = C["remove_hi"], C["remove_out"], "✕", C["remove_out"]
            else:
                # nave con gradiente orizzontale simulato
                bg, out, sym, sc = C["cell_ship"], C["ship_outline"], "◼", C["ship_outline"]
        elif show == COLPITO:
            if frame > 0:
                v = min(255, 107 + int(80 * frame / 20))
                bg = f"#{v:02x}0000"
            else:
                bg = C["cell_hit"]
            out, sym, sc = C["fire2"], "✕", C["fire3"]
        elif show == MANCATO:
            bg, out, sym, sc = C["cell_miss"], C["water2"], "·", C["water2"]
        elif prev:
            ok = val == ACQUA
            bg  = "#003322" if ok else "#330000"
            out = C["preview_ok"] if ok else C["preview_no"]
            sym = "◻"
            sc  = C["preview_ok"] if ok else C["preview_no"]
        elif hover and (self.interactive or self.place_mode):
            bg, out = C["cell_hover"], C["accent"]
            sym = "+" if (self.interactive and show == ACQUA) else ""
            sc  = C["accent"]
        else:
            bg, out, sym, sc = C["cell_sea"], C["grid_line"], "", C["cell_sea"]

        tag = self._cell_tag(r, c)
        self.itemconfig(tag,         fill=bg,  outline=out)
        self.itemconfig(tag + "_sym", text=sym, fill=sc)

    def refresh_all(self):
        for r in range(GRID):
            for c in range(GRID):
                self._refresh_cell(r, c)

    def set_cell(self, r, c, val):
        self.cells[r][c] = val
        self._refresh_cell(r, c)

    def set_grid(self, g):
        for r in range(GRID):
            for c in range(GRID):
                self.cells[r][c] = g[r][c]
        self.refresh_all()

    # ── preview ────────────────────────────────────────────

    def _compute_preview(self, cell):
        if self.ship_drag is None or cell is None:
            return set()
        r, c = cell
        n = self.ship_drag
        if self.drag_orient:
            return {(r, c+i) for i in range(n) if c+i < GRID}
        return {(r+i, c) for i in range(n) if r+i < GRID}

    def _set_preview(self, new_p):
        old = self.preview_cells
        self.preview_cells = new_p
        for cell in old | new_p:
            self._refresh_cell(*cell)

    # ── eventi mouse ───────────────────────────────────────

    def _on_motion(self, event):
        cell = self._xy_to_cell(event.x, event.y)
        old  = self.hover_cell
        self.hover_cell = cell
        if old != cell:
            if old:
                self._refresh_cell(*old)
            if cell:
                self._refresh_cell(*cell)
            if cell and self.interactive and self.cells[cell[0]][cell[1]] == ACQUA:
                play("hover")
        if self.place_mode:
            self._set_preview(self._compute_preview(cell))

    def _on_leave(self, event):
        old = self.hover_cell
        self.hover_cell = None
        if old:
            self._refresh_cell(*old)
        self._set_preview(set())

    def _on_click_ev(self, event):
        cell = self._xy_to_cell(event.x, event.y)
        if not cell:
            return
        r, c = cell
        if self.place_mode:
            if self.cells[r][c] == NAVE and self.on_remove:
                play("click")
                self.on_remove(r, c)
            elif self.ship_drag is not None and self.on_place:
                play("click")
                self.on_place(r, c)
        elif self.interactive and self.on_click:
            self.on_click(r, c)

    def _on_right_click(self, event):
        self.drag_orient = not self.drag_orient
        play("click")
        if self.place_mode:
            self._set_preview(self._compute_preview(self.hover_cell))

    # ── particelle ─────────────────────────────────────────

    def spawn_explosion(self, r, c):
        x1, y1 = self._cell_xy(r, c)
        cx, cy = x1 + CELL//2, y1 + CELL//2
        colors = [C["fire1"],C["fire2"],C["fire3"],"#ffffff",C["accent2"]]
        for _ in range(28):
            ang   = random.uniform(0, 2*math.pi)
            speed = random.uniform(2, 6)
            self.particles.append({
                "x":cx,"y":cy,"vx":math.cos(ang)*speed,"vy":math.sin(ang)*speed-2,
                "color":random.choice(colors),"size":random.uniform(3,7),
                "life":random.randint(20,42),"max_life":42,
            })
        self.animations[(r,c)] = 22
        self._refresh_cell(r, c)

    def spawn_splash(self, r, c):
        x1, y1 = self._cell_xy(r, c)
        cx, cy = x1 + CELL//2, y1 + CELL//2
        colors = [C["water1"],C["water2"],C["accent"],"#90e0ef","#ffffff"]
        for _ in range(16):
            ang   = random.uniform(-math.pi, 0)
            speed = random.uniform(1.5, 5)
            self.particles.append({
                "x":cx,"y":cy,"vx":math.cos(ang)*speed,"vy":math.sin(ang)*speed-1.5,
                "color":random.choice(colors),"size":random.uniform(2,5),
                "life":random.randint(14,30),"max_life":30,
            })

    def spawn_sunk(self, cells_list):
        for i, (r, c) in enumerate(cells_list):
            self._after_id = self.after(i * 120, lambda r=r, c=c: self.spawn_explosion(r, c))

    def _tick_particles(self):
        self.delete("particle")
        changed = []
        for cell in list(self.animations):
            self.animations[cell] -= 1
            if self.animations[cell] <= 0:
                del self.animations[cell]
            changed.append(cell)
        for r, c in changed:
            self._refresh_cell(r, c)
        for p in self.particles[:]:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["vy"] += 0.4
            p["life"] -= 1
            if p["life"] <= 0:
                self.particles.remove(p)
                continue
            a    = p["life"] / p["max_life"]
            size = max(1, int(p["size"] * a))
            x, y = int(p["x"]), int(p["y"])
            self.create_oval(x-size, y-size, x+size, y+size,
                             fill=p["color"], outline="", tags="particle")
        self._after_id = self.after(33, self._tick_particles)


# ══════════════════════════════════════════════
# WIDGET PERSONALIZZATI
# ══════════════════════════════════════════════

def _btn(parent, text, command, fg=None, bg=None, font=None, **kw):
    """Bottone uniformato con effetti hover."""
    fg  = fg  or C["accent"]
    bg  = bg  or C["navy"]
    fnt = font or ("Courier", 9, "bold")
    b = tk.Button(parent, text=text, command=command,
                  font=fnt, bg=bg, fg=fg,
                  activebackground=C["border_hi"],
                  activeforeground=C["text_hi"],
                  relief="flat", cursor="hand2",
                  highlightthickness=1,
                  highlightbackground=C["border"], **kw)
    b.bind("<Enter>", lambda e: [b.config(bg=C["border_hi"]), play("hover")])
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    return b

def _entry(parent, default="", fg=None, width=20):
    fg = fg or C["accent"]
    e = tk.Entry(parent, font=("Courier", 11, "bold"),
                 bg=C["bg3"], fg=fg, insertbackground=fg,
                 relief="flat", width=width,
                 highlightthickness=1,
                 highlightcolor=C["accent"],
                 highlightbackground=C["border"])
    e.insert(0, default)
    return e

def _label(parent, text, size=9, fg=None, bg=None, bold=False, **kw):
    fg  = fg  or C["text_dim"]
    bg  = bg  or C["bg"]
    wgt = "bold" if bold else "normal"
    return tk.Label(parent, text=text,
                    font=("Courier", size, wgt),
                    bg=bg, fg=fg, **kw)

def _sep(parent, bg=None):
    bg = bg or C["bg"]
    tk.Frame(parent, height=1, bg=C["border"]).pack(fill="x", pady=6)


# ══════════════════════════════════════════════
# BARRA DI STATO ANIMATA (turno, countdown, ecc.)
# ══════════════════════════════════════════════

class StatusBar(tk.Canvas):
    """Barra animata in basso/alto con testo che scorre e luci lampeggianti."""

    def __init__(self, master, **kw):
        super().__init__(master, height=28, bg=C["panel"],
                         highlightthickness=0, **kw)
        self._msg    = ""
        self._color  = C["text_dim"]
        self._phase  = 0
        self._blink  = False
        self._scroll = 0
        self._after_id = self.after(50, self._tick)

    def set(self, msg, color=None, blink=False):
        self._msg   = msg
        self._color = color or C["text_dim"]
        self._blink = blink
        self._scroll = 0

    def _tick(self):
        self.delete("all")
        w = self.winfo_width() or 800
        self._phase += 1
        # sfondo con scanline
        self.create_rectangle(0, 0, w, 28, fill=C["panel"], outline="")
        for x in range(0, w, 2):
            self.create_line(x, 0, x, 28, fill="#1a1a1a")
        # luci laterali lampeggianti
        blink_col = C["accent"] if (self._phase % 20 < 10 and self._blink) else C["border"]
        for x in [6, 14]:
            self.create_oval(x-3, 11, x+3, 17, fill=blink_col, outline="")
        for x in [w-6, w-14]:
            self.create_oval(x-3, 11, x+3, 17, fill=blink_col, outline="")
        # testo
        col = self._color
        if self._blink and self._phase % 16 < 8:
            col = C["text_hi"]
        self.create_text(w//2, 14, text=self._msg,
                         font=("Courier", 9, "bold"),
                         fill=col, anchor="center")
        self._after_id = self.after(50, self._tick)


# ══════════════════════════════════════════════
# CONTATORE COLPI / STATISTICHE IN-GAME
# ══════════════════════════════════════════════

class StatsPanel(tk.Frame):
    """Mini panel con contatori animati: colpi a segno, mancati, navi affondate."""

    def __init__(self, master, label="", **kw):
        super().__init__(master, bg=C["panel"], padx=8, pady=6, **kw)
        _label(self, label, size=7, fg=C["text_dim"], bg=C["panel"],
               bold=True).pack(anchor="w")
        tk.Frame(self, height=1, bg=C["border"]).pack(fill="x", pady=3)
        row = tk.Frame(self, bg=C["panel"])
        row.pack()
        self._vars = {}
        for key, icon, col in [
            ("hit",  "💥 COLPI",  C["fire2"]),
            ("miss", "○  ACQUA",  C["water2"]),
            ("sunk", "🚢 AFFONDATE", C["accent2"]),
        ]:
            f = tk.Frame(row, bg=C["panel"], padx=6)
            f.pack(side="left")
            _label(f, icon, size=7, fg=col, bg=C["panel"]).pack()
            var = tk.StringVar(value="0")
            self._vars[key] = var
            tk.Label(f, textvariable=var, font=("Courier", 16, "bold"),
                     bg=C["panel"], fg=col).pack()

    def inc(self, key):
        try:
            v = int(self._vars[key].get()) + 1
            self._vars[key].set(str(v))
        except Exception:
            pass

    def reset(self):
        for v in self._vars.values():
            v.set("0")


# ══════════════════════════════════════════════
# APP PRINCIPALE
# ══════════════════════════════════════════════

class BattagliaNavaleApp:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("⚓ Battaglia Navale — Naval Combat System")
        self.root.configure(bg=C["bg"])
        self.root.resizable(True, True)

        # font
        self.F = {
            "title":  tkfont.Font(family="Courier", size=20, weight="bold"),
            "sub":    tkfont.Font(family="Courier", size=11, weight="bold"),
            "body":   tkfont.Font(family="Courier", size=9),
            "small":  tkfont.Font(family="Courier", size=8),
            "tiny":   tkfont.Font(family="Courier", size=7),
            "btn":    tkfont.Font(family="Courier", size=9, weight="bold"),
            "num":    tkfont.Font(family="Courier", size=16, weight="bold"),
        }

        # stato sessione
        self.conn            = None
        self.nome            = ""
        self.nome_avv        = ""
        self.mio_turno       = False
        self.partita_finita  = False
        self.griglia_casa    = Griglia()
        self.griglia_attacco = Griglia()
        self.placed_ships    = []
        self.fleet_queue     = []
        self.sel_idx         = 0
        self._ships_hidden   = False
        global _sfx_enabled
        self._sfx_on         = True

        self._build_login()
        self.root.mainloop()

    # ══════════════════════════════════════════
    # UTILITÀ
    # ══════════════════════════════════════════

    def _send(self, msg):
        if self.conn:
            try:
                self.conn.sendall((json.dumps(msg)+"\n").encode())
            except Exception:
                pass

    def _recv(self):
        try:
            buf = b""
            while True:
                ch = self.conn.recv(1)
                if not ch:
                    return None
                if ch == b"\n":
                    break
                buf += ch
            return json.loads(buf.decode())
        except Exception:
            return None

    def _clear(self):
        if hasattr(self, "_radar_id"):
            try: self.root.after_cancel(self._radar_id)
            except Exception: pass
        for w in self.root.winfo_children():
            w.destroy()

    def _log(self, testo, tag=""):
        if hasattr(self, "log_text"):
            self.log_text.config(state="normal")
            self.log_text.insert("end", testo+"\n", tag)
            self.log_text.see("end")
            self.log_text.config(state="disabled")

    # ══════════════════════════════════════════
    # SCHERMATA 1 — LOGIN
    # ══════════════════════════════════════════

    def _build_login(self):
        self._clear()
        self.root.geometry("640x680")

        outer = tk.Frame(self.root, bg=C["bg"])
        outer.pack(fill="both", expand=True)

        # Logo animato
        logo = LogoCanvas(outer, w=640, h=200)
        logo.pack()

        # Card centrale
        card = tk.Frame(outer, bg=C["bg2"],
                        highlightthickness=1,
                        highlightbackground=C["border"])
        card.pack(padx=60, pady=6, fill="x")

        # Campi input
        fields = tk.Frame(card, bg=C["bg2"])
        fields.pack(padx=24, pady=16, fill="x")

        def row(parent, lbl_txt, default, fg=None):
            r = tk.Frame(parent, bg=C["bg2"])
            r.pack(fill="x", pady=5)
            _label(r, lbl_txt, size=7, fg=C["text_dim"], bg=C["bg2"]).pack(anchor="w")
            e = _entry(r, default, fg=fg, width=28)
            e.pack(fill="x", ipady=7)
            return e

        self.entry_nome = row(fields, "▸ IDENTIFICATIVO UFFICIALE", "", C["accent"])
        self.entry_host = row(fields, "▸ INDIRIZZO SERVER",         SERVER_HOST, C["text"])
        self.entry_port = row(fields, "▸ PORTA",                    str(SERVER_PORT), C["text"])
        self.entry_nome.focus()

        # Status
        self.login_status = _label(card, "", size=8, fg=C["text_dim"], bg=C["bg2"])
        self.login_status.pack(pady=(0,6))

        # Bottoni
        btn_row = tk.Frame(card, bg=C["bg2"])
        btn_row.pack(pady=(0,16))

        b_conn = _btn(btn_row, "  ▶  CONNETTI  ",
                      self._connect, fg=C["accent"], bg=C["navy"],
                      font=("Courier", 11, "bold"), padx=18, pady=10)
        b_conn.pack(side="left", padx=6)

        b_rank = _btn(btn_row, "  🏆  CLASSIFICA  ",
                      self._show_leaderboard, fg=C["gold"], bg=C["bg3"],
                      font=("Courier", 9, "bold"), padx=12, pady=10)
        b_rank.pack(side="left", padx=6)

        # Toggle audio
        self.btn_sfx = _btn(card, "🔊 AUDIO: ON", self._toggle_sfx,
                             fg=C["accent3"], bg=C["bg3"],
                             font=("Courier", 8), pady=4)
        self.btn_sfx.pack(pady=(0,10))

        for e in (self.entry_nome, self.entry_host, self.entry_port):
            e.bind("<Return>", lambda ev: self._connect())

        # Barra di stato
        self.status_bar = StatusBar(outer)
        self.status_bar.pack(fill="x", side="bottom")
        self.status_bar.set("⚓  SISTEMA PRONTO  —  INSERIRE IDENTIFICATIVO")

        play("ping")

    def _toggle_sfx(self):
        global _sfx_enabled
        self._sfx_on = not self._sfx_on
        _sfx_enabled = self._sfx_on
        self.btn_sfx.config(text=f"{'🔊' if self._sfx_on else '🔇'} AUDIO: {'ON' if self._sfx_on else 'OFF'}")

    def _connect(self):
        self.nome = self.entry_nome.get().strip() or "Comandante"
        host      = self.entry_host.get().strip() or SERVER_HOST
        try:
            port = int(self.entry_port.get().strip())
        except ValueError:
            self.login_status.config(text="✗ Porta non valida", fg=C["accent2"])
            return
        play("click")
        self.login_status.config(text=f"Connessione a {host}:{port}...", fg=C["text_dim"])
        self.status_bar.set(f"CONNESSIONE IN CORSO → {host}:{port}", C["accent"], True)
        self.root.update()
        try:
            self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.conn.connect((host, port))
        except Exception as e:
            self.login_status.config(text=f"✗ {e}", fg=C["accent2"])
            self.status_bar.set(f"✗ CONNESSIONE FALLITA: {e}", C["accent2"], False)
            return
        play("confirm")
        self.login_status.config(text="✓ Connesso! In attesa avversario...", fg=C["accent3"])
        self.status_bar.set("✓ CONNESSO — IN ATTESA DELL'AVVERSARIO", C["accent3"], True)
        self._send({"tipo": "nome", "nome": self.nome})
        threading.Thread(target=self._wait_opponent, daemon=True).start()

    def _wait_opponent(self):
        msg = self._recv()
        if not msg: return
        msg = self._recv()
        if msg and msg.get("tipo") == "avversario":
            self.nome_avv = msg["nome"]
        self._recv()
        self.root.after(0, lambda: fade_transition(self.root, self._build_placement))

    # ══════════════════════════════════════════
    # CLASSIFICA
    # ══════════════════════════════════════════

    def _show_leaderboard(self):
        play("click")
        win = tk.Toplevel(self.root)
        win.title("🏆 Classifica")
        win.configure(bg=C["bg"])
        win.resizable(False, False)
        win.geometry("520x580")
        win.grab_set()

        tk.Frame(win, bg=C["accent"], height=3).pack(fill="x")
        _label(win, "🏆  CLASSIFICA UFFICIALE", size=18, fg=C["gold"],
               bg=C["bg"], bold=True).pack(pady=(14,2))
        _label(win, "HALL OF FAME — NAVAL COMBAT SYSTEM", size=8,
               fg=C["text_dim"], bg=C["bg"]).pack()
        _sep(win, C["bg"])

        hdr = tk.Frame(win, bg=C["bg2"], pady=7)
        hdr.pack(fill="x", padx=16)
        for txt, w, fg in [("#",3,C["accent"]), ("COMANDANTE",16,C["accent"]),
                            ("V",4,C["accent3"]), ("S",4,C["accent2"]),
                            ("PARTITE",7,C["text"]), ("WIN%",6,C["gold"])]:
            _label(hdr, txt, size=8, fg=fg, bg=C["bg2"], bold=True,
                   width=w, anchor="center").pack(side="left")

        scroll_frame = tk.Frame(win, bg=C["bg"])
        scroll_frame.pack(fill="both", expand=True, padx=16, pady=4)

        stats = {}
        if os.path.exists(STATS_FILE):
            try:
                with open(STATS_FILE) as f:
                    stats = json.load(f)
            except Exception:
                pass

        if not stats:
            _label(scroll_frame,
                   "\n\nNessuna partita registrata.\nGioca la tua prima battaglia!",
                   size=10, fg=C["text_dim"], bg=C["bg"],
                   justify="center").pack(expand=True)
        else:
            ranking = sorted(stats.items(),
                             key=lambda x: (x[1].get("vittorie",0),
                                            x[1].get("vittorie",0)/max(x[1].get("partite",1),1)),
                             reverse=True)
            medals = [("🥇",C["gold"]), ("🥈",C["silver"]), ("🥉",C["bronze"])]
            for pos, (nome, dati) in enumerate(ranking, 1):
                v   = dati.get("vittorie",0)
                s   = dati.get("sconfitte",0)
                p   = dati.get("partite",0)
                pct = f"{v/p*100:.0f}%" if p > 0 else "—"
                med, mcol = medals[pos-1] if pos <= 3 else (f"{pos}.", C["text_dim"])
                bg_row = C["bg3"] if pos % 2 == 0 else C["bg2"]
                row = tk.Frame(scroll_frame, bg=bg_row, pady=5)
                row.pack(fill="x", pady=1)
                for txt, w, fg in [(med,3,mcol),(nome,16,C["text_hi"] if pos==1 else C["text"]),
                                   (str(v),4,C["accent3"]),(str(s),4,C["accent2"]),
                                   (str(p),7,C["text"]),(pct,6,C["gold"])]:
                    _label(row, txt, size=8, fg=fg, bg=bg_row,
                           width=w, anchor="center").pack(side="left")

        _sep(win, C["bg"])
        _btn(win, "  ✕  CHIUDI  ", win.destroy,
             fg=C["text"], bg=C["navy"],
             font=("Courier", 9, "bold"), padx=16, pady=8).pack(pady=8)

    # ══════════════════════════════════════════
    # SCHERMATA 2 — POSIZIONAMENTO
    # ══════════════════════════════════════════

    def _build_placement(self):
        self._clear()
        self.root.geometry("840x740")

        self.placed_ships = []
        self.griglia_casa = Griglia()
        self._rebuild_fleet_queue()

        # Header
        hdr = tk.Frame(self.root, bg=C["bg2"], pady=10)
        hdr.pack(fill="x")
        hdr_l = tk.Frame(hdr, bg=C["bg2"])
        hdr_l.pack(side="left", padx=16)
        _label(hdr_l, "⚓  DISPONI LA TUA FLOTTA", size=13, fg=C["accent"],
               bg=C["bg2"], bold=True).pack(anchor="w")
        _label(hdr_l, "Click SX = piazza/rimuovi  │  Click DX = ruota  │  Tutte le navi modificabili finché non avvii",
               size=7, fg=C["text_dim"], bg=C["bg2"]).pack(anchor="w")
        # avversario
        hdr_r = tk.Frame(hdr, bg=C["bg2"])
        hdr_r.pack(side="right", padx=16)
        _label(hdr_r, f"VS", size=18, fg=C["accent2"], bg=C["bg2"], bold=True).pack()
        _label(hdr_r, self.nome_avv.upper(), size=10, fg=C["text"], bg=C["bg2"], bold=True).pack()

        # Body
        body = tk.Frame(self.root, bg=C["bg"])
        body.pack(expand=True, fill="both", padx=12, pady=8)

        # Griglia
        gf = tk.Frame(body, bg=C["bg"])
        gf.pack(side="left")

        name_frame = tk.Frame(gf, bg=C["bg"])
        name_frame.pack(fill="x", pady=(0,4))
        _label(name_frame, f"[ {self.nome.upper()} ]", size=10,
               fg=C["accent3"], bg=C["bg"], bold=True).pack(side="left")

        self.place_canvas = GridCanvas(gf)
        self.place_canvas.place_mode  = True
        self.place_canvas.remove_mode = True
        self.place_canvas.on_place    = self._place_ship
        self.place_canvas.on_remove   = self._remove_ship_at
        self.place_canvas.pack()

        # Pannello laterale
        side = tk.Frame(body, bg=C["bg2"], padx=14, pady=14, width=240)
        side.pack(side="left", fill="y", padx=(14,0))
        side.pack_propagate(False)

        _label(side, "MANIFESTO DI FLOTTA", size=8, fg=C["accent"],
               bg=C["bg2"], bold=True).pack(pady=(0,6))

        self.fleet_frame = tk.Frame(side, bg=C["bg2"])
        self.fleet_frame.pack(fill="x")

        _sep(side, C["bg2"])

        # Orientamento
        self.lbl_orient = tk.Label(side, text="", font=("Courier",8),
                                   bg=C["bg3"], fg=C["accent3"], pady=5, width=26)
        self.lbl_orient.pack(fill="x", pady=(0,4))

        # Stato
        self.lbl_nave = tk.Label(side, text="", font=("Courier",8),
                                 bg=C["bg2"], fg=C["accent3"], wraplength=210,
                                 justify="left")
        self.lbl_nave.pack(pady=4)

        _sep(side, C["bg2"])

        # Progress flotta
        self.progress_label = _label(side, "0 / 8 navi piazzate", size=8,
                                     fg=C["text_dim"], bg=C["bg2"])
        self.progress_label.pack()
        self.progress_bar = tk.Canvas(side, height=8, bg=C["bg3"],
                                      highlightthickness=0)
        self.progress_bar.pack(fill="x", pady=(2,8))

        _sep(side, C["bg2"])

        # Bottoni azione
        self.btn_avvia = _btn(side, "  ▶  AVVIA PARTITA  ",
                              self._send_grid, fg=C["text_dim"],
                              bg=C["green_dim"],
                              font=("Courier",10,"bold"), pady=12)
        self.btn_avvia.config(state="disabled")
        self.btn_avvia.pack(fill="x", pady=4)

        _btn(side, "  ↻  RUOTA  (o Click DX)  ", self._rotate_ship,
             fg=C["accent"], bg=C["bg3"],
             font=("Courier",8), pady=7).pack(fill="x", pady=2)

        _btn(side, "  ⟳  AUTO-POSIZIONA  ", self._auto_place,
             fg=C["text"], bg=C["navy"],
             font=("Courier",8), pady=7).pack(fill="x", pady=2)

        _btn(side, "  ✕  RESET COMPLETO  ", self._reset_placement,
             fg=C["accent2"], bg=C["navy"],
             font=("Courier",8), pady=7).pack(fill="x", pady=2)

        # Statusbar
        self.status_bar = StatusBar(self.root)
        self.status_bar.pack(fill="x", side="bottom")

        self._refresh_placement_ui()
        play("ping")

    # ── logica placement ──────────────────────────────────

    def _rebuild_fleet_queue(self):
        count = {}
        for nome, _, _ in self.placed_ships:
            count[nome] = count.get(nome, 0) + 1
        self.fleet_queue = []
        for nome, lung, qty in FLOTTA:
            for _ in range(qty - count.get(nome, 0)):
                self.fleet_queue.append((nome, lung))
        self.sel_idx = min(self.sel_idx, max(0, len(self.fleet_queue)-1))

    def _rebuild_fleet_labels(self):
        for w in self.fleet_frame.winfo_children():
            w.destroy()

        total = sum(q for _,_,q in FLOTTA)
        placed = len(self.placed_ships)

        # Navi piazzate
        for i, (nome, lung, _) in enumerate(self.placed_ships):
            row = tk.Frame(self.fleet_frame, bg=C["bg3"], pady=3)
            row.pack(fill="x", pady=1)
            _label(row, f"✓ {'█'*lung}", size=8, fg=C["accent3"],
                   bg=C["bg3"], width=8, anchor="w").pack(side="left")
            _label(row, nome, size=8, fg=C["accent3"],
                   bg=C["bg3"], anchor="w").pack(side="left")
            _btn(row, "✕", lambda i=i: self._remove_ship_by_index(i),
                 fg=C["accent2"], bg=C["bg3"],
                 font=("Courier",7), padx=4, pady=2).pack(side="right")

        # Navi da piazzare
        for i, (nome, lung) in enumerate(self.fleet_queue):
            is_sel = (i == self.sel_idx)
            bg_r   = C["navy"] if is_sel else C["bg2"]
            fg_r   = C["accent"] if is_sel else C["text_dim"]
            row = tk.Frame(self.fleet_frame, bg=bg_r, pady=3,
                           cursor="hand2",
                           highlightthickness=1 if is_sel else 0,
                           highlightbackground=C["accent"])
            row.pack(fill="x", pady=1)
            _label(row, f"{'▶ ' if is_sel else '  '}{'□'*lung}", size=8,
                   fg=fg_r, bg=bg_r, width=10, anchor="w",
                   bold=is_sel).pack(side="left")
            _label(row, nome, size=8, fg=fg_r, bg=bg_r,
                   anchor="w", bold=is_sel).pack(side="left")
            row.bind("<Button-1>", lambda e, idx=i: self._select_ship(idx))
            for child in row.winfo_children():
                child.bind("<Button-1>", lambda e, idx=i: self._select_ship(idx))

        # Aggiorna barra progresso
        if hasattr(self, "progress_label"):
            self.progress_label.config(text=f"{placed} / {total} navi piazzate")
        if hasattr(self, "progress_bar"):
            self.progress_bar.delete("all")
            w = self.progress_bar.winfo_width() or 200
            pct = placed / max(total, 1)
            self.progress_bar.create_rectangle(0,0,w,8, fill=C["bg3"], outline="")
            if pct > 0:
                col = C["accent3"] if pct < 1.0 else C["gold"]
                self.progress_bar.create_rectangle(0,0,int(w*pct),8,
                                                   fill=col, outline="")

    def _select_ship(self, idx):
        self.sel_idx = idx
        play("click")
        self._refresh_placement_ui()
        if self.place_canvas.hover_cell:
            self.place_canvas._set_preview(
                self.place_canvas._compute_preview(self.place_canvas.hover_cell))

    def _rotate_ship(self):
        self.place_canvas.drag_orient = not self.place_canvas.drag_orient
        play("click")
        self.place_canvas._set_preview(
            self.place_canvas._compute_preview(self.place_canvas.hover_cell))
        self._update_orient_label()

    def _update_orient_label(self):
        ori = "→  ORIZZONTALE" if self.place_canvas.drag_orient else "↓  VERTICALE"
        self.lbl_orient.config(text=f"Orientamento: {ori}")

    def _place_ship(self, r, c):
        if not self.fleet_queue or self.sel_idx >= len(self.fleet_queue):
            return
        nome, lung = self.fleet_queue[self.sel_idx]
        ori = self.place_canvas.drag_orient
        if self.griglia_casa.piazza_nave(r, c, lung, ori):
            cells = [(r, c+i) for i in range(lung)] if ori else [(r+i,c) for i in range(lung)]
            for ri, ci in cells:
                self.place_canvas.set_cell(ri, ci, NAVE)
            self.placed_ships.append((nome, lung, cells))
            self.fleet_queue.pop(self.sel_idx)
            self.sel_idx = min(self.sel_idx, max(0, len(self.fleet_queue)-1))
            self.place_canvas._set_preview(set())
            play("confirm")
            self._refresh_placement_ui()

    def _remove_ship_at(self, r, c):
        for i, (nome, lung, cells) in enumerate(self.placed_ships):
            if (r, c) in cells:
                self._remove_ship_by_index(i)
                return

    def _remove_ship_by_index(self, idx):
        nome, lung, cells = self.placed_ships.pop(idx)
        for ri, ci in cells:
            self.griglia_casa.celle[ri][ci] = ACQUA
            self.place_canvas.set_cell(ri, ci, ACQUA)
        self.fleet_queue.insert(0, (nome, lung))
        self.sel_idx = 0
        play("click")
        self._refresh_placement_ui()

    def _reset_placement(self):
        self.placed_ships = []
        self.griglia_casa = Griglia()
        self._rebuild_fleet_queue()
        self.place_canvas.cells = [[ACQUA]*GRID for _ in range(GRID)]
        self.place_canvas.refresh_all()
        self.place_canvas._set_preview(set())
        play("click")
        self._refresh_placement_ui()

    def _auto_place(self):
        while self.fleet_queue:
            nome, lung = self.fleet_queue[0]
            for _ in range(2000):
                r = random.randint(0,9); c = random.randint(0,9)
                ori = random.choice([True,False])
                if self.griglia_casa.piazza_nave(r, c, lung, ori):
                    cells = [(r,c+i) for i in range(lung)] if ori else [(r+i,c) for i in range(lung)]
                    for ri, ci in cells:
                        self.place_canvas.set_cell(ri, ci, NAVE)
                    self.placed_ships.append((nome, lung, cells))
                    self.fleet_queue.pop(0)
                    break
        self.sel_idx = 0
        self.place_canvas._set_preview(set())
        play("confirm")
        self._refresh_placement_ui()

    def _refresh_placement_ui(self):
        self._rebuild_fleet_labels()
        total = sum(q for _,_,q in FLOTTA)
        if self.fleet_queue:
            if self.sel_idx >= len(self.fleet_queue):
                self.sel_idx = len(self.fleet_queue)-1
            nome, lung = self.fleet_queue[self.sel_idx]
            self.lbl_nave.config(text=f"Prossima:\n{nome}\n{'█'*lung}  ({lung} celle)")
            self.place_canvas.ship_drag = lung
            self.btn_avvia.config(state="disabled", bg=C["green_dim"], fg=C["text_dim"])
            self.status_bar.set(f"PIAZZA: {nome.upper()}  ({lung} celle) — {len(self.placed_ships)}/{total}",
                                C["accent"], True)
        else:
            self.lbl_nave.config(text="✓ Flotta completa!\nPronto all'attacco.")
            self.place_canvas.ship_drag = None
            self.btn_avvia.config(state="normal", bg="#1a7a40", fg=C["accent3"],
                                  cursor="hand2")
            self.status_bar.set("✓ FLOTTA COMPLETA — PREMI AVVIA PER INIZIARE",
                                C["accent3"], True)
        self._update_orient_label()

    def _send_grid(self):
        play("confirm")
        self._send({"tipo": "griglia", "celle": self.griglia_casa.to_list()})
        fade_transition(self.root, self._build_game)

    # ══════════════════════════════════════════
    # SCHERMATA 3 — PARTITA
    # ══════════════════════════════════════════

    def _build_game(self):
        self._clear()
        self.root.geometry("1160x780")
        self._ships_hidden   = False
        self.mio_turno       = False
        self.partita_finita  = False
        self.griglia_attacco = Griglia()

        # ─ Header ─────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=C["bg2"], pady=0)
        hdr.pack(fill="x")

        # barra superiore con scanline
        top_bar = tk.Canvas(hdr, height=46, bg=C["bg2"], highlightthickness=0)
        top_bar.pack(fill="x")
        top_bar.bind("<Configure>", lambda e: self._redraw_topbar(top_bar))
        self._topbar = top_bar
        self._redraw_topbar(top_bar)

        # ─ Body ───────────────────────────────────────────
        body = tk.Frame(self.root, bg=C["bg"])
        body.pack(expand=True, fill="both", padx=8, pady=6)

        # Griglia casa
        col_l = tk.Frame(body, bg=C["bg"])
        col_l.pack(side="left")

        top_l = tk.Frame(col_l, bg=C["bg"])
        top_l.pack(fill="x", pady=(0,3))
        _label(top_l, f"LE TUE NAVI  [ {self.nome} ]", size=8,
               fg=C["text_dim"], bg=C["bg"]).pack(side="left")
        self.btn_hide = _btn(top_l, "👁 NASCONDI", self._toggle_hide_ships,
                             fg=C["accent"], bg=C["navy"],
                             font=("Courier",7), padx=6, pady=3)
        self.btn_hide.pack(side="right")

        self.canvas_casa = GridCanvas(col_l)
        self.canvas_casa.set_grid(self.griglia_casa.celle)
        self.canvas_casa.pack()

        # Statistiche proprie
        self.stats_casa = StatsPanel(col_l, label=f"DANNI SUBITI")
        self.stats_casa.pack(fill="x", pady=(6,0))

        # Divisore centrale
        div = tk.Frame(body, bg=C["bg"], width=10)
        div.pack(side="left", fill="y", padx=4)

        vs_canvas = tk.Canvas(div, width=10, bg=C["bg"], highlightthickness=0)
        vs_canvas.pack(fill="y", expand=True)
        vs_canvas.bind("<Configure>", lambda e: self._draw_vs(vs_canvas))

        # Griglia attacco
        col_r = tk.Frame(body, bg=C["bg"])
        col_r.pack(side="left", padx=(4,0))

        _label(col_r, f"ATTACCHI SU  [ {self.nome_avv} ]", size=8,
               fg=C["text_dim"], bg=C["bg"]).pack(pady=(0,3))
        self.canvas_att = GridCanvas(col_r, interactive=False)
        self.canvas_att.on_click = self._fire
        self.canvas_att.pack()

        # Statistiche attacco
        self.stats_att = StatsPanel(col_r, label=f"TUOI ATTACCHI")
        self.stats_att.pack(fill="x", pady=(6,0))

        # Pannello destro (chat + log)
        side = tk.Frame(body, bg=C["panel"], padx=8, pady=8)
        side.pack(side="left", fill="both", expand=True, padx=(8,0))

        _label(side, "◉ COMUNICAZIONI DI BORDO", size=7,
               fg=C["accent"], bg=C["panel"], bold=True).pack(anchor="w")
        tk.Frame(side, height=1, bg=C["border"]).pack(fill="x", pady=3)

        self.log_text = tk.Text(side, font=("Courier",8),
                                bg=C["bg"], fg=C["text"], relief="flat",
                                width=24, height=18, state="disabled",
                                wrap="word", highlightthickness=1,
                                highlightbackground=C["border"])
        self.log_text.pack(fill="both", expand=True, pady=(0,6))
        for tag, col in [
            ("hit",    C["fire2"]),
            ("miss",   C["water2"]),
            ("sunk",   C["accent2"]),
            ("chat",   C["accent3"]),
            ("system", C["text_dim"]),
            ("win",    C["gold"]),
            ("enemy",  C["accent2"]),
        ]:
            self.log_text.tag_config(tag, foreground=col)

        # Chat
        _label(side, "TRASMISSIONE", size=7, fg=C["text_dim"],
               bg=C["panel"]).pack(anchor="w")
        chat_row = tk.Frame(side, bg=C["panel"])
        chat_row.pack(fill="x", pady=(2,0))
        self.chat_entry = tk.Entry(chat_row, font=("Courier",9),
                                   bg=C["bg3"], fg=C["accent3"],
                                   insertbackground=C["accent3"],
                                   relief="flat", highlightthickness=1,
                                   highlightcolor=C["accent"],
                                   highlightbackground=C["border"])
        self.chat_entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.chat_entry.bind("<Return>", lambda e: self._send_chat())
        _btn(chat_row, "▶", self._send_chat,
             fg=C["accent3"], bg=C["navy"],
             font=("Courier",9,"bold"), padx=8, pady=5).pack(side="left", padx=(3,0))

        # Status bar
        self.status_bar = StatusBar(self.root)
        self.status_bar.pack(fill="x", side="bottom")

        threading.Thread(target=self._listen_loop, daemon=True).start()
        self._log("⚓ Sistema operativo. In attesa inizio partita...", "system")
        self.status_bar.set("⚓ IN ATTESA DELL'INIZIO PARTITA", C["text_dim"], True)

    def _redraw_topbar(self, canvas):
        """Disegna la topbar con nome, VS e turno."""
        canvas.delete("all")
        try:
            w = canvas.winfo_width() or 1160
        except Exception:
            return
        canvas.create_rectangle(0, 0, w, 46, fill=C["bg2"], outline="")
        # scanline
        for x in range(0, w, 3):
            canvas.create_line(x, 0, x, 46, fill="#101010")
        # nome giocatore
        canvas.create_text(20, 14, text="COMANDANTE", fill=C["text_dim"],
                           font=("Courier",7), anchor="w")
        canvas.create_text(20, 32, text=self.nome.upper(),
                           fill=C["accent3"], font=("Courier",12,"bold"), anchor="w")
        # turno al centro
        turn_text = getattr(self, "_turn_text", "IN ATTESA...")
        turn_col  = getattr(self, "_turn_col",  C["text_dim"])
        canvas.create_text(w//2, 23, text=turn_text,
                           fill=turn_col, font=("Courier",12,"bold"), anchor="center")
        # avversario
        canvas.create_text(w-20, 14, text="AVVERSARIO", fill=C["text_dim"],
                           font=("Courier",7), anchor="e")
        canvas.create_text(w-20, 32, text=self.nome_avv.upper(),
                           fill=C["accent2"], font=("Courier",12,"bold"), anchor="e")
        # linea inferiore
        canvas.create_line(0, 45, w, 45, fill=C["border"])

    def _draw_vs(self, canvas):
        h = canvas.winfo_height() or 600
        canvas.delete("all")
        canvas.create_rectangle(0, 0, 10, h, fill=C["bg"], outline="")
        for y in range(0, h, 40):
            canvas.create_text(5, y+20, text="│", fill=C["border"],
                               font=("Courier",8))

    def _toggle_hide_ships(self):
        self._ships_hidden = not self._ships_hidden
        self.canvas_casa.hide_ships = self._ships_hidden
        self.canvas_casa.refresh_all()
        self.btn_hide.config(text="👁 MOSTRA" if self._ships_hidden else "👁 NASCONDI",
                             fg=C["accent2"] if self._ships_hidden else C["accent"])

    # ── ascolto server ────────────────────────────────────

    def _listen_loop(self):
        while True:
            msg = self._recv()
            if msg is None:
                self.root.after(0, lambda: self._log("⚠ Connessione persa.", "system"))
                break
            self.root.after(0, lambda m=msg: self._handle_msg(m))

    def _handle_msg(self, msg):
        tipo = msg.get("tipo")
        if tipo == "inizio":
            primo = msg["turno"]
            self.mio_turno = (primo == self.nome)
            self._log(f"⚓ Partita iniziata! Primo turno: {primo}", "system")
            self._update_turn_display()
        elif tipo == "turno":
            self.mio_turno = (msg["giocatore"] == self.nome)
            self._update_turn_display()
        elif tipo == "risultato_colpo":
            self._handle_colpo(msg)
        elif tipo == "chat":
            self._log(f"[{msg['ora']}] {msg['mittente']}: {msg['testo']}", "chat")
        elif tipo == "fine_partita":
            self.partita_finita = True
            vincitore = msg["vincitore"]
            self._log(f"\n🏆 {msg['messaggio']}", "win")
            v = vincitore == self.nome
            self._turn_text = f"🏆 {vincitore.upper()} HA VINTO!"
            self._turn_col  = C["gold"] if v else C["accent2"]
            if hasattr(self, "_topbar"):
                self._redraw_topbar(self._topbar)
            self.status_bar.set(
                f"{'🏆 VITTORIA!' if v else '💀 SCONFITTA'} — {vincitore.upper()} VINCE",
                C["gold"] if v else C["accent2"], True)
            play("win" if v else "lose")
            self.root.after(800, lambda: self._show_end_overlay(v))
        elif tipo == "disconnessione":
            self._log(f"⚠ {msg['messaggio']}", "system")
            self.status_bar.set("AVVERSARIO DISCONNESSO", C["accent2"], False)
            self.root.after(600, self._show_disconnect_overlay)

    def _handle_colpo(self, msg):
        r, c     = msg["riga"], msg["col"]
        esito    = msg["esito"]
        tiratore = msg["tiratore"]
        mio      = (tiratore == self.nome)
        val      = COLPITO if esito in ("colpito","affondato") else MANCATO

        if mio:
            self.canvas_att.set_cell(r, c, val)
            self.griglia_attacco.celle[r][c] = val
            if val == COLPITO:
                self.canvas_att.spawn_explosion(r, c)
                self._log(f"💥 ({r},{c}) → {esito.upper()}!", "hit")
                self.stats_att.inc("hit")
                play("explosion")
            else:
                self.canvas_att.spawn_splash(r, c)
                self._log(f"○  ({r},{c}) → ACQUA", "miss")
                self.stats_att.inc("miss")
                play("splash")
        else:
            self.canvas_casa.set_cell(r, c, val)
            self.griglia_casa.celle[r][c] = val
            if val == COLPITO:
                self.canvas_casa.spawn_explosion(r, c)
                self._log(f"🎯 {tiratore} → ({r},{c}): {esito.upper()}", "enemy")
                self.stats_casa.inc("hit")
                play("explosion")
            else:
                self.canvas_casa.spawn_splash(r, c)
                self._log(f"   {tiratore} → ({r},{c}): acqua", "miss")
                self.stats_casa.inc("miss")
                play("splash")

        if esito == "affondato":
            self._log("🚢 NAVE AFFONDATA!", "sunk")
            if mio:
                self.canvas_att.spawn_sunk(msg.get("nave",[]))
                self.stats_att.inc("sunk")
            else:
                self.stats_casa.inc("sunk")
            play("sunk")
            self.status_bar.set("🚢 NAVE AFFONDATA!", C["accent2"], True)

    def _update_turn_display(self):
        if self.mio_turno:
            self._turn_text = "⚡  IL TUO TURNO — FUOCO!"
            self._turn_col  = C["accent"]
            self.canvas_att.interactive = True
            self.status_bar.set("⚡ IL TUO TURNO — CLICCA SULLA GRIGLIA PER SPARARE",
                                C["accent"], True)
            play("your_turn")
        else:
            self._turn_text = f"⏳  TURNO DI {self.nome_avv.upper()}"
            self._turn_col  = C["text_dim"]
            self.canvas_att.interactive = False
            self.status_bar.set(f"⏳ TURNO DI {self.nome_avv.upper()} — ATTENDI",
                                C["text_dim"], False)
        if hasattr(self, "_topbar"):
            self._redraw_topbar(self._topbar)

    # ── overlay fine partita ──────────────────────────────

    def _show_end_overlay(self, vittoria: bool):
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.configure(bg=C["bg"])
        ov.geometry("520x320+320+230")

        # bordo luminoso
        border_col = C["gold"] if vittoria else C["accent2"]
        tk.Frame(ov, bg=border_col, height=3).pack(fill="x")

        # Logo mini
        logo_mini = tk.Canvas(ov, width=520, height=80,
                              bg=C["bg"], highlightthickness=0)
        logo_mini.pack()
        title = "⚓  VITTORIA!" if vittoria else "💀  SCONFITTA"
        col   = C["gold"] if vittoria else C["accent2"]
        logo_mini.create_text(260, 24, text=title,
                              font=("Courier",26,"bold"), fill=col)
        sub = "Hai affondato tutta la flotta nemica." if vittoria else "La tua flotta è stata distrutta."
        logo_mini.create_text(260, 58, text=sub,
                              font=("Courier",10), fill=C["text_dim"])

        # Statistiche veloci
        stat_frame = tk.Frame(ov, bg=C["bg2"], pady=8)
        stat_frame.pack(fill="x", padx=20, pady=8)
        if hasattr(self, "stats_att"):
            for key, icon, c_col in [("hit","💥 Colpi a segno",C["fire2"]),
                                     ("sunk","🚢 Navi affondate",C["accent2"])]:
                v = self.stats_att._vars.get(key, tk.StringVar(value="0")).get()
                r = tk.Frame(stat_frame, bg=C["bg2"])
                r.pack(side="left", padx=16)
                _label(r, icon, size=8, fg=c_col, bg=C["bg2"]).pack()
                _label(r, v,    size=22, fg=c_col, bg=C["bg2"], bold=True).pack()

        # Bottoni
        btn_row = tk.Frame(ov, bg=C["bg"])
        btn_row.pack(pady=12)
        _btn(btn_row, "  🏆 CLASSIFICA  ",
             lambda: [ov.destroy(), self._show_leaderboard()],
             fg=C["gold"], bg=C["bg3"],
             font=("Courier",9,"bold"), padx=12, pady=10).pack(side="left", padx=5)
        _btn(btn_row, "  ⟳ NUOVA PARTITA  ",
             lambda: [ov.destroy(), self._restart()],
             fg=C["accent"], bg=C["navy"],
             font=("Courier",9,"bold"), padx=12, pady=10).pack(side="left", padx=5)
        _btn(btn_row, "  ✕ ESCI  ",
             self.root.quit,
             fg=C["accent2"], bg=C["bg3"],
             font=("Courier",9,"bold"), padx=12, pady=10).pack(side="left", padx=5)

        tk.Frame(ov, bg=border_col, height=3).pack(fill="x", side="bottom")

    def _show_disconnect_overlay(self):
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.configure(bg=C["bg"])
        ov.geometry("440x220+360+290")
        tk.Frame(ov, bg=C["accent2"], height=3).pack(fill="x")
        _label(ov, "⚠  DISCONNESSIONE", size=20, fg=C["accent2"],
               bg=C["bg"], bold=True).pack(pady=(16,4))
        _label(ov, "L'avversario ha abbandonato la battaglia.",
               size=9, fg=C["text_dim"], bg=C["bg"]).pack()
        btn_row = tk.Frame(ov, bg=C["bg"])
        btn_row.pack(pady=18)
        _btn(btn_row, "  ⟳ NUOVA PARTITA  ",
             lambda: [ov.destroy(), self._restart()],
             fg=C["accent"], bg=C["navy"],
             font=("Courier",9,"bold"), padx=12, pady=8).pack(side="left", padx=5)
        _btn(btn_row, "  ✕ ESCI  ", self.root.quit,
             fg=C["accent2"], bg=C["bg3"],
             font=("Courier",9,"bold"), padx=12, pady=8).pack(side="left", padx=5)
        tk.Frame(ov, bg=C["accent2"], height=3).pack(fill="x", side="bottom")

    def _restart(self):
        play("click")
        if self.conn:
            try: self.conn.close()
            except Exception: pass
            self.conn = None
        self.nome = self.nome_avv = ""
        self.mio_turno = self.partita_finita = False
        self.griglia_casa    = Griglia()
        self.griglia_attacco = Griglia()
        self.placed_ships = []
        self.fleet_queue  = []
        self.sel_idx      = 0
        self._ships_hidden = False
        fade_transition(self.root, self._build_login)

    # ── azioni utente ─────────────────────────────────────

    def _fire(self, r, c):
        if not self.mio_turno or self.partita_finita:
            return
        if self.griglia_attacco.celle[r][c] in (COLPITO, MANCATO):
            self._log("⚠ Cella già colpita!", "system")
            return
        play("click")
        self._send({"tipo": "colpo", "riga": r, "col": c})

    def _send_chat(self):
        testo = self.chat_entry.get().strip()
        if not testo: return
        self._send({"tipo": "chat", "testo": testo})
        self._log(f"[tu] {testo}", "chat")
        self.chat_entry.delete(0, "end")
        play("click")


if __name__ == "__main__":
    BattagliaNavaleApp()
