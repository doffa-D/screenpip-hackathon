"""Deterministic routine mining over verified discovery records.

Finds "after A you usually do B" from real timestamps and flags the latest A that never got its B.
No model and no desktop access: every number it reports can be recomputed from discovery.json.
"""
import hashlib
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median


def parse(value):
    moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def timeline(state, include_dismissed=False, exclude=()):
    """Every occurrence of every pattern as (start, end, pattern_id, occurrence_id), oldest first.

    `exclude` lists (start, end) spans of Melon's own overnight runs so its work never counts as the user's routine."""
    events = []
    for pattern_id, pattern in state['patterns'].items():
        if pattern.get('status') == 'dismissed' and not include_dismissed:
            continue
        for occurrence_id in pattern['occurrence_ids']:
            occurrence = state['occurrences'].get(occurrence_id)
            if not occurrence:
                continue
            start = parse(occurrence['timestamp'])
            end = parse(occurrence['ended_at']) if occurrence.get('ended_at') else start
            if any(a <= start <= b for a, b in exclude):
                continue
            events.append((start, max(start, end), pattern_id, occurrence_id))
    return sorted(events)


def percentile(values, share):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(share * len(ordered)) - 1)]


def find_gaps(state, now, *, horizon=timedelta(hours=24), min_support=2, min_probability=0.6,
              min_wait=timedelta(minutes=30), lift=0.25, exclude=()):
    """Routine steps the user usually does next but has not done yet.

    A→B counts only A occurrences whose follow-up window already closed, so a fresh A is never
    penalised for being recent. B must beat its own base rate by `lift`, otherwise a task that simply
    happens all day would look like a "usual next step" of everything.
    """
    events = timeline(state, exclude=exclude)
    if len(events) < 2 * min_support:
        return []
    by_pattern = defaultdict(list)
    for event in events:
        by_pattern[event[2]].append(event)
    span = max(max(e[1] for e in events) - min(e[0] for e in events), horizon)
    gaps = []
    for a_id, a_events in by_pattern.items():
        countable = [a for a in a_events if a[1] + horizon <= now]
        if len(countable) < min_support:
            continue
        latest = max(a_events, key=lambda e: e[1])
        if not (min_wait <= now - latest[1] < horizon):
            continue
        for b_id, b_events in by_pattern.items():
            if b_id == a_id or len(b_events) < min_support:
                continue
            lags, pairs, taken = [], [], set()
            for a in sorted(countable, key=lambda e: e[1]):
                # One-to-one: a single B cannot vouch for several As, or three As a day would "always" be followed by one B.
                follow = [(b[0] - a[1], b) for b in b_events if timedelta(0) <= b[0] - a[1] <= horizon and b[3] not in taken]
                if follow:
                    lag, b = min(follow, key=lambda f: f[0])
                    taken.add(b[3])
                    lags.append(lag)
                    pairs.append((a[3], b[3]))
            if len(lags) < min_support:
                continue
            probability = len(lags) / len(countable)
            baseline = 1 - math.exp(-len(b_events) * horizon / span)
            if probability < min_probability or probability < baseline + lift:
                continue
            typical = median(lags)
            wait = max(min_wait, 1.5 * percentile(lags, 0.9))
            if now - latest[1] < wait:
                continue
            if any(b[0] >= latest[1] for b in b_events):
                continue  # the follow-up already happened after the latest A
            gaps.append({'kind': 'missed_next_step', 'after_pattern_id': a_id, 'expected_pattern_id': b_id,
                'trigger_occurrence_id': latest[3], 'trigger_ended_at': latest[1].isoformat(),
                'examples': [i for pair in pairs[-2:] for i in pair],
                'support': len(lags), 'sample': len(countable), 'probability': round(probability, 3),
                'baseline': round(baseline, 3), 'typical_lag_minutes': round(typical.total_seconds() / 60),
                'overdue_minutes': round((now - latest[1] - typical).total_seconds() / 60),
                'pair_key': hashlib.sha256(f'{a_id}|{b_id}'.encode()).hexdigest()[:16],
                'gap_key': hashlib.sha256(f'{a_id}|{b_id}|{latest[3]}'.encode()).hexdigest()[:24]})
    # One proposal per trigger: keep the most reliable follow-up, not every downstream step of the same moment.
    best = {}
    for gap in sorted(gaps, key=lambda g: (-g['probability'], -g['support'])):
        best.setdefault(gap['trigger_occurrence_id'], gap)
    return sorted(best.values(), key=lambda g: (-g['probability'], -g['support']))


def already_done(state, pattern_id, after):
    """Did the user do this pattern themselves since `after`? Used to cancel stale proposals."""
    pattern = state['patterns'].get(pattern_id)
    if not pattern:
        return False
    for occurrence_id in pattern['occurrence_ids']:
        occurrence = state['occurrences'].get(occurrence_id)
        if occurrence and parse(occurrence['timestamp']) >= after:
            return True
    return False
