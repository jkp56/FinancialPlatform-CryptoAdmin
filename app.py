import html
import json
import math
import mimetypes
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from wsgiref.simple_server import make_server

import db
from calculations import CRYPTO_ACTIONS, build_ledger

ROOT = Path(__file__).parent
APP_VERSION = "1.0.0"
TYPES = ["Inkoop", "Verkoop", "Dust sweeping", "Storting", "Opname", "Reward", "EUR Storting", "EUR Opname"]


NUMBER_FIELDS = {"asset_amount", "eur_gross", "fee_eur", "transferred_cost_basis_eur"}


def decimal_text(value):
    return format(Decimal(str(value or 0)), "f")


def form_value(value):
    try:
        return decimal_text(value) if value != "" else ""
    except Exception:
        return str(value)


def money(value):
    amount = Decimal(str(value or 0))
    return f"€ {amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def signed_money(value):
    amount = Decimal(str(value or 0))
    if not amount:
        return "–"
    return f'{"+" if amount > 0 else "−"} {money(abs(amount))}'


def crypto_amount(value):
    formatted = decimal_text(value)
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    whole, _, fraction = formatted.partition(".")
    return f"{whole}.{fraction.ljust(8, '0')}"


def btc(value):
    return crypto_amount(value)


def pct(value):
    return f"{Decimal(str(value)) * 100:.2f}%".replace(".", ",")


def esc(value):
    return html.escape(str(value or ""))


def refresh_prices():
    results = {}
    settings = db.get_settings()
    for item in db.get_assets():
        asset, pair = item["symbol"], item["kraken_pair"]
        try:
            url = f"https://api.kraken.com/0/public/Ticker?pair={pair}&assetVersion=1"
            with urllib.request.urlopen(url, timeout=6) as response:
                payload = json.load(response)
            if payload.get("error"):
                raise ValueError(", ".join(payload["error"]))
            item = next(iter(payload["result"].values()))
            price = decimal_text(item["c"][0])
            db.set_setting(f"price_{asset}", price)
            db.set_setting(f"price_source_{asset}", "Kraken · laatste transactie")
            db.set_setting(f"price_updated_{asset}", datetime.now(timezone.utc).isoformat())
            results[asset] = True
        except Exception:
            db.set_setting(f"price_{asset}", item["manual_price"])
            db.set_setting(f"price_source_{asset}", "Handmatige terugvalprijs")
            results[asset] = False
    return results


def context():
    settings = db.get_settings()
    assets = db.get_assets()
    prices = {
        item["symbol"]: settings.get(f'price_{item["symbol"]}', item["manual_price"])
        for item in assets
    }
    rows, metrics = build_ledger(db.get_transactions(), settings["opening_cash"], prices)
    return settings, assets, rows, metrics


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


def layout(title, active, body, assets=()):
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
    <link rel="stylesheet" href="/static/styles.css?v={APP_VERSION}">
    <link rel="stylesheet" href="/static/metric-breakdown.css?v={APP_VERSION}">
    <link rel="stylesheet" href="/static/crud.css?v={APP_VERSION}">
    <link rel="stylesheet" href="/static/compact.css?v={APP_VERSION}">
    <link rel="stylesheet" href="/static/method.css?v={APP_VERSION}"></head>
    <body><aside><a class="brand" href="/"><span class="coin-mark">₿Ξ</span><b>Crypto Rendement</b>
    <small>Kraken portfolio · v{APP_VERSION}</small></a><nav>{links}</nav>
    <div class="aside-foot">Gemiddelde kostprijsmethode<br><span>{" · ".join([*(item["symbol"] for item in assets), "EUR"])}</span></div></aside>
    <main class="{active}-page">{body}</main><script src="/static/app.js?v={APP_VERSION}"></script></body></html>"""


def dashboard(settings, assets, rows, metrics):
    symbols = [item["symbol"] for item in assets]
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
    for asset in symbols:
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
        f'<td>{crypto_amount(row["asset_delta"]) if row["asset"] in symbols else "–"}</td>'
        f'<td>{money(row["eur_delta"])}</td></tr>'
        for row in rows[-3:][::-1]
    )
    chart = pnl_chart(rows)
    return layout(
        "Dashboard",
        "dashboard",
        f"""<header><div><p class="eyebrow">PORTFOLIO OVERZICHT</p><h1>Dashboard</h1>
        <p>Actueel inzicht in je cryptoposities en gezamenlijk rendement.</p></div>
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
        assets,
    )


