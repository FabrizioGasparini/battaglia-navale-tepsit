"""
client.py - Client GUI Battaglia Navale (v4.0)
Canvas riscritto con tag-based rendering: niente delete("all") ogni frame,
aggiornamento diretto delle singole celle. Hover e navi sempre visibili.
"""

import tkinter as tk
from tkinter import font as tkfont
import socket
import threading
import json
import os
import random
import math
from game_logic import Griglia, ACQUA, NAVE, COLPITO, MANCATO, FLOTTA

SERVER_HOST = "127.0.0.1"
SERVER_PORT  = 50007
STATS_FILE   = "statistiche.json"

# ─────────────────────────────────────────────
# Palette
# ─────────────────────────────────────────────
C = {
    "bg":         "#050d15",
    "bg2":        "#0a1a27",
    "bg3":        "#0f2236",
    "panel":      "#071520",
    "border":     "#1a4060",
    "border_hi":  "#2a7ab0",
    "accent":     "#00d4ff",
    "accent2":    "#ff6b35",
    "accent3":    "#00ff88",
    "text":       "#c8e8f8",
    "text_dim":   "#4a7a9b",
    "text_hi":    "#ffffff",
    "navy":       "#1a3a5c",
    "cell_sea":   "#0a2540",
    "cell_hover": "#1a5080",
    "cell_ship":  "#1a6b3a",
    "cell_hit":   "#8b1a1a",
    "cell_miss":  "#0d2d45",
    "ship_outline":"#52be80",
    "fire1":      "#ff4500",
    "fire2":      "#ff8c00",
    "fire3":      "#ffd700",
    "water1":     "#006994",
    "water2":     "#00b4d8",
    "grid_line":  "#112233",
    "green_dim":  "#004422",
    "radar":      "#00ff44",
    "remove_hi":  "#cc1133",
    "remove_out": "#ff4466",
    "preview_ok": "#00ff88",
    "preview_no": "#ff3333",
}

CELL = 46   # dimensione cella in pixel
GRID = 10
PAD  = 28   # padding griglia (spazio per le etichette)


# ══════════════════════════════════════════════════════════════
# GridCanvas — rendering tag-based, niente full-redraw ogni tick
# ══════════════════════════════════════════════════════════════

