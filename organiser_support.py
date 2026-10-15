"""Read-only organiser fixtures; integration adapter, not a replacement adjudicator.

Keep this file beside organiser_data/. No expected ruling is exposed to agents.
"""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import re

DATA = Path(__file__).resolve().parent / 'organiser_data'
CASE_IDS = ('DISP-001', 'DISP-002', 'DISP-003')
TOOLS = ('get_trip', 'get_messages', 'get_payment', 'get_metrics', 'get_policy', 'get_history')
PROVENANCE = 'Organiser-provided hackathon fixture; not independently verified live operational data'


def cents(value):
    if value is None:
        return None
    return int((Decimal(str(value)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def seconds(start, end):
    if start is None or end is None:
        return None
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def load_case(case_id):
    if case_id not in CASE_IDS:
        raise ValueError(f'Unknown organiser case: {case_id}')
    return json.loads((DATA / f'{case_id}.json').read_text(encoding='utf-8'))


def list_cases():
    return [dict(case_id=i,
                 category=load_case(i)['dispute_ticket']['dispute_type'],
                 complaint=load_case(i)['dispute_ticket']['description'],
                 source=PROVENANCE) for i in CASE_IDS]


def policy_sections():
    text = (DATA / 'policy_v2_1.md').read_text(encoding='utf-8')
    pattern = r'^### (?:Precedent )?(\d+\.\d+)[^\n]*\n.*?(?=^### |^## |\Z)'
    return [{'id': 'ORG-V2.1-' + m.group(1), 'text': m.group(0).strip()}
            for m in re.finditer(pattern, text, re.M | re.S)]


def route(points):
    if points is None:
        return None
    return [{'lat': p['lat'], 'lon': p['lng'],
             **({'timestamp': p['timestamp']} if 'timestamp' in p else {})}
            for p in points]


def calculate_metrics(raw):
    t = raw['trip_data']
    category = raw['dispute_ticket']['dispute_type']
    common = {'category': category, 'currency': 'SGD',
              'rider_fraud_flags': raw['rider_profile'].get('fraud_flags'),
              'driver_fraud_flags': raw['driver_profile'].get('fraud_flags')}
    if category == 'route_deviation':
        actual, reference = t.get('actual_distance_km'), t.get('estimated_distance_km')
        excess = None if actual is None or reference is None else Decimal(str(actual)) - Decimal(str(reference))
        return {**common,
                'distance_source': 'Organiser trip_data road distances; not sparse GPS straight-line lengths',
                'actual_distance_m': None if actual is None else float(Decimal(str(actual))*1000),
                'reference_distance_m': None if reference is None else float(Decimal(str(reference))*1000),
                'excess_distance_m': None if excess is None else float(excess*1000),
                'excess_distance_fare_cents': cents(raw.get('fare_breakdown', {}).get('excess_distance_fare')),
                'fare_difference_cents': cents(t.get('excess_fare')),
                'duration_difference_min': t['actual_duration_min']-t['estimated_duration_min'],
                'requires_route_threshold_review': None if excess is None else excess > Decimal('2'),
                'route_threshold_clause_id': 'ORG-V2.1-6.2'}
    if category == 'no_show_charge':
        cancel = t.get('cancellation_time')
        start = t.get('scheduled_time')
        contacts = [m for m in raw.get('chat_logs', [])
                    if m.get('sender') == 'driver' and cancel is not None
                    and datetime.fromisoformat(m['timestamp']) <= datetime.fromisoformat(cancel)]
        return {**common,
                'arrival_to_cancel_seconds': seconds(t.get('driver_arrival_time'), cancel),
                'scheduled_to_cancel_seconds': seconds(start, cancel),
                'free_wait_clock_basis': 'scheduled pickup time, organiser policy 2.1',
                'pre_cancel_driver_message_count': sum(m.get('type') == 'message' for m in contacts),
                'pre_cancel_driver_call_attempt_count': sum(m.get('type') == 'call' for m in contacts),
                'cancellation_fee_cents': cents(t.get('cancellation_fee')),
                'telemetry_note': 'Assess pickup presence using actual GPS samples separately from reported arrival.',
                'log_completeness': 'Unknown beyond supplied fixture; counts describe supplied records only'}
    if category == 'fare_dispute':
        quote, actual = t.get('upfront_quote'), t.get('actual_fare')
        return {**common,
                'upfront_quote_cents': cents(quote), 'charged_cents': cents(actual),
                'fare_difference_cents': None if quote is None or actual is None else cents(Decimal(str(actual))-Decimal(str(quote))),
                'surge_difference_cents': cents(raw.get('fare_breakdown', {}).get('comparison', {}).get('surge_amount_difference')),
                'surge_pricing_log': deepcopy(raw.get('surge_pricing_log'))}
    raise ValueError(f'Unsupported category: {category}')


def get_evidence(case_id, tool):
    if tool not in TOOLS:
        raise ValueError(f'Unknown tool: {tool}')
    raw = load_case(case_id)
    t = raw['trip_data']
    category = raw['dispute_ticket']['dispute_type']
    policy_ids = []
    if tool == 'get_trip':
        trip = {**deepcopy(t), 'category': category,
                'actual_route': route(raw.get('gps_telemetry')) if category == 'route_deviation' else None,
                'reference_route': route(raw.get('optimal_route', {}).get('waypoints')),
                'pickup': route([t['pickup_location']])[0],
                'arrived_at': t.get('driver_arrival_time'),
                'cancelled_at': t.get('cancellation_time'),
                'scheduled_at': t.get('scheduled_time'),
                'pickup_presence_samples': route([p for p in raw.get('gps_telemetry', [])
                    if p.get('status') in ('arrived', 'waiting', 'cancelled')]) if category == 'no_show_charge' else None}
        data = {'trip': trip, 'gps_telemetry': raw.get('gps_telemetry'),
                'optimal_route': raw.get('optimal_route'), 'traffic_conditions': raw.get('traffic_conditions'),
                'app_events': raw.get('app_events')}
    elif tool == 'get_messages':
        data = {'messages': raw.get('chat_logs'), 'app_events': raw.get('app_events'),
                'surge_pricing_log': raw.get('surge_pricing_log'),
                'call_recordings': None,
                'absence_note': 'No recording supplied does not prove no verbal notification occurred.'}
    elif tool == 'get_payment':
        fee = t.get('cancellation_fee')
        charge = t.get('actual_fare', fee)
        data = {'payment': {'currency': 'SGD', 'charged_cents': cents(charge),
                'reference_fare_cents': cents(t.get('upfront_quote', t.get('estimated_fare'))),
                'cancellation_fee_cents': cents(fee),
                'fare_breakdown': raw.get('fare_breakdown'),
                'surge_pricing_log': raw.get('surge_pricing_log'),
                'source_note': 'Fixture reported charge; no independent payment settlement record supplied.'}}
    elif tool == 'get_metrics':
        data = {'metrics': calculate_metrics(raw)}
    elif tool == 'get_history':
        data = {'history': {'rider_profile': raw['rider_profile'], 'driver_profile': raw['driver_profile'],
                'note': 'Ratings and flags do not establish fault in this trip. No dated cancellation list is supplied.'}}
    else:
        sections = policy_sections()
        policy_ids = [s['id'] for s in sections]
        data = {'policy': {'version': 'organiser-v2.1', 'source': 'Organiser-provided hackathon policy',
                'clauses': sections,
                'full_text': (DATA/'policy_v2_1.md').read_text(encoding='utf-8'),
                'conflicts': ['DISP-001 supplied sample ruling expects refund, but its 4.3 km deviation exceeds policy 6.2 autonomous threshold.',
                    'DISP-002 fixture starts free waiting at arrival; policy 2.1 starts it at scheduled pickup. Show both clocks.',
                    'Route fixture cites Driver Policy 4.2, a different document; use this policy 1.2 for route notification.']}}
    evidence_id = f'{case_id}:{tool}'
    return {'case_id': case_id, 'id': evidence_id, 'evidence_ids': [evidence_id],
            'policy_ids': policy_ids, 'source': PROVENANCE, 'data': deepcopy(data)}
