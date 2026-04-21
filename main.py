#!/usr/bin/env python3
"""
Terminal-based keystroke frequency logger + chorded layout suggester.

Features:
- Logs counts of keys and bigrams into SQLite.
- Terminal dashboard: top keys, last keys, QWERTY-aligned primaries per finger.
- Suggests chords for remaining symbols to reduce clashes using bigram stats.
- Uses in-memory caches to reduce DB reads; DB is written in batches (UPSERT).

Stop: Ctrl+C

Install:
  pip install pynput

Run:
  python3 key_freq_terminal.py

Show DB totals:
  python3 key_freq_terminal.py --display

Notes:
- This tool does NOT record text. It logs only counts of keys and bigrams.
"""

import argparse
import os
import sqlite3
import threading
import time
import shutil
from collections import Counter, deque
from dataclasses import dataclass
from itertools import combinations
from typing import Dict, List, Optional, Tuple

from pynput.keyboard import (
    Key,
    Listener,
)  # Listener callbacks run in its own thread. [1](https://deepwiki.com/moses-palmer/pynput/4.1-basic-keyboard-control)

DB_PATH = "key_counts.db"

# Performance knobs
BATCH_SIZE = 400  # flush sooner => less loss on crash, more disk writes
COMMIT_INTERVAL_SEC = 10
UI_REFRESH_SEC = 2

# Layout knobs
DEFAULT_FINGERS = 8
DEFAULT_MAX_CHORD_SIZE = 3
DEFAULT_CHORD_SUGGESTIONS = 40
DEFAULT_LOAD_BIGRAMS = 5000  # seed optimiser with top N bigrams from DB (optional)

# Thumb candidates (you said thumbs for whitespace/backspace/modifiers)
THUMB_CANDIDATES = [
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
]


# ---------------------------
# DB helpers
# ---------------------------


