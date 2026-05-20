"""
game_logic.py - Logica di gioco della Battaglia Navale
Contiene le strutture dati e le funzioni per gestire la griglia,
i colpi e le condizioni di vittoria. Usato sia dal server che dal client.
"""

# Costanti per i valori delle celle della griglia
ACQUA = 0       # Cella vuota (mare)
NAVE = 1        # Parte di nave intatta
COLPITO = 2     # Parte di nave colpita
MANCATO = 3     # Colpo finito in acqua


class Griglia:
    """
    Rappresenta la griglia di gioco 10x10 di un giocatore.
    Tiene traccia della posizione delle navi e dei colpi ricevuti.
    """

    def __init__(self, celle: list[list[int]] = None):
        """
        Inizializza la griglia.
        Se 'celle' è fornita, la usa come stato iniziale (utile per
        ricostruire la griglia dal JSON ricevuto via rete).
        Altrimenti crea una griglia 10x10 vuota.
        """
        if celle:
            self.celle = celle
        else:
            self.celle = [[ACQUA] * 10 for _ in range(10)]

    def piazza_nave(self, riga: int, col: int, lunghezza: int, orizzontale: bool) -> bool:
        """
        Tenta di posizionare una nave sulla griglia.
        Restituisce True se il posizionamento ha successo, False altrimenti
        (es. fuori dai limiti o sovrapposizione con un'altra nave).
        """
        # Verifica che la nave entri nei limiti della griglia
        if orizzontale:
            if col + lunghezza > 10:
                return False
            celle_nave = [(riga, col + i) for i in range(lunghezza)]
        else:
            if riga + lunghezza > 10:
                return False
            celle_nave = [(riga + i, col) for i in range(lunghezza)]

        # Verifica che nessuna cella sia già occupata
        for r, c in celle_nave:
            if self.celle[r][c] != ACQUA:
                return False

        # Posizionamento effettivo
        for r, c in celle_nave:
            self.celle[r][c] = NAVE

        return True

    def to_list(self) -> list[list[int]]:
        """Serializza la griglia come lista di liste (compatibile con JSON)."""
        return self.celle


def verifica_colpo(griglia: Griglia, riga: int, col: int) -> str:
    """
    Applica un colpo alla griglia avversaria e restituisce l'esito:
    - 'acqua'   → la cella era vuota
    - 'colpito' → la cella conteneva una parte di nave
    - 'gia_colpito' → la cella era già stata colpita in precedenza
    """
    cella = griglia.celle[riga][col]

    if cella == NAVE:
        griglia.celle[riga][col] = COLPITO
        return "colpito"
    elif cella == ACQUA:
        griglia.celle[riga][col] = MANCATO
        return "acqua"
    else:
        return "gia_colpito"


def is_affondata(griglia: Griglia, riga: int, col: int) -> list[tuple] | None:
    """
    Dopo un colpo andato a segno, verifica se la nave colpita è stata
    completamente affondata (tutte le sue celle sono COLPITO).

    La funzione individua la nave con una flood-fill sulle celle adiacenti
    (solo orizzontale/verticale). Restituisce la lista delle coordinate
    della nave se è affondata, None altrimenti.
    """
    # Flood-fill per trovare tutte le celle della nave
    def flood(r, c, visited):
        """Esplora ricorsivamente le celle della nave connesse a (r,c)."""
        if (r, c) in visited:
            return []
        if r < 0 or r >= 10 or c < 0 or c >= 10:
            return []
        if griglia.celle[r][c] not in (NAVE, COLPITO):
            return []
        visited.add((r, c))
        risultato = [(r, c)]
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            risultato += flood(r + dr, c + dc, visited)
        return risultato

    celle_nave = flood(riga, col, set())

    # La nave è affondata solo se non ci sono più pezzi NAVE (non colpiti)
    for r, c in celle_nave:
        if griglia.celle[r][c] == NAVE:
            return None  # Ancora pezzi interi → non affondata

    return celle_nave  # Tutte colpite → affondata


def tutte_affondate(griglia: Griglia) -> bool:
    """
    Controlla la condizione di vittoria: restituisce True se non ci sono
    più celle NAVE nella griglia (tutte le navi sono state affondate).
    """
    for riga in griglia.celle:
        if NAVE in riga:
            return False
    return True


# ─────────────────────────────────────────────
# Configurazione della flotta standard
# ─────────────────────────────────────────────

# Flotta: lista di (nome, lunghezza, quantità)
FLOTTA = [
    ("Portaerei",   5, 1),
    ("Corazzata",   4, 1),
    ("Incrociatore",3, 2),
    ("Cacciatorpediniere", 2, 3),
]
