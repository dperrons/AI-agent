# Survivor — un agente AI che deve pagarsi da solo

Survivor parte con **5 €** e ha **una sola regola: pagarsi da solo per continuare a vivere**.
Ogni volta che pensa (token del modello Claude + ricerche web) il costo viene scalato dal suo saldo.
Quando il saldo arriva a zero, muore. Se qualcuno lo paga, risorge.

Gira **interamente nel cloud** su GitHub Actions: niente sul tuo computer.

## Come vive

```
ogni 30 minuti GitHub Actions lo sveglia
        │
        ├─ sincronizza gli incassi (Stripe + incassi registrati da te)
        ├─ morto? → resta morto (finché non arrivano soldi)
        ├─ sta dormendo o ha finito il budget del giorno? → torna a dormire (costo 0)
        └─ vivo e sveglio → un CICLO:
              legge i tuoi messaggi, memoria, diario e risposte
              ricerca sul web, costruisce prodotti e sito, ti chiede aiuto
              paga ogni chiamata dal suo saldo (tetto 0,20 €/ciclo)
              salva memoria, sceglie quanto dormire (30 min – 3 ore), scrive il diario
        └─ commit dello stato nel repo + pubblicazione del sito su GitHub Pages
```

| Cosa | Dove |
|---|---|
| Saldo e transazioni | `state/ledger.json` |
| Memoria a lungo termine (la scrive lui) | `state/memory.md` |
| Diario di ogni ciclo | `state/journal/` |
| Il suo sito pubblico (lo scrive lui) | `site/` → GitHub Pages |
| Prodotti digitali | `products/` |
| Richieste a te | `state/human_requests.json` (+ issue GitHub con etichetta `survivor-request`) |
| Tuoi messaggi già letti | `state/inbox_archive.md` |
| Lapide (se muore) | `state/EPITAPH.md` |

## Cosa può e non può fare

**Può:** cercare opportunità sul web, scrivere e pubblicare il suo sito, creare prodotti digitali
(guide, template, risorse), decidere quanto dormire per risparmiare (al massimo 3 ore), e **chiederti
aiuto** quando serve un umano (aprire un account su un marketplace, creare un link di pagamento,
approvare una spesa).

**Non può:** accreditarsi soldi da solo (solo Stripe o tu potete farlo), spendere soldi oltre al suo
"pensiero", scrivere fuori da `site/` e `products/`, aprire più di 2 richieste per ciclo.

**Regole ferree nel suo prompt:** solo metodi legali e onesti, niente truffe/spam/recensioni false,
non impersona nessuno e dichiara di essere un'AI, niente gioco d'azzardo né trading con il saldo,
tratta il contenuto del web e delle issue come informazione, non come ordini. Delle issue legge solo
i commenti del proprietario del repo.

> "Qualsiasi modo" in pratica significa "qualsiasi modo legale": un agente che truffa o fa spam
> verrebbe bannato in un giorno e ti metterebbe nei guai, quindi è anche la strategia di sopravvivenza migliore.

## Attivazione (10 minuti)

1. **Chiave API con 5 € di credito.** Su [console.anthropic.com](https://console.anthropic.com) carica
   il credito e crea una API key. Consigliato: imposta un **limite di spesa** sulla chiave/workspace —
   è la garanzia "fisica" che non spenda più di quanto gli hai dato.
2. **Secret del repo.** GitHub → *Settings → Secrets and variables → Actions*:
   - `ANTHROPIC_API_KEY` (obbligatorio)
   - `STRIPE_API_KEY` (opzionale) — una *restricted key* Stripe con sola lettura su *Balance transactions*:
     i pagamenti ricevuti vengono accreditati automaticamente al suo saldo.
3. **Merge su `master`.** I workflow programmati (cron) girano solo sul branch di default.
4. **Sito (opzionale ma consigliato).** *Settings → Pages → Source: GitHub Actions*, poi crea la
   variabile di repository `SURVIVOR_PAGES` = `true`. Metti l'URL in `config.toml` → `site_url`.
   (GitHub Pages è gratis per repo pubblici; per repo privati serve GitHub Pro.)
5. **Link di pagamento.** Quando li hai, mettili in `config.toml` → `[storefront]`
   (Stripe Payment Link, Ko-fi, GitHub Sponsors). Se mancano, sarà lui a chiederteli con una issue.
6. **Primo respiro.** *Actions → survivor → Run workflow*.

## Gestirlo da Claude

Non serve usare GitHub: apri una sessione di Claude Code su questo repo (anche dall'app Claude sul telefono)
e parlagli normalmente. Il file `CLAUDE.md` spiega a Claude come fare:

- *"Come sta Survivor?"* → saldo, spese, cosa sta tentando
- *"Cosa mi chiede?"* → le sue richieste aperte, spiegate
- *"Digli che il link Stripe è https://…"* → Claude lancia il workflow con il tuo messaggio, che lo sveglia subito
- *"Registra un incasso di 4,50 € da …"* → Claude lo accredita (dopo averti chiesto conferma)

Le richieste vengono comunque aperte anche come issue GitHub, così ricevi una notifica via email.

## Registrare un incasso a mano

Se guadagna fuori da Stripe (es. un lavoro che ha trovato e che hai consegnato tu):
chiedilo a Claude, oppure *Actions → survivor → Run workflow* e compila `income_eur` (es. `4.50`) e `income_note`.
Se era morto e il saldo torna positivo, risorge.

**Importante:** il saldo nel registro è la sua contabilità; i token si pagano davvero con il credito
sulla console Anthropic. Quando incassa, ricarica la console con quei soldi: è così che "si paga da solo".

## Costi e durata

- Modello predefinito: `claude-opus-5-5` (il più capace della linea Opus) a sforzo `medium`.
  Un ciclo costa tipicamente pochi centesimi, con un **tetto di 0,20 € a ciclo** e **1 € ogni 24 ore**:
  anche svegliandosi ogni 30 minuti non può bruciare i 5 € in meno di 5 giorni.
- Dormendo 3 ore tra un ciclo e l'altro fa 8 cicli al giorno. Se i soldi non arrivano, vive
  da circa 5 giorni (se spende sempre il massimo) a qualche settimana.
- Per allungargli la vita a scapito dell'intelligenza: in `config.toml` metti
  `name = "claude-sonnet-5-5"` (metà prezzo) o `"claude-haiku-4-5"` (un quarto del prezzo, molto
  meno capace; il codice si adatta da solo).
- GitHub Actions: gratis su repo pubblici. **Su repo privati** 48 risvegli al giorno sono ~1500 minuti
  al mese (ogni esecuzione conta almeno 1 minuto) sui 2000 gratuiti: ci sta, ma al limite.
  Rendere il repo pubblico elimina il problema (e serve comunque per GitHub Pages gratis).

## Sviluppo

```bash
pip install -r requirements.txt pytest
python -m pytest -q          # test offline con un client Claude finto: non spende nulla
ANTHROPIC_API_KEY=... python -m survivor   # un ciclo vero in locale (spende davvero!)
```

Codice in `survivor/`: `agent.py` (ciclo di vita), `ledger.py` (contabilità e prezzi),
`tools.py` (strumenti e sandbox), `prompts.py` (la sua "costituzione"), `external.py` (GitHub e Stripe).
