import numpy as np


def detect_fvg(df):
    out = []
    for i in range(2, len(df)):
        if df["l"].iloc[i] > df["h"].iloc[i - 2]:
            out.append({"type": "bullish_fvg", "top": df["l"].iloc[i], "bot": df["h"].iloc[i - 2]})
        if df["h"].iloc[i] < df["l"].iloc[i - 2]:
            out.append({"type": "bearish_fvg", "top": df["l"].iloc[i - 2], "bot": df["h"].iloc[i]})
    return out[-5:]


def detect_ifvg(df, price, pip):
    out = []
    for fvg in detect_fvg(df):
        touched = ((df["l"] <= fvg["top"]) & (df["h"] >= fvg["bot"]))
        if touched.any():
            typ = "bearish_ifvg" if fvg["type"].startswith("bullish") else "bullish_ifvg"
            mid = (fvg["top"] + fvg["bot"]) / 2
            out.append({"type": typ, "top": fvg["top"], "bot": fvg["bot"], "distance_pips": round(abs(price - mid) / pip, 1)})
    return out[-5:]


def detect_ob(df):
    out = []
    for i in range(3, len(df)):
        body = abs(df["c"].iloc[i] - df["o"].iloc[i])
        rng = max(df["h"].iloc[i] - df["l"].iloc[i], 1e-9)
        strong = body / rng > 0.6
        if not strong:
            continue
        prev = i - 1
        if df["c"].iloc[i] > df["o"].iloc[i] and df["c"].iloc[prev] < df["o"].iloc[prev]:
            out.append({"type": "bullish_ob", "top": df["h"].iloc[prev], "bot": df["l"].iloc[prev]})
        if df["c"].iloc[i] < df["o"].iloc[i] and df["c"].iloc[prev] > df["o"].iloc[prev]:
            out.append({"type": "bearish_ob", "top": df["h"].iloc[prev], "bot": df["l"].iloc[prev]})
    return out[-4:]


def detect_crt(df):
    if len(df) < 5:
        return None
    ref, sweep, curr = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    if sweep["h"] > ref["h"] and curr["c"] < ref["h"]:
        return {"type": "bearish_crt", "swept": ref["h"], "range_high": ref["h"], "range_low": ref["l"]}
    if sweep["l"] < ref["l"] and curr["c"] > ref["l"]:
        return {"type": "bullish_crt", "swept": ref["l"], "range_high": ref["h"], "range_low": ref["l"]}
    return None


def detect_bos_choch(df, trend):
    sh, sl = [], []
    for i in range(2, len(df) - 2):
        if df["h"].iloc[i] > df["h"].iloc[i - 1] and df["h"].iloc[i] > df["h"].iloc[i + 1]: sh.append(df["h"].iloc[i])
        if df["l"].iloc[i] < df["l"].iloc[i - 1] and df["l"].iloc[i] < df["l"].iloc[i + 1]: sl.append(df["l"].iloc[i])
    last = df["c"].iloc[-1]
    out = []
    if sh and last > sh[-1]: out.append({"type": "bullish_bos", "level": sh[-1], "choch": trend == "bearish"})
    if sl and last < sl[-1]: out.append({"type": "bearish_bos", "level": sl[-1], "choch": trend == "bullish"})
    return out


def detect_sweep(df, pip):
    out = []
    for i in range(5, len(df)):
        w = df.iloc[i - 5:i]
        eq_h = w[abs(w["h"] - w["h"].mean()) < pip * 0.5]["h"].mean()
        eq_l = w[abs(w["l"] - w["l"].mean()) < pip * 0.5]["l"].mean()
        c = df.iloc[i]
        if not np.isnan(eq_h) and c["h"] > eq_h and c["c"] < eq_h: out.append({"type": "bearish_sweep", "level": round(eq_h, 2)})
        if not np.isnan(eq_l) and c["l"] < eq_l and c["c"] > eq_l: out.append({"type": "bullish_sweep", "level": round(eq_l, 2)})
    return out[-3:]


