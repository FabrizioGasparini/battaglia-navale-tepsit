# ⚓ Battaglia Navale — Progetto FSL TEPSIT

Applicazione **client-server** in Python per giocare a Battaglia Navale in rete locale via **TCP**.

---

## Struttura del progetto

```
battaglia_navale/
│
├── server.py        → Gestisce la partita, i turni e le statistiche
├── client.py        → Interfaccia utente a terminale per ogni giocatore
├── game_logic.py    → Logica di gioco condivisa (griglia, colpi, vittoria)
├── statistiche.json → Creato automaticamente dopo la prima partita
└── README.md
```

---

## Requisiti

- **Python 3.10+** (usa la sintassi `list[int]` per i type hint)
- Nessuna libreria esterna richiesta (solo moduli standard: `socket`, `threading`, `json`)

---

## Come avviare il gioco

### 1. Avvia il server (una sola volta, su una macchina)

```bash
python server.py
```

Il server rimane in ascolto su `0.0.0.0:5000` e aspetta **due client**.

### 2. Avvia il client (su due terminali / macchine diverse)

```bash
python client.py
```

> Se il server è su un'altra macchina, modifica la riga in `client.py`:
> ```python
> SERVER_HOST = "192.168.x.x"   # IP del server
> ```

---

## Come si gioca

1. Inserisci il tuo nome
2. Scegli il posizionamento delle navi (manuale o automatico)
3. Aspetta che entrambi i giocatori siano pronti
4. Quando è il tuo turno, digita `<riga> <colonna>` per sparare (es. `3 5`)
5. Per mandare un messaggio in chat: `chat Ciao!`

---

## Flotta

| Nave               | Lunghezza | Quantità |
|--------------------|-----------|----------|
| Portaerei          | 5         | 1        |
| Corazzata          | 4         | 1        |
| Incrociatore       | 3         | 2        |
| Cacciatorpediniere | 2         | 3        |

---

## Funzionalità implementate

| Funzionalità                  | Stato |
|-------------------------------|-------|
| Comunicazione TCP client-server | ✅   |
| Gestione turni                | ✅    |
| Verifica colpi (acqua/colpito/affondato) | ✅ |
| Condizione di vittoria        | ✅    |
| Chat integrata tra giocatori  | ✅    |
| Salvataggio statistiche (JSON)| ✅    |
| Gestione disconnessione       | ✅    |
| Posizionamento manuale/automatico | ✅ |
| Interfaccia colorata a terminale | ✅  |

---

## Protocollo applicativo (messaggi JSON)

Tutti i messaggi sono oggetti JSON terminati da `\n`, scambiati via TCP.

| `tipo`            | Direzione       | Descrizione                              |
|-------------------|-----------------|------------------------------------------|
| `nome`            | client → server | Registrazione con il proprio nome        |
| `ok`              | server → client | Conferma connessione                     |
| `avversario`      | server → client | Nome dell'avversario connesso            |
| `richiesta_griglia` | server → client | Richiesta di invio della griglia        |
| `griglia`         | client → server | Griglia con posizione delle navi         |
| `inizio`          | server → client | Segnale di inizio partita                |
| `colpo`           | client → server | Coordinate del colpo `{riga, col}`       |
| `risultato_colpo` | server → client | Esito del colpo (acqua/colpito/affondato)|
| `turno`           | server → client | Aggiornamento del turno attivo           |
| `chat`            | bidirezionale   | Messaggio di chat `{testo}`              |
| `fine_partita`    | server → client | Fine partita con nome del vincitore      |
| `disconnessione`  | server → client | Avversario disconnesso                   |
| `errore`          | server → client | Errore generico                          |

---

## Statistiche

Dopo ogni partita, il file `statistiche.json` viene aggiornato automaticamente:

```json
{
  "Mario": { "vittorie": 3, "sconfitte": 1, "partite": 4 },
  "Luigi": { "vittorie": 1, "sconfitte": 3, "partite": 4 }
}
```

---

## Note per il colloquio orale

- **`game_logic.py`** è completamente separato dalla rete → rispetta la separazione tra logica e comunicazione
- Il server usa **`threading`**: un thread per giocatore + `threading.Lock` per accesso sicuro allo stato condiviso
- La connessione TCP garantisce **ordine** e **affidabilità** dei pacchetti (a differenza di UDP)
- La **disconnessione** viene rilevata quando `recv()` restituisce `None` o lancia un'eccezione
