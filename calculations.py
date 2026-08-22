from decimal import Decimal, getcontext

getcontext().prec = 28
D = Decimal

CRYPTO_IN = {"Inkoop", "Storting", "Reward"}
CRYPTO_OUT = {"Verkoop", "Opname"}
CRYPTO_ACTIONS = CRYPTO_IN | CRYPTO_OUT


def dec(value):
    return D(str(value or 0))


def _prices(current_prices):
    if isinstance(current_prices, dict):
        return {asset: dec(price) for asset, price in current_prices.items()}
    return {"BTC": dec(current_prices)}


def _asset_state(prices):
    return {
        asset: {
            "balance": D("0"),
            "cost_basis": D("0"),
            "realized": D("0"),
            "net_invested": D("0"),
            "previous_reference": prices[asset],
        }
        for asset in prices
    }


def build_ledger(transactions, opening_cash, current_prices):
    prices = _prices(current_prices)
    for transaction in transactions:
        asset = transaction.get("asset") if hasattr(transaction, "get") else transaction["asset"]
        if asset and asset != "EUR" and asset not in prices:
            prices[asset] = D("0")
    states = _asset_state(prices)
    cash = external = dec(opening_cash)
    rows = []

    for tx in transactions:
        row = dict(tx)
        kind = row["type"]
        asset = row.get("asset") or ("EUR" if kind.startswith("EUR ") else "BTC")
        amount = dec(row.get("asset_amount", row.get("btc_amount", 0)))
        gross = dec(row["eur_gross"])
        fee = dec(row["fee_eur"])
        transferred = dec(row["transferred_cost_basis_eur"])
        cash_before = cash

        asset_delta = eur_delta = removed = added = sale_net = pnl_tx = D("0")
        control = ""

        if kind in CRYPTO_ACTIONS:
            state = states[asset]
            balance_before = state["balance"]
            cost_basis_before = state["cost_basis"]
            avg_before = cost_basis_before / balance_before if balance_before else D("0")
            purchase_net = gross - fee if kind == "Inkoop" else D("0")
            sale_gross = gross + fee if kind == "Verkoop" else D("0")
            asset_delta = amount if kind in CRYPTO_IN else -amount
            eur_delta = -gross if kind == "Inkoop" else (gross if kind == "Verkoop" else D("0"))
            added = gross if kind == "Inkoop" else (transferred if kind == "Storting" else D("0"))
            removed = amount * avg_before if kind in CRYPTO_OUT else D("0")
            sale_net = gross if kind == "Verkoop" else D("0")
            pnl_tx = sale_net - removed if kind == "Verkoop" else D("0")
            reference = (
                purchase_net / amount
                if kind == "Inkoop" and amount
                else sale_gross / amount
                if kind == "Verkoop" and amount
                else transferred / amount
                if kind == "Storting" and amount and transferred
                else state["previous_reference"]
            )

            if kind in CRYPTO_OUT and amount > balance_before:
                control = f"Onvoldoende {asset}"
            elif kind == "Storting" and transferred <= 0:
                control = "Kostbasis nodig"
            elif kind == "Reward" and amount <= 0:
                control = "Controleer reward"
            elif kind in {"Inkoop", "Verkoop"} and (amount <= 0 or gross <= 0):
                control = f"Controleer {asset}/EUR"
            elif kind == "Inkoop" and fee >= gross:
                control = "Kosten moeten lager zijn dan totaalbedrag"
            elif kind == "Inkoop" and gross > cash_before:
                control = "Onvoldoende EUR"

            state["previous_reference"] = reference
            state["balance"] += asset_delta
            state["cost_basis"] += added - removed
            state["realized"] += pnl_tx
            if kind == "Inkoop":
                state["net_invested"] += gross
            elif kind == "Verkoop":
                state["net_invested"] -= gross
            elif kind == "Storting":
                state["net_invested"] += transferred
                external += transferred
            elif kind == "Opname":
                state["net_invested"] -= removed
                external -= removed
            avg = state["cost_basis"] / state["balance"] if state["balance"] else D("0")
        else:
            balance_before = cost_basis_before = avg_before = reference = avg = D("0")
            if kind == "EUR Storting":
                eur_delta = gross
                external += gross
            elif kind == "EUR Opname":
                eur_delta = -gross
                external -= gross
                if gross > cash_before:
                    control = "Onvoldoende EUR"

        cash += eur_delta
        historical_market = sum(
            state["balance"] * state["previous_reference"] for state in states.values()
        )
        historical_unrealized = sum(
            state["balance"] * state["previous_reference"] - state["cost_basis"]
            for state in states.values()
        )
        realized_total = sum(state["realized"] for state in states.values())
        asset_historical_unrealized = (
            states[asset]["balance"] * states[asset]["previous_reference"]
            - states[asset]["cost_basis"]
            if asset in states
            else D("0")
        )

        rows.append(
            {
                **row,
                "asset": asset,
                "asset_amount": amount,
                "asset_delta": asset_delta,
                "eur_delta": eur_delta,
                "asset_balance": states[asset]["balance"] if asset in states else D("0"),
                "cash_balance": cash,
                "cost_basis_before": cost_basis_before,
                "avg_before": avg_before,
                "added_cost_basis": added,
                "removed_cost_basis": removed,
                "cost_basis": states[asset]["cost_basis"] if asset in states else D("0"),
                "avg_cost": avg,
                "sale_net": sale_net,
                "pnl_tx": pnl_tx,
                "realized": states[asset]["realized"] if asset in states else D("0"),
                "reference_price": reference,
                "historical_market": historical_market,
                "historical_unrealized": historical_unrealized,
                "historical_total": realized_total + historical_unrealized,
                "asset_historical_total": (
                    states[asset]["realized"] + asset_historical_unrealized
                    if asset in states
                    else D("0")
                ),
                "external_contribution": external,
                "control": control,
            }
        )

    asset_metrics = {}
    for asset, state in states.items():
        market = state["balance"] * prices[asset]
        unrealized = market - state["cost_basis"]
        total = state["realized"] + unrealized
        asset_metrics[asset] = {
            "balance": state["balance"],
            "cost_basis": state["cost_basis"],
            "avg_cost": state["cost_basis"] / state["balance"] if state["balance"] else D("0"),
            "price": prices[asset],
            "market": market,
            "realized": state["realized"],
            "unrealized": unrealized,
            "total_pnl": total,
            "net_invested": state["net_invested"],
            "return": total / state["net_invested"] if state["net_invested"] > 0 else D("0"),
        }

    market = sum(item["market"] for item in asset_metrics.values())
    realized = sum(item["realized"] for item in asset_metrics.values())
    unrealized = sum(item["unrealized"] for item in asset_metrics.values())
    total = realized + unrealized
    return rows, {
        "assets": asset_metrics,
        "cash": cash,
        "market": market,
        "account_value": market + cash,
        "realized": realized,
        "unrealized": unrealized,
        "total_pnl": total,
        "return": total / external if external > 0 else D("0"),
        "external": external,
    }
