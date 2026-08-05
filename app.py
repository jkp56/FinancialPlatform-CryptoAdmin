import html
import json
import math
import mimetypes
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from wsgiref.simple_server import make_server

import db
from calculations import ASSETS, CRYPTO_ACTIONS, build_ledger

ROOT = Path(__file__).parent
TYPES = ["Inkoop", "Verkoop", "Storting", "Opname", "Reward", "EUR Storting", "EUR Opname"]
KRAKEN_PAIRS = {"BTC": "XBTEUR", "ETH": "ETHEUR"}


def money(value):
    return f"€ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def crypto_amount(value):
    formatted = f"{Decimal(str(value or 0)):.12f}".rstrip("0").rstrip(".") or "0"
    whole, _, fraction = formatted.partition(".")
    return f"{whole}.{fraction.ljust(8, '0')}"


def btc(value):
    return crypto_amount(value)


def pct(value):
    return f"{float(value) * 100:.2f}%".replace(".", ",")


def esc(value):
    return html.escape(str(value or ""))


def refresh_prices():
    results = {}
    settings = db.get_settings()
    for asset, pair in KRAKEN_PAIRS.items():
        try:
            url = f"https://api.kraken.com/0/public/Ticker?pair={pair}&assetVersion=1"
            with urllib.request.urlopen(url, timeout=6) as response:
                payload = json.load(response)
            if payload.get("error"):
                raise ValueError(", ".join(payload["error"]))
            item = next(iter(payload["result"].values()))
            price = float(item["c"][0])
            db.set_setting(f"price_{asset}", price)
            db.set_setting(f"price_source_{asset}", "Kraken · laatste transactie")
            db.set_setting(f"price_updated_{asset}", datetime.now(timezone.utc).isoformat())
            results[asset] = True
        except Exception:
            db.set_setting(f"price_{asset}", settings[f"manual_price_{asset}"])
            db.set_setting(f"price_source_{asset}", "Handmatige terugvalprijs")
            results[asset] = False
    return results


def context():
    settings = db.get_settings()
    prices = {asset: settings[f"price_{asset}"] for asset in ASSETS}
    rows, metrics = build_ledger(db.get_transactions(), settings["opening_cash"], prices)
    return settings, rows, metrics


def chart_label(value):
    amount = abs(value)
    if amount == 0:
        return "€ 0"
    decimals = 0 if amount >= 10 else 1
    number = f"{amount:.{decimals}f}".replace(".", ",")
    return f'{"−" if value < 0 else ""}€ {number}'