class GridCanvas(tk.Canvas):
    """
    Griglia 10x10 con:
    - rendering a tag: ogni cella ha un tag fisso, viene aggiornata solo quando cambia
    - hover immediato via eventi (non aspetta il tick)
    - preview piazzamento nave (celle colorate sotto il cursore)
    - particelle per esplosioni/spruzzi (solo schermata di gioco)
    """

    def __init__(self, master, interactive=False, **kwargs):
        w = h = PAD + CELL * GRID + 6
        super().__init__(master, width=w, height=h,
                         bg=C["bg"], highlightthickness=2,
                         highlightbackground=C["border"], **kwargs)

        self.interactive   = interactive
        self.place_mode    = False
        self.remove_mode   = False
        self.hide_ships    = False

        self.cells         = [[ACQUA] * GRID for _ in range(GRID)]
        self._prev_cells   = [[ACQUA] * GRID for _ in range(GRID)]  # stato precedente
        self.hover_cell    = None
        self._prev_hover   = None
        self.preview_cells = set()
        self._prev_preview = set()
        self.drag_orient   = True   # True = orizzontale
        self.ship_drag     = None   # lunghezza nave da piazzare

        self.particles     = []
        self.animations    = {}     # (r,c) -> frame rimasti

        self.on_click  = None
        self.on_place  = None
        self.on_remove = None

        self._build_static()      # disegna sfondo, etichette, griglia (una volta sola)
        self._init_cells()        # crea i rettangoli delle celle con tag
        self._tick_particles()    # loop particelle separato

        self.bind("<Motion>",    self._on_motion)
        self.bind("<Leave>",     self._on_leave)
        self.bind("<Button-1>",  self._on_click_ev)
        self.bind("<Button-3>",  self._on_right_click)

    # ── coordinate ────────────────────────────────────────────

    def _cell_xy(self, r, c):
        """Angolo in alto a sinistra della cella (r,c)."""
        return PAD + c * CELL, PAD + r * CELL

    def _xy_to_cell(self, x, y):
        c = (x - PAD) // CELL
        r = (y - PAD) // CELL
        if 0 <= r < GRID and 0 <= c < GRID:
            return int(r), int(c)
        return None

    def _cell_tag(self, r, c):
        return f"cell_{r}_{c}"

    # ── costruzione statica ────────────────────────────────────

    def _build_static(self):
        """Disegna sfondo e etichette (eseguito una sola volta)."""
        letters = "ABCDEFGHIJ"
        font_lbl = ("Courier", 8, "bold")
        for i in range(GRID):
            # lettere in alto
            self.create_text(PAD + i * CELL + CELL // 2, PAD // 2,
                             text=letters[i], fill=C["text_dim"], font=font_lbl,
                             tags="static")
            # numeri a sinistra
            self.create_text(PAD // 2, PAD + i * CELL + CELL // 2,
                             text=str(i), fill=C["text_dim"], font=font_lbl,
                             tags="static")

    def _init_cells(self):
        """Crea un rettangolo per ogni cella con il suo tag univoco."""
        for r in range(GRID):
            for c in range(GRID):
                x1, y1 = self._cell_xy(r, c)
                x2, y2 = x1 + CELL, y1 + CELL
                tag = self._cell_tag(r, c)
                self.create_rectangle(x1, y1, x2, y2,
                                      fill=C["cell_sea"], outline=C["grid_line"],
                                      width=1, tags=tag)
                # Placeholder per il simbolo interno (sopra il rettangolo)
                self.create_text(x1 + CELL//2, y1 + CELL//2,
                                 text="", fill=C["ship_outline"],
                                 font=("Courier", 14, "bold"),
                                 tags=tag + "_sym")

    # ── aggiornamento celle ────────────────────────────────────

    def _refresh_cell(self, r, c, force=False):
        """Aggiorna colore e simbolo di una singola cella se necessario."""
        val     = self.cells[r][c]
        hover   = self.hover_cell == (r, c)
        in_prev = (r, c) in self.preview_cells
        frame   = self.animations.get((r, c), 0)

        # Valore visivo (hide_ships nasconde le navi)
        show = ACQUA if (self.hide_ships and val == NAVE) else val

        # ── calcola colore sfondo ──────────────────────────
        if show == NAVE:
            if self.remove_mode and hover:
                bg, out = C["remove_hi"], C["remove_out"]
            else:
                bg, out = C["cell_ship"], C["ship_outline"]
        elif show == COLPITO:
            if frame > 0:
                v = min(255, 139 + int(60 * frame / 12))
                bg = f"#{v:02x}1a1a"
            else:
                bg = C["cell_hit"]
            out = C["fire2"]
        elif show == MANCATO:
            bg, out = C["cell_miss"], C["water2"]
        elif in_prev:
            # preview piazzamento
            ok = val == ACQUA
            bg  = "#003322" if ok else "#330000"
            out = C["preview_ok"] if ok else C["preview_no"]
        elif hover and (self.interactive or self.place_mode):
            bg, out = C["cell_hover"], C["border_hi"]
        else:
            bg, out = C["cell_sea"], C["grid_line"]

        # ── simbolo interno ────────────────────────────────
        if show == NAVE:
            sym      = "◼"
            sym_col  = C["remove_out"] if (self.remove_mode and hover) else C["ship_outline"]
        elif show == COLPITO:
            sym     = "✕"
            sym_col = C["fire3"]
        elif show == MANCATO:
            sym     = "·"
            sym_col = C["water2"]
        elif in_prev:
            ok      = val == ACQUA
            sym     = "◻"
            sym_col = C["preview_ok"] if ok else C["preview_no"]
        elif hover and self.interactive and show == ACQUA:
            sym     = "+"
            sym_col = C["accent"]
        else:
            sym     = ""
            sym_col = C["cell_sea"]

        tag     = self._cell_tag(r, c)
        tag_sym = tag + "_sym"
        self.itemconfig(tag,     fill=bg, outline=out)
        self.itemconfig(tag_sym, text=sym, fill=sym_col)

    def refresh_all(self):
        """Ridisegna tutte le celle (usato dopo cambi di stato globali)."""
        for r in range(GRID):
            for c in range(GRID):
                self._refresh_cell(r, c)

    # ── api pubblica ───────────────────────────────────────────

    def set_cell(self, r, c, val):
        self.cells[r][c] = val
        self._refresh_cell(r, c)

    def set_grid(self, grid_2d):
        """Carica un'intera griglia e ridisegna tutto."""
        for r in range(GRID):
            for c in range(GRID):
                self.cells[r][c] = grid_2d[r][c]
        self.refresh_all()

    # ── preview piazzamento ────────────────────────────────────

    def _compute_preview(self, cell):
        """Calcola le celle della preview in base alla posizione e all'orientamento."""
        if self.ship_drag is None or cell is None:
            return set()
        r, c = cell
        n = self.ship_drag
        if self.drag_orient:
            return {(r, c + i) for i in range(n) if c + i < GRID}
        else:
            return {(r + i, c) for i in range(n) if r + i < GRID}

    def _set_preview(self, new_preview):
        """Aggiorna la preview: ridisegna solo le celle cambiate."""
        old = self.preview_cells
        self.preview_cells = new_preview
        for cell in old | new_preview:
            r, c = cell
            self._refresh_cell(r, c)

    # ── eventi mouse ───────────────────────────────────────────

    def _on_motion(self, event):
        cell = self._xy_to_cell(event.x, event.y)

        # Aggiorna hover
        old_hover = self.hover_cell
        self.hover_cell = cell
        if old_hover != cell:
            if old_hover:
                self._refresh_cell(*old_hover)
            if cell:
                self._refresh_cell(*cell)

        # Aggiorna preview
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
                self.on_remove(r, c)
            elif self.ship_drag is not None and self.on_place:
                self.on_place(r, c)
        elif self.interactive and self.on_click:
            self.on_click(r, c)

    def _on_right_click(self, event):
        self.drag_orient = not self.drag_orient
        if self.place_mode:
            self._set_preview(self._compute_preview(self.hover_cell))

    # ── particelle (solo effetti di gioco) ────────────────────

    def spawn_explosion(self, r, c):
        x1, y1 = self._cell_xy(r, c)
        cx, cy = x1 + CELL // 2, y1 + CELL // 2
        colors = [C["fire1"], C["fire2"], C["fire3"], "#ffffff", C["accent2"]]
        for _ in range(22):
            ang   = random.uniform(0, 2 * math.pi)
            speed = random.uniform(1.5, 5)
            self.particles.append({
                "x": cx, "y": cy,
                "vx": math.cos(ang) * speed, "vy": math.sin(ang) * speed - 2,
                "color": random.choice(colors),
                "size": random.uniform(2, 6),
                "life": random.randint(18, 38), "max_life": 38,
            })
        self.animations[(r, c)] = 20
        self._refresh_cell(r, c)

    def spawn_splash(self, r, c):
        x1, y1 = self._cell_xy(r, c)
        cx, cy = x1 + CELL // 2, y1 + CELL // 2
        colors = [C["water1"], C["water2"], C["accent"], "#90e0ef"]
        for _ in range(14):
            ang   = random.uniform(-math.pi, 0)
            speed = random.uniform(1, 4)
            self.particles.append({
                "x": cx, "y": cy,
                "vx": math.cos(ang) * speed, "vy": math.sin(ang) * speed - 1,
                "color": random.choice(colors),
                "size": random.uniform(2, 5),
                "life": random.randint(12, 28), "max_life": 28,
            })

    def spawn_sunk(self, cells_list):
        for r, c in cells_list:
            self.after(random.randint(0, 300),
                       lambda r=r, c=c: self.spawn_explosion(r, c))

    def _tick_particles(self):
        """Loop separato solo per le particelle — non ridisegna le celle."""
        # Rimuovi i tag delle particelle vecchie
        self.delete("particle")

        # Aggiorna animazioni celle
        changed = []
        for cell in list(self.animations):
            self.animations[cell] -= 1
            if self.animations[cell] <= 0:
                del self.animations[cell]
            changed.append(cell)
        for r, c in changed:
            self._refresh_cell(r, c)

        # Aggiorna e disegna particelle
        for p in self.particles[:]:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["vy"] += 0.35
            p["life"] -= 1
            if p["life"] <= 0:
                self.particles.remove(p)
                continue
            a    = max(0.0, p["life"] / p["max_life"])
            size = max(1, int(p["size"] * a))
            x, y = int(p["x"]), int(p["y"])
            self.create_oval(x - size, y - size, x + size, y + size,
                             fill=p["color"], outline="", tags="particle")

        self.after(33, self._tick_particles)


