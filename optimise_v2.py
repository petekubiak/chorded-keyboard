#!/usr/bin/env python3
"""
Optimise a chorded keyboard layout from unigram and bigram counts.

Compared with the original script, this version:
  * does NOT pin single-finger chords to ASETNIOP by default
  * uses a richer ergonomic model for individual chords
  * uses a richer transition model for bigrams
  * uses a greedy seed + simulated annealing with O(neighbourhood) swap scoring
  * keeps thumb / special keys out of the optimiser by default

Expected SQLite schema (same as the previous script):
    key_counts(key TEXT, count INTEGER)
    bigram_counts(bigram TEXT, count INTEGER)    # e.g. 't h'
"""

from __future__ import annotations

import argparse
import re
import math
import random
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import DefaultDict, Dict, Iterable, List, Tuple

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------

DB_PATH = "key_counts.db"
MAX_CHORD_SIZE = 3
ANNEAL_STEPS = 300_000
SEED = 1

# Finger indices: 0..7
# 0..3 = left hand   (pinky, ring, middle, index)
# 4..7 = right hand  (index, middle, ring, pinky)
FINGER_NAMES = ["kA", "kS", "kE", "kT", "kN", "kI", "kO", "kP"]
LEFT = {0, 1, 2, 3}
RIGHT = {4, 5, 6, 7}