def pnl_chart(rows):
    if not rows:
        return '<div class="chart-empty">Nog geen transacties om te tonen.</div>'
    values = [float(row["historical_total"]) for row in rows]
    raw_low = min(0, min(values))
    raw_high = max(0, max(values))
    span = max(raw_high - raw_low, 1)
    rough_step = span / 4
    magnitude = 10 ** math.floor(math.log10(rough_step))
    step = next(size * magnitude for size in (1, 2, 5, 10) if size * magnitude >= rough_step)
    low = math.floor(raw_low / step) * step
    high = math.ceil(raw_high / step) * step
    if low == high:
        high = low + step
    width, height, left, right, top, bottom = 1000, 140, 8, 992, 8, 132
    y = lambda value: top + (high - value) * (bottom - top) / (high - low)
    x = lambda index: (left + right) / 2 if len(rows) == 1 else left + index * (right - left) / (len(rows) - 1)
    coordinates = [(x(index), y(value)) for index, value in enumerate(values)]
    points = " ".join(f"{px:.1f},{py:.1f}" for px, py in coordinates)
    zero_y = y(0)
    area = f"{coordinates[0][0]:.1f},{zero_y:.1f} {points} {coordinates[-1][0]:.1f},{zero_y:.1f}"
    levels = [high - index * (high - low) / 4 for index in range(5)]
    grid = "".join(
        f'<line class="chart-gridline" x1="{left}" y1="{y(level):.1f}" x2="{right}" y2="{y(level):.1f}"/>'
        for level in levels
    )
    labels = "".join(
        f'<span style="top:{100 * y(level) / height:.1f}%">{chart_label(level)}</span>'
        for level in dict.fromkeys((high, 0, low))
    )
    markers = "".join(
        f'<circle class="chart-point" cx="{px:.1f}" cy="{py:.1f}" r="4">'
        f'<title>{esc(row["tx_date"])} · {esc(row["asset"])} {esc(row["type"])} · {esc(money(row["historical_total"]))}</title></circle>'
        for (px, py), row in zip(coordinates, rows)
    )
    first_date = datetime.strptime(rows[0]["tx_date"], "%Y-%m-%d").strftime("%d-%m-%Y")
    last_date = datetime.strptime(rows[-1]["tx_date"], "%Y-%m-%d").strftime("%d-%m-%Y")
    return (
        f'<div class="chart-plot"><div class="chart-y-labels">{labels}</div>'
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" '
        f'aria-label="Gezamenlijk PnL-verloop van {chart_label(low)} tot {chart_label(high)}">'
        '<defs><linearGradient id="pnl-area" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#2774b5" stop-opacity=".24"/>'
        '<stop offset="1" stop-color="#2774b5" stop-opacity=".03"/></linearGradient></defs>'
        f'{grid}<line class="chart-zero" x1="{left}" y1="{zero_y:.1f}" x2="{right}" y2="{zero_y:.1f}"/>'
        f'<polygon class="chart-area" points="{area}"/><polyline class="chart-line" points="{points}"/>{markers}</svg>'
        f'<div class="chart-x-labels"><span>{first_date}</span><span>{last_date}</span></div></div>'
    )


def layout(title, active, body):
    nav = [
        ("dashboard", "Dashboard", "/"),
        ("transactions", "Transacties", "/transactions"),
        ("settings", "Instellingen", "/settings"),
        ("method", "Methodiek", "/method"),
        ("checks", "Bron & controles", "/checks"),
    ]
    links = "".join(
        f'<a class="nav-link {"active" if active == key else ""}" href="{url}">{name}</a>'
        for key, name, url in nav
    )
    return f"""<!doctype html><html lang="nl"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{esc(title)} · Crypto Rendement</title>
    <link rel="stylesheet" href="/static/styles.css">
    <link rel="stylesheet" href="/static/metric-breakdown.css">
    <link rel="stylesheet" href="/static/crud.css">
    <link rel="stylesheet" href="/static/compact.css">
    <link rel="stylesheet" href="/static/method.css"></head>
    <body><aside><a class="brand" href="/"><span class="coin-mark">₿Ξ</span><b>Crypto Rendement</b>
    <small>Kraken portfolio</small></a><nav>{links}</nav>
    <div class="aside-foot">Gemiddelde kostprijsmethode<br><span>BTC · ETH · EUR</span></div></aside>
    <main class="{active}-page">{body}</main><script src="/static/app.js"></script></body></html>"""


