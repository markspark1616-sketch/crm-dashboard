#!/usr/bin/env python3
"""Fetches data from Bitrix24 and aggregates into data/dashboard.json"""
import os, json, re, time, urllib.request, urllib.parse
from datetime import datetime, timedelta

WEBHOOK_URL = os.environ.get('BITRIX_WEBHOOK_URL', '').rstrip('/') + '/'
DATA_FILE   = 'data/dashboard.json'
DATE_FROM   = '2026-01-01'

# Only these 3 sources are shown in the dashboard
ALLOWED_SOURCES = {'27', '65', '84'}  # Victory контекст, Victory VK, Victory парсинг

# Deal categories (pipelines) to exclude entirely
HIDDEN_CATEGORIES = {'4', '5', '6', '12', '15', '16', '20', '22'}
# Нижний Новгород, Ростов, Краснодар, Новосибирск (x2), НВСБ доп, Дожим, Улан-Удэ

# Lead cities (from TITLE parsing) to exclude entirely
HIDDEN_LEAD_CITIES = {
    'Нижний Новгород', 'Ростов', 'Краснодар',
    'Новосибирск', 'Дожим', 'Улан-Удэ',
}

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

ACTIVE_STAGES = {
    'NEW', 'PREPARATION', 'PREPAYMENT_INVOICE', 'PREPAYMENT_INVOIC',
    'EXECUTING', 'FINAL_INVOICE', '1', '6', '7',
    'UC_MLCFYZ', 'UC_IA4RQ3', 'UC_FCWL21', 'UC_LNVU9C', 'UC_MSD2TV',
}


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


def fetch_all(method, select_fields, extra_params=None):
    params = {f'select[{i}]': f for i, f in enumerate(select_fields)}
    if extra_params:
        params.update(extra_params)
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
        return CITY_MAP.get(m.group(1), m.group(1))
    return 'Другой'


def normalize_stage(stage_id):
    return stage_id.split(':', 1)[1] if ':' in stage_id else stage_id


def parse_money(val):
    if not val:
        return 0.0
    try:
        return float(str(val).split('|')[0] or '0')
    except Exception:
        return 0.0


def md_lead_init():
    return {'t': 0, 'pcp': 0, 'rec': 0, 'came': 0, 'junk': 0, 'miss': 0}


def md_deal_init():
    return {'won': 0, 'won_r': 0.0, 'inst_r': 0.0, 'plan_r': 0.0}


def update_lead_md(md, status):
    md['t'] += 1
    # ПЦП: все кто хоть раз был записан (включая пришедших) или не записан/отменил
    if status in ('UC_I0XLWE', 'UC_KXIWFH', 'UC_W36M8K', 'UC_CI0W8O', 'UC_TD7XTT', 'CONVERTED'):
        md['pcp'] += 1
    # Записан: все кто был когда-либо записан (включая пришедших — они тоже были записаны)
    if status in ('UC_W36M8K', 'UC_CI0W8O', 'UC_TD7XTT', 'CONVERTED'):
        md['rec'] += 1
    if status == 'CONVERTED':
        md['came'] += 1
    if status in ('JUNK', '1'):
        md['junk'] += 1
    if status == 'PROCESSED':
        md['miss'] += 1


