# Deployment van Windows naar de Ubuntu-NUC

Deze handleiding beschrijft de volledige deployment van **Crypto Admin** vanaf de
Windows-ontwikkelcomputer naar de Ubuntu-NUC. Volg bij een eerste installatie de
hoofdstukken in de aangegeven volgorde.

## Snelstart

De onderstaande opdrachten met `intelnuc` vereisen eerst deze Windows-configuratie
in `$HOME\.ssh\config`:

```text
Host intelnuc
    HostName 192.168.2.28
    User jkpieters
```

Zonder deze configuratie gebruik je in SSH-opdrachten
`jkpieters@192.168.2.28` in plaats van `intelnuc`.

### Lokaal starten op Windows

```powershell
cd C:\Users\jkpieters\Develop\FinancialPlatform\apps\CryptoAdmin
.\start.ps1
```

Open daarna:

<http://127.0.0.1:8000>

Stop de lokale app met `Ctrl+C`.

### Reeds geïnstalleerde app starten op de NUC

Log vanaf Windows in op de NUC:

```powershell
ssh intelnuc
```

Start vervolgens de bestaande container:

```bash
sudo docker compose \
  -f /opt/apps/crypto-admin/app/deploy/compose.yaml \
  up -d
```

Controleer de status:

```bash
sudo docker compose \
  -f /opt/apps/crypto-admin/app/deploy/compose.yaml \
  ps

curl --fail http://127.0.0.1:8010/healthz
```

De healthcheck hoort `ok` terug te geven.

### Starten en opnieuw bouwen na een codewijziging

```bash
sudo docker compose \
  -f /opt/apps/crypto-admin/app/deploy/compose.yaml \
  up -d --build
```

### App vervolgens vanuit Windows openen

Open een tweede PowerShell-venster en maak een SSH-tunnel:

```powershell
ssh -N -L 8010:127.0.0.1:8010 intelnuc
```

Zonder SSH-configuratie:

```powershell
ssh -N -L 8010:127.0.0.1:8010 jkpieters@192.168.2.28
```

Laat dat venster open en bezoek:

<http://127.0.0.1:8010>

## Inhoud

1. Vaste namen en locaties
2. SSH vanaf Windows configureren
3. Docker Engine op de NUC installeren
4. Mappen op de NUC maken
5. Applicatie uploaden
6. Bestaande database uploaden
7. Container bouwen en starten
8. App vanuit Windows openen
9. Procedure voor iedere code-update
10. Dagelijks beheer
11. Databaseback-up terugzetten
12. Configuratie en secrets
13. Problemen oplossen
14. Controlelijst

## 1. Vaste namen en locaties

In deze handleiding worden deze vaste waarden gebruikt:

| Onderdeel | Waarde |
|---|---|
| Windows-project | `C:\Users\jkpieters\Develop\FinancialPlatform\apps\CryptoAdmin` |
| NUC-hostnaam | `intelnuc` |
| NUC-IP-adres | `192.168.2.28` |
| NUC-gebruiker | `jkpieters` |
| App-code op NUC | `/opt/apps/crypto-admin/app` |
| Productiedata op NUC | `/opt/apps/crypto-admin/data` |
| Database op NUC | `/opt/apps/crypto-admin/data/crypto_admin.sqlite3` |
| Compose-bestand | `/opt/apps/crypto-admin/app/deploy/compose.yaml` |
| Lokale NUC-poort | `127.0.0.1:8010` |
| Containerpoort | `8000` |
| Containergebruiker | UID/GID `10001:10001` |

De productiestructuur is:

```text
/opt/apps/crypto-admin/
├── app/                         # applicatiecode en deploymentbestanden
└── data/
    └── crypto_admin.sqlite3     # persistente productiedatabase
```

De database staat op Windows naast `db.py`. In productie wordt via Compose een
ander pad ingesteld:

```text
Windowsontwikkeling:
C:\Users\jkpieters\Develop\FinancialPlatform\apps\CryptoAdmin\crypto_admin.sqlite3

NUC:
/opt/apps/crypto-admin/data/crypto_admin.sqlite3

Container:
/var/lib/crypto-admin/crypto_admin.sqlite3
```

De database wordt nooit opgenomen in de containerimage en nooit door een
code-update overschreven.

## 2. Eenmalig: SSH vanaf Windows configureren