def dashboard(settings, rows, metrics):
    pnl_breakdown = (
        '<small class="metric-breakdown">'
        f'<span><em>Gerealiseerd</em><b>{money(metrics["realized"])}</b></span>'
        f'<span><em>Ongerealiseerd</em><b>{money(metrics["unrealized"])}</b></span>'
        "</small>"
    )
    cards = [
        ("Totale rekeningwaarde", money(metrics["account_value"]), "<small>Crypto + kassaldo</small>"),
        ("Totaal PnL", money(metrics["total_pnl"]), pnl_breakdown),
        ("Totaal rendement", pct(metrics["return"]), "<small>Op externe netto-inleg</small>"),
        ("Kassaldo", money(metrics["cash"]), "<small>Beschikbaar EUR</small>"),
    ]
    card_html = "".join(
        f'<article class="metric"><span>{label}</span><strong>{value}</strong>{detail}</article>'
        for label, value, detail in cards
    )
    asset_cards = ""
    for asset in ASSETS:
        item = metrics["assets"][asset]
        asset_cards += f"""<article class="asset-summary">
        <div class="asset-summary-head"><span class="asset-badge {asset.lower()}">{asset}</span>
        <strong>{crypto_amount(item["balance"])} {asset}</strong></div>
        <dl><div><dt>Waarde</dt><dd>{money(item["market"])}</dd></div>
        <div><dt>Gem. kostprijs</dt><dd>{money(item["avg_cost"])}</dd></div>
        <div><dt>Totaal PnL</dt><dd class="{"negative" if item["total_pnl"] < 0 else "positive"}">{money(item["total_pnl"])}</dd></div>
        <div><dt>Rendement</dt><dd>{pct(item["return"])}</dd></div></dl></article>"""
    recent = "".join(
        f'<tr><td>{esc(row["tx_date"])}</td><td><span class="asset-badge mini {row["asset"].lower()}">{esc(row["asset"])}</span></td>'
        f'<td><span class="pill">{esc(row["type"])}</span></td>'
        f'<td>{crypto_amount(row["asset_delta"]) if row["asset"] in ASSETS else "–"}</td>'
        f'<td>{money(row["eur_delta"])}</td></tr>'
        for row in rows[-3:][::-1]
    )
    chart = pnl_chart(rows)
    return layout(
        "Dashboard",
        "dashboard",
        f"""<header><div><p class="eyebrow">PORTFOLIO OVERZICHT</p><h1>Dashboard</h1>
        <p>Actueel inzicht in je BTC- en ETH-posities en gezamenlijk rendement.</p></div>
        <form method="post" action="/refresh-prices"><button class="secondary">↻ Koersen vernieuwen</button></form></header>
        <section class="metrics">{card_html}</section>
        <section class="grid"><article class="panel chart"><div class="panel-head"><div>
        <h2>Gezamenlijk rendementsverloop</h2><p>Indicatief PnL op transactiemomenten · dynamische schaal</p>
        </div><strong>{money(metrics["total_pnl"])}</strong></div>{chart}</article>
        <article class="panel asset-panel"><h2>Posities per coin</h2><div class="asset-summaries">{asset_cards}</div></article></section>
        <section class="panel"><div class="panel-head"><div><h2>Laatste transacties</h2>
        <p>De meest recente mutaties</p></div><a class="text-link" href="/transactions">Alles bekijken →</a></div>
        <div class="table-wrap"><table><thead><tr><th>Datum</th><th>Coin</th><th>Type</th>
        <th>Hoeveelheid</th><th>EUR-mutatie</th></tr></thead><tbody>{recent}</tbody></table></div></section>""",
    )