def init_db(db_path: str = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS key_counts (
            key TEXT PRIMARY KEY,
            count INTEGER NOT NULL
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS bigram_counts (
            bigram TEXT PRIMARY KEY,
            count INTEGER NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def display_counts(db_path: str = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    print("Individual Key Counts:")
    for row in c.execute("SELECT key, count FROM key_counts ORDER BY count DESC"):
        print(f"{row[0]}: {row[1]}")

    print("\nBigram Counts:")
    for row in c.execute("SELECT bigram, count FROM bigram_counts ORDER BY count DESC"):
        print(f"{row[0]}: {row[1]}")

    conn.close()


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


# ---------------------------
# Symbol normalisation
# ---------------------------

MODIFIER_NAMES = {
    "ctrl",
    "alt",
    "shift",
    "cmd",
    "ctrl_l",
    "ctrl_r",
    "alt_l",
    "alt_r",
    "shift_r",
}


def strip_modifiers(key_name: str) -> str:
    """Convert 'ctrl+shift+a' -> 'a' (keep last token)."""
    if "+" not in key_name:
        return key_name
    return key_name.split("+")[-1]


def is_layout_symbol(sym: str) -> bool:
    """
    Symbols we allow for primaries/chords:
    - any single character (letters, digits, punctuation)
    - plus named: space/enter/tab/backspace
    Excludes:
    - modifiers themselves
    """
    if not sym:
        return False
    if sym in MODIFIER_NAMES:
        return False
    if len(sym) == 1:
        return True
    if sym in {"space", "enter", "tab", "backspace"}:
        return True
    return False


# ---------------------------
# QWERTY finger mapping (touch typing approximation)
# ---------------------------

# Finger indices: 0..7
# 0 LP, 1 LR, 2 LM, 3 LI, 4 RI, 5 RM, 6 RR, 7 RP
FINGER_NAMES_8 = [
    "L Pinky",
    "L Ring",
    "L Middle",
    "L Index",
    "R Index",
    "R Middle",
    "R Ring",
    "R Pinky",
]
FINGER_ABBR_8 = ["LP", "LR", "LM", "LI", "RI", "RM", "RR", "RP"]

# Dominance penalty weights: lower is better
# index≈middle > ring > pinky
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


def build_qwerty_letter_map() -> Dict[str, int]:
    # Touch typing groups (approximate, but matches the intuition you want)
    mapping = {}
    # left hand
    for ch in "qaz":
        mapping[ch] = 0
    for ch in "wsx":
        mapping[ch] = 1
    for ch in "edc":
        mapping[ch] = 2
    for ch in "rtfvgb":
        mapping[ch] = 3
    # right hand
    for ch in "yhnujm":
        mapping[ch] = 4
    for ch in "ik":
        mapping[ch] = 5
    for ch in "ol":
        mapping[ch] = 6
    for ch in "p":
        mapping[ch] = 7
    return mapping


QWERTY_LETTERS = build_qwerty_letter_map()

# Number row (approximate: 1..5 left, 6..0 right)
QWERTY_NUMBERS = {
    "1": 0,
    "2": 1,
    "3": 2,
    "4": 3,
    "5": 3,
    "6": 4,
    "7": 4,
    "8": 5,
    "9": 6,
    "0": 7,
}

# Common punctuation positions (approximate touch typing)
# Note: backslash differs on some layouts; keep it on RP (common)
PUNCT_BASE = {
    "-": 7,
    "=": 7,
    "[": 7,
    "]": 7,
    ";": 7,
    "'": 7,
    ",": 5,
    ".": 6,
    "/": 7,
    "`": 0,
    "\\": 7,
}

# Shifted symbols mapped to the same finger as their base key
SHIFTED_US = {
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    ":": ";",
    '"': "'",
    "<": ",",
    ">": ".",
    "?": "/",
    "~": "`",
    "|": "\\",
}

# UK differences (minimal set)
# On UK ISO keyboards, '@' and '"' are swapped compared to US (common case).
SHIFTED_UK = dict(SHIFTED_US)
SHIFTED_UK["@"] = "'"  # often Shift+' on UK
SHIFTED_UK['"'] = "2"  # often Shift+2 on UK
# UK has an extra key for "#/~" near enter; many users hit with right pinky.
# We'll still keep '#' mapped to '3' by default; but allow explicit override later.


def qwerty_finger(sym: str, layout: str = "uk") -> Optional[int]:
    """
    Returns the finger index (0..7) typically used on QWERTY for this symbol,
    or None if unknown.
    """
    if not sym:
        return None

    if sym in {"space", "enter", "tab", "backspace"}:
        # thumbs, but we treat separately; return None for finger-primaries
        return None

    # single characters
    if len(sym) == 1:
        ch = sym.lower()
        if ch in QWERTY_LETTERS:
            return QWERTY_LETTERS[ch]
        if ch in QWERTY_NUMBERS:
            return QWERTY_NUMBERS[ch]
        if ch in PUNCT_BASE:
            return PUNCT_BASE[ch]

        # shifted punctuation
        shifted = SHIFTED_UK if layout == "uk" else SHIFTED_US
        if sym in shifted:
            base = shifted[sym]
            # base could be digit or punctuation
            if base in QWERTY_NUMBERS:
                return QWERTY_NUMBERS[base]
            if base in PUNCT_BASE:
                return PUNCT_BASE[base]
    return None


# ---------------------------
# Chord model
# ---------------------------


def popcount(x: int) -> int:
    return x.bit_count()


def overlap_bits(a: int, b: int) -> int:
    return popcount(a & b)


def mask_to_fingers(mask: int) -> str:
    # e.g., 0b00011000 -> "LI+RI"
    parts = []
    for i in range(8):
        if mask & (1 << i):
            parts.append(FINGER_ABBR_8[i])
    return "+".join(parts) if parts else "-"


def generate_chord_masks(max_size: int) -> List[int]:
    """Generate all finger-subset masks up to size max_size (excluding empty)."""
    masks = []
    fingers = list(range(8))
    for r in range(1, max_size + 1):
        for comb in combinations(fingers, r):
            m = 0
            for f in comb:
                m |= 1 << f
            masks.append(m)
    return masks


@dataclass(frozen=True)
class ChordCostWeights:
    # Penalty for same-finger overlap between consecutive symbols (scaled by bigram count)
    clash: float = 1.0
    # Penalty for chord size (scaled by symbol frequency)
    size: float = 0.015
    # Penalty for weak fingers used (scaled by symbol frequency)
    weakness: float = 0.01
    # Penalty if chord doesn't include the QWERTY finger for that symbol (small bias)
    qwerty_bias: float = 0.12


# ---------------------------
# Main application
# ---------------------------


class KeyFreqTerminal:
    def __init__(
        self,
        db_path: str,
        qwerty_layout: str,
        ignore_modifiers_for_layout: bool,
        load_db_at_start: bool,
        load_bigrams: int,
        max_chord_size: int,
        chord_suggestions: int,
        cost_weights: ChordCostWeights = ChordCostWeights(),
    ):
        self.db_path = db_path
        self.qwerty_layout = qwerty_layout
        self.ignore_mods = ignore_modifiers_for_layout
        self.load_db_at_start = load_db_at_start
        self.load_bigrams = load_bigrams
        self.max_chord_size = max_chord_size
        self.chord_suggestions = chord_suggestions
        self.cost_weights = cost_weights

        # Listener state
        self.last_key_raw: Optional[str] = None
        self.last_ten_keys_raw = deque(maxlen=10)
        self.current_modifiers = set()
        self.modifier_keys = {
            "ctrl_l": "ctrl",
            "ctrl_r": "ctrl",
            "ctrl": "ctrl",
            "alt_l": "alt",
            "alt_r": "alt",
            "alt": "alt",
            "shift": "shift",
            "shift_r": "shift",
            "cmd": "cmd",
            "cmd_r": "cmd",
            "cmd_l": "cmd",
        }

        # In-memory caches (dashboard uses these, minimising DB reads)
        self.key_counts_raw: Counter = Counter()
        self.bigram_counts_raw: Counter = Counter()  # raw bigram strings
        self.bigram_counts_sym: Counter = Counter()  # (symA, symB) processed for layout

        # Batch buffers for DB writes
        self.lock = threading.Lock()
        self.key_batch: Counter = Counter()
        self.bigram_batch: Counter = Counter()

        self.stop_event = threading.Event()

        # Precompute candidate chord masks
        self.all_masks = generate_chord_masks(self.max_chord_size)

        # Listener (runs in background thread)
        self.listener = Listener(on_press=self.on_press, on_release=self.on_release)

        if self.load_db_at_start:
            self._load_cache_from_db()

        if self.load_bigrams > 0:
            self._seed_bigrams_from_db(self.load_bigrams)

    # ---------- DB cache warm-up ----------

    def _load_cache_from_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        for key, cnt in c.execute("SELECT key, count FROM key_counts"):
            self.key_counts_raw[key] = cnt
        conn.close()

    def _seed_bigrams_from_db(self, n: int) -> None:
        """
        Load top-N bigrams from DB so chord optimisation sees historical clash patterns
        without reading the entire bigram table.
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        rows = c.execute(
            "SELECT bigram, count FROM bigram_counts ORDER BY count DESC LIMIT ?",
            (n,),
        ).fetchall()
        conn.close()

        for bg, cnt in rows:
            self.bigram_counts_raw[bg] = cnt
            a, b = bg.split(" ", 1) if " " in bg else (bg, "")
            a_sym = self._to_layout_symbol(a)
            b_sym = self._to_layout_symbol(b)
            if a_sym and b_sym:
                self.bigram_counts_sym[(a_sym, b_sym)] += cnt

    # ---------- symbol conversion for layout analysis ----------

    def _to_layout_symbol(self, raw_key: str) -> Optional[str]:
        sym = strip_modifiers(raw_key) if self.ignore_mods else raw_key

        # Collapse A..Z -> a..z for layout/chord purposes (Shift is a thumb modifier in your design)
        if isinstance(sym, str) and len(sym) == 1 and sym.isalpha():
            sym = sym.lower()

        return sym if is_layout_symbol(sym) else None

    # ---------- pynput callbacks (listener thread) ----------

    def on_press(self, key) -> None:
        key_str = None

        if isinstance(key, Key):
            key_str = key.name

            if key_str in self.modifier_keys:
                # Track modifier state
                self.current_modifiers.add(key_str)

                # ALSO record the modifier itself as an event (thumb workload)
                mod_canon = self.modifier_keys[key_str]  # e.g. shift_l -> shift

                # DO NOT count shift on press (we'll count it only when it makes a letter)
                if mod_canon == "shift":
                    return

                # Count other modifiers immediately (ctrl/alt/cmd) as thumb workload
                flush_now = False
                with self.lock:
                    self.last_ten_keys_raw.append(mod_canon)
                    self.key_counts_raw[mod_canon] += 1
                    self.key_batch[mod_canon] += 1

                    if self.last_key_raw:
                        bg_raw = f"{self.last_key_raw} {mod_canon}"
                        self.bigram_counts_raw[bg_raw] += 1
                        self.bigram_batch[bg_raw] += 1

                        a_sym = self._to_layout_symbol(self.last_key_raw)
                        b_sym = self._to_layout_symbol(mod_canon)
                        if a_sym and b_sym:
                            self.bigram_counts_sym[(a_sym, b_sym)] += 1

                    self.last_key_raw = mod_canon

                    if (
                        sum(self.key_batch.values()) + sum(self.bigram_batch.values())
                    ) >= BATCH_SIZE:
                        flush_now = True

                if flush_now:
                    self.flush_to_db()

                return
        else:
            try:
                key_str = key.char
                # Map control chars (ASCII 1..26) -> a..z
                if key_str and 1 <= ord(key_str) <= 26:
                    key_str = chr(ord("a") + ord(key_str) - 1)
            except AttributeError:
                key_str = str(key)

        if not key_str:
            return

        combined_mods = {
            self.modifier_keys[m]
            for m in self.current_modifiers
            if m in self.modifier_keys
        }
        # If shift is held AND the produced key is a letter, count shift usage (thumb workload)
        shift_held = "shift" in {
            self.modifier_keys[m]
            for m in self.current_modifiers
            if m in self.modifier_keys
        }
        is_letter = isinstance(key_str, str) and len(key_str) == 1 and key_str.isalpha()

        if shift_held and is_letter:
            with self.lock:
                self.key_counts_raw["shift"] += 1
                self.key_batch["shift"] += 1

        raw = (
            "+".join(sorted(combined_mods)) + "+" + key_str
            if combined_mods
            else key_str
        )

        flush_now = False
        with self.lock:
            self.last_ten_keys_raw.append(raw)

            # raw counts
            self.key_counts_raw[raw] += 1
            self.key_batch[raw] += 1

            # raw bigram
            if self.last_key_raw:
                bg_raw = f"{self.last_key_raw} {raw}"
                self.bigram_counts_raw[bg_raw] += 1
                self.bigram_batch[bg_raw] += 1

                # layout bigram (symbols)
                a_sym = self._to_layout_symbol(self.last_key_raw)
                b_sym = self._to_layout_symbol(raw)
                if a_sym and b_sym:
                    self.bigram_counts_sym[(a_sym, b_sym)] += 1

            self.last_key_raw = raw

            if (
                sum(self.key_batch.values()) + sum(self.bigram_batch.values())
            ) >= BATCH_SIZE:
                flush_now = True

        if flush_now:
            self.flush_to_db()

    def on_release(self, key) -> None:
        if isinstance(key, Key):
            key_str = key.name
            if key_str in self.modifier_keys:
                self.current_modifiers.discard(key_str)

    # ---------- Efficient DB flush (aggregate + UPSERT) ----------

    def flush_to_db(self) -> None:
        with self.lock:
            key_updates = dict(self.key_batch)
            bigram_updates = dict(self.bigram_batch)
            self.key_batch.clear()
            self.bigram_batch.clear()

        if not key_updates and not bigram_updates:
            return

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        if key_updates:
            c.executemany(
                """
                INSERT INTO key_counts(key, count)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET count = count + excluded.count
                """,
                list(key_updates.items()),
            )

        if bigram_updates:
            c.executemany(
                """
                INSERT INTO bigram_counts(bigram, count)
                VALUES(?, ?)
                ON CONFLICT(bigram) DO UPDATE SET count = count + excluded.count
                """,
                list(bigram_updates.items()),
            )

        conn.commit()
        conn.close()

    # ---------------------------
    # QWERTY-aligned primaries
    # ---------------------------

    def _layout_symbol_counts(self) -> Counter:
        """
        Collapse raw key counts into symbol counts for layout (strip modifiers optionally).
        """
        out = Counter()
        for raw, cnt in self.key_counts_raw.items():
            sym = self._to_layout_symbol(raw)
            if sym:
                out[sym] += cnt
        return out

    def _thumb_symbol_counts(self) -> Counter:
        out = Counter()
        for raw, cnt in self.key_counts_raw.items():
            sym = strip_modifiers(raw) if self.ignore_mods else raw

            # collapse letters for layout, but leave named keys alone
            if isinstance(sym, str) and len(sym) == 1 and sym.isalpha():
                sym = sym.lower()

            # Canonicalise modifier variants and named keys
            sym = self._canonical_modifier(sym)

            if is_thumb_symbol(sym):
                out[sym] += cnt
        return out

    def recommend_thumb_keys(self, sym_counts: Counter) -> List[Tuple[str, int]]:
        ranked = [(k, sym_counts.get(k, 0)) for k in THUMB_CANDIDATES]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return [x for x in ranked if x[1] > 0]

    def recommend_primaries_qwerty_aligned(self) -> List[Tuple[str, str, int]]:
        """
        For each finger, pick the most-used symbol that maps to that finger on QWERTY.
        If a finger has no mapped candidates in your data, fall back to best unused symbol.
        """
        sym_counts = self._layout_symbol_counts()

        # exclude thumb candidates from finger primaries
        for t in THUMB_CANDIDATES:
            if t in sym_counts:
                del sym_counts[t]

        # bucket by qwerty finger
        bucket: Dict[int, List[Tuple[str, int]]] = {i: [] for i in range(8)}
        unknown: List[Tuple[str, int]] = []

        for sym, cnt in sym_counts.items():
            f = qwerty_finger(sym, self.qwerty_layout)
            if f is None:
                unknown.append((sym, cnt))
            else:
                bucket[f].append((sym, cnt))

        for f in bucket:
            bucket[f].sort(key=lambda x: x[1], reverse=True)
        unknown.sort(key=lambda x: x[1], reverse=True)

        primaries: List[Tuple[str, str, int]] = []
        used = set()

        # first pass: per-finger best qwerty-mapped
        for f in range(8):
            pick = None
            for sym, cnt in bucket[f]:
                if sym not in used:
                    pick = (FINGER_NAMES_8[f], sym, cnt)
                    used.add(sym)
                    break
            primaries.append(pick if pick else (FINGER_NAMES_8[f], "-", 0))

        # second pass: fill any "-" with best remaining overall
        remaining = [(s, c) for s, c in sym_counts.most_common() if s not in used]
        ri = 0
        fixed = []
        for fname, sym, cnt in primaries:
            if sym != "-":
                fixed.append((fname, sym, cnt))
            else:
                while ri < len(remaining) and remaining[ri][0] in used:
                    ri += 1
                if ri < len(remaining):
                    s, c = remaining[ri]
                    used.add(s)
                    fixed.append((fname, s, c))
                    ri += 1
                else:
                    fixed.append((fname, "-", 0))
        return fixed

    # ---------------------------
    # Chord suggestions (clash-aware)
    # ---------------------------

    def _primary_masks(self, primaries: List[Tuple[str, str, int]]) -> Dict[str, int]:
        """Map primary symbols to single-finger masks."""
        sym_to_mask = {}
        for i, (_, sym, _) in enumerate(primaries):
            if sym != "-" and sym:
                sym_to_mask[sym] = 1 << i
        return sym_to_mask

    def _candidate_masks_for_symbol(self, sym: str, used_masks: set) -> List[int]:
        """
        Candidate chord masks for sym, filtered to avoid used chords and reserved singletons.
        Prefer including sym's QWERTY finger if known (small bias in scoring anyway).
        """
        preferred = qwerty_finger(sym, self.qwerty_layout)
        candidates = []
        for m in self.all_masks:
            if m in used_masks:
                continue
            candidates.append(m)

        # If we know the preferred finger, keep those first to speed up greedy search
        if preferred is not None:
            preferred_list = [m for m in candidates if (m & (1 << preferred))]
            other_list = [m for m in candidates if not (m & (1 << preferred))]
            return preferred_list + other_list
        return candidates

    def _mask_weakness(self, mask: int) -> int:
        return sum(FINGER_WEAKNESS[i] for i in range(8) if (mask & (1 << i)))

    def _incremental_cost(
        self,
        sym: str,
        sym_freq: int,
        mask: int,
        assigned_masks: Dict[str, int],
        sym_counts: Counter,
    ) -> float:
        """
        Cost = clash + size + weakness + qwerty-bias
        Clash uses observed bigrams: penalise overlap between chords for consecutive symbols.
        """
        cost = 0.0

        # size penalty (relative to single-finger)
        cost += self.cost_weights.size * (popcount(mask) - 1) * sym_freq

        # weakness penalty
        cost += self.cost_weights.weakness * self._mask_weakness(mask) * sym_freq

        # qwerty bias (small): prefer chords that include the QWERTY finger for that symbol
        pref = qwerty_finger(sym, self.qwerty_layout)
        if pref is not None and not (mask & (1 << pref)):
            cost += self.cost_weights.qwerty_bias * sym_freq

        # clash penalty: overlap weighted by bigram count
        # only consider already-assigned symbols for incremental evaluation
        for other_sym, other_mask in assigned_masks.items():
            # bigram sym->other
            fwd = self.bigram_counts_sym.get((sym, other_sym), 0)
            # bigram other->sym
            rev = self.bigram_counts_sym.get((other_sym, sym), 0)
            if fwd:
                cost += self.cost_weights.clash * fwd * overlap_bits(mask, other_mask)
            if rev:
                cost += self.cost_weights.clash * rev * overlap_bits(other_mask, mask)

        return cost

    def suggest_chords(self, primaries: List[Tuple[str, str, int]]) -> Dict[str, int]:
        """
        Greedy chord assignment:
        - Reserve single-finger masks for the 8 primaries (one per finger)
        - Assign remaining high-frequency symbols to unique masks up to max_chord_size
        - Minimise incremental cost using bigram overlap + chord size + finger weakness
        """
        sym_counts = self._layout_symbol_counts()

        # exclude thumb candidates from finger-chord pool (thumb handled separately)
        for t in THUMB_CANDIDATES:
            sym_counts.pop(t, None)

        primary_map = self._primary_masks(primaries)

        # Reserve primary masks (singletons)
        used_masks = set(primary_map.values())

        assigned = dict(primary_map)

        # Candidate symbols for chord suggestion:
        # - ignore primaries
        # - take most common up to N suggestions (plus primaries)
        candidates = [s for s, _ in sym_counts.most_common() if s not in assigned]
        candidates = candidates[: self.chord_suggestions]

        # For each candidate, choose best chord
        for sym in candidates:
            freq = sym_counts[sym]
            best_mask = None
            best_cost = float("inf")

            for m in self._candidate_masks_for_symbol(sym, used_masks):
                # disallow singletons that are not free (already prevented by used_masks)
                # but allow other singletons only if not already used (rarely helpful; keep simple)
                # You can uncomment the next line to forbid all singletons for non-primaries:
                if popcount(m) == 1:
                    continue

                cost = self._incremental_cost(sym, freq, m, assigned, sym_counts)
                if cost < best_cost:
                    best_cost = cost
                    best_mask = m

                # small optimisation: if we found a very good 2-finger chord early, break?
                # (keeping deterministic and simple -> no early break)

            if best_mask is not None:
                assigned[sym] = best_mask
                used_masks.add(best_mask)

        return assigned

    def _canonical_modifier(self, sym: str) -> str:
        # Normalise left/right variants and Key names
        # If it’s something like 'shift_r' (rare in our stored keys now), map it.
        if sym in self.modifier_keys:
            return self.modifier_keys[sym]
        # Normalise escape naming
        if sym == "escape":
            return "esc"
        return sym

    # ---------------------------
    # Dashboard
    # ---------------------------

    def _top10_raw(self) -> List[Tuple[str, int]]:
        return self.key_counts_raw.most_common(10)

    def _last10_raw(self) -> List[str]:
        with self.lock:
            return list(self.last_ten_keys_raw)

    def _clash_summary(
        self, chord_map: Dict[str, int], top_n: int = 40
    ) -> Tuple[int, int]:
        """
        Returns (clash_bigrams, total_bigrams) for the most common bigrams in sym space.
        A 'clash' means overlap_bits > 0.
        """
        most = self.bigram_counts_sym.most_common(top_n)
        total = sum(cnt for _, cnt in most)
        clashes = 0
        for (a, b), cnt in most:
            if a in chord_map and b in chord_map:
                if overlap_bits(chord_map[a], chord_map[b]) > 0:
                    clashes += cnt
        return clashes, total

    def render(self) -> None:
        clear_screen()

        top10 = self._top10_raw()
        last10 = self._last10_raw()

        sym_counts = self._layout_symbol_counts()
        thumb_counts = self._thumb_symbol_counts()

        thumbs = self.recommend_thumb_keys(thumb_counts)
        primaries = self.recommend_primaries_qwerty_aligned()
        chord_map = self.suggest_chords(primaries)

        clash_cnt, total_cnt = self._clash_summary(chord_map, top_n=60)
        clash_pct = (100.0 * clash_cnt / total_cnt) if total_cnt else 0.0

        print("Keystroke Frequency Counter + Chorded Layout Helper (terminal)")
        print("-------------------------------------------------------------")
        print(f"DB: {self.db_path} | Stop: Ctrl+C")
        print(
            f"Batch: {BATCH_SIZE} | Flush: {COMMIT_INTERVAL_SEC}s | UI: {UI_REFRESH_SEC}s"
        )
        print(
            f"QWERTY layout: {self.qwerty_layout} | ignore_modifiers_for_layout: {self.ignore_mods}"
        )
        print(
            f"Chord suggestions: {self.chord_suggestions} | max chord size: {self.max_chord_size}"
        )
        if not self.load_db_at_start:
            print(
                "NOTE: --no-load-db enabled (dashboard shows only this session so far)"
            )
        if self.load_bigrams == 0:
            print(
                "NOTE: bigram seeding disabled; clash optimisation uses this session only"
            )
        print()

        print("Top 10 keys (raw, includes modifiers):")
        if top10:
            for k, cnt in top10:
                print(f"  {k:28s} {cnt}")
        else:
            print("  (no data yet)")
        print()

        print("Last 10 keys (raw):")
        print("  " + (" ".join(last10) if last10 else "(none yet)"))
        print()

        print("Thumb candidates (your preference: whitespace/backspace/modifiers):")
        # Terminal-aware two-column layout

        term_w = shutil.get_terminal_size(fallback=(100, 30)).columns

        # Width per column. Subtract a small gutter between columns.
        gutter = 2
        col_w = max(36, (term_w - gutter) // 2) - 1

        thumbs_len = len(thumbs)
        half = (thumbs_len + 1) // 2
        if thumbs:
            for i in range(half):
                (key, count) = thumbs[i]
                line = f" {key:12s} {count}".ljust(col_w)
                if i + half < thumbs_len:
                    (key, count) = thumbs[i + half]
                    line += f"  {key:12s} {count}"
                print(line)
        else:
            print("  (no thumb candidates observed yet)")
        print()

        print(
            "QWERTY-aligned finger primaries (most-used symbol normally typed with that finger):"
        )
        for i, (fname, sym, cnt) in enumerate(primaries):
            m = chord_map.get(sym, (1 << i)) if sym != "-" else 0
            print(f"  {fname:10s}: {sym:10s}  ({cnt:7d})   chord={mask_to_fingers(m)}")
        print()

        print("Chord suggestions (most-used non-primaries):")
        # show only non-primaries from the chord map, sorted by frequency
        primary_syms = {sym for _, sym, _ in primaries if sym != "-"}
        candidates = [
            s
            for s, _ in sym_counts.most_common()
            if s not in primary_syms and s in chord_map
        ]
        candidates = candidates[: self.chord_suggestions]

        # Build rows
        rows = []
        for s in candidates:
            rows.append((s, mask_to_fingers(chord_map[s]), sym_counts[s]))

        def fmt_cell(sym: str, chord: str, freq: int) -> str:
            # single-line cell text (NO '\n')
            text = f"{sym:5s} -> {chord:12s} f={freq}"
            if len(text) > col_w:
                # Trim to fit column width cleanly
                text = text[: max(0, col_w - 3)] + "..."
            return text.ljust(col_w - 1)

        n = len(rows)
        half = (n + 1) // 2  # ceil(n/2)

        # Column-first ordering:
        # left column gets rows[0:half], right column gets rows[half: ]
        for i in range(half):
            left = fmt_cell(*rows[i])
            if i + half < n:
                right = fmt_cell(*rows[i + half])
                line = "  " + left + (" " * gutter) + right
            else:
                line = "  " + left
            print(line)

        print()

        if total_cnt:
            print(
                f"Clash estimate on top bigrams: {clash_cnt}/{total_cnt} = {clash_pct:.1f}% "
                f"(lower is better)"
            )
        else:
            print("Clash estimate: not enough bigram data yet")

    # ---------------------------
    # Run loop
    # ---------------------------

    def run(self) -> None:
        self.listener.start()

        next_commit = time.time() + COMMIT_INTERVAL_SEC
        next_ui = time.time() + UI_REFRESH_SEC

        try:
            while not self.stop_event.is_set():
                now = time.time()

                if now >= next_commit:
                    self.flush_to_db()
                    next_commit = now + COMMIT_INTERVAL_SEC

                if now >= next_ui:
                    self.render()
                    next_ui = now + UI_REFRESH_SEC

                time.sleep(0.05)

        except KeyboardInterrupt:
            pass
        finally:
            try:
                self.listener.stop()
                if self.listener.is_alive():
                    self.listener.join(timeout=1.0)
            except Exception:
                pass

            self.flush_to_db()
            clear_screen()
            print("Stopped. Final data flushed to DB.")
            print(f"View totals: python3 {os.path.basename(__file__)} --display")


def is_thumb_symbol(sym: str) -> bool:
    if not sym:
        return False
    if sym in THUMB_CANDIDATES:
        return True
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Keystroke logger + chorded layout helper (terminal)"
    )
    parser.add_argument(
        "--display",
        action="store_true",
        help="Display DB contents sorted by highest counts",
    )
    parser.add_argument(
        "--db", default=DB_PATH, help="SQLite DB path (default: key_counts.db)"
    )
    parser.add_argument(
        "--qwerty",
        choices=["uk", "us"],
        default="uk",
        help="QWERTY layout mapping used for finger alignment (default: uk)",
    )
    parser.add_argument(
        "--ignore-modifiers",
        dest="ignore_modifiers",
        action="store_true",
        help="For layout, treat 'ctrl+a' as 'a' (default)",
    )
    parser.add_argument(
        "--no-ignore-modifiers",
        dest="ignore_modifiers",
        action="store_false",
        help="For layout, keep modifiers in symbol names",
    )
    parser.set_defaults(ignore_modifiers=True)
    parser.add_argument(
        "--no-load-db",
        action="store_true",
        help="Do not read existing DB at startup (dashboard shows only this session)",
    )
    parser.add_argument(
        "--load-bigrams",
        type=int,
        default=DEFAULT_LOAD_BIGRAMS,
        help=f"Seed optimiser with top-N bigrams from DB (default: {DEFAULT_LOAD_BIGRAMS}; 0 disables)",
    )
    parser.add_argument(
        "--max-chord-size",
        type=int,
        default=DEFAULT_MAX_CHORD_SIZE,
        help=f"Maximum chord size to consider (default: {DEFAULT_MAX_CHORD_SIZE})",
    )
    parser.add_argument(
        "--chord-suggestions",
        type=int,
        default=DEFAULT_CHORD_SUGGESTIONS,
        help=f"How many non-primary symbols to assign chords for (default: {DEFAULT_CHORD_SUGGESTIONS})",
    )

    args = parser.parse_args()
    init_db(args.db)

    if args.display:
        display_counts(args.db)
        return

    app = KeyFreqTerminal(
        db_path=args.db,
        qwerty_layout=args.qwerty,
        ignore_modifiers_for_layout=args.ignore_modifiers,
        load_db_at_start=(not args.no_load_db),
        load_bigrams=args.load_bigrams,
        max_chord_size=args.max_chord_size,
        chord_suggestions=args.chord_suggestions,
    )
    app.run()


if __name__ == "__main__":
    main()