def detect_bts_stb(df, ob_or_fvg):
    out = []
    for i in range(3, len(df) - 1):
        prev3 = df.iloc[i - 3:i]
        bull3 = all(prev3["c"] > prev3["o"])
        bear3 = all(prev3["c"] < prev3["o"])
        inv_bear = df["c"].iloc[i] < df["o"].iloc[i]
        inv_bull = df["c"].iloc[i] > df["o"].iloc[i]
        near_zone = len(ob_or_fvg) > 0
        if bull3 and inv_bear and near_zone: out.append({"type": "bts", "zone": df["c"].iloc[i], "strength": 3})
        if bear3 and inv_bull and near_zone: out.append({"type": "stb", "zone": df["c"].iloc[i], "strength": 3})
    return out[-3:]


def h1_bias(df):
    if len(df) < 20:
        return "neutral"
    highs = df["h"].rolling(5).max()
    lows = df["l"].rolling(5).min()
    hh, hl = highs.iloc[-1] > highs.iloc[-6], lows.iloc[-1] > lows.iloc[-6]
    lh, ll = highs.iloc[-1] < highs.iloc[-6], lows.iloc[-1] < lows.iloc[-6]
    if hh and hl: return "bullish"
    if lh and ll: return "bearish"
    return "neutral"


def detect_alchemist(df_h1):
    ref = df_h1[df_h1["time"].dt.hour == 13].tail(1)
    c14 = df_h1[df_h1["time"].dt.hour == 14].tail(1)
    c15 = df_h1[df_h1["time"].dt.hour == 15].tail(1)
    if ref.empty or c14.empty or c15.empty:
        return {"triggered": False}
    rh, rl = ref["h"].iloc[0], ref["l"].iloc[0]
    d = None
    if c14["c"].iloc[0] > rh: d = "BUY"
    if c14["c"].iloc[0] < rl: d = "SELL"
    tapped = c15["l"].iloc[0] <= rh and c15["h"].iloc[0] >= rl
    return {"direction": d, "zone_top": rh, "zone_bot": rl, "triggered": bool(d and tapped)}


def find_reverse_levels(direction, price, ob_h1, fvg_m15, fvg_m5, df_h1, df_m15, pip, crt=None, entry_ob=None):
    candidates = []
    liq_level = None
    liq_type = ""
    if direction == "BUY":
        for ob in ob_h1:
            if ob.get("type") == "bearish_ob" and ob.get("top", 0) > price:
                candidates.append((ob["top"], "OB H1 bearish"))
        for fvg in (fvg_m15 or []) + (fvg_m5 or []):
            if fvg.get("type") == "bearish_fvg" and fvg.get("top", 0) > price:
                candidates.append((fvg["top"], "FVG bearish"))
        rev = min(candidates, key=lambda x: x[0]) if candidates else (None, "")
        w = df_m15.tail(10)
        highs = w["h"].tolist() if len(w) else []
        for i in range(len(highs)-1):
            for j in range(i+1, len(highs)):
                if abs(highs[i]-highs[j]) <= pip*0.5 and highs[i] > price:
                    liq_level, liq_type = highs[i], "equal highs"
                    break
        inv_opts = []
        if crt and crt.get("range_low") is not None: inv_opts.append(crt["range_low"])
        if entry_ob and entry_ob.get("bot") is not None: inv_opts.append(entry_ob["bot"])
        inv = min(inv_opts) if inv_opts else None
    else:
        for ob in ob_h1:
            if ob.get("type") == "bullish_ob" and ob.get("bot", 0) < price:
                candidates.append((ob["bot"], "OB H1 bullish"))
        for fvg in (fvg_m15 or []) + (fvg_m5 or []):
            if fvg.get("type") == "bullish_fvg" and fvg.get("bot", 0) < price:
                candidates.append((fvg["bot"], "FVG bullish"))
        rev = max(candidates, key=lambda x: x[0]) if candidates else (None, "")
        w = df_m15.tail(10)
        lows = w["l"].tolist() if len(w) else []
        for i in range(len(lows)-1):
            for j in range(i+1, len(lows)):
                if abs(lows[i]-lows[j]) <= pip*0.5 and lows[i] < price:
                    liq_level, liq_type = lows[i], "equal lows"
                    break
        inv_opts = []
        if crt and crt.get("range_high") is not None: inv_opts.append(crt["range_high"])
        if entry_ob and entry_ob.get("top") is not None: inv_opts.append(entry_ob["top"])
        inv = max(inv_opts) if inv_opts else None
    return {
        "reverse_level": rev[0],
        "reverse_reason": rev[1],
        "invalidation_level": inv,
        "liquidity_level": liq_level,
        "liquidity_type": liq_type,
    }