def transactions(rows, form_error="", draft=None, page_error=""):
    draft = draft or {}
    selected_type = draft.get("type", TYPES[0])
    selected_asset = draft.get("asset", ASSETS[0])
    type_options = "".join(
        f'<option{" selected" if item == selected_type else ""}>{item}</option>' for item in TYPES
    )
    asset_options = "".join(
        f'<option{" selected" if item == selected_asset else ""}>{item}</option>' for item in ASSETS
    )
    value = lambda name, default="": html.escape(str(draft[name] if name in draft else default))
    is_edit = bool(draft.get("id"))
    error_html = (
        f'<div id="tx-error" class="form-error" role="alert"><b>Transactie niet opgeslagen</b>'
        f"<span>{esc(form_error)}</span></div>"
        if form_error
        else ""
    )
    page_error_html = (
        f'<div class="page-error" role="alert"><b>Wijziging niet uitgevoerd.</b> {esc(page_error)}</div>'
        if page_error
        else ""
    )
    reopen = ' data-validation-error="true"' if form_error else ""
    table_rows = []
    for row in rows:
        edit_data = esc(
            json.dumps(
                {
                    key: row[key]
                    for key in (
                        "id",
                        "tx_date",
                        "asset",
                        "type",
                        "description",
                        "asset_amount",
                        "eur_gross",
                        "fee_eur",
                        "transferred_cost_basis_eur",
                    )
                },
                ensure_ascii=False,
                default=str,
            )
        )
        actions = f"""<div class="row-actions"><button type="button" class="icon edit-transaction"
        data-transaction="{edit_data}" title="Transactie bewerken" aria-label="Transactie bewerken">✎</button>
        <form class="delete-transaction" method="post" action="/delete"><input type="hidden" name="id" value="{row['id']}">
        <button class="icon danger" title="Transactie verwijderen" aria-label="Transactie verwijderen">×</button></form></div>"""
        asset_cell = (
            f'<span class="asset-badge mini {row["asset"].lower()}">{esc(row["asset"])}</span>'
            if row["asset"] in ASSETS
            else "EUR"
        )
        table_rows.append(
            f'<tr><td>{row["id"]}</td><td>{esc(row["tx_date"])}</td><td>{asset_cell}</td>'
            f'<td><span class="pill">{esc(row["type"])}</span></td><td>{esc(row["description"])}</td>'
            f'<td>{crypto_amount(row["asset_amount"]) if row["asset"] in ASSETS else "–"}</td>'
            f'<td>{money(row["eur_gross"]) if row["eur_gross"] else "–"}</td>'
            f'<td>{money(row["fee_eur"]) if row["fee_eur"] else "–"}</td><td>{money(row["avg_cost"])}</td>'
            f'<td class="{"negative" if row["historical_total"] < 0 else "positive"}">{money(row["historical_total"])}</td>'
            f"<td>{actions}</td></tr>"
        )
    return layout(
        "Transacties",
        "transactions",
        f"""<header><div><p class="eyebrow">JOURNAAL</p><h1>Transacties</h1>
        <p>Beheer BTC-, ETH- en EUR-mutaties; alle posities worden chronologisch herberekend.</p></div>
        <button id="add-transaction" data-open="tx-dialog">+ Transactie toevoegen</button></header>{page_error_html}
        <section class="panel"><div class="table-wrap wide"><table><thead><tr><th>#</th><th>Datum</th>
        <th>Coin</th><th>Type</th><th>Omschrijving</th><th>Hoeveelheid</th><th>EUR totaal</th>
        <th>Kosten</th><th>Gem. kostprijs</th><th>Portefeuille-PnL</th><th>Acties</th></tr></thead>
        <tbody>{"".join(table_rows)}</tbody></table></div></section>
        <dialog id="tx-dialog"{reopen}><form id="tx-form" method="post" action="/transactions">
        <input type="hidden" name="id" value="{value('id')}"><div class="dialog-head"><div>
        <h2 id="tx-dialog-title">{"Transactie bewerken" if is_edit else "Nieuwe transactie"}</h2>
        <p>Velden passen zich aan het transactietype aan.</p></div>
        <button type="button" class="icon" data-close>×</button></div>{error_html}
        <div class="form-grid top-fields"><label>Type<select name="type" id="tx-type">{type_options}</select></label>
        <label data-field="asset">Coin<select name="asset" id="tx-asset">{asset_options}</select></label></div>
        <div class="form-grid"><label>Datum<input required type="date" name="tx_date"
        value="{value('tx_date', datetime.now().date())}"></label>
        <label>Omschrijving<input name="description" value="{value('description')}"
        placeholder="Bijv. periodieke aankoop"></label>
        <label data-field="amount"><span id="amount-label">Hoeveelheid</span>
        <input type="number" step="any" min="0" inputmode="decimal" name="asset_amount"
        value="{value('asset_amount')}"></label>
        <label data-field="eur"><span id="eur-label">Bedrag EUR</span>
        <input type="number" step="0.01" min="0" name="eur_gross" value="{value('eur_gross')}">
        <small id="eur-help"></small></label>
        <label data-field="fee">Kosten EUR<input type="number" step="0.01" min="0" name="fee_eur"
        value="{value('fee_eur', 0)}"></label>
        <label data-field="cost">Historische kostbasis EUR<input type="number" step="0.01" min="0"
        name="transferred_cost_basis_eur" value="{value('transferred_cost_basis_eur')}"></label></div>
        <div class="actions"><button type="button" class="secondary" data-close>Annuleren</button>
        <button id="save-transaction">{"Wijzigingen opslaan" if is_edit else "Transactie opslaan"}</button>
        </div></form></dialog>""",
    )


