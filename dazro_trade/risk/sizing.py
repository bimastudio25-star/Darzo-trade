def suggested_lot_size(account_balance: float, risk_per_trade: float, entry: float, sl: float, value_per_price_unit: float = 100.0) -> float:
    distance = abs(entry - sl)
    if account_balance <= 0 or risk_per_trade <= 0 or distance <= 0 or value_per_price_unit <= 0:
        return 0.0
    risk_amount = account_balance * risk_per_trade
    return round(risk_amount / (distance * value_per_price_unit), 2)