# Larger means worse / weaker.
FINGER_EFFORT = {
    0: 1.10,  # L pinky
    1: 0.50,  # L ring
    2: 0.18,  # L middle
    3: 0.00,  # L index
    4: 0.00,  # R index
    5: 0.18,  # R middle
    6: 0.50,  # R ring
    7: 1.10,  # R pinky
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

# Optional manual pinning, e.g. {'e': 1 << 3}
PINNED_SYMBOLS: Dict[str, int] = {}

DEFAULT_SELF_BIGRAM_SCALES: Dict[str, float] = {
    # "j": 0.3,
    # "k": 0.2,
    # "x": 0.2,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def popcount(x: int) -> int:
    return x.bit_count()


def bit_iter(mask: int) -> Iterable[int]:
    i = 0
    while mask:
        if mask & 1:
            yield i
        mask >>= 1
        i += 1


def mask_to_fingers(mask: int) -> str:
    return "+".join(FINGER_NAMES[i] for i in range(8) if mask & (1 << i))


def generate_chords(max_size: int) -> List[int]:
    masks = []
    for r in range(1, max_size + 1):
        for combo in combinations(range(8), r):
            m = 0
            for f in combo:
                m |= 1 << f
            masks.append(m)
    return masks


def hand_id(f: int) -> int:
    return 0 if f < 4 else 1


def local_index(f: int) -> int:
    return f if f < 4 else f - 4


# ---------------------------------------------------------------------------
# Normalisation / DB loading
# ---------------------------------------------------------------------------


def normalise_key(sym: str) -> str | None:
    """
    Convert raw pynput-style key names into a canonical symbol.

    Examples:
      'shift+E'      -> 'e'
      'shift+}'      -> '}'
      'ctrl+shift+a' -> 'a'
      'a'            -> 'a'
      'space'        -> 'space'
    """
    if not sym:
        return None

    if "+" in sym:
        sym = sym.split("+")[-1]

    if sym in {"space", "enter", "tab", "backspace"}:
        return sym

    if len(sym) == 1 and sym.isalpha():
        return sym.lower()

    if len(sym) == 1:
        return sym

    return None


def load_db(
    db_path: str,
) -> Tuple[DefaultDict[str, int], DefaultDict[Tuple[str, str], int]]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    freq: DefaultDict[str, int] = defaultdict(int)
    for raw_key, count in cur.execute("SELECT key, count FROM key_counts"):
        key = normalise_key(raw_key)
        if key is not None:
            freq[key] += int(count)

    bigrams: DefaultDict[Tuple[str, str], int] = defaultdict(int)
    for raw_bg, count in cur.execute("SELECT bigram, count FROM bigram_counts"):
        if " " not in raw_bg:
            continue
        a, b = raw_bg.split(" ", 1)
        na = normalise_key(a)
        nb = normalise_key(b)
        if na is not None and nb is not None:
            bigrams[(na, nb)] += int(count)

    conn.close()
    return freq, bigrams


# ---------------------------------------------------------------------------
# Ergonomic model
# ---------------------------------------------------------------------------


def chord_cost(mask: int) -> float:
    """Lower is better."""
    fingers = list(bit_iter(mask))
    n = len(fingers)

    # Strong preference for fewer keys.
    size_penalty = {1: 0.00, 2: 1.05, 3: 2.55}.get(n, 4.5 + 2.0 * (n - 3))

    effort = sum(FINGER_EFFORT[f] for f in fingers)

    # Penalise bunching many fingers on one hand.
    left_count = sum(1 for f in fingers if f in LEFT)
    right_count = n - left_count
    same_hand_penalty = 0.0
    if n >= 2:
        if left_count == n or right_count == n:
            same_hand_penalty += 0.55 * (n - 1)
        elif n == 2 and left_count == 1 and right_count == 1:
            # Slight bonus for a simple mirrored two-hand chord.
            same_hand_penalty -= 0.10

    # Penalise awkward gaps on the same hand: contiguous clusters are better.
    gap_penalty = 0.0
    for hand in (LEFT, RIGHT):
        local = sorted(local_index(f) for f in fingers if f in hand)
        if len(local) >= 2:
            span = local[-1] - local[0]
            gaps = span - (len(local) - 1)
            gap_penalty += 0.35 * gaps

    # Extra penalty for involving outer fingers, especially pinkies, in larger chords.
    outer_penalty = 0.0
    for f in fingers:
        if f in {0, 7}:  # pinkies
            outer_penalty += 0.28 * max(0, n - 1)
        elif f in {1, 6}:  # rings
            outer_penalty += 0.10 * max(0, n - 1)

    return size_penalty + effort + same_hand_penalty + gap_penalty + outer_penalty


def transition_cost(a: int, b: int) -> float:
    """Directed cost for typing chord b after chord a."""
    a_bits = set(bit_iter(a))
    b_bits = set(bit_iter(b))

    overlap = a_bits & b_bits
    overlap_penalty = 3.2 * len(overlap)

    # Reusing weak fingers in the next stroke is worse.
    overlap_penalty += 0.85 * sum(FINGER_EFFORT[f] for f in overlap)

    # Hand alternation: some bias towards alternating work between hands.
    a_left = sum(1 for f in a_bits if f in LEFT)
    a_right = len(a_bits) - a_left
    b_left = sum(1 for f in b_bits if f in LEFT)
    b_right = len(b_bits) - b_left

    one_hand_a = a_left == 0 or a_right == 0
    one_hand_b = b_left == 0 or b_right == 0
    same_side_penalty = 0.0
    if one_hand_a and one_hand_b:
        a_side = 0 if a_left else 1
        b_side = 0 if b_left else 1
        if a_side == b_side:
            same_side_penalty += 0.75
        else:
            same_side_penalty -= 0.12

    # Large reconfiguration between chords is slightly worse.
    changed = len(a_bits ^ b_bits)
    movement_penalty = 0.12 * changed

    # A strict subset/superset transition can be a little sticky.
    subset_penalty = 0.0
    if a != b and (a_bits < b_bits or b_bits < a_bits):
        subset_penalty += 0.20

    return overlap_penalty + same_side_penalty + movement_penalty + subset_penalty


# ---------------------------------------------------------------------------
# Objective / incremental scoring
# ---------------------------------------------------------------------------


@dataclass
class ScoreModel:
    freq_w: Dict[str, float]
    bigram_w: Dict[Tuple[str, str], float]
    outgoing: Dict[str, List[Tuple[str, float]]]
    incoming: Dict[str, List[Tuple[str, float]]]

    @classmethod
    def build(
        cls,
        freq: Dict[str, int],
        bigrams: Dict[Tuple[str, str], int],
        bigram_multiplier: float,
        self_bigram_scale: float = 1.0,
        self_bigram_scales: Dict[str, float] | None = None,
    ) -> "ScoreModel":
        total_freq = sum(freq.values()) or 1

        scaled_bigrams: Dict[Tuple[str, str], float] = {}
        for (a, b), c in bigrams.items():
            scale = 1.0
            if a == b:
                if self_bigram_scales is not None and a in self_bigram_scales:
                    scale = self_bigram_scales[a]
                else:
                    scale = self_bigram_scale

            scaled = c * scale
            if scaled > 0:
                scaled_bigrams[(a, b)] = scaled

        total_bigrams = sum(scaled_bigrams.values()) or 1.0

        freq_w = {s: c / total_freq for s, c in freq.items()}
        bigram_w = {
            pair: (c / total_bigrams) * bigram_multiplier
            for pair, c in scaled_bigrams.items()
        }

        outgoing: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        incoming: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        for (a, b), w in bigram_w.items():
            outgoing[a].append((b, w))
            incoming[b].append((a, w))

        return cls(
            freq_w=freq_w, bigram_w=bigram_w, outgoing=outgoing, incoming=incoming
        )


def symbol_importance(sym: str, model: ScoreModel) -> float:
    x = model.freq_w.get(sym, 0.0)
    x += sum(w for _, w in model.outgoing.get(sym, []))
    x += sum(w for _, w in model.incoming.get(sym, []))
    return x


def total_score(
    mapping: Dict[str, int], symbols: List[str], model: ScoreModel
) -> float:
    score = 0.0
    for s in symbols:
        score += model.freq_w.get(s, 0.0) * chord_cost(mapping[s])
    for (a, b), w in model.bigram_w.items():
        if a in mapping and b in mapping:
            score += w * transition_cost(mapping[a], mapping[b])
    return score


def delta_swap(mapping: Dict[str, int], a: str, b: str, model: ScoreModel) -> float:
    """Score(new after swapping a/b) - Score(old). Lower is better."""
    ma = mapping[a]
    mb = mapping[b]
    if ma == mb:
        return 0.0

    delta = 0.0

    # unigram terms
    delta += model.freq_w.get(a, 0.0) * (chord_cost(mb) - chord_cost(ma))
    delta += model.freq_w.get(b, 0.0) * (chord_cost(ma) - chord_cost(mb))

    affected_pairs = set()
    for other, _ in model.outgoing.get(a, []):
        affected_pairs.add((a, other))
    for other, _ in model.incoming.get(a, []):
        affected_pairs.add((other, a))
    for other, _ in model.outgoing.get(b, []):
        affected_pairs.add((b, other))
    for other, _ in model.incoming.get(b, []):
        affected_pairs.add((other, b))

    def mapped(sym: str) -> int:
        if sym == a:
            return mb
        if sym == b:
            return ma
        return mapping[sym]

    for x, y in affected_pairs:
        if x not in mapping or y not in mapping:
            continue
        w = model.bigram_w[(x, y)]
        old = transition_cost(mapping[x], mapping[y])
        new = transition_cost(mapped(x), mapped(y))
        delta += w * (new - old)

    return delta


# ---------------------------------------------------------------------------
# Initial assignment + optimisation
# ---------------------------------------------------------------------------


def greedy_initial_mapping(
    symbols: List[str],
    chords: List[int],
    fixed: Dict[str, int],
    model: ScoreModel,
) -> Dict[str, int]:
    mapping = dict(fixed)
    available = [c for c in chords if c not in fixed.values()]
    available.sort(key=chord_cost)

    # Most important symbols get the ergonomically best free chords first.
    ordered_symbols = sorted(
        [s for s in symbols if s not in fixed],
        key=lambda s: (-symbol_importance(s, model), -model.freq_w.get(s, 0.0), s),
    )

    for s, c in zip(ordered_symbols, available):
        mapping[s] = c

    return mapping


def anneal(
    symbols: List[str],
    chords: List[int],
    fixed: Dict[str, int],
    model: ScoreModel,
    steps: int,
    seed: int,
) -> Tuple[Dict[str, int], float]:
    random.seed(seed)

    mapping = greedy_initial_mapping(symbols, chords, fixed, model)
    free_syms = [s for s in symbols if s not in fixed]

    curr_score = total_score(mapping, symbols, model)
    best_score = curr_score
    best = dict(mapping)

    # A little random scrambling helps escape the purely frequency-driven seed.
    for _ in range(min(2000, max(0, len(free_syms) * 25))):
        a, b = random.sample(free_syms, 2)
        delta = delta_swap(mapping, a, b, model)
        if delta < 0:
            mapping[a], mapping[b] = mapping[b], mapping[a]
            curr_score += delta
            if curr_score < best_score:
                best_score = curr_score
                best = dict(mapping)

    curr_score = total_score(mapping, symbols, model)

    t0 = 0.35
    t1 = 0.0005
    for step in range(steps):
        t = t0 * (t1 / t0) ** (step / max(1, steps - 1))
        a, b = random.sample(free_syms, 2)
        delta = delta_swap(mapping, a, b, model)

        if delta <= 0 or random.random() < math.exp(-delta / max(1e-12, t)):
            mapping[a], mapping[b] = mapping[b], mapping[a]
            curr_score += delta
            if curr_score < best_score:
                best_score = curr_score
                best = dict(mapping)

    return best, best_score


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def clash_stats(mapping: Dict[str, int], bigrams: Dict[Tuple[str, str], int]) -> None:
    overlap_total = 0
    total = 0
    rows = []

    for (a, b), cnt in bigrams.items():
        if a not in mapping or b not in mapping:
            continue
        overlap = popcount(mapping[a] & mapping[b])
        if overlap:
            overlap_total += cnt
            rows.append((cnt, a, b, overlap))
        total += cnt

    pct = (overlap_total / total) if total else 0.0
    print(f"\nOverlap bigrams: {overlap_total} / {total} ({pct:.2%})")
    print("Top overlapping bigrams:")
    for cnt, a, b, overlap in sorted(rows, reverse=True)[:15]:
        print(f"  {a!r:>3} -> {b!r:<3}  count={cnt:<8} overlap={overlap}")


def print_layout(
    mapping: Dict[str, int], freq: Dict[str, int], model: ScoreModel
) -> None:
    def order(item: Tuple[str, int]):
        sym, mask = item
        return (
            popcount(mask),
            chord_cost(mask),
            -symbol_importance(sym, model),
            sym,
        )

    print("\n=== Optimised chord layout ===\n")
    for sym, mask in sorted(mapping.items(), key=order):
        if sym in THUMB_SYMBOLS:
            continue
        print(
            f"{sym:>4} -> {mask_to_fingers(mask):<16} "
            f"size={popcount(mask)}  effort={chord_cost(mask):.3f}  freq={freq.get(sym, 0)}"
        )


def score_contribution_stats(
    mapping: Dict[str, int],
    model: ScoreModel,
    limit: int = 20,
) -> None:
    rows = []

    for (a, b), w in model.bigram_w.items():
        if a not in mapping or b not in mapping:
            continue

        tc = transition_cost(mapping[a], mapping[b])
        contribution = w * tc
        overlap = popcount(mapping[a] & mapping[b])

        rows.append(
            {
                "pair": (a, b),
                "weight": w,
                "transition_cost": tc,
                "contribution": contribution,
                "overlap": overlap,
                "a_mask": mapping[a],
                "b_mask": mapping[b],
            }
        )

    rows.sort(key=lambda row: row["contribution"], reverse=True)

    print(f"\nTop {min(limit, len(rows))} bigrams by score contribution:")
    for row in rows[:limit]:
        a, b = row["pair"]
        print(
            f"  {a!r:>3} -> {b!r:<3}  "
            f"contrib={row['contribution']:.6f}  "
            f"weight={row['weight']:.6f}  "
            f"tcost={row['transition_cost']:.3f}  "
            f"overlap={row['overlap']}  "
            f"{mask_to_fingers(row['a_mask'])} -> {mask_to_fingers(row['b_mask'])}"
        )


def score_contribution_nonself_stats(
    mapping: Dict[str, int],
    model: ScoreModel,
    limit: int = 20,
) -> None:
    """
    Same as score_contribution_stats(), but excludes self-bigrams (a == b).
    This is useful because self-bigrams often dominate the objective while being
    comparatively "unavoidable", and can crowd out the most important cross-symbol
    transitions.
    """
    rows = []

    for (a, b), w in model.bigram_w.items():
        if a == b:
            continue
        if a not in mapping or b not in mapping:
            continue

        tc = transition_cost(mapping[a], mapping[b])
        contribution = w * tc
        overlap = popcount(mapping[a] & mapping[b])

        rows.append(
            {
                "pair": (a, b),
                "weight": w,
                "transition_cost": tc,
                "contribution": contribution,
                "overlap": overlap,
                "a_mask": mapping[a],
                "b_mask": mapping[b],
            }
        )

    rows.sort(key=lambda row: row["contribution"], reverse=True)

    print(f"\nTop {min(limit, len(rows))} NON-SELF bigrams by score contribution:")
    for row in rows[:limit]:
        a, b = row["pair"]
        print(
            f"  {a!r:>3} -> {b!r:<3}  "
            f"contrib={row['contribution']:.6f}  "
            f"weight={row['weight']:.6f}  "
            f"tcost={row['transition_cost']:.3f}  "
            f"overlap={row['overlap']}  "
            f"{mask_to_fingers(row['a_mask'])} -> {mask_to_fingers(row['b_mask'])}"
        )


def score_contribution_totals(
    mapping: Dict[str, int],
    model: ScoreModel,
) -> None:
    """
    Print a breakdown of *bigram* score contribution by category:
      - self bigrams (a == b)
      - cross bigrams with overlap (a != b and overlap > 0)
      - cross bigrams without overlap (a != b and overlap == 0)

    Contribution for a bigram is: model.bigram_w[(a,b)] * transition_cost(mapping[a], mapping[b])
    (i.e. exactly the same quantity used in the per-bigram contribution report).
    """

    self_total = 0.0
    cross_overlap_total = 0.0
    cross_no_overlap_total = 0.0

    # Track the top contributor in each bucket: ((a,b), contrib)
    top_self: Tuple[Tuple[str, str] | None, float] = (None, -1.0)
    top_cross_ov: Tuple[Tuple[str, str] | None, float] = (None, -1.0)
    top_cross_no: Tuple[Tuple[str, str] | None, float] = (None, -1.0)

    for (a, b), w in model.bigram_w.items():
        if a not in mapping or b not in mapping:
            continue

        tc = transition_cost(mapping[a], mapping[b])
        contrib = w * tc

        if a == b:
            self_total += contrib
            if contrib > top_self[1]:
                top_self = ((a, b), contrib)
        else:
            overlap = popcount(mapping[a] & mapping[b])
            if overlap > 0:
                cross_overlap_total += contrib
                if contrib > top_cross_ov[1]:
                    top_cross_ov = ((a, b), contrib)
            else:
                cross_no_overlap_total += contrib
                if contrib > top_cross_no[1]:
                    top_cross_no = ((a, b), contrib)

    cross_total = cross_overlap_total + cross_no_overlap_total
    all_total = self_total + cross_total

    denom = all_total if all_total > 1e-12 else 1.0

    print("\nContribution totals by category:")
    print(
        f"  self bigrams (a==b):            {self_total:.6f}  ({self_total/denom:.1%})"
    )
    print(
        f"  cross bigrams with overlap:     {cross_overlap_total:.6f}  ({cross_overlap_total/denom:.1%})"
    )
    print(
        f"  cross bigrams without overlap:  {cross_no_overlap_total:.6f}  ({cross_no_overlap_total/denom:.1%})"
    )
    print(
        f"  cross total (a!=b):             {cross_total:.6f}  ({cross_total/denom:.1%})"
    )
    print(f"  all bigrams total:              {all_total:.6f}  (100.0%)")

    # def fmt_pair(p: Tuple[str, str] | None) -> str:
    #     if p is None:
    #         return "-"
    #     return f\"{p[0]!r}->{p[1]!r}\"

    # if top_self[0] is not None:
    #     print(f\"  top self contributor:           {fmt_pair(top_self[0])}  ({top_self[1]:.6f})\")
    # if top_cross_ov[0] is not None:
    #     print(f\"  top cross+overlap contributor:  {fmt_pair(top_cross_ov[0])}  ({top_cross_ov[1]:.6f})\")
    # if top_cross_no[0] is not None:
    #     print(f\"  top cross no-overlap contrib:   {fmt_pair(top_cross_no[0])}  ({top_cross_no[1]:.6f})\")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=DB_PATH, help="Path to SQLite database")
    p.add_argument("--max-chord-size", type=int, default=MAX_CHORD_SIZE)
    p.add_argument("--steps", type=int, default=ANNEAL_STEPS)
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument(
        "--bigram-weight",
        type=float,
        default=6.0,
        help="How strongly to care about transitions relative to single-symbol ease",
    )
    p.add_argument(
        "--include-specials",
        action="store_true",
        help="Include named non-character keys in optimisation",
    )
    p.add_argument(
        "--self-bigram-scale",
        type=float,
        default=1.0,
        help=(
            "Scale factor for self-bigrams like 'j->j'. "
            "1.0 = unchanged, 0.0 = ignore them entirely."
        ),
    )
    p.add_argument(
        "--self-bigram-symbol",
        action="append",
        default=[],
        metavar="SYM=SCALE",
        help=(
            "Per-symbol override for self-bigrams. Can be supplied multiple times."
            "Examples: --self-bigram-symbol j=0.3 --self-bigram-symbol k=0.2"
        ),
    )

    return p.parse_args()


def parse_self_bigram_scales(items: List[str]) -> Dict[str, float]:
    """
    Parse CLI items like ['j=0.3', 'k=0.2'] into {'j': 0.3, 'k': 0.2}.
    Accepts single-character symbols and named keys (if you choose to include them).
    """
    out: Dict[str, float] = {}
    for item in items:
        m = re.match(r"^(.*)=(.)$", item.strip())
        if not m:
            raise SystemExit(
                f"Bad --self-bigram-symbol value {item!r} (expected SYM=SCALE)"
            )
        sym = m.group(1)
        try:
            scale = float(m.group(2))
        except ValueError:
            raise SystemExit(
                f"Bad scale in --self-bigram-symbol {item!r} (expected float)"
            )
        out[sym] = scale
    return out


def main() -> None:
    args = parse_args()
    freq, bigrams = load_db(args.db)

    if args.include_specials:
        symbols = sorted(freq)
    else:
        symbols = sorted(s for s in freq if s not in THUMB_SYMBOLS and len(s) == 1)

    chords = generate_chords(args.max_chord_size)
    if len(symbols) > len(chords):
        raise SystemExit(
            f"Need {len(symbols)} chords but only {len(chords)} available. "
            f"Increase --max-chord-size."
        )

    symbol_set = set(symbols)

    filtered_freq = {s: freq[s] for s in symbols}
    filtered_bigrams = {
        (a, b): c
        for (a, b), c in bigrams.items()
        if a in symbol_set and b in symbol_set
    }

    # Merge defaults  CLI overrides (CLI wins).
    self_scales = dict(DEFAULT_SELF_BIGRAM_SCALES)
    self_scales.update(parse_self_bigram_scales(args.self_bigram_symbol))

    model = ScoreModel.build(
        filtered_freq,
        filtered_bigrams,
        bigram_multiplier=args.bigram_weight,
        self_bigram_scale=args.self_bigram_scale,
        self_bigram_scales=self_scales if self_scales else None,
    )

    mapping, score = anneal(
        symbols=symbols,
        chords=chords,
        fixed=PINNED_SYMBOLS,
        model=model,
        steps=args.steps,
        seed=args.seed,
    )

    print(f"Optimised score: {score:.6f}")
    print_layout(mapping, freq, model)
    clash_stats(mapping, filtered_bigrams)
    score_contribution_stats(mapping, model, limit=20)
    score_contribution_nonself_stats(mapping, model, limit=20)
    score_contribution_totals(mapping, model)


if __name__ == "__main__":
    main()
