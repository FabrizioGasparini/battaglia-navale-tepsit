"""
server.py - Server della Battaglia Navale
Gestisce la connessione di due client, coordina i turni e salva le statistiche.
"""

import socket
import threading
import json
import os
from datetime import datetime
from game_logic import Griglia, verifica_colpo, is_affondata, tutte_affondate

# Indirizzo e porta su cui il server si mette in ascolto
HOST = "0.0.0.0"
PORT = 50007
STATS_FILE = "statistiche.json"


# ─────────────────────────────────────────────
# Gestione statistiche (JSON)
# ─────────────────────────────────────────────

def carica_statistiche():
    """Carica le statistiche dei giocatori dal file JSON.
    Se il file non esiste restituisce un dizionario vuoto."""
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    return {}


def salva_statistiche(stats: dict):
    """Salva le statistiche aggiornate nel file JSON."""
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)


def aggiorna_stats(stats: dict, vincitore: str, perdente: str):
    """Incrementa vittorie/sconfitte per i due giocatori e salva."""
    for nome in [vincitore, perdente]:
        if nome not in stats:
            stats[nome] = {"vittorie": 0, "sconfitte": 0, "partite": 0}
    stats[vincitore]["vittorie"] += 1
    stats[vincitore]["partite"] += 1
    stats[perdente]["sconfitte"] += 1
    stats[perdente]["partite"] += 1
    salva_statistiche(stats)


# ─────────────────────────────────────────────
# Stato condiviso della partita
# ─────────────────────────────────────────────

class StatoPartita:
    """
    Contiene tutto lo stato condiviso tra i due thread dei giocatori:
    griglie, nomi, turno corrente, eventi di sincronizzazione.
    """
    def __init__(self):
        self.lock = threading.Lock()

        # Connessioni e nomi dei due giocatori (indice 0 e 1)
        self.conn = [None, None]
        self.nomi = [None, None]

        # Griglie di gioco: griglia[i] = griglia del giocatore i
        self.griglie = [None, None]

        # Flag: True quando entrambi i giocatori hanno piazzato le navi
        self.pronto = [False, False]
        self.evento_pronti = threading.Event()

        # Indice del giocatore il cui turno è attivo (0 o 1)
        self.turno = 0
        self.evento_turno = [threading.Event(), threading.Event()]

        # Risultato dell'ultimo colpo (stringa JSON)
        self.risultato_colpo = None

        # True quando la partita è finita
        self.partita_finita = False
        self.vincitore_idx = None


stato = StatoPartita()


# ─────────────────────────────────────────────
# Comunicazione con i client
# ─────────────────────────────────────────────

def invia(conn: socket.socket, msg: dict):
    """
    Serializza un dizionario in JSON e lo invia al client.
    Il messaggio è terminato da un newline per facilitare il parsing.
    """
    try:
        conn.sendall((json.dumps(msg) + "\n").encode())
    except Exception:
        pass  # La disconnessione sarà rilevata alla prossima recv


def ricevi(conn: socket.socket) -> dict | None:
    """
    Legge una riga JSON dal client e la deserializza.
    Restituisce None in caso di errore o disconnessione.
    """
    try:
        buf = b""
        while True:
            chunk = conn.recv(1)
            if not chunk:
                return None  # Client disconnesso
            if chunk == b"\n":
                break
            buf += chunk
        return json.loads(buf.decode())
    except Exception:
        return None


# ─────────────────────────────────────────────
# Thread per la chat
# ─────────────────────────────────────────────

def gestisci_chat(idx: int, msg_data: dict):
    """
    Riceve un messaggio di chat dal giocatore idx e lo inoltra all'avversario.
    Il messaggio viene arricchito con il nome del mittente e il timestamp.
    """
    avversario = 1 - idx
    if stato.conn[avversario]:
        invia(stato.conn[avversario], {
            "tipo": "chat",
            "mittente": stato.nomi[idx],
            "testo": msg_data.get("testo", ""),
            "ora": datetime.now().strftime("%H:%M")
        })


# ─────────────────────────────────────────────
# Thread principale per ogni giocatore
# ─────────────────────────────────────────────