METHOD = [
    (
        "Crypto-inkoop",
        "BTC en ETH volgen dezelfde regels.",
        "Het totaalbedrag is inclusief fee. De cryptoaankoopwaarde is totaal minus fee. Het volledige totaalbedrag verlaagt het kassaldo en verhoogt de kostbasis van de gekozen coin.",
    ),
    (
        "Crypto-verkoop",
        "Netto-opbrengst na fee.",
        "De ingevoerde opbrengst is de netto EUR-bijschrijving. Kostbasis wordt afgeboekt tegen de gemiddelde kostprijs van de verkochte coin. Gerealiseerde PnL is netto-opbrengst minus afgeboekte kostbasis.",
    ),
    (
        "Storting en opname",
        "Overdracht zonder directe PnL.",
        "Een cryptostorting voegt de coin en de opgegeven historische kostbasis toe. Een opname verwijdert de coin en gemiddelde kostbasis. Voor iedere coin wordt afzonderlijk gecontroleerd of voldoende saldo beschikbaar is.",
    ),
    (
        "Rewards",
        "Coin zonder EUR-kasstroom.",
        "Een BTC- of ETH-reward verhoogt het coinsaldo met kostbasis nul. De actuele waarde telt daardoor volledig mee in de ongerealiseerde PnL van die coin.",
    ),
    (
        "Kostbasis per coin",
        "Gescheiden administratie voor BTC en ETH.",
        "Saldo, gemiddelde kostprijs, resterende kostbasis, gerealiseerde PnL en ongerealiseerde PnL worden per coin bijgehouden volgens de gemiddelde kostprijsmethode.",
    ),
    (
        "Rendement per coin",
        "PnL ten opzichte van netto-inleg.",
        "Coinrendement is totale coin-PnL gedeeld door de netto-inleg in die coin: aankopen en inkomende kostbasis, verminderd met netto verkoopopbrengsten en uitgaande kostbasis.",
    ),
    (
        "Gezamenlijk rendement",
        "BTC, ETH en EUR als één portefeuille.",
        "Totale PnL is de som van gerealiseerde en ongerealiseerde PnL van BTC en ETH. Totaal rendement is deze PnL gedeeld door de externe netto-inleg. Kassaldo telt mee in de rekeningwaarde, maar niet als PnL.",
    ),
    (
        "Koersen en herberekening",
        "Kraken-koers per coin.",
        "BTC/EUR en ETH/EUR worden afzonderlijk bij Kraken opgehaald, met een eigen handmatige terugvalprijs. Na toevoegen, bewerken of verwijderen worden alle transacties chronologisch opnieuw doorgerekend.",
    ),
]


def settings_page(settings):
    price_rows = "".join(
        f"""<article class="price-row"><span class="asset-badge {asset.lower()}">{asset}</span>
        <div><strong>{money(settings[f"price_{asset}"])}</strong><small>EUR per {asset}</small></div>
        <div class="price-source"><i></i>{esc(settings[f"price_source_{asset}"])}</div></article>"""
        for asset in ASSETS
    )
    return layout(
        "Instellingen",
        "settings",
        f"""<header><div><p class="eyebrow">CONFIGURATIE</p><h1>Instellingen</h1>
        <p>Koersbronnen en uitgangspunten voor de portefeuilleberekeningen.</p></div></header>
        <section class="grid settings-grid"><form class="panel form-card" method="post" action="/settings">
        <h2>Financiële instellingen</h2><label>Beginsaldo EUR<input name="opening_cash" type="number"
        step="0.01" value="{esc(settings['opening_cash'])}"><small>Saldo vóór de eerste transactie.</small></label>
        <div class="form-grid"><label>Terugvalprijs BTC/EUR<input name="manual_price_BTC" type="number"
        step="0.01" value="{esc(settings['manual_price_BTC'])}"></label>
        <label>Terugvalprijs ETH/EUR<input name="manual_price_ETH" type="number"
        step="0.01" value="{esc(settings['manual_price_ETH'])}"></label></div>
        <p class="form-hint">Deze prijzen worden alleen gebruikt als Kraken niet bereikbaar is.</p>
        <button>Instellingen opslaan</button></form>
        <article class="panel price-status"><h2>Koersstatus</h2><div class="price-rows">{price_rows}</div>
        <form method="post" action="/refresh-prices"><button class="secondary">↻ Beide koersen vernieuwen</button>
        </form></article></section>""",
    )