Open PowerShell op Windows en controleer de verbinding met het IP-adres:

```powershell
ssh jkpieters@192.168.2.28
```

Maak daarna een vaste SSH-alias:

```powershell
notepad $HOME\.ssh\config
```

Voeg dit toe en sla het bestand op:

```text
Host intelnuc
    HostName 192.168.2.28
    User jkpieters
```

Controleer de alias:

```powershell
ssh intelnuc
```

Als het IP-adres van de NUC later verandert, hoeft alleen `HostName` in dit
configuratiebestand aangepast te worden.

Controleer ook of de benodigde Windows-programma's aanwezig zijn:

```powershell
Get-Command ssh, scp, tar
```

## 3. Eenmalig: Docker Engine op de NUC installeren

Sla dit hoofdstuk over als onderstaande opdrachten al beide een versie tonen:

```bash
sudo docker --version
sudo docker compose version
```

Log vanaf Windows in:

```powershell
ssh intelnuc
```

Installeer vervolgens Docker Engine en de Docker Compose-plugin vanuit de
officiële Docker-repository:

```bash
sudo apt update
sudo apt install -y ca-certificates curl

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin

sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker compose version
```

Ubuntu 26.04 LTS en `amd64` worden door de officiële Docker Engine-packages
ondersteund. De actuele bron voor deze installatieprocedure is:

<https://docs.docker.com/engine/install/ubuntu/>

## 4. Eenmalig: mappen op de NUC maken

Voer dit uit in de SSH-sessie op de NUC:

```bash
sudo install -d -m 0755 /opt/apps

sudo install -d -m 0755 \
  -o jkpieters -g jkpieters \
  /opt/apps/crypto-admin

sudo install -d -m 0755 \
  -o jkpieters -g jkpieters \
  /opt/apps/crypto-admin/app

sudo install -d -m 0750 /opt/apps/crypto-admin/data
sudo chown 10001:10001 /opt/apps/crypto-admin/data

install -d -m 0700 /home/jkpieters/backups/crypto-admin
```

Controleer de structuur en het numerieke eigenaarschap:

```bash
stat -c '%A %u:%g %n' \
  /opt/apps/crypto-admin \
  /opt/apps/crypto-admin/app \
  /opt/apps/crypto-admin/data \
  /home/jkpieters/backups/crypto-admin
```

Voor de datamap hoort ongeveer dit zichtbaar te zijn:

```text
drwxr-x--- 10001:10001 /opt/apps/crypto-admin/data
```

De Linux-gebruiker `10001` hoeft niet op de NUC aangemaakt te worden. Dit is de
numerieke identiteit van de niet-rootgebruiker in de container.

## 5. Eerste deployment: applicatie uploaden

Open een nieuwe PowerShell in Windows:

```powershell
cd C:\Users\jkpieters\Develop\FinancialPlatform\apps\CryptoAdmin
.\deploy\copy-to-nuc.ps1
```

Het script:

1. maakt lokaal een tijdelijk `tar.gz`-archief;
2. sluit `.git`, `.agents`, Python-caches en alle `*.sqlite3`-bestanden uit;
3. uploadt het archief met `scp`;
4. pakt het uit in `/opt/apps/crypto-admin/app`;
5. verwijdert de tijdelijke archieven.

Zonder SSH-alias kan expliciet het IP-adres worden gebruikt:

```powershell
.\deploy\copy-to-nuc.ps1 -NucHost 192.168.2.28
```

Controleer op de NUC:

```powershell
ssh intelnuc
```

```bash
ls -la /opt/apps/crypto-admin/app
ls -la /opt/apps/crypto-admin/app/deploy
```

Minimaal moeten `Dockerfile`, `app.py`, `db.py`, `static/` en
`deploy/compose.yaml` aanwezig zijn.

## 6. Eerste deployment: bestaande database uploaden

Voer dit alleen uit voor de initiële ingebruikname of wanneer bewust een
database wordt teruggezet.

Upload de database vanuit Windows eerst naar de home-directory:

```powershell
cd C:\Users\jkpieters\Develop\FinancialPlatform\apps\CryptoAdmin
scp .\crypto_admin.sqlite3 intelnuc:/home/jkpieters/crypto_admin.sqlite3
```

Log daarna in op de NUC:

```powershell
ssh intelnuc
```

Plaats de database met de juiste rechten in de productiedatamap:

```bash
sudo install -m 0600 \
  /home/jkpieters/crypto_admin.sqlite3 \
  /opt/apps/crypto-admin/data/crypto_admin.sqlite3

sudo chown 10001:10001 \
  /opt/apps/crypto-admin/data/crypto_admin.sqlite3

rm /home/jkpieters/crypto_admin.sqlite3

sudo stat -c '%A %u:%g %s %n' \
  /opt/apps/crypto-admin/data/crypto_admin.sqlite3
```

Verwacht eigenaarschap:

```text
10001:10001
```

Start de container pas nadat deze stap is afgerond. Als geen bestaande database
wordt geplaatst, maakt de app bij de eerste start zelf een nieuwe database met
voorbeeldtransacties.

## 7. Eerste deployment: container bouwen en starten

Voer op de NUC uit:

```bash
sudo bash /opt/apps/crypto-admin/app/deploy/install-ubuntu.sh
```

Het script:

1. controleert de vaste deploymentlocatie;
2. controleert en corrigeert de datamap;
3. bouwt de lokale Dockerimage;
4. start de container;
5. toont de Compose-status.

Controleer daarna:

```bash
sudo docker compose \
  -f /opt/apps/crypto-admin/app/deploy/compose.yaml \
  ps

curl --fail http://127.0.0.1:8010/healthz

sudo docker compose \
  -f /opt/apps/crypto-admin/app/deploy/compose.yaml \
  logs --tail=100
```

De healthcheck moet `ok` teruggeven en de containerstatus moet na korte tijd
`healthy` zijn.

## 8. App vanuit Windows openen

Poort `8010` is uitsluitend gekoppeld aan `127.0.0.1` van de NUC. Dat voorkomt
directe toegang vanaf het LAN of internet.

Maak voor tijdelijk beheer een SSH-tunnel vanuit Windows:

```powershell
ssh -N -L 8010:127.0.0.1:8010 intelnuc
```

Laat dit PowerShell-venster open en bezoek op Windows:

<http://127.0.0.1:8010>

Stop de tunnel met `Ctrl+C`.

Bij gebruik van Cloudflare Tunnel is de origin op de NUC:

```text
http://localhost:8010
```

## 9. Vaste procedure voor iedere code-update

### Stap 1 — Tests uitvoeren op Windows

```powershell
cd C:\Users\jkpieters\Develop\FinancialPlatform\apps\CryptoAdmin
& 'C:\Users\jkpieters\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest
```

Ga alleen verder als alle tests slagen.

### Stap 2 — Nieuwe code uploaden

```powershell
.\deploy\copy-to-nuc.ps1
```

De draaiende container blijft tijdens de upload actief. De database wordt niet
meegenomen en niet gewijzigd.

### Stap 3 — Database back-uppen en nieuwe image starten

Log in:

```powershell
ssh intelnuc
```

Voer op de NUC uit:

```bash
compose_file=/opt/apps/crypto-admin/app/deploy/compose.yaml
database=/opt/apps/crypto-admin/data/crypto_admin.sqlite3
backup="$HOME/backups/crypto-admin/crypto_admin-$(date +%Y%m%d-%H%M%S).sqlite3"

sudo docker compose -f "$compose_file" stop
sudo install -m 0600 "$database" "$backup"
sudo chown jkpieters:jkpieters "$backup"
sudo docker compose -f "$compose_file" up -d --build
```

Controleer de nieuwe versie:

```bash
curl --fail http://127.0.0.1:8010/healthz
sudo docker compose -f "$compose_file" ps
sudo docker compose -f "$compose_file" logs --tail=100
```

## 10. Dagelijks beheer

Status:

```bash
sudo docker compose \
  -f /opt/apps/crypto-admin/app/deploy/compose.yaml \
  ps
```

Recente logs:

```bash
sudo docker compose \
  -f /opt/apps/crypto-admin/app/deploy/compose.yaml \
  logs --tail=100
```

Live logs:

```bash
sudo docker compose \
  -f /opt/apps/crypto-admin/app/deploy/compose.yaml \
  logs --follow
```

Herstarten:

```bash
sudo docker compose \
  -f /opt/apps/crypto-admin/app/deploy/compose.yaml \
  restart
```