# ══════════════════════════════════════════════════════════════
# App principale
# ══════════════════════════════════════════════════════════════

class BattagliaNavaleApp:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("⚓ Battaglia Navale")
        self.root.configure(bg=C["bg"])
        self.root.resizable(True, True)

        self.font_title = tkfont.Font(family="Courier", size=22, weight="bold")
        self.font_sub   = tkfont.Font(family="Courier", size=11, weight="bold")
        self.font_chat  = tkfont.Font(family="Courier", size=9)
        self.font_small = tkfont.Font(family="Courier", size=8)
        self.font_btn   = tkfont.Font(family="Courier", size=10, weight="bold")

        self.conn            = None
        self.nome            = ""
        self.nome_avv        = ""
        self.mio_turno       = False
        self.partita_finita  = False
        self.griglia_casa    = Griglia()
        self.griglia_attacco = Griglia()
        self.placed_ships    = []   # [(nome, lung, [(r,c),...]), ...]
        self.fleet_queue     = []   # [(nome, lung), ...]
        self.sel_idx         = 0
        self._ships_hidden   = False

        self._build_login()
        self.root.mainloop()

    # ══════════════════════════════════════════
    # Utilità di rete
    # ══════════════════════════════════════════

    def _send(self, msg: dict):
        if self.conn:
            try:
                self.conn.sendall((json.dumps(msg) + "\n").encode())
            except Exception:
                pass

    def _recv(self) -> dict | None:
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
            try:
                self.root.after_cancel(self._radar_id)
            except Exception:
                pass
        for w in self.root.winfo_children():
            w.destroy()

    # ══════════════════════════════════════════
    # SCHERMATA 1 — Login
    # ══════════════════════════════════════════

    def _build_login(self):
        self._clear()
        self.root.geometry("480x600")

        frame = tk.Frame(self.root, bg=C["bg"])
        frame.pack(expand=True, fill="both")

        self.radar_canvas = tk.Canvas(frame, width=480, height=160,
                                      bg=C["bg"], highlightthickness=0)
        self.radar_canvas.pack()
        self._radar_angle = 0
        self._animate_radar()

        tk.Label(frame, text="⚓  BATTAGLIA NAVALE",
                 font=self.font_title, bg=C["bg"], fg=C["accent"]).pack(pady=(0, 4))
        tk.Label(frame, text="SISTEMA DI COMBATTIMENTO NAVALE v4.0",
                 font=self.font_small, bg=C["bg"], fg=C["text_dim"]).pack()
        tk.Frame(frame, height=1, bg=C["border"], width=380).pack(pady=14)

        def field(label, default=""):
            tk.Label(frame, text=label, font=self.font_small,
                     bg=C["bg"], fg=C["text_dim"]).pack()
            e = tk.Entry(frame, font=self.font_sub, bg=C["bg3"], fg=C["accent"],
                         insertbackground=C["accent"], relief="flat", width=22,
                         highlightthickness=1, highlightcolor=C["border_hi"],
                         highlightbackground=C["border"])
            e.insert(0, default)
            e.pack(pady=6, ipady=8)
            return e

        self.entry_nome = field("IDENTIFICATIVO UFFICIALE", "")
        self.entry_host = field("INDIRIZZO SERVER", SERVER_HOST)
        self.entry_port = field("PORTA", str(SERVER_PORT))
        self.entry_port.config(fg=C["text"])
        self.entry_nome.focus()

        self.login_status = tk.Label(frame, text="", font=self.font_small,
                                     bg=C["bg"], fg=C["text_dim"])
        self.login_status.pack(pady=4)

        btn_row = tk.Frame(frame, bg=C["bg"])
        btn_row.pack(pady=10)
        tk.Button(btn_row, text="▶  CONNETTI",
                  font=self.font_btn, bg=C["navy"], fg=C["accent"],
                  activebackground=C["border_hi"], activeforeground=C["text_hi"],
                  relief="flat", padx=20, pady=10, cursor="hand2",
                  command=self._connect).pack(side="left", padx=(0, 8))
        tk.Button(btn_row, text="🏆 CLASSIFICA",
                  font=self.font_btn, bg=C["bg3"], fg=C["fire3"],
                  relief="flat", padx=14, pady=10, cursor="hand2",
                  command=self._show_leaderboard).pack(side="left")

        for e in (self.entry_nome, self.entry_host, self.entry_port):
            e.bind("<Return>", lambda ev: self._connect())

    def _animate_radar(self):
        if not hasattr(self, "radar_canvas"):
            return
        try:
            cv = self.radar_canvas
            cv.delete("all")
        except tk.TclError:
            return
        cx, cy, r = 240, 80, 60
        for i in range(1, 5):
            ri = r * i // 4
            cv.create_oval(cx - ri, cy - ri, cx + ri, cy + ri,
                           outline=C["green_dim"], width=1)
        cv.create_line(cx - r, cy, cx + r, cy, fill=C["green_dim"], width=1)
        cv.create_line(cx, cy - r, cx, cy + r, fill=C["green_dim"], width=1)
        a = math.radians(self._radar_angle)
        for i in range(30):
            ai = a - math.radians(i * 2)
            alpha = (30 - i) / 30
            x2 = cx + r * math.cos(ai)
            y2 = cy + r * math.sin(ai)
            intensity = int(alpha * 180)
            col = f"#00{intensity:02x}00"
            cv.create_line(cx, cy, x2, y2, fill=col, width=2)
        cv.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=C["radar"], outline="")
        if random.random() < 0.08:
            bx = cx + random.randint(-r + 10, r - 10)
            by = cy + random.randint(-r + 10, r - 10)
            cv.create_oval(bx - 3, by - 3, bx + 3, by + 3, fill=C["radar"], outline="")
        self._radar_angle = (self._radar_angle + 4) % 360
        self._radar_id = self.root.after(40, self._animate_radar)

    def _connect(self):
        self.nome = self.entry_nome.get().strip() or "Comandante"
        host      = self.entry_host.get().strip() or SERVER_HOST
        try:
            port = int(self.entry_port.get().strip())
        except ValueError:
            self.login_status.config(text="✗ Porta non valida", fg=C["accent2"])
            return
        self.login_status.config(text=f"Connessione a {host}:{port}...", fg=C["text_dim"])
        self.root.update()
        try:
            self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.conn.connect((host, port))
        except Exception as e:
            self.login_status.config(text=f"✗ {e}", fg=C["accent2"])
            return
        self._send({"tipo": "nome", "nome": self.nome})
        self.login_status.config(text="✓ Connesso! In attesa avversario...", fg=C["accent3"])
        threading.Thread(target=self._wait_opponent, daemon=True).start()

    def _wait_opponent(self):
        msg = self._recv()      # ok / benvenuto
        if not msg:
            return
        msg = self._recv()      # avversario
        if msg and msg.get("tipo") == "avversario":
            self.nome_avv = msg["nome"]
        self._recv()            # richiesta_griglia
        self.root.after(0, self._build_placement)

    # ══════════════════════════════════════════
    # CLASSIFICA
    # ══════════════════════════════════════════

    def _show_leaderboard(self):
        win = tk.Toplevel(self.root)
        win.title("🏆 Classifica")
        win.configure(bg=C["bg"])
        win.resizable(False, False)
        win.geometry("500x540")

        tk.Frame(win, bg=C["border"], height=2).pack(fill="x")
        tk.Label(win, text="🏆  CLASSIFICA UFFICIALE",
                 font=self.font_title, bg=C["bg"], fg=C["fire3"]).pack(pady=(14, 4))
        tk.Label(win, text="Statistiche partite giocate",
                 font=self.font_small, bg=C["bg"], fg=C["text_dim"]).pack()
        tk.Frame(win, bg=C["border"], height=1).pack(fill="x", pady=10)

        hdr = tk.Frame(win, bg=C["bg2"], pady=6)
        hdr.pack(fill="x", padx=16)
        for txt, w in [("#", 3), ("GIOCATORE", 16), ("V", 4), ("S", 4), ("P", 4), ("%V", 6)]:
            tk.Label(hdr, text=txt, font=self.font_small, bg=C["bg2"],
                     fg=C["accent"], width=w, anchor="center").pack(side="left")

        body = tk.Frame(win, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=16)

        stats = {}
        if os.path.exists(STATS_FILE):
            try:
                with open(STATS_FILE) as f:
                    stats = json.load(f)
            except Exception:
                pass

        if not stats:
            tk.Label(body, text="\n\nNessuna partita registrata.\nGioca la tua prima partita!",
                     font=self.font_sub, bg=C["bg"], fg=C["text_dim"],
                     justify="center").pack(expand=True)
        else:
            ranking = sorted(
                stats.items(),
                key=lambda x: (x[1].get("vittorie", 0),
                               x[1].get("vittorie", 0) / max(x[1].get("partite", 1), 1)),
                reverse=True
            )
            medals = ["🥇", "🥈", "🥉"]
            for pos, (nome, dati) in enumerate(ranking, 1):
                v   = dati.get("vittorie", 0)
                s   = dati.get("sconfitte", 0)
                p   = dati.get("partite", 0)
                pct = f"{v / p * 100:.0f}%" if p > 0 else "—"
                med = medals[pos - 1] if pos <= 3 else f"{pos}."
                bg  = C["bg3"] if pos % 2 == 0 else C["bg2"]
                col = C["fire3"] if pos == 1 else C["text"]
                row = tk.Frame(body, bg=bg, pady=4)
                row.pack(fill="x", pady=1)
                for txt, w in [(med, 3), (nome, 16), (str(v), 4),
                               (str(s), 4), (str(p), 4), (pct, 6)]:
                    tk.Label(row, text=txt, font=self.font_small, bg=bg,
                             fg=col, width=w, anchor="center").pack(side="left")

        tk.Frame(win, bg=C["border"], height=1).pack(fill="x", pady=8)
        tk.Button(win, text="✕  CHIUDI", font=self.font_btn,
                  bg=C["navy"], fg=C["text"], relief="flat",
                  padx=16, pady=8, cursor="hand2",
                  command=win.destroy).pack(pady=8)

    # ══════════════════════════════════════════
    # SCHERMATA 2 — Posizionamento navi
    # ══════════════════════════════════════════

    def _build_placement(self):
        self._clear()
        self.root.geometry("780x700")

        self.placed_ships = []
        self.griglia_casa = Griglia()
        self._rebuild_fleet_queue()

        # Header
        hdr = tk.Frame(self.root, bg=C["bg2"], pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚓  POSIZIONAMENTO FLOTTA",
                 font=self.font_sub, bg=C["bg2"], fg=C["accent"]).pack()
        tk.Label(hdr,
                 text="Click SX su cella vuota = piazza  │  Click SX su nave = rimuovi  │  Click DX = ruota",
                 font=self.font_small, bg=C["bg2"], fg=C["text_dim"]).pack()

        body = tk.Frame(self.root, bg=C["bg"])
        body.pack(expand=True, fill="both", padx=12, pady=8)

        # ── Griglia centrale ──────────────────────────────
        gf = tk.Frame(body, bg=C["bg"])
        gf.pack(side="left")
        tk.Label(gf, text=f"[ {self.nome.upper()} ] — LA TUA GRIGLIA",
                 font=self.font_small, bg=C["bg"], fg=C["text_dim"]).pack(pady=(0, 4))

        self.place_canvas = GridCanvas(gf)
        self.place_canvas.place_mode  = True
        self.place_canvas.remove_mode = True
        self.place_canvas.on_place    = self._place_ship
        self.place_canvas.on_remove   = self._remove_ship_at
        self.place_canvas.pack()

        # ── Pannello laterale ─────────────────────────────
        side = tk.Frame(body, bg=C["bg2"], padx=14, pady=14, width=220)
        side.pack(side="left", fill="y", padx=(14, 0))
        side.pack_propagate(False)

        tk.Label(side, text="FLOTTA", font=self.font_sub,
                 bg=C["bg2"], fg=C["accent"]).pack(pady=(0, 6))

        # Lista navi
        self.fleet_frame = tk.Frame(side, bg=C["bg2"])
        self.fleet_frame.pack(fill="x")

        tk.Frame(side, height=1, bg=C["border"]).pack(fill="x", pady=8)

        # Indicatore orientamento
        self.lbl_orient = tk.Label(side, text="", font=self.font_small,
                                   bg=C["bg3"], fg=C["accent3"],
                                   pady=4, width=24)
        self.lbl_orient.pack(fill="x", pady=(0, 4))

        # Stato corrente
        self.lbl_nave = tk.Label(side, text="", font=self.font_small,
                                 bg=C["bg2"], fg=C["accent3"],
                                 wraplength=190, justify="left")
        self.lbl_nave.pack(pady=4)

        tk.Frame(side, height=1, bg=C["border"]).pack(fill="x", pady=6)

        # Pulsanti
        self.btn_avvia = tk.Button(side, text="▶  AVVIA PARTITA",
                                   font=self.font_btn, bg=C["green_dim"],
                                   fg=C["text_dim"], relief="flat",
                                   pady=10, cursor="hand2", state="disabled",
                                   command=self._send_grid)
        self.btn_avvia.pack(fill="x", pady=4)

        tk.Button(side, text="↻  RUOTA  (o Click DX)",
                  font=self.font_small, bg=C["bg3"], fg=C["accent"],
                  relief="flat", pady=7, cursor="hand2",
                  command=self._rotate_ship).pack(fill="x", pady=2)

        tk.Button(side, text="⟳  AUTO-POSIZIONA TUTTO",
                  font=self.font_small, bg=C["navy"], fg=C["text"],
                  relief="flat", pady=7, cursor="hand2",
                  command=self._auto_place).pack(fill="x", pady=2)

        tk.Button(side, text="✕  RESET COMPLETO",
                  font=self.font_small, bg=C["navy"], fg=C["accent2"],
                  relief="flat", pady=7, cursor="hand2",
                  command=self._reset_placement).pack(fill="x", pady=2)

        self._refresh_placement_ui()

    # ── logica placement ──────────────────────────────────────

    def _rebuild_fleet_queue(self):
        count = {}
        for nome, _, _ in self.placed_ships:
            count[nome] = count.get(nome, 0) + 1
        self.fleet_queue = []
        for nome, lung, qty in FLOTTA:
            for _ in range(qty - count.get(nome, 0)):
                self.fleet_queue.append((nome, lung))
        self.sel_idx = min(self.sel_idx, max(0, len(self.fleet_queue) - 1))

    def _rebuild_fleet_labels(self):
        for w in self.fleet_frame.winfo_children():
            w.destroy()

        for i, (nome, lung, _) in enumerate(self.placed_ships):
            row = tk.Frame(self.fleet_frame, bg=C["bg3"], pady=2)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"✓ {'█' * lung}",
                     font=("Courier", 8), bg=C["bg3"], fg=C["accent3"],
                     width=8, anchor="w").pack(side="left")
            tk.Label(row, text=nome,
                     font=("Courier", 8), bg=C["bg3"], fg=C["text_dim"],
                     anchor="w").pack(side="left")
            tk.Button(row, text="✕", font=("Courier", 7), bg=C["bg3"],
                      fg=C["accent2"], relief="flat", cursor="hand2",
                      command=lambda idx=i: self._remove_ship_by_index(idx)).pack(side="right")

        for i, (nome, lung) in enumerate(self.fleet_queue):
            is_sel = (i == self.sel_idx)
            bg     = C["navy"] if is_sel else C["bg2"]
            fg     = C["accent"] if is_sel else C["text_dim"]
            row = tk.Frame(self.fleet_frame, bg=bg, pady=2, cursor="hand2")
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"{'▶' if is_sel else '  '} {'□' * lung}",
                     font=("Courier", 8, "bold" if is_sel else "normal"),
                     bg=bg, fg=fg, width=8, anchor="w").pack(side="left")
            tk.Label(row, text=nome,
                     font=("Courier", 8, "bold" if is_sel else "normal"),
                     bg=bg, fg=fg, anchor="w").pack(side="left")
            row.bind("<Button-1>", lambda e, idx=i: self._select_ship(idx))
            for child in row.winfo_children():
                child.bind("<Button-1>", lambda e, idx=i: self._select_ship(idx))

    def _select_ship(self, idx):
        self.sel_idx = idx
        self._refresh_placement_ui()
        if self.place_canvas.hover_cell:
            self.place_canvas._set_preview(
                self.place_canvas._compute_preview(self.place_canvas.hover_cell))

    def _rotate_ship(self):
        self.place_canvas.drag_orient = not self.place_canvas.drag_orient
        self.place_canvas._set_preview(
            self.place_canvas._compute_preview(self.place_canvas.hover_cell))
        self._update_orient_label()

    def _update_orient_label(self):
        orient = "→ ORIZZONTALE" if self.place_canvas.drag_orient else "↓ VERTICALE"
        self.lbl_orient.config(text=f"Orientamento: {orient}")

    def _place_ship(self, r, c):
        if not self.fleet_queue or self.sel_idx >= len(self.fleet_queue):
            return
        nome, lung = self.fleet_queue[self.sel_idx]
        ori = self.place_canvas.drag_orient

        if self.griglia_casa.piazza_nave(r, c, lung, ori):
            cells = [(r, c + i) for i in range(lung)] if ori else [(r + i, c) for i in range(lung)]
            for ri, ci in cells:
                self.place_canvas.set_cell(ri, ci, NAVE)
            self.placed_ships.append((nome, lung, cells))
            self.fleet_queue.pop(self.sel_idx)
            self.sel_idx = min(self.sel_idx, max(0, len(self.fleet_queue) - 1))
            self.place_canvas._set_preview(set())
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
        self._refresh_placement_ui()

    def _reset_placement(self):
        self.placed_ships = []
        self.griglia_casa = Griglia()
        self._rebuild_fleet_queue()
        self.place_canvas.cells = [[ACQUA] * GRID for _ in range(GRID)]
        self.place_canvas.refresh_all()
        self.place_canvas._set_preview(set())
        self._refresh_placement_ui()

    def _auto_place(self):
        while self.fleet_queue:
            nome, lung = self.fleet_queue[0]
            for _ in range(2000):
                r   = random.randint(0, 9)
                c   = random.randint(0, 9)
                ori = random.choice([True, False])
                if self.griglia_casa.piazza_nave(r, c, lung, ori):
                    cells = [(r, c + i) for i in range(lung)] if ori else [(r + i, c) for i in range(lung)]
                    for ri, ci in cells:
                        self.place_canvas.set_cell(ri, ci, NAVE)
                    self.placed_ships.append((nome, lung, cells))
                    self.fleet_queue.pop(0)
                    break
        self.sel_idx = 0
        self.place_canvas._set_preview(set())
        self._refresh_placement_ui()

    def _refresh_placement_ui(self):
        self._rebuild_fleet_labels()
        if self.fleet_queue:
            if self.sel_idx >= len(self.fleet_queue):
                self.sel_idx = len(self.fleet_queue) - 1
            nome, lung = self.fleet_queue[self.sel_idx]
            self.lbl_nave.config(text=f"Da piazzare:\n{nome}\n{'█' * lung}  ({lung} celle)")
            self.place_canvas.ship_drag = lung
            self.btn_avvia.config(state="disabled", bg=C["green_dim"], fg=C["text_dim"])
        else:
            self.lbl_nave.config(text="✓ Flotta completa!\nPronto all'attacco.")
            self.place_canvas.ship_drag = None
            self.btn_avvia.config(state="normal", bg="#1a6e3a", fg=C["accent3"])
        self._update_orient_label()

    def _send_grid(self):
        self._send({"tipo": "griglia", "celle": self.griglia_casa.to_list()})
        self._build_game()

    # ══════════════════════════════════════════
    # SCHERMATA 3 — Partita
    # ══════════════════════════════════════════

    def _build_game(self):
        self._clear()
        self.root.geometry("1100x740")
        self._ships_hidden   = False
        self.mio_turno       = False
        self.partita_finita  = False
        self.griglia_attacco = Griglia()

        # Header
        hdr = tk.Frame(self.root, bg=C["bg2"], pady=6)
        hdr.pack(fill="x")
        hdr_l = tk.Frame(hdr, bg=C["bg2"])
        hdr_l.pack(side="left", padx=16)
        tk.Label(hdr_l, text="⚓  BATTAGLIA NAVALE",
                 font=self.font_sub, bg=C["bg2"], fg=C["accent"]).pack(anchor="w")
        self.lbl_status = tk.Label(hdr_l, text="In attesa dell'inizio...",
                                   font=self.font_small, bg=C["bg2"], fg=C["text_dim"])
        self.lbl_status.pack(anchor="w")
        hdr_r = tk.Frame(hdr, bg=C["bg2"])
        hdr_r.pack(side="right", padx=16)
        self.lbl_turn = tk.Label(hdr_r, text="",
                                 font=self.font_sub, bg=C["bg2"], fg=C["text_dim"])
        self.lbl_turn.pack(anchor="e")

        body = tk.Frame(self.root, bg=C["bg"])
        body.pack(expand=True, fill="both", padx=8, pady=4)

        # Griglia casa
        col_l = tk.Frame(body, bg=C["bg"])
        col_l.pack(side="left")
        top_l = tk.Frame(col_l, bg=C["bg"])
        top_l.pack(fill="x", pady=(0, 4))
        tk.Label(top_l, text=f"LE TUE NAVI  [ {self.nome} ]",
                 font=self.font_small, bg=C["bg"], fg=C["text_dim"]).pack(side="left")
        self.btn_hide = tk.Button(top_l, text="👁 NASCONDI",
                                  font=self.font_small, bg=C["navy"], fg=C["accent"],
                                  relief="flat", padx=8, cursor="hand2",
                                  command=self._toggle_hide_ships)
        self.btn_hide.pack(side="right")

        self.canvas_casa = GridCanvas(col_l)
        self.canvas_casa.set_grid(self.griglia_casa.celle)
        self.canvas_casa.pack()

        # Griglia attacco
        col_r = tk.Frame(body, bg=C["bg"])
        col_r.pack(side="left", padx=(8, 0))
        tk.Label(col_r, text=f"ATTACCHI SU  [ {self.nome_avv} ]",
                 font=self.font_small, bg=C["bg"], fg=C["text_dim"]).pack(pady=(0, 4))
        self.canvas_att = GridCanvas(col_r, interactive=False)
        self.canvas_att.on_click = self._fire
        self.canvas_att.pack()

        # Chat + log
        side = tk.Frame(body, bg=C["panel"], padx=8, pady=8)
        side.pack(side="left", fill="both", expand=True, padx=(8, 0))
        tk.Label(side, text="COMUNICAZIONI", font=self.font_small,
                 bg=C["panel"], fg=C["text_dim"]).pack(anchor="w")
        self.log_text = tk.Text(side, font=self.font_chat,
                                bg=C["bg"], fg=C["text"], relief="flat",
                                width=26, height=22, state="disabled",
                                wrap="word", highlightthickness=1,
                                highlightbackground=C["border"])
        self.log_text.pack(fill="both", expand=True, pady=(4, 8))
        for tag, col in [("hit", C["fire2"]), ("miss", C["water2"]),
                         ("sunk", C["accent2"]), ("chat", C["accent3"]),
                         ("system", C["text_dim"]), ("win", C["fire3"])]:
            self.log_text.tag_config(tag, foreground=col)

        chat_row = tk.Frame(side, bg=C["panel"])
        chat_row.pack(fill="x")
        self.chat_entry = tk.Entry(chat_row, font=self.font_chat,
                                   bg=C["bg3"], fg=C["accent3"],
                                   insertbackground=C["accent3"],
                                   relief="flat", highlightthickness=1,
                                   highlightcolor=C["border_hi"],
                                   highlightbackground=C["border"])
        self.chat_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.chat_entry.bind("<Return>", lambda e: self._send_chat())
        tk.Button(chat_row, text="▶", font=self.font_small,
                  bg=C["navy"], fg=C["accent3"], relief="flat",
                  padx=6, cursor="hand2",
                  command=self._send_chat).pack(side="left", padx=(4, 0))

        threading.Thread(target=self._listen_loop, daemon=True).start()
        self._log("Sistema pronto. In attesa dell'inizio partita...", "system")

    # ── toggle navi ───────────────────────────────────────────

    def _toggle_hide_ships(self):
        self._ships_hidden = not self._ships_hidden
        self.canvas_casa.hide_ships = self._ships_hidden
        self.canvas_casa.refresh_all()
        if self._ships_hidden:
            self.btn_hide.config(text="👁 MOSTRA", fg=C["accent2"])
        else:
            self.btn_hide.config(text="👁 NASCONDI", fg=C["accent"])

    # ── ascolto server ────────────────────────────────────────

    def _listen_loop(self):
        while True:
            msg = self._recv()
            if msg is None:
                self.root.after(0, lambda: self._log("⚠ Connessione persa.", "system"))
                break
            self.root.after(0, lambda m=msg: self._handle_msg(m))

    def _handle_msg(self, msg: dict):
        tipo = msg.get("tipo")
        if tipo == "inizio":
            primo = msg["turno"]
            self.mio_turno = (primo == self.nome)
            self._log(f"⚓ Partita iniziata! Inizia: {primo}", "system")
            self._update_turn_display()
            self.lbl_status.config(text="PARTITA IN CORSO", fg=C["accent3"])
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
            self.lbl_turn.config(
                text=f"🏆 {vincitore} VINCE!",
                fg=C["fire3"] if vincitore == self.nome else C["accent2"])
            self._show_end_overlay(vincitore == self.nome)
        elif tipo == "disconnessione":
            self._log(f"⚠ {msg['messaggio']}", "system")
            self.lbl_turn.config(text="AVVERSARIO DISCONNESSO", fg=C["text_dim"])
            self._show_disconnect_overlay()

    def _handle_colpo(self, msg: dict):
        r, c     = msg["riga"], msg["col"]
        esito    = msg["esito"]
        tiratore = msg["tiratore"]
        mio      = (tiratore == self.nome)
        val      = COLPITO if esito in ("colpito", "affondato") else MANCATO

        if mio:
            self.canvas_att.set_cell(r, c, val)
            self.griglia_attacco.celle[r][c] = val
            if val == COLPITO:
                self.canvas_att.spawn_explosion(r, c)
                self._log(f"💥 ({r},{c}) → {esito.upper()}!", "hit")
            else:
                self.canvas_att.spawn_splash(r, c)
                self._log(f"○  ({r},{c}) → ACQUA", "miss")
        else:
            self.canvas_casa.set_cell(r, c, val)
            self.griglia_casa.celle[r][c] = val
            if val == COLPITO:
                self.canvas_casa.spawn_explosion(r, c)
                self._log(f"🎯 {tiratore} → ({r},{c}): {esito.upper()}", "hit")
            else:
                self.canvas_casa.spawn_splash(r, c)
                self._log(f"   {tiratore} → ({r},{c}): acqua", "miss")

        if esito == "affondato":
            self._log("🚢 NAVE AFFONDATA!", "sunk")
            if mio:
                self.canvas_att.spawn_sunk(msg.get("nave", []))

    def _update_turn_display(self):
        if self.mio_turno:
            self.lbl_turn.config(text="🎯 IL TUO TURNO — FUOCO!", fg=C["accent"])
            self.canvas_att.interactive = True
        else:
            self.lbl_turn.config(text=f"⏳ Turno di {self.nome_avv}...", fg=C["text_dim"])
            self.canvas_att.interactive = False

    # ── overlay fine partita ──────────────────────────────────

    def _show_end_overlay(self, vittoria: bool):
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.configure(bg=C["bg"])
        ov.geometry("460x260+300+220")
        tk.Frame(ov, bg=C["border"], height=2).pack(fill="x")
        testo  = "⚓  VITTORIA!" if vittoria else "✗  SCONFITTA"
        colore = C["fire3"] if vittoria else C["accent2"]
        sub    = "Hai affondato tutta la flotta nemica." if vittoria else "La tua flotta è stata affondata."
        tk.Label(ov, text=testo,
                 font=tkfont.Font(family="Courier", size=26, weight="bold"),
                 bg=C["bg"], fg=colore, pady=14).pack()
        tk.Label(ov, text=sub, font=self.font_sub, bg=C["bg"], fg=C["text_dim"]).pack()
        row = tk.Frame(ov, bg=C["bg"])
        row.pack(pady=18)
        tk.Button(row, text="🏆 CLASSIFICA", font=self.font_btn,
                  bg=C["bg3"], fg=C["fire3"], relief="flat",
                  padx=12, pady=8, cursor="hand2",
                  command=lambda: [ov.destroy(), self._show_leaderboard()]).pack(side="left", padx=5)
        tk.Button(row, text="⟳ NUOVA PARTITA", font=self.font_btn,
                  bg=C["navy"], fg=C["accent"], relief="flat",
                  padx=12, pady=8, cursor="hand2",
                  command=lambda: [ov.destroy(), self._restart()]).pack(side="left", padx=5)
        tk.Button(row, text="✕ ESCI", font=self.font_btn,
                  bg=C["bg3"], fg=C["accent2"], relief="flat",
                  padx=12, pady=8, cursor="hand2",
                  command=self.root.quit).pack(side="left", padx=5)
        tk.Frame(ov, bg=C["border"], height=2).pack(fill="x", side="bottom")

    def _show_disconnect_overlay(self):
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.configure(bg=C["bg"])
        ov.geometry("420x200+320+260")
        tk.Frame(ov, bg=C["border"], height=2).pack(fill="x")
        tk.Label(ov, text="⚠  DISCONNESSIONE",
                 font=tkfont.Font(family="Courier", size=20, weight="bold"),
                 bg=C["bg"], fg=C["accent2"], pady=14).pack()
        tk.Label(ov, text="L'avversario ha abbandonato la partita.",
                 font=self.font_sub, bg=C["bg"], fg=C["text_dim"]).pack()
        row = tk.Frame(ov, bg=C["bg"])
        row.pack(pady=16)
        tk.Button(row, text="⟳ NUOVA PARTITA", font=self.font_btn,
                  bg=C["navy"], fg=C["accent"], relief="flat",
                  padx=12, pady=8, cursor="hand2",
                  command=lambda: [ov.destroy(), self._restart()]).pack(side="left", padx=5)
        tk.Button(row, text="✕ ESCI", font=self.font_btn,
                  bg=C["bg3"], fg=C["accent2"], relief="flat",
                  padx=12, pady=8, cursor="hand2",
                  command=self.root.quit).pack(side="left", padx=5)
        tk.Frame(ov, bg=C["border"], height=2).pack(fill="x", side="bottom")

    def _restart(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None
        self.nome = self.nome_avv = ""
        self.mio_turno = self.partita_finita = False
        self.griglia_casa    = Griglia()
        self.griglia_attacco = Griglia()
        self.placed_ships = []
        self.fleet_queue  = []
        self.sel_idx      = 0
        self._ships_hidden = False
        self._build_login()

    # ── azioni utente ─────────────────────────────────────────

    def _fire(self, r, c):
        if not self.mio_turno or self.partita_finita:
            return
        if self.griglia_attacco.celle[r][c] in (COLPITO, MANCATO):
            self._log("⚠ Cella già colpita!", "system")
            return
        self._send({"tipo": "colpo", "riga": r, "col": c})

    def _send_chat(self):
        testo = self.chat_entry.get().strip()
        if not testo:
            return
        self._send({"tipo": "chat", "testo": testo})
        self._log(f"[tu] {testo}", "chat")
        self.chat_entry.delete(0, "end")

    def _log(self, testo: str, tag: str = ""):
        self.log_text.config(state="normal")
        self.log_text.insert("end", testo + "\n", tag)
        self.log_text.see("end")
        self.log_text.config(state="disabled")


if __name__ == "__main__":
    BattagliaNavaleApp()