def method_page():
    items = "".join(
        f"""<details class="method-card"><summary><span class="method-number">{index + 1:02}</span>
        <span class="method-title"><strong>{title}</strong><small>{summary}</small></span>
        <span class="method-toggle" aria-hidden="true">+</span></summary>
        <div class="method-detail"><p>{detail}</p></div></details>"""
        for index, (title, summary, detail) in enumerate(METHOD)
    )
    return layout(
        "Methodiek",
        "method",
        f"""<header><div><p class="eyebrow">REKENMETHODE</p><h1>Methodiek</h1>
        <p>Klik op een onderwerp voor de uitwerking. Er staat steeds één toelichting open.</p></div></header>
        <section class="method-accordion">{items}</section><aside class="note method-note">
        <b>Belangrijke aanname</b><p>Gebruik bij een cryptostorting de oorspronkelijke aankoopkosten als
        historische kostbasis, niet alleen de marktwaarde op de transferdatum.</p></aside>""",
    )


def checks_page(rows, metrics, settings):
    checks = [("Aantal transacties", len(rows), "SQLite")]
    for asset in ASSETS:
        asset_rows = [row for row in rows if row["asset"] == asset]
        checks.extend(
            [
                (f"{asset} gekocht", crypto_amount(sum((row["asset_amount"] for row in asset_rows if row["type"] == "Inkoop"), Decimal("0"))), asset),
                (f"{asset} gestort", crypto_amount(sum((row["asset_amount"] for row in asset_rows if row["type"] == "Storting"), Decimal("0"))), asset),
                (f"{asset} rewards", crypto_amount(sum((row["asset_amount"] for row in asset_rows if row["type"] == "Reward"), Decimal("0"))), asset),
                (f"{asset} eindsaldo", crypto_amount(metrics["assets"][asset]["balance"]), asset),
            ]
        )
    checks.append(("Huidig kassaldo", money(metrics["cash"]), "EUR"))
    table_rows = "".join(
        f'<tr><td>{label}</td><td>{value}</td><td>{unit}</td><td><span class="status">OK</span></td></tr>'
        for label, value, unit in checks
    )
    return layout(
        "Bron & controles",
        "checks",
        f"""<header><div><p class="eyebrow">AUDIT</p><h1>Bron & controles</h1>
        <p>Controle van BTC, ETH, EUR en de gezamenlijke modeluitkomsten.</p></div></header>
        <section class="grid checks-grid"><article class="panel"><h2>Modelcontroles</h2>
        <div class="table-wrap checks-table"><table><thead><tr><th>Maatstaf</th><th>Model</th>
        <th>Eenheid</th><th>Status</th></tr></thead><tbody>{table_rows}</tbody></table></div></article>
        <article class="panel position"><h2>Gezamenlijke uitkomst</h2><dl>
        <div><dt>Cryptomarktwaarde</dt><dd>{money(metrics["market"])}</dd></div>
        <div><dt>Gerealiseerde PnL</dt><dd>{money(metrics["realized"])}</dd></div>
        <div><dt>Ongerealiseerde PnL</dt><dd>{money(metrics["unrealized"])}</dd></div>
        <div><dt>Totale PnL</dt><dd>{money(metrics["total_pnl"])}</dd></div>
        <div><dt>Totaal rendement</dt><dd>{pct(metrics["return"])}</dd></div></dl></article></section>
        <aside class="note"><b>Bronnen</b><p>Transacties staan lokaal in SQLite. Actuele BTC/EUR- en
        ETH/EUR-koersen komen uit de publieke Kraken Spot REST Ticker; per coin is een terugvalprijs beschikbaar.</p></aside>""",
    )