Stoppen:

```bash
sudo docker compose \
  -f /opt/apps/crypto-admin/app/deploy/compose.yaml \
  down
```

Opnieuw starten zonder rebuild:

```bash
sudo docker compose \
  -f /opt/apps/crypto-admin/app/deploy/compose.yaml \
  up -d
```

## 11. Databaseback-up terugzetten

Kies eerst het gewenste back-upbestand:

```bash
ls -lh /home/jkpieters/backups/crypto-admin
```

Stop daarna de container en herstel de database:

```bash
compose_file=/opt/apps/crypto-admin/app/deploy/compose.yaml

sudo docker compose -f "$compose_file" down

sudo install -m 0600 \
  /home/jkpieters/backups/crypto-admin/NAAM-VAN-DE-BACKUP.sqlite3 \
  /opt/apps/crypto-admin/data/crypto_admin.sqlite3

sudo chown 10001:10001 \
  /opt/apps/crypto-admin/data/crypto_admin.sqlite3

sudo docker compose -f "$compose_file" up -d
curl --fail http://127.0.0.1:8010/healthz
```

Vervang `NAAM-VAN-DE-BACKUP.sqlite3` door de echte bestandsnaam.

## 12. Configuratie en secrets

De app gebruikt momenteel geen wachtwoorden, API-sleutels of andere secrets en
heeft daarom geen `.env`-bestand nodig.

Deze niet-geheime containerinstellingen staan rechtstreeks in Compose:

```yaml
CRYPTO_ADMIN_HOST: 0.0.0.0
CRYPTO_ADMIN_PORT: 8000
CRYPTO_ADMIN_DB_PATH: /var/lib/crypto-admin/crypto_admin.sqlite3
```

Wanneer later secrets worden toegevoegd, moeten die buiten de repository worden
opgeslagen, bijvoorbeeld in `/etc/apps/crypto-admin.env`. Pas dan wordt een
`env_file` aan Compose toegevoegd.

## 13. Problemen oplossen

### `Could not resolve hostname intelnuc`

Windows kan de hostnaam niet omzetten naar een IP-adres. Controleer
`$HOME\.ssh\config` of gebruik:

```powershell
.\deploy\copy-to-nuc.ps1 -NucHost 192.168.2.28
```

### `Permission denied` bij de datamap

Dit is normaal voor gebruiker `jkpieters`. De map is alleen toegankelijk voor
de containergebruiker met UID `10001` en voor `root`. Gebruik voor beheer:

```bash
sudo ls -la /opt/apps/crypto-admin/data
```

### `install: invalid user '10001'`

Gebruik voor numeriek eigenaarschap eerst `install` en daarna `chown`:

```bash
sudo install -d -m 0750 /opt/apps/crypto-admin/data
sudo chown 10001:10001 /opt/apps/crypto-admin/data
```

Maak geen Linux-gebruiker met de naam `10001`.

### App toont een nieuwe of lege database

Controleer welke map daadwerkelijk gekoppeld is:

```bash
sudo docker inspect crypto-admin \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

Verwachte koppeling:

```text
/opt/apps/crypto-admin/data -> /var/lib/crypto-admin
```

Controleer daarna:

```bash
sudo ls -la /opt/apps/crypto-admin/data
```

### Container is niet healthy

```bash
sudo docker compose \
  -f /opt/apps/crypto-admin/app/deploy/compose.yaml \
  ps

sudo docker compose \
  -f /opt/apps/crypto-admin/app/deploy/compose.yaml \
  logs --tail=200
```

### Poort `8010` is al in gebruik

```bash
sudo ss -ltnp | grep ':8010'
```

Wijzig de hostpoort alleen als dat nodig is. Pas dan zowel `deploy/compose.yaml`
als de Cloudflare-origin of SSH-tunnel aan.

## 14. Controlelijst

Een deployment is voltooid als:

- de code in `/opt/apps/crypto-admin/app` staat;
- de database in `/opt/apps/crypto-admin/data` staat;
- database en datamap eigenaar `10001:10001` hebben;
- `docker compose ps` de container als `healthy` toont;
- `curl http://127.0.0.1:8010/healthz` `ok` retourneert;
- de app via een SSH- of Cloudflare-tunnel opent;
- er vóór een update een recente databaseback-up is gemaakt.
