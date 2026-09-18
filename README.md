# Crypto Rendement

Lokale Python-webapp voor een Kraken-portefeuille met dynamisch beheerde crypto-assets en EUR. De app houdt transacties, kassaldo, gemiddelde kostprijs en rendement per coin én voor de gezamenlijke portefeuille bij. BTC en ETH zijn standaard aanwezig; aanvullende assets beheer je via **Instellingen**.

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

**Koersen vernieuwen** gebruikt de publieke Kraken Spot REST Ticker voor de EUR-paren die per asset zijn ingesteld. Standaard zijn dit:

- BTC/EUR
- ETH/EUR

Bij een netwerkstoring gebruikt iedere coin zijn eigen handmatige terugvalprijs uit **Instellingen**. Daar kun je ook assets toevoegen, hun naam of Kraken-paar wijzigen en ongebruikte assets verwijderen. Een asset met gekoppelde transacties kan niet worden verwijderd. Er zijn geen Kraken API-sleutels nodig.

## Transacties

De ondersteunde transactietypen zijn voor alle beheerde crypto-assets identiek:

- Inkoop
- Verkoop
- Dust sweeping
- Storting
- Opname
- Reward

Daarnaast zijn EUR-stortingen en EUR-opnames beschikbaar.

Bij **Inkoop** is het EUR-bedrag het totaal inclusief kosten. De cryptoaankoopwaarde is totaal minus fee; kassaldo en kostbasis wijzigen met het volledige totaalbedrag.

Bij **Verkoop** is het EUR-bedrag de netto bijschrijving na kosten. De bruto verkoopwaarde is netto-opbrengst plus fee; het kassaldo stijgt met de netto-opbrengst.

Een cryptostorting vereist de oorspronkelijke historische kostbasis. Rewards krijgen in deze administratie kostbasis nul.

Bij **Dust sweeping** worden restsaldi naar EUR omgezet. Vul per ingeleverde asset de hoeveelheid, de netto EUR-opbrengst en de kosten in. Dit verlaagt de hoeveelheid en gemiddelde kostbasis, verhoogt het EUR-saldo met de netto-opbrengst en verwerkt het verschil als gerealiseerd resultaat. Een netto-opbrengst van nul is toegestaan. Bedragen kleiner dan een cent kunnen worden ingevoerd en worden met extra decimalen weergegeven.

Bij een sweep met meerdere assets verdeel je de netto-opbrengst en kosten over de betrokken assets, bijvoorbeeld naar verhouding van hun absolute `amountusd` in de Kraken-export. Zorg dat de deelbedragen exact optellen tot de gezamenlijke opbrengst en kosten. Gebruik dezelfde Kraken-`refid` in de omschrijvingen. Boek de EUR-ontvangst niet daarnaast als storting: dit zou het kassaldo en de externe inleg onterecht verhogen. Een niet-EUR-valuta zoals USD moet eerst als asset met zijn eigen saldo en historische EUR-kostbasis zijn vastgelegd.

Voorbeeld uit de aangeleverde Kraken-export: op 11 september 2026 wordt 0,0085 USD en 0,0000013466 ETH ingeleverd voor 0,0101 EUR, met 0,0003 EUR kosten. De totale netto kasmutatie is dus 0,0098 EUR. De app ondersteunt handmatige invoer; automatische Kraken-CSV-import is nog niet beschikbaar.

## Rendement

Voor iedere beheerde crypto-asset worden afzonderlijk bijgehouden:

- saldo en marktwaarde;
- gemiddelde kostprijs en resterende kostbasis;
- gerealiseerde, ongerealiseerde en totale PnL;
- rendement op de netto-inleg in de coin.

Coinrendement is totale coin-PnL gedeeld door de netto-inleg in die coin: aankopen en inkomende historische kostbasis, verminderd met netto verkoopopbrengsten en uitgaande kostbasis.

Gezamenlijke PnL is de som van BTC- en ETH-PnL. Gezamenlijk rendement is deze PnL gedeeld door de externe netto-inleg van de portefeuille. Het EUR-kassaldo telt mee in de rekeningwaarde, maar is geen PnL.

## Data en migratie

Hoeveelheden, EUR-bedragen en handmatige koersen worden als decimale tekst opgeslagen, zodat SQLite geen decimalen door binaire afronding verliest. Bewerkvelden gebruiken gewone decimale notatie (bijvoorbeeld `0.0000003166`, zonder E-notatie). Hoeveelheden en bedragen worden zonder vaste afkapgrens weergegeven; percentages en grafiekassen blijven voor leesbaarheid afgerond. Berekeningen gebruiken 60 significante cijfers; delingen zoals een gemiddelde kostprijs kunnen afronding vereisen.

Bij het openen van een oudere database worden de numerieke kolommen automatisch omgezet. Vooraf wordt eenmalig een SQLite-back-up met achtervoegsel `.pre_decimal.sqlite3` gemaakt. Reeds eerder verloren precisie kan niet uit de oude database worden hersteld.

Transacties en instellingen staan lokaal in `crypto_admin.sqlite3`. In de
container staat dit bestand in `/var/lib/crypto-admin/crypto_admin.sqlite3`; die
locatie is gekoppeld aan `/opt/apps/crypto-admin/data` op de NUC.

Bij de eerste start van de multi-coin versie wordt de bestaande BTC-database automatisch gemigreerd:

- bestaande cryptotransacties blijven BTC;
- de hoeveelheidkolom wordt generiek voor alle crypto-assets;
- vóór de migratie wordt eenmalig `crypto_admin.pre_multi_asset.sqlite3` aangemaakt.

Maak voor aanvullende back-ups een kopie van het SQLite-bestand terwijl de app niet draait.
