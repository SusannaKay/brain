# Vision Module M1

## Cosa fa M1

- Riceve media da Telegram, crea un job in `brain.db` e genera segnali **dummy**.
- Propone un evento all'utente con conferma manuale (human-in-the-loop).
- Nessuna integrazione esterna (niente Google Calendar/Places).

## Privacy

I media **non vengono persistiti**: il bot scarica il file in `/tmp`, calcola lo SHA256 e poi elimina il file.

## Come provarlo su Telegram

1. Invia una foto o un documento al bot.
2. Il bot risponde con una card "Evento rilevato" e i pulsanti di azione.

## Pulsanti e callback

- ✅ Crea → `V1|A|<signal_id>` (stato: APPROVED → EXECUTED)
- ❌ Ignora → `V1|R|<signal_id>` (stato: REJECTED)
- ✏️ Modifica orario → `V1|M|<signal_id>|time`
- ✏️ Modifica titolo → `V1|M|<signal_id>|title`
- ✏️ Modifica luogo → `V1|M|<signal_id>|location`

Quando si modifica, il bot chiede il nuovo valore e aggiorna il payload salvato.
