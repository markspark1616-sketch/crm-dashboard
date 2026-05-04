#!/usr/bin/env python3
"""Fetches data from Bitrix24 and aggregates into data/dashboard.json"""
import os, json, re, time, urllib.request, urllib.parse
from datetime import datetime, timedelta

WEBHOOK_URL = os.environ.get('BITRIX_WEBHOOK_URL', '').rstrip('/') + '/'
DATA_FILE = 'data/dashboard.json'
MONTHS_BACK = 18

CITY_MAP = {
    'SPb': 'Санкт-Петербург', 'Spb': 'Санкт-Петербург',
    'NNov': 'Нижний Новгород', 'Nnov': 'Нижний Новгород',
    'Rostov': 'Ростов', 'Krasnodar': 'Краснодар',
    'Kemerovo': 'Кемерово', 'Kaliningrad': 'Калининград',
    'Novokuznetsk': 'Новокузнецк', 'Omsk': 'Омск',
    'Perm': 'Пермь', 'Novosibirsk': 'Новосибирск',
    'Samara': 'Самара', 'Krasnoyarsk': 'Красноярск',
    'Barnaul': 'Барнаул', 'TLT': 'Тольятти', 'Tlt': 'Тольятти',
    'UlanUde': 'Улан-Удэ', 'Volgograd': 'Волгоград',
    'Irkutsk': 'Иркутск',
}

CATEGORY_CITIES = {
    '1': 'Санкт-Петербург', '4': 'Нижний Новгород', '5': 'Ростов',
    '6': 'Краснодар', '7': 'Кемерово', '8': 'Калининград',
    '9': 'Новокузнецк', '10': 'Омск', '11': 'Пермь',
    '12': 'Новосибирск (первичный)', '13': 'Самара', '14': 'Красноярск',
    '15': 'Новосибирск (вторичный)', '16': 'НВСБ доп. продажи',
    '17': 'AI лидогенерация', '18': 'NPS', '19': 'Барнаул',
    '20': 'Дожим', '21': 'Тольятти', '22': 'Улан-Удэ',
    '23': 'Волгоград', '24': 'Иркутск',
}

LEAD_STATUS_NAMES = {
    'NEW': 'Новая заявка', 'IN_PROCESS': 'Взят в работу',
    'PROCESSED': 'Недозвон', 'UC_I0XLWE': 'Не записан',
    'UC_KXIWFH': 'Отменил запись', 'UC_W36M8K': 'Записан',
    'UC_CI0W8O': 'Подтверждён на завтра', 'UC_TD7XTT': 'Подтвержден на сегодня',
    '3': 'Условный отказ', 'CONVERTED': 'Пришёл',
    'JUNK': 'Не учитываем', '1': 'Некачественный лид',
}

LEAD_STATUS_ORDER = [
    'NEW', 'IN_PROCESS', 'PROCESSED', 'UC_I0XLWE', 'UC_KXIWFH',
    'UC_W36M8K', 'UC_CI0W8O', 'UC_TD7XTT', '3', 'CONVERTED', 'JUNK', '1',
]

DEAL_STAGE_NAMES = {
    'NEW': 'Пришел', 'PREPARATION': 'Назначен ТМ',
    'PREPAYMENT_INVOICE': 'На презентации', 'PREPAYMENT_INVOIC': 'На презентации',
    'EXECUTING': 'На осмотре', 'FINAL_INVOICE': 'На закрытие',
    '1': 'Фин отдел', '6': 'ТМ назначен', '7': 'Фин отдел',
    'WON': 'Сделка успешна', 'LOSE': 'Сделка провалена',
    'APOLOGY': 'Расторжение', '2': 'Не учитываем', '3': 'Не учитываем',
    'UC_ZFGB34': 'Полный отказ', 'UC_MLCFYZ': 'На осмотре',
    'UC_IA4RQ3': 'На закрытие', 'UC_FCWL21': 'Фин отдел',
    'UC_LNVU9C': 'ТМ назначен', 'UC_MSD2TV': 'Фин отдел',
}

DEAL_STAGE_ORDER = [
    'NEW', 'PREPARATION', 'PREPAYMENT_INVOICE', 'EXECUTING',
    'FINAL_INVOICE', '1', 'WON', 'LOSE', 'APOLOGY', '2',
]