def transactions(assets, rows, form_error="", draft=None, page_error=""):
    draft = draft or {}
    symbols = [item["symbol"] for item in assets]
    selected_type = draft.get("type", TYPES[0])
    selected_asset = draft.get("asset", symbols[0] if symbols else "")
    type_options = "".join(
        f'<option{" selected" if item == selected_type else ""}>{item}</option>' for item in TYPES
    )
    asset_options = "".join(
        f'<option{" selected" if item == selected_asset else ""}>{item}</option>' for item in symbols
    )
    filter_asset_options = "".join(
        f'<option value="{esc(item)}">{esc(item)}</option>' for item in [*symbols, "EUR"]
    )
    filter_type_options = "".join(
        f'<option value="{esc(item)}">{esc(item)}</option>' for item in TYPES
    )
    value = lambda name, default="": html.escape(
        form_value(draft.get(name, default)) if name in NUMBER_FIELDS else str(draft.get(name, default))
    )
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
    for row in reversed(rows):
        edit_data = esc(
            json.dumps(
                {
                    key: decimal_text(row[key]) if key in NUMBER_FIELDS else row[key]
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
            if row["asset"] in symbols
            else "EUR"
        )
        table_rows.append(
            f'<tr data-transaction-row data-asset="{esc(row["asset"])}" data-type="{esc(row["type"])}">'
            f'<td>{row["id"]}</td><td>{esc(row["tx_date"])}</td><td>{asset_cell}</td>'
            f'<td><span class="pill">{esc(row["type"])}</span></td><td>{esc(row["description"])}</td>'
            f'<td>{crypto_amount(row["asset_amount"]) if row["asset"] in symbols else "–"}</td>'
            f'<td class="{"negative" if row["eur_delta"] < 0 else "positive" if row["eur_delta"] > 0 else ""}">'
            f'{signed_money(row["eur_delta"])}</td>'
            f'<td>{money(row["fee_eur"]) if row["fee_eur"] else "–"}</td><td>{money(row["avg_cost"])}</td>'
            f'<td class="{"negative" if row["historical_total"] < 0 else "positive"}">{money(row["historical_total"])}</td>'
            f"<td>{actions}</td></tr>"
        )
    return layout(
        "Transacties",
        "transactions",
        f"""<header><div><p class="eyebrow">JOURNAAL</p><h1>Transacties</h1>
        <p>Beheer crypto- en EUR-mutaties; alle posities worden chronologisch herberekend.</p></div>
        <button id="add-transaction" data-open="tx-dialog">+ Transactie toevoegen</button></header>{page_error_html}
        <section class="panel"><div class="transaction-toolbar" aria-label="Transacties filteren">
        <div class="transaction-filters"><label>Coin<select id="transaction-filter-asset">
        <option value="">Alle coins</option>{filter_asset_options}</select></label>
        <label>Type<select id="transaction-filter-type"><option value="">Alle types</option>
        {filter_type_options}</select></label>
        <button type="button" class="secondary" id="transaction-filter-clear">Filters wissen</button></div>
        <p class="filter-status" id="transaction-filter-status" aria-live="polite">{len(rows)} transacties</p></div>
        <div class="table-wrap wide"><table id="transaction-table"><thead><tr><th>#</th><th>Datum</th>
        <th>Coin</th><th>Type</th><th>Omschrijving</th><th>Hoeveelheid</th><th>EUR-kasmutatie</th>
        <th>Kosten</th><th>Gem. kostprijs</th><th>Portefeuille-PnL</th><th>Acties</th></tr></thead>
        <tbody>{"".join(table_rows)}<tr id="transaction-filter-empty" hidden><td colspan="11">
        Geen transacties gevonden voor deze filters.</td></tr></tbody></table></div></section>
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
        <input type="number" step="any" min="0" name="eur_gross" value="{value('eur_gross')}">
        <small id="eur-help"></small></label>
        <label data-field="fee">Kosten EUR<input type="number" step="any" min="0" name="fee_eur"
        value="{value('fee_eur', 0)}"></label>
        <label data-field="cost">Historische kostbasis EUR<input type="number" step="any" min="0"
        name="transferred_cost_basis_eur" value="{value('transferred_cost_basis_eur')}"></label></div>
        <div class="actions"><button type="button" class="secondary" data-close>Annuleren</button>
        <button id="save-transaction">{"Wijzigingen opslaan" if is_edit else "Transactie opslaan"}</button>
        </div></form></dialog>""",
        assets,
    )


METHOD = [
    (
        "EUR-opname",
        "Totaalbedrag inclusief kosten.",
        "Het totaalbedrag verlaagt het Kraken-kassaldo. De bank ontvangt het totaal minus de kosten: bij €200 met €1 kosten is dat €199. Alleen de netto bankontvangst verlaagt de externe inleg; de kosten verlagen de gerealiseerde portefeuille-PnL, zonder toewijzing aan een coin.",
    ),
    (
        "Dust sweeping",
        "Kleine restsaldi omzetten naar EUR.",
        "Boek per ingeleverde asset een dust sweeping met de hoeveelheid, het eigen aandeel in de netto EUR-opbrengst en de kosten. De kostbasis wordt afgeboekt en het verschil met de netto-opbrengst is gerealiseerde PnL. Verdeel bij meerdere assets de opbrengst en kosten; boek de EUR-ontvangst niet nogmaals als storting. Bedragen kleiner dan een cent en een netto-opbrengst van nul zijn toegestaan.",
    ),
    (
        "Crypto-inkoop",
        "Alle beheerde assets volgen dezelfde regels.",
        "Het totaalbedrag is de volledige kasuitstroom inclusief fee. De handelswaarde exclusief fee is totaal minus kosten. Het volledige totaalbedrag verlaagt het kassaldo en verhoogt de kostbasis van de gekozen coin.",
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
        "Een crypto-reward verhoogt het coinsaldo met kostbasis nul. De actuele waarde telt daardoor volledig mee in de ongerealiseerde PnL van die coin.",
    ),
    (
        "Kostbasis per coin",
        "Gescheiden administratie voor iedere asset.",
        "Saldo, gemiddelde kostprijs, resterende kostbasis, gerealiseerde PnL en ongerealiseerde PnL worden per coin bijgehouden volgens de gemiddelde kostprijsmethode.",
    ),
    (
        "Rendement per coin",
        "PnL ten opzichte van netto-inleg.",
        "Coinrendement is totale coin-PnL gedeeld door de netto-inleg in die coin: aankopen en inkomende kostbasis, verminderd met netto verkoopopbrengsten en uitgaande kostbasis.",
    ),
    (
        "Gezamenlijk rendement",
        "Alle crypto-assets en EUR als één portefeuille.",
        "Totale PnL is de som van gerealiseerde en ongerealiseerde PnL van alle assets, verminderd met EUR-opnamekosten. Totaal rendement is deze PnL gedeeld door de externe netto-inleg. Kassaldo telt mee in de rekeningwaarde, maar niet als PnL.",
    ),
    (
        "Koersen en herberekening",
        "Kraken-koers per coin.",
        "De geconfigureerde EUR-paren worden afzonderlijk bij Kraken opgehaald, met een eigen handmatige terugvalprijs. Na toevoegen, bewerken of verwijderen worden alle transacties chronologisch opnieuw doorgerekend.",
    ),
]


def settings_page(settings, assets, asset_error=""):
    price_rows = "".join(
        f"""<article class="price-row"><span class="asset-badge {item['symbol'].lower()}">{item['symbol']}</span>
        <div><strong>{money(settings.get(f"price_{item['symbol']}", item['manual_price']))}</strong>
        <small>EUR per {item['symbol']}</small></div>
        <div class="price-source"><i></i>{esc(settings.get(f"price_source_{item['symbol']}", 'Handmatige terugvalprijs'))}</div></article>"""
        for item in assets
    )
    asset_rows = "".join(
        f"""<div class="asset-manage-row"><form class="asset-update-form" method="post" action="/assets/update">
        <input type="hidden" name="symbol" value="{esc(item['symbol'])}">
        <label>Symbool<input value="{esc(item['symbol'])}" disabled></label>
        <label>Naam<input name="name" maxlength="50" required value="{esc(item['name'])}"></label>
        <label>Kraken-paar<input name="kraken_pair" maxlength="20" required value="{esc(item['kraken_pair'])}"></label>
        <label>Terugvalprijs EUR<input name="manual_price" type="number" step="any" min="0"
        required value="{esc(decimal_text(item['manual_price']))}"></label>
        <button class="secondary">Opslaan</button></form>
        <form class="delete-asset" method="post" action="/assets/delete">
        <input type="hidden" name="symbol" value="{esc(item['symbol'])}">
        <button class="icon danger" title="Asset verwijderen" aria-label="{esc(item['symbol'])} verwijderen">×</button></form></div>"""
        for item in assets
    )
    error_html = (
        f'<div class="page-error" role="alert"><b>Asset niet gewijzigd.</b> {esc(asset_error)}</div>'
        if asset_error else ""
    )
    return layout(
        "Instellingen",
        "settings",
        f"""<header><div><p class="eyebrow">CONFIGURATIE</p><h1>Instellingen</h1>
        <p>Beheer assets, koersbronnen en uitgangspunten voor de portefeuilleberekeningen.</p></div></header>{error_html}
        <section class="grid settings-grid"><form class="panel form-card" method="post" action="/settings">
        <h2>Financiële instellingen</h2><label>Beginsaldo EUR<input name="opening_cash" type="number"
        step="any" value="{esc(decimal_text(settings['opening_cash']))}"><small>Saldo vóór de eerste transactie.</small></label>
        <button>Instellingen opslaan</button></form>
        <article class="panel price-status"><h2>Koersstatus</h2><div class="price-rows">{price_rows}</div>
        <form method="post" action="/refresh-prices"><button class="secondary">↻ Alle koersen vernieuwen</button>
        </form></article></section>
        <section class="panel asset-management"><div class="panel-head"><div><h2>Crypto-assets</h2>
        <p>Het Kraken-paar is de ticker-code die voor de EUR-koers wordt gebruikt.</p></div></div>
        <div class="asset-manage-list">{asset_rows}</div>
        <form class="asset-add-form" method="post" action="/assets/create"><h3>Asset toevoegen</h3>
        <div class="form-grid"><label>Symbool<input name="symbol" maxlength="10" required placeholder="SOL"></label>
        <label>Naam<input name="name" maxlength="50" required placeholder="Solana"></label>
        <label>Kraken-paar<input name="kraken_pair" maxlength="20" required placeholder="SOLEUR"></label>
        <label>Terugvalprijs EUR<input name="manual_price" type="number" step="any" min="0" required></label></div>
        <button>Asset toevoegen</button></form></section>""",
        assets,
    )


def method_page(assets):
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
        assets,
    )


def checks_page(assets, rows, metrics, settings):
    checks = [("Aantal transacties", len(rows), "SQLite")]
    for asset in (item["symbol"] for item in assets):
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
        <p>Controle van alle crypto-assets, EUR en de gezamenlijke modeluitkomsten.</p></div></header>
        <section class="grid checks-grid"><article class="panel"><h2>Modelcontroles</h2>
        <div class="table-wrap checks-table"><table><thead><tr><th>Maatstaf</th><th>Model</th>
        <th>Eenheid</th><th>Status</th></tr></thead><tbody>{table_rows}</tbody></table></div></article>
        <article class="panel position"><h2>Gezamenlijke uitkomst</h2><dl>
        <div><dt>Cryptomarktwaarde</dt><dd>{money(metrics["market"])}</dd></div>
        <div><dt>Gerealiseerde PnL</dt><dd>{money(metrics["realized"])}</dd></div>
        <div><dt>Ongerealiseerde PnL</dt><dd>{money(metrics["unrealized"])}</dd></div>
        <div><dt>Totale PnL</dt><dd>{money(metrics["total_pnl"])}</dd></div>
        <div><dt>Totaal rendement</dt><dd>{pct(metrics["return"])}</dd></div></dl></article></section>
        <aside class="note"><b>Bronnen</b><p>Transacties en assets staan lokaal in SQLite. Actuele
        EUR-koersen komen uit de publieke Kraken Spot REST Ticker; per coin is een terugvalprijs beschikbaar.</p></aside>""",
        assets,
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


def asset_values(data, creating=False):
    symbol = str(data.get("symbol", "")).strip().upper()
    name = str(data.get("name", "")).strip()
    pair = str(data.get("kraken_pair", "")).strip().upper().replace("/", "")
    manual_price = decimal_field(data, "manual_price")
    if not re.fullmatch(r"[A-Z0-9]{2,10}", symbol):
        raise ValueError("Gebruik een symbool van 2 tot 10 letters of cijfers.")
    if symbol == "EUR":
        raise ValueError("EUR is gereserveerd voor het kassaldo.")
    if not name or len(name) > 50:
        raise ValueError("Vul een naam van maximaal 50 tekens in.")
    if not re.fullmatch(r"[A-Z0-9.]{3,20}", pair):
        raise ValueError("Vul een geldig Kraken-paar in, bijvoorbeeld SOLEUR.")
    if manual_price <= 0:
        raise ValueError("De terugvalprijs moet groter dan nul zijn.")
    if creating and db.get_asset(symbol):
        raise ValueError(f"Asset {symbol} bestaat al.")
    return {
        "symbol": symbol,
        "name": name,
        "kraken_pair": pair,
        "manual_price": decimal_text(manual_price),
    }


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
    asset = data.get("asset", "") if is_crypto else "EUR"
    symbols = {item["symbol"] for item in db.get_assets()}
    if is_crypto and asset not in symbols:
        raise ValueError("Kies een bestaande crypto-asset.")
    asset_amount = decimal_field(data, "asset_amount") if is_crypto else Decimal("0")
    eur_gross = (
        decimal_field(data, "eur_gross")
        if kind in {"Inkoop", "Verkoop", "Dust sweeping", "EUR Storting", "EUR Opname"}
        else Decimal("0")
    )
    fee_eur = decimal_field(data, "fee_eur") if kind in {"Inkoop", "Verkoop", "Dust sweeping", "EUR Opname"} else Decimal("0")
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
        "asset_amount": decimal_text(asset_amount),
        "eur_gross": decimal_text(eur_gross),
        "fee_eur": decimal_text(fee_eur),
        "transferred_cost_basis_eur": decimal_text(transferred),
    }


def ledger_validation_error(transactions):
    settings = db.get_settings()
    prices = {
        item["symbol"]: settings.get(f'price_{item["symbol"]}', item["manual_price"])
        for item in db.get_assets()
    }
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
    if kind == "EUR Opname" and fee > gross:
        return "De kosten mogen niet hoger zijn dan het totaalbedrag."
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
            return redirect(start, "/settings")
        if path in {"/assets/create", "/assets/update", "/assets/delete"}:
            try:
                symbol = str(data.get("symbol", "")).strip().upper()
                if path == "/assets/create":
                    db.create_asset(asset_values(data, creating=True))
                elif path == "/assets/update":
                    if not db.get_asset(symbol):
                        raise ValueError("De asset bestaat niet meer.")
                    db.update_asset(symbol, asset_values(data))
                else:
                    if len(db.get_assets()) <= 1:
                        raise ValueError("Er moet minimaal één crypto-asset blijven bestaan.")
                    count = db.asset_transaction_count(symbol)
                    if count:
                        raise ValueError(
                            f"{symbol} kan niet worden verwijderd omdat er {count} transactie(s) aan gekoppeld zijn."
                        )
                    if not db.delete_asset(symbol):
                        raise ValueError("De asset bestaat niet meer.")
            except ValueError as exc:
                settings, assets, _, _ = context()
                return html_response(
                    start, settings_page(settings, assets, str(exc)), "422 Unprocessable Entity"
                )
            return redirect(start, "/settings")
        if path == "/delete":
            error = deletion_validation_error(data.get("id"))
            if error:
                _, assets, rows, _ = context()
                return html_response(
                    start, transactions(assets, rows, page_error=error), "422 Unprocessable Entity"
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
                _, assets, rows, _ = context()
                draft = {**data, **(values or {})}
                return html_response(
                    start, transactions(assets, rows, error, draft), "422 Unprocessable Entity"
                )
            if data.get("id"):
                db.update_transaction(data["id"], values)
            else:
                db.create_transaction(values)
            return redirect(start, "/transactions")
    settings, assets, rows, metrics = context()
    page = (
        dashboard(settings, assets, rows, metrics)
        if path == "/"
        else transactions(assets, rows)
        if path == "/transactions"
        else settings_page(settings, assets)
        if path == "/settings"
        else method_page(assets)
        if path == "/method"
        else checks_page(assets, rows, metrics, settings)
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