def parse_post(environ):
    length = int(environ.get("CONTENT_LENGTH") or 0)
    return {
        key: value[0]
        for key, value in urllib.parse.parse_qs(environ["wsgi.input"].read(length).decode()).items()
    }


def redirect(start, path):
    start("303 See Other", [("Location", path)])
    return [b""]


def decimal_field(data, name):
    raw = str(data.get(name) or "0").strip().replace(",", ".")
    try:
        value = Decimal(raw)
    except Exception as exc:
        raise ValueError(f"Vul bij {name} een geldig getal in.") from exc
    if not value.is_finite() or value < 0:
        raise ValueError("Bedragen en cryptohoeveelheden mogen niet negatief zijn.")
    return value


def transaction_values(data):
    kind = data.get("type")
    if kind not in TYPES:
        raise ValueError("Ongeldig transactietype.")
    tx_date = data.get("tx_date", "")
    try:
        datetime.strptime(tx_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Vul een geldige transactiedatum in.") from exc
    is_crypto = kind in CRYPTO_ACTIONS
    asset = data.get("asset", "BTC") if is_crypto else "EUR"
    if is_crypto and asset not in ASSETS:
        raise ValueError("Kies BTC of ETH.")
    asset_amount = decimal_field(data, "asset_amount") if is_crypto else Decimal("0")
    eur_gross = (
        decimal_field(data, "eur_gross")
        if kind in {"Inkoop", "Verkoop", "EUR Storting", "EUR Opname"}
        else Decimal("0")
    )
    fee_eur = decimal_field(data, "fee_eur") if kind in {"Inkoop", "Verkoop"} else Decimal("0")
    transferred = (
        decimal_field(data, "transferred_cost_basis_eur")
        if kind == "Storting"
        else Decimal("0")
    )
    return {
        "tx_date": tx_date,
        "asset": asset,
        "type": kind,
        "description": data.get("description", "").strip(),
        "asset_amount": str(asset_amount),
        "eur_gross": str(eur_gross),
        "fee_eur": str(fee_eur),
        "transferred_cost_basis_eur": str(transferred),
    }


def ledger_validation_error(transactions):
    settings = db.get_settings()
    prices = {asset: settings[f"price_{asset}"] for asset in ASSETS}
    rows, _ = build_ledger(
        sorted(transactions, key=lambda transaction: (transaction["tx_date"], int(transaction["id"]))),
        settings["opening_cash"],
        prices,
    )
    return next((row for row in rows if row["control"]), None)


def transaction_validation_error(values, transaction_id=""):
    kind = values["type"]
    asset = values["asset"]
    amount = Decimal(values["asset_amount"])
    gross = Decimal(values["eur_gross"])
    fee = Decimal(values["fee_eur"])
    transferred = Decimal(values["transferred_cost_basis_eur"])
    if kind in CRYPTO_ACTIONS and amount <= 0:
        return f"Vul een {asset}-hoeveelheid groter dan nul in."
    if kind in {"Inkoop", "Verkoop", "EUR Storting", "EUR Opname"} and gross <= 0:
        return "Vul een EUR-bedrag groter dan nul in."
    if kind == "Storting" and transferred <= 0:
        return f"Vul de historische kostbasis van de gestorte {asset} in."
    if kind == "Inkoop" and fee >= gross:
        return "De kosten moeten lager zijn dan het totaalbedrag."
    existing = [dict(row) for row in db.get_transactions()]
    if transaction_id:
        try:
            candidate_id = int(transaction_id)
        except ValueError:
            return "Ongeldig transactienummer."
        if not any(int(row["id"]) == candidate_id for row in existing):
            return "De te bewerken transactie bestaat niet meer."
        prospective = [
            {**values, "id": candidate_id} if int(row["id"]) == candidate_id else row
            for row in existing
        ]
    else:
        candidate_id = max((int(row["id"]) for row in existing), default=0) + 1
        prospective = [*existing, {**values, "id": candidate_id}]
    invalid = ledger_validation_error(prospective)
    if not invalid:
        return ""
    if int(invalid["id"]) == candidate_id:
        return invalid["control"] + "."
    return (
        f'Door deze wijziging wordt transactie #{invalid["id"]} ongeldig: '
        f'{invalid["control"].lower()}.'
    )


def deletion_validation_error(transaction_id):
    try:
        deleted_id = int(transaction_id)
    except (TypeError, ValueError):
        return "Ongeldig transactienummer."
    existing = [dict(row) for row in db.get_transactions()]
    if not any(int(row["id"]) == deleted_id for row in existing):
        return "De transactie bestaat niet meer."
    invalid = ledger_validation_error(
        [row for row in existing if int(row["id"]) != deleted_id]
    )
    return (
        f'Hierdoor wordt transactie #{invalid["id"]} ongeldig: {invalid["control"].lower()}.'
        if invalid
        else ""
    )


def html_response(start, page, status="200 OK"):
    body = page.encode()
    start(
        status,
        [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body)))],
    )
    return [body]


