# Crypto Rendement

Lokale Python-webapp voor een Kraken-portefeuille met BTC, ETH en EUR. De app houdt transacties, kassaldo, gemiddelde kostprijs en rendement per coin én voor de gezamenlijke portefeuille bij.

De volledige, eenduidige procedure voor installatie en updates vanaf Windows
staat in [DEPLOYMENT.md](DEPLOYMENT.md).

## Lokaal starten op Windows

Gebruik Python 3.11 of nieuwer:

```powershell
cd "C:\Users\jkpieters\Develop\FinancialPlatform\apps\CryptoAdmin"
.\start.ps1
```

Open daarna `http://127.0.0.1:8000`. Er zijn geen externe Python-packages nodig.

## Productie op de Ubuntu-NUC

De app draait in productie als een zelfstandige Docker Compose-stack. De indeling
sluit aan op de vaste serverstructuur voor huidige en toekomstige apps:

```text
/opt/apps/crypto-admin/
├── app/                         # deze repository
└── data/
    └── crypto_admin.sqlite3     # persistente database
```

De container:

- draait als niet-rootgebruiker;
- heeft een alleen-lezen filesystem, behalve de datamap;
- start na een reboot automatisch opnieuw;
- heeft een healthcheck op `/healthz`;
- publiceert poort 8010 uitsluitend op `127.0.0.1` van de NUC.

De app heeft momenteel geen secrets en gebruikt daarom geen `.env`-bestand. De
drie containerinstellingen voor host, poort en databasepad staan expliciet in
`deploy/compose.yaml`. Als later secrets worden toegevoegd, horen die buiten Git
in bijvoorbeeld `/etc/apps/crypto-admin.env`.

Daardoor is de app niet rechtstreeks via het LAN of internet bereikbaar. Een
Cloudflare Tunnel op de NUC kan `http://localhost:8010` als origin gebruiken.

Gebruik voor zowel de eerste installatie als iedere latere update uitsluitend de
stappen in [DEPLOYMENT.md](DEPLOYMENT.md). Daar staan ook de databaseoverdracht,
startcommando's, back-up, herstelprocedure, SSH-toegang en foutoplossing.

## Koersen

**Koersen vernieuwen** gebruikt de publieke Kraken Spot REST Ticker voor:

- BTC/EUR
- ETH/EUR

Bij een netwerkstoring gebruikt iedere coin zijn eigen handmatige terugvalprijs uit **Instellingen**. Er zijn geen Kraken API-sleutels nodig.

## Transacties

De ondersteunde transactietypen zijn voor BTC en ETH identiek:

- Inkoop
- Verkoop
- Storting
- Opname
- Reward

Daarnaast zijn EUR-stortingen en EUR-opnames beschikbaar.

Bij **Inkoop** is het EUR-bedrag het totaal inclusief kosten. De cryptoaankoopwaarde is totaal minus fee; kassaldo en kostbasis wijzigen met het volledige totaalbedrag.

Bij **Verkoop** is het EUR-bedrag de netto bijschrijving na kosten. De bruto verkoopwaarde is netto-opbrengst plus fee; het kassaldo stijgt met de netto-opbrengst.

Een cryptostorting vereist de oorspronkelijke historische kostbasis. Rewards krijgen in deze administratie kostbasis nul.

## Rendement

Voor BTC en ETH worden afzonderlijk bijgehouden:

- saldo en marktwaarde;
- gemiddelde kostprijs en resterende kostbasis;
- gerealiseerde, ongerealiseerde en totale PnL;
- rendement op de netto-inleg in de coin.

Coinrendement is totale coin-PnL gedeeld door de netto-inleg in die coin: aankopen en inkomende historische kostbasis, verminderd met netto verkoopopbrengsten en uitgaande kostbasis.

Gezamenlijke PnL is de som van BTC- en ETH-PnL. Gezamenlijk rendement is deze PnL gedeeld door de externe netto-inleg van de portefeuille. Het EUR-kassaldo telt mee in de rekeningwaarde, maar is geen PnL.

## Data en migratie

Transacties en instellingen staan lokaal in `crypto_admin.sqlite3`. In de
container staat dit bestand in `/var/lib/crypto-admin/crypto_admin.sqlite3`; die
locatie is gekoppeld aan `/opt/apps/crypto-admin/data` op de NUC.

Bij de eerste start van de multi-coin versie wordt de bestaande BTC-database automatisch gemigreerd:

- bestaande cryptotransacties blijven BTC;
- de hoeveelheidkolom wordt generiek voor BTC en ETH;
- vóór de migratie wordt eenmalig `crypto_admin.pre_multi_asset.sqlite3` aangemaakt.

Maak voor aanvullende back-ups een kopie van het SQLite-bestand terwijl de app niet draait.