def main():
    if not WEBHOOK_URL or WEBHOOK_URL == '/':
        print("ERROR: BITRIX_WEBHOOK_URL not set")
        return

    os.makedirs('data', exist_ok=True)
    print(f"Fetching data since {DATE_FROM}...")

    # Users
    print("Users...")
    users = {}
    start = 0
    while True:
        r = api_get('user.get', {
            'select[0]': 'ID', 'select[1]': 'NAME', 'select[2]': 'LAST_NAME',
            'start': start
        })
        for u in r.get('result', []):
            users[str(u['ID'])] = f"{u.get('NAME','')} {u.get('LAST_NAME','')}".strip()
        if 'next' in r:
            start = r['next']
            time.sleep(0.3)
        else:
            break
    print(f"  {len(users)} users loaded")

    # Sources — only allowed ones
    print("Sources...")
    source_names = {}
    r = api_get('crm.status.list', {'filter[ENTITY_ID]': 'SOURCE'})
    for s in r.get('result', []):
        if s['STATUS_ID'] in ALLOWED_SOURCES:
            source_names[s['STATUS_ID']] = s['NAME']

    # Visible categories (for meta)
    visible_categories = {k: v for k, v in CATEGORY_CITIES.items() if k not in HIDDEN_CATEGORIES}

    # Leads
    print("Leads...")
    leads = fetch_all('crm.lead.list',
        ['ID', 'STATUS_ID', 'ASSIGNED_BY_ID', 'DATE_CREATE', 'TITLE', 'SOURCE_ID'],
        {'filter[>=DATE_CREATE]': DATE_FROM})

    # Deals
    print("Deals...")
    deals = fetch_all('crm.deal.list',
        ['ID', 'STAGE_ID', 'CATEGORY_ID', 'ASSIGNED_BY_ID', 'DATE_CREATE',
         'DATE_MODIFY', 'OPPORTUNITY',
         'UF_CRM_1751552162', 'UF_CRM_1751552078', 'UF_CRM_1751552023'],
        {'filter[>=DATE_CREATE]': DATE_FROM})

    print(f"Aggregating {len(leads)} leads, {len(deals)} deals...")

    # ── Leads aggregation ──
    lead_daily       = {}
    lead_op_monthly  = {}
    # monthly_detail[month][city_or__total] = md_lead_init()
    lead_monthly_detail = {}

    skipped_leads = 0
    for lead in leads:
        city = extract_city(lead.get('TITLE', ''))
        if city in HIDDEN_LEAD_CITIES:
            skipped_leads += 1
            continue

        date   = lead['DATE_CREATE'][:10]
        month  = date[:7]
        status = lead.get('STATUS_ID', 'unknown')
        op     = str(lead.get('ASSIGNED_BY_ID', ''))
        src    = lead.get('SOURCE_ID', '') or ''

        # daily
        d = lead_daily.setdefault(date, {'t': 0, 's': {}, 'c': {}, 'src': {}})
        d['t'] += 1
        d['s'][status] = d['s'].get(status, 0) + 1
        d['c'][city]   = d['c'].get(city, 0) + 1
        if src in ALLOWED_SOURCES:
            d['src'][src] = d['src'].get(src, 0) + 1

        # monthly detail — total and per city
        if month not in lead_monthly_detail:
            lead_monthly_detail[month] = {'_total': md_lead_init()}
        if city not in lead_monthly_detail[month]:
            lead_monthly_detail[month][city] = md_lead_init()
        update_lead_md(lead_monthly_detail[month]['_total'], status)
        update_lead_md(lead_monthly_detail[month][city], status)

        # operator monthly
        if op:
            m = lead_op_monthly.setdefault(month, {})
            op_d = m.setdefault(op, {'t': 0, 's': {}})
            op_d['t'] += 1
            op_d['s'][status] = op_d['s'].get(status, 0) + 1

    print(f"  Leads skipped (hidden cities): {skipped_leads}")

    # ── Deals aggregation ──
    deal_daily       = {}
    deal_op_monthly  = {}
    deal_monthly_detail = {}
    pipeline  = {}
    at_risk   = []
    now       = datetime.utcnow()
    risk_threshold = now - timedelta(days=30)

    skipped_deals = 0
    for deal in deals:
        cat = str(deal.get('CATEGORY_ID', '0'))
        if cat in HIDDEN_CATEGORIES:
            skipped_deals += 1
            continue

        date       = deal['DATE_CREATE'][:10]
        month      = date[:7]
        stage_raw  = deal.get('STAGE_ID', '')
        stage_code = normalize_stage(stage_raw)
        city       = CATEGORY_CITIES.get(cat, f'Категория {cat}')
        op         = str(deal.get('ASSIGNED_BY_ID', ''))
        revenue    = float(deal.get('OPPORTUNITY') or 0)
        date_mod   = (deal.get('DATE_MODIFY', '') or '')[:10] or date

        inst_flag = deal.get('UF_CRM_1751552162', '') or ''
        inst_bal  = parse_money(deal.get('UF_CRM_1751552078'))
        plan_agr  = parse_money(deal.get('UF_CRM_1751552023'))
        is_won    = (stage_code == 'WON')

        # daily
        d = deal_daily.setdefault(date, {
            't': 0, 'g': {}, 'c': {}, 'r': 0, 'won_r': 0,
            'inst': 0, 'inst_r': 0, 'plan': 0, 'plan_r': 0,
        })
        d['t'] += 1
        d['g'][stage_code] = d['g'].get(stage_code, 0) + 1
        d['c'][city]       = d['c'].get(city, 0) + 1
        d['r']            += revenue
        if is_won:
            d['won_r'] += revenue
        if inst_flag:
            d['inst']   += 1
            d['inst_r'] += inst_bal
        if plan_agr > 0:
            d['plan']   += 1
            d['plan_r'] += plan_agr

        # monthly detail — total and per city
        if month not in deal_monthly_detail:
            deal_monthly_detail[month] = {'_total': md_deal_init()}
        if city not in deal_monthly_detail[month]:
            deal_monthly_detail[month][city] = md_deal_init()

        for md in (deal_monthly_detail[month]['_total'], deal_monthly_detail[month][city]):
            if is_won:
                md['won']   += 1
                md['won_r'] += revenue
            md['inst_r'] += inst_bal
            md['plan_r'] += plan_agr

        # operator monthly
        if op:
            m = deal_op_monthly.setdefault(month, {})
            op_d = m.setdefault(op, {'t': 0, 'r': 0, 'g': {}})
            op_d['t'] += 1
            op_d['r'] += revenue
            op_d['g'][stage_code] = op_d['g'].get(stage_code, 0) + 1

        # pipeline
        if stage_code in ACTIVE_STAGES:
            pg = pipeline.setdefault(stage_code, {'count': 0, 'sum': 0.0, 'plan_r': 0.0})
            pg['count'] += 1
            pg['sum']   += revenue
            pg['plan_r'] += plan_agr

            try:
                mod_dt = datetime.strptime(date_mod, '%Y-%m-%d')
                if mod_dt < risk_threshold:
                    at_risk.append({
                        'id': deal['ID'], 'city': city, 'stage': stage_code,
                        'opp': revenue, 'mod': date_mod,
                        'days_idle': (now.date() - mod_dt.date()).days,
                    })
            except Exception:
                pass

    print(f"  Deals skipped (hidden cities): {skipped_deals}")
    at_risk.sort(key=lambda x: x['days_idle'], reverse=True)
    at_risk = at_risk[:50]

    dashboard = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'date_from':    DATE_FROM,
        'meta': {
            'users':             users,
            'lead_statuses':     LEAD_STATUS_NAMES,
            'lead_status_order': LEAD_STATUS_ORDER,
            'deal_stages':       DEAL_STAGE_NAMES,
            'deal_stage_order':  DEAL_STAGE_ORDER,
            'categories':        visible_categories,
            'sources':           source_names,
        },
        'leads': {
            'total':          len(leads) - skipped_leads,
            'daily':          lead_daily,
            'monthly_detail': lead_monthly_detail,
            'operators':      lead_op_monthly,
        },
        'deals': {
            'total':          len(deals) - skipped_deals,
            'daily':          deal_daily,
            'monthly_detail': deal_monthly_detail,
            'operators':      deal_op_monthly,
            'pipeline':       pipeline,
            'at_risk':        at_risk,
        },
    }

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(dashboard, f, ensure_ascii=False, separators=(',', ':'))

    size_kb = os.path.getsize(DATA_FILE) / 1024
    print(f"Saved {DATA_FILE} ({size_kb:.0f} KB)")
    print(f"Pipeline active: {len(pipeline)} stages, At risk: {len(at_risk)} deals")


if __name__ == '__main__':
    main()