def api_get(method, params=None):
    url = f"{WEBHOOK_URL}{method}.json"
    if params:
        url += '?' + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:
            print(f"  Error {method}: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
    return {}


def fetch_all(method, select_fields, date_from):
    params = {f'select[{i}]': f for i, f in enumerate(select_fields)}
    params['filter[>=DATE_CREATE]'] = date_from
    items, start = [], 0
    while True:
        params['start'] = start
        result = api_get(method, params)
        batch = result.get('result', [])
        items.extend(batch)
        total = result.get('total', 0)
        print(f"  {method}: {len(items)}/{total}", end='\r')
        if 'next' in result:
            start = result['next']
            time.sleep(0.4)
        else:
            break
    print()
    return items


def extract_city(title):
    m = re.search(r'Victory[_\- ]?([A-Za-z]+)', title or '')
    if m:
        code = m.group(1)
        return CITY_MAP.get(code, code)
    return 'Другой'


def normalize_stage(stage_id):
    return stage_id.split(':', 1)[1] if ':' in stage_id else stage_id


def parse_money(val):
    if not val:
        return 0.0
    return float(str(val).split('|')[0] or '0')


def main():
    if not WEBHOOK_URL or WEBHOOK_URL == '/':
        print("ERROR: BITRIX_WEBHOOK_URL not set")
        return

    os.makedirs('data', exist_ok=True)
    date_from = (datetime.now() - timedelta(days=MONTHS_BACK * 30)).strftime('%Y-%m-%d')
    print(f"Fetching data since {date_from}...")

    # Users
    print("Users...")
    users = {}
    r = api_get('user.get', {'select[0]': 'ID', 'select[1]': 'NAME', 'select[2]': 'LAST_NAME'})
    for u in r.get('result', []):
        users[str(u['ID'])] = f"{u.get('NAME','')} {u.get('LAST_NAME','')}".strip()

    # Sources
    print("Sources...")
    source_names = {}
    r = api_get('crm.status.list', {'filter[ENTITY_ID]': 'SOURCE'})
    for s in r.get('result', []):
        source_names[s['STATUS_ID']] = s['NAME']

    # Leads
    print("Leads...")
    leads = fetch_all('crm.lead.list',
        ['ID', 'STATUS_ID', 'ASSIGNED_BY_ID', 'DATE_CREATE', 'TITLE', 'SOURCE_ID'], date_from)

    # Deals
    print("Deals...")
    deals = fetch_all('crm.deal.list',
        ['ID', 'STAGE_ID', 'CATEGORY_ID', 'ASSIGNED_BY_ID', 'DATE_CREATE', 'OPPORTUNITY',
         'UF_CRM_1751552162', 'UF_CRM_1751552078', 'UF_CRM_1751552023'], date_from)

    print(f"Aggregating {len(leads)} leads, {len(deals)} deals...")

    # Aggregate leads by day
    lead_daily = {}
    lead_op_monthly = {}
    lead_monthly = {}  # for trend chart

    for lead in leads:
        date = lead['DATE_CREATE'][:10]
        month = date[:7]
        status = lead.get('STATUS_ID', 'unknown')
        city = extract_city(lead.get('TITLE', ''))
        op = str(lead.get('ASSIGNED_BY_ID', ''))
        src = lead.get('SOURCE_ID', '') or 'unknown'

        d = lead_daily.setdefault(date, {'t': 0, 's': {}, 'c': {}, 'src': {}})
        d['t'] += 1
        d['s'][status] = d['s'].get(status, 0) + 1
        d['c'][city] = d['c'].get(city, 0) + 1
        d['src'][src] = d['src'].get(src, 0) + 1

        lead_monthly[month] = lead_monthly.get(month, 0) + 1

        if op:
            m = lead_op_monthly.setdefault(month, {})
            op_d = m.setdefault(op, {'t': 0, 's': {}})
            op_d['t'] += 1
            op_d['s'][status] = op_d['s'].get(status, 0) + 1

    # Aggregate deals by day
    deal_daily = {}
    deal_op_monthly = {}
    deal_monthly = {}  # for trend chart

    for deal in deals:
        date = deal['DATE_CREATE'][:10]
        month = date[:7]
        stage_code = normalize_stage(deal.get('STAGE_ID', ''))
        cat = str(deal.get('CATEGORY_ID', '0'))
        city = CATEGORY_CITIES.get(cat, f'Категория {cat}')
        op = str(deal.get('ASSIGNED_BY_ID', ''))
        revenue = float(deal.get('OPPORTUNITY') or 0)

        inst_flag = deal.get('UF_CRM_1751552162', '') or ''
        inst_balance = parse_money(deal.get('UF_CRM_1751552078'))
        plan_agreed = parse_money(deal.get('UF_CRM_1751552023'))

        d = deal_daily.setdefault(date, {'t': 0, 'g': {}, 'c': {}, 'r': 0,
                                         'inst': 0, 'inst_r': 0, 'plan': 0, 'plan_r': 0})
        d['t'] += 1
        d['g'][stage_code] = d['g'].get(stage_code, 0) + 1
        d['c'][city] = d['c'].get(city, 0) + 1
        d['r'] += revenue

        if inst_flag:
            d['inst'] += 1
            d['inst_r'] += inst_balance
        if plan_agreed > 0:
            d['plan'] += 1
            d['plan_r'] += plan_agreed

        deal_monthly[month] = deal_monthly.get(month, 0) + 1

        if op:
            m = deal_op_monthly.setdefault(month, {})
            op_d = m.setdefault(op, {'t': 0, 'r': 0, 'g': {}})
            op_d['t'] += 1
            op_d['r'] += revenue
            op_d['g'][stage_code] = op_d['g'].get(stage_code, 0) + 1

    dashboard = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'date_from': date_from,
        'meta': {
            'users': users,
            'lead_statuses': LEAD_STATUS_NAMES,
            'lead_status_order': LEAD_STATUS_ORDER,
            'deal_stages': DEAL_STAGE_NAMES,
            'deal_stage_order': DEAL_STAGE_ORDER,
            'categories': CATEGORY_CITIES,
            'sources': source_names,
        },
        'leads': {
            'total': len(leads),
            'daily': lead_daily,
            'monthly': lead_monthly,
            'operators': lead_op_monthly,
        },
        'deals': {
            'total': len(deals),
            'daily': deal_daily,
            'monthly': deal_monthly,
            'operators': deal_op_monthly,
        },
    }

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(dashboard, f, ensure_ascii=False, separators=(',', ':'))

    size_kb = os.path.getsize(DATA_FILE) / 1024
    print(f"Saved {DATA_FILE} ({size_kb:.0f} KB)")


if __name__ == '__main__':
    main()