def gestisci_giocatore(conn: socket.socket, idx: int):
    """
    Thread che gestisce tutta la comunicazione con un singolo giocatore.
    Fasi: registrazione → posizionamento navi → loop di gioco.
    """
    avversario = 1 - idx

    # ── Fase 1: ricezione del nome ──────────────────────────────
    msg = ricevi(conn)
    if not msg or msg.get("tipo") != "nome":
        conn.close()
        return

    with stato.lock:
        stato.nomi[idx] = msg["nome"]

    invia(conn, {"tipo": "ok", "messaggio": f"Benvenuto, {stato.nomi[idx]}! Attendi l'avversario..."})

    # Attendi che anche l'altro giocatore si sia connesso
    while stato.nomi[avversario] is None:
        pass  # busy-wait leggero, breve durata

    invia(conn, {"tipo": "avversario", "nome": stato.nomi[avversario]})

    # ── Fase 2: ricezione del posizionamento navi ────────────────
    invia(conn, {"tipo": "richiesta_griglia"})
    msg = ricevi(conn)
    if not msg or msg.get("tipo") != "griglia":
        gestisci_disconnessione(idx)
        return

    with stato.lock:
        stato.griglie[idx] = Griglia(msg["celle"])
        stato.pronto[idx] = True

    # Attendi che entrambi i giocatori abbiano inviato la griglia
    while not all(stato.pronto):
        pass

    invia(conn, {"tipo": "inizio", "turno": stato.nomi[stato.turno],
                 "messaggio": "La partita ha inizio!"})

    # ── Fase 3: loop di gioco ───────────────────────────────────
    while not stato.partita_finita:
        msg = ricevi(conn)
        if msg is None:
            # Il client si è disconnesso improvvisamente
            gestisci_disconnessione(idx)
            return

        tipo = msg.get("tipo")

        # Messaggio di chat: inoltrato all'avversario, non interrompe il flusso
        if tipo == "chat":
            gestisci_chat(idx, msg)
            continue

        # Colpo sparato: elaborato solo se è il turno di questo giocatore
        if tipo == "colpo":
            with stato.lock:
                if stato.turno != idx:
                    invia(conn, {"tipo": "errore", "messaggio": "Non è il tuo turno!"})
                    continue

                riga, col = msg["riga"], msg["col"]
                griglia_avv = stato.griglie[avversario]
                esito = verifica_colpo(griglia_avv, riga, col)

                risposta = {
                    "tipo": "risultato_colpo",
                    "riga": riga, "col": col,
                    "esito": esito,
                    "tiratore": stato.nomi[idx]
                }

                # Controlla se la nave è stata affondata
                if esito == "colpito":
                    nave_affondata = is_affondata(griglia_avv, riga, col)
                    if nave_affondata:
                        risposta["esito"] = "affondato"
                        risposta["nave"] = nave_affondata

                # Informa entrambi i giocatori dell'esito
                invia(stato.conn[idx], risposta)
                invia(stato.conn[avversario], risposta)

                # Controlla condizione di vittoria
                if tutte_affondate(griglia_avv):
                    stato.partita_finita = True
                    stato.vincitore_idx = idx
                    msg_fine = {
                        "tipo": "fine_partita",
                        "vincitore": stato.nomi[idx],
                        "messaggio": f"{stato.nomi[idx]} ha vinto la partita!"
                    }
                    invia(stato.conn[0], msg_fine)
                    invia(stato.conn[1], msg_fine)

                    # Aggiorna le statistiche
                    stats = carica_statistiche()
                    aggiorna_stats(stats, stato.nomi[idx], stato.nomi[avversario])
                    break

                # Passa il turno all'avversario (solo se non si è affondato)
                if risposta["esito"] == "acqua":
                    stato.turno = avversario
                    invia(stato.conn[0], {"tipo": "turno", "giocatore": stato.nomi[stato.turno]})
                    invia(stato.conn[1], {"tipo": "turno", "giocatore": stato.nomi[stato.turno]})

    conn.close()


def gestisci_disconnessione(idx: int):
    """
    Chiamata quando un client si disconnette a metà partita.
    Notifica l'avversario e chiude la sessione.
    """
    avversario = 1 - idx
    stato.partita_finita = True
    nome_disc = stato.nomi[idx] or f"Giocatore {idx+1}"
    print(f"[SERVER] {nome_disc} si è disconnesso.")
    if stato.conn[avversario]:
        invia(stato.conn[avversario], {
            "tipo": "disconnessione",
            "messaggio": f"{nome_disc} si è disconnesso. Sei il vincitore!"
        })
        stato.conn[avversario].close()


# ─────────────────────────────────────────────
# Entry point del server
# ─────────────────────────────────────────────

def main():
    """Avvia il server, accetta esattamente due client e avvia la partita."""
    global stato
    stats = carica_statistiche()
    print(f"[SERVER] In ascolto su {HOST}:{PORT}")
    print(f"[SERVER] Statistiche caricate: {len(stats)} giocatori registrati.")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        # SO_REUSEADDR evita l'errore "Address already in use" al riavvio
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((HOST, PORT))
        server_sock.listen(2)

        # Accetta il primo giocatore
        print("[SERVER] Attendo il primo giocatore...")
        conn0, addr0 = server_sock.accept()
        print(f"[SERVER] Giocatore 1 connesso da {addr0}")
        stato.conn[0] = conn0

        # Accetta il secondo giocatore
        print("[SERVER] Attendo il secondo giocatore...")
        conn1, addr1 = server_sock.accept()
        print(f"[SERVER] Giocatore 2 connesso da {addr1}")
        stato.conn[1] = conn1

        # Avvia un thread per ciascun giocatore
        t0 = threading.Thread(target=gestisci_giocatore, args=(conn0, 0), daemon=True)
        t1 = threading.Thread(target=gestisci_giocatore, args=(conn1, 1), daemon=True)
        t0.start()
        t1.start()
        t0.join()
        t1.join()

    print("[SERVER] Partita terminata.")


if __name__ == "__main__":
    main()
