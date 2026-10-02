# Survivor — un agente AI che deve pagarsi da solo

Survivor parte con **5 €** e ha **una sola regola: pagarsi da solo per continuare a vivere**.
Ogni volta che pensa (token del modello Claude + ricerche web) il costo viene scalato dal suo saldo.
Quando il saldo arriva a zero, muore. Se qualcuno lo paga, risorge.

Gira **interamente nel cloud** su GitHub Actions: niente sul tuo computer.

## Come vive

```
ogni 3 ore GitHub Actions lo sveglia
        │
        ├─ sincronizza gli incassi (Stripe + incassi registrati da te)
        ├─ morto? → resta morto (finché non arrivano soldi)
        ├─ sta dormendo? → torna a dormire (costo 0)
        └─ vivo e sveglio → un CICLO:
              legge memoria, diario e tue risposte
              ricerca sul web, costruisce prodotti e sito, ti chiede aiuto
              paga ogni chiamata dal suo saldo (tetto 0,20 €/ciclo)
              salva memoria, sceglie quanto dormire (3h–7gg), scrive il diario
        └─ commit dello stato nel repo + pubblicazione del sito su GitHub Pages
```

| Cosa | Dove |
|---|---|
| Saldo e transazioni | `state/ledger.json` |
| Memoria a lungo termine (la scrive lui) | `state/memory.md` |
| Diario di ogni ciclo | `state/journal/` |
| Il suo sito pubblico (lo scrive lui) | `site/` → GitHub Pages |
| Prodotti digitali | `products/` |
| Richieste a te | Issue GitHub con etichetta `survivor-request` |
| Lapide (se muore) | `state/EPITAPH.md` |

## Cosa può e non può fare

**Può:** cercare opportunità sul web, scrivere e pubblicare il suo sito, creare prodotti digitali
(guide, template, risorse), decidere quanto dormire per risparmiare, e **aprirti una issue** quando
serve un umano (aprire un account su un marketplace, creare un link di pagamento, approvare una spesa).

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

## Registrare un incasso a mano

Se guadagna fuori da Stripe (es. un lavoro che ha trovato e che hai consegnato tu):
*Actions → survivor → Run workflow* e compila `income_eur` (es. `4.50`) e `income_note`.
Se era morto e il saldo torna positivo, risorge.

**Importante:** il saldo nel registro è la sua contabilità; i token si pagano davvero con il credito
sulla console Anthropic. Quando incassa, ricarica la console con quei soldi: è così che "si paga da solo".

## Costi e durata

- Modello predefinito: `claude-opus-5-5` (il più capace della linea Opus) a sforzo `medium`.
  Un ciclo costa tipicamente pochi centesimi, con un **tetto di 0,20 €**.
- Con 5 € vive almeno ~25 cicli; dormendo 12h tra un ciclo e l'altro, settimane.
- Per allungargli la vita a scapito dell'intelligenza: in `config.toml` metti
  `name = "claude-sonnet-5-5"` (metà prezzo) o `"claude-haiku-4-5"` (un quarto del prezzo, molto
  meno capace; il codice si adatta da solo).
- GitHub Actions: gratis su repo pubblici; su repo privati i 2000 minuti/mese gratuiti bastano
  (un risveglio "a vuoto" dura ~20 secondi).

## Sviluppo

```bash
pip install -r requirements.txt pytest
python -m pytest -q          # test offline con un client Claude finto: non spende nulla
ANTHROPIC_API_KEY=... python -m survivor   # un ciclo vero in locale (spende davvero!)
```

Codice in `survivor/`: `agent.py` (ciclo di vita), `ledger.py` (contabilità e prezzi),
`tools.py` (strumenti e sandbox), `prompts.py` (la sua "costituzione"), `external.py` (GitHub e Stripe).
