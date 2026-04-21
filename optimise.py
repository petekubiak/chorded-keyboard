#!/usr/env python3
import sqlite3
import random
import math
from itertools import combinations
from collections import defaultdict

DB_PATH = "key_counts.db"

PRIMARY = "asetniop"
MAX_CHORD_SIZE = 3
ANNEAL_STEPS = 250_000

# Finger indices: 0..7
FINGER_NAMES = ["kA", "kS", "kE", "kT", "kN", "kI", "kO", "kP"]

FINGER_WEAKNESS = {
    0: 2,  # LP
    1: 1,  # LR
    2: 0,  # LM
    3: 0,  # LI
    4: 0,  # RI
    5: 0,  # RM
    6: 1,  # RR
    7: 2,  # RP
}

THUMB_SYMBOLS = {
    "space",
    "enter",
    "backspace",
    "tab",
    "esc",
    "shift",
    "ctrl",
    "alt",
    "cmd",
    "delete",
}


def popcount(x: int) -> int:
    return x.bit_count()


def mask_to_fingers(mask: int) -> str:
    return "+".join(FINGER_NAMES[i] for i in range(8) if mask & (1 << i))


def generate_chords(max_size: int):
    masks = []
    for r in range(1, max_size + 1):
        for combo in combinations(range(8), r):
            m = 0
            for f in combo:
                m |= 1 << f
            masks.append(m)
    return masks


# ---- Load DB ----


def load_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT key, count FROM key_counts")
    freq = defaultdict(int)
    for raw_key, count in cur.fetchall():
        key = normalise_key(raw_key)
        if key is not None:
            freq[key] += count

    cur.execute("SELECT bigram, count FROM bigram_counts")
    bigram_counts = defaultdict(int)
    for raw_bg, c in cur.fetchall():
        a, b = raw_bg.split(" ", 1)
        na = normalise_key(a)
        nb = normalise_key(b)

        if na is not None and nb is not None:
            bigram_counts[(na, nb)] += c

    conn.close()
    return freq, bigram_counts


# ---- Cost model ----


def per_symbol_cost(mask: int) -> float:
    cost = 0.0
    cost += 0.02 * popcount(mask)  # chord size
    for i in range(8):
        if mask & (1 << i):
            cost += 0.01 * FINGER_WEAKNESS[i]
    return cost


def transition_cost(a: int, b: int) -> float:
    overlap = popcount(a & b)
    cost = 0.0
    if overlap:
        cost += 1.0 * overlap
    cost += 0.01 * (popcount(a) + popcount(b))
    return cost


def total_score(mapping, freq, bigrams):
    score = 0.0

    for s, mask in mapping.items():
        score += freq.get(s, 0) * per_symbol_cost(mask)

    for (a, b), cnt in bigrams.items():
        if a in mapping and b in mapping:
            score += cnt * transition_cost(mapping[a], mapping[b])

    return score


# ---- Optimisation ----


def anneal(symbols, chords, fixed, freq, bigrams):
    mapping = dict(fixed)

    free_syms = [s for s in symbols if s not in fixed]
    free_chords = [c for c in chords if c not in fixed.values()]

    random.shuffle(free_syms)
    for s, c in zip(free_syms, free_chords):
        mapping[s] = c

    best = dict(mapping)
    best_score = total_score(mapping, freq, bigrams)
    curr_score = best_score

    for step in range(ANNEAL_STEPS):
        t = 5 * (0.01 / 5) ** (step / ANNEAL_STEPS)

        a, b = random.sample(free_syms, 2)
        mapping[a], mapping[b] = mapping[b], mapping[a]

        new_score = total_score(mapping, freq, bigrams)
        delta = new_score - curr_score

        if delta < 0 or random.random() < math.exp(-delta / max(1e-9, t)):
            curr_score = new_score
            if new_score < best_score:
                best_score = new_score
                best = dict(mapping)
        else:
            mapping[a], mapping[b] = mapping[b], mapping[a]

    return best


def clash_stats(mapping, bigrams):
    clash_count = 0
    total = 0
    clash_freq = defaultdict(int)
    for (a, b), cnt in bigrams.items():
        if a in mapping and b in mapping:
            if popcount(mapping[a] & mapping[b]) > 0:
                clash_count += cnt
                clash_freq[(a, b)] = cnt
            total += cnt
    print(f"\nClash bigrams: {clash_count} / {total} ({clash_count/total:.2%})")
    print("Top clashing bigrams:")
    for (a, b), cnt in sorted(clash_freq.items(), key=lambda x: -x[1])[:10]:
        print(f"{a}->{b}: {cnt}")


def normalise_key(sym: str) -> str | None:
    """
    Convert raw pynput-style key names into a canonical symbol.

    Examples:
      'shift+E'     -> 'e'
      'shift+}'     -> '}'
      'ctrl+shift+a'-> 'a'
      'a'           -> 'a'
      'space'       -> 'space'
    """
    if not sym:
        return None

    # Take the last token only (strip modifiers)
    if "+" in sym:
        sym = sym.split("+")[-1]

    # Named special keys we keep
    if sym in {"space", "enter", "tab", "backspace"}:
        return sym

    # Letters: collapse case
    if len(sym) == 1 and sym.isalpha():
        return sym.lower()

    # Single-character symbols: keep as-is
    if len(sym) == 1:
        return sym

    # Everything else gets dropped (mods, fn keys, etc)
    return None


# ---- Main ----


def main():
    (freq, bigrams) = load_db()
    print(freq)

    symbols = sorted(s for s in freq if s not in THUMB_SYMBOLS and len(s) == 1)

    chords = generate_chords(MAX_CHORD_SIZE)

    fixed = {ch: (1 << i) for i, ch in enumerate(PRIMARY)}

    mapping = anneal(symbols, chords, fixed, freq, bigrams)

    print("\n=== Optimised chord layout ===\n")

    def key_order(item):
        sym, mask = item
        return (popcount(mask), -freq.get(sym, 0))

    for sym, mask in sorted(mapping.items(), key=key_order):
        print(f"{sym:>3} -> {mask_to_fingers(mask):<15}  freq={freq.get(sym,0)}")

    clash_stats(mapping, bigrams)


if __name__ == "__main__":
    main()