def application(environ, start):
    path = environ["PATH_INFO"]
    if path == "/healthz":
        body = b"ok"
        start(
            "200 OK",
            [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))],
        )
        return [body]
    if path.startswith("/static/"):
        file = ROOT / path.lstrip("/")
        if file.is_file():
            start(
                "200 OK",
                [("Content-Type", mimetypes.guess_type(file)[0] or "application/octet-stream")],
            )
            return [file.read_bytes()]
    if environ["REQUEST_METHOD"] == "POST":
        data = parse_post(environ)
        if path == "/refresh-prices":
            refresh_prices()
            return redirect(start, environ.get("HTTP_REFERER", "/"))
        if path == "/settings":
            db.set_setting("opening_cash", data.get("opening_cash", 0))
            for asset in ASSETS:
                db.set_setting(f"manual_price_{asset}", data.get(f"manual_price_{asset}", 0))
            return redirect(start, "/settings")
        if path == "/delete":
            error = deletion_validation_error(data.get("id"))
            if error:
                _, rows, _ = context()
                return html_response(
                    start, transactions(rows, page_error=error), "422 Unprocessable Entity"
                )
            db.delete_transaction(data.get("id"))
            return redirect(start, "/transactions")
        if path == "/transactions":
            try:
                values = transaction_values(data)
                error = transaction_validation_error(values, data.get("id", ""))
            except ValueError as exc:
                values = None
                error = str(exc)
            if error:
                _, rows, _ = context()
                draft = {**data, **(values or {})}
                return html_response(
                    start, transactions(rows, error, draft), "422 Unprocessable Entity"
                )
            if data.get("id"):
                db.update_transaction(data["id"], values)
            else:
                db.create_transaction(values)
            return redirect(start, "/transactions")
    settings, rows, metrics = context()
    page = (
        dashboard(settings, rows, metrics)
        if path == "/"
        else transactions(rows)
        if path == "/transactions"
        else settings_page(settings)
        if path == "/settings"
        else method_page()
        if path == "/method"
        else checks_page(rows, metrics, settings)
        if path == "/checks"
        else None
    )
    if page is None:
        start("404 Not Found", [("Content-Type", "text/plain")])
        return [b"Niet gevonden"]
    return html_response(start, page)


def run_server(server_factory=make_server):
    db.init_db()
    host = os.environ.get("CRYPTO_ADMIN_HOST", "127.0.0.1")
    port = int(os.environ.get("CRYPTO_ADMIN_PORT", "8000"))
    server = server_factory(host, port, application)
    print(f"Crypto Rendement draait op http://{host}:{port}")
    print("Druk op Ctrl+C om netjes af te sluiten.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCrypto Rendement is gestopt.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
