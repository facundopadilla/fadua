"""Generate a realistic 18-month daily seed for metricas_campanas_ventas.

Stdlib only. Deterministic (fixed seed). Emits db/init.sql with a CREATE TABLE
plus one batched multi-row INSERT (~547 daily rows ending 2026-07-01).

The funnel is internally coherent so KPIs land in believable ranges:
impresiones -> clics (CTR ~2-4%) -> leads -> ventas, with weekly seasonality
(dealership traffic peaks on weekends), a mild upward trend, and noise.
"""

import os
import random
from datetime import date, timedelta

random.seed(42)

DAYS = 547
END = date(2026, 7, 1)
START = END - timedelta(days=DAYS - 1)

# (tipo, models, average price USD)
VEHICLES = [
    ("SUV", ["Toyota RAV4", "Honda CR-V", "Ford Escape", "Volkswagen Tiguan"], 34000),
    ("Sedán", ["Toyota Corolla", "Honda Civic", "Volkswagen Vento", "Nissan Sentra"], 22000),
    ("Pickup", ["Ford Ranger", "Toyota Hilux", "Volkswagen Amarok", "Chevrolet S10"], 41000),
    ("Hatchback", ["Volkswagen Golf", "Ford Fiesta", "Peugeot 208", "Renault Sandero"], 18000),
]

# Monday=0 .. Sunday=6
WEEKDAY_MULT = [0.90, 0.90, 0.95, 1.00, 1.15, 1.35, 1.20]


def gen_row(d, i):
    trend = 1.0 + 0.30 * (i / DAYS)          # +30% growth across the period
    season = WEEKDAY_MULT[d.weekday()]
    base = trend * season

    def noise():
        return random.uniform(0.85, 1.15)

    g_impr = int(random.uniform(18000, 32000) * base * noise())
    g_clics = max(1, int(g_impr * random.uniform(0.022, 0.040)))
    g_costo = round(g_clics * random.uniform(1.4, 2.6), 2)
    g_leads = max(0, int(g_clics * random.uniform(0.05, 0.11)))

    m_impr = int(random.uniform(9000, 18000) * base * noise())
    m_clics = max(1, int(m_impr * random.uniform(0.018, 0.034)))
    m_costo = round(m_clics * random.uniform(0.7, 1.6), 2)
    m_leads = max(0, int(m_clics * random.uniform(0.045, 0.10)))

    total_leads = g_leads + m_leads
    ventas = max(0, int(total_leads * random.uniform(0.08, 0.16)))

    vtipo, vmodels, vprice = random.choice(VEHICLES)
    vmodel = random.choice(vmodels)
    ingresos = round(ventas * vprice * random.uniform(0.92, 1.10), 2)

    return (
        d.isoformat(), g_impr, g_clics, g_costo, g_leads,
        m_impr, m_clics, m_costo, m_leads, total_leads, ventas,
        vtipo, vmodel, ingresos,
    )


def sql_val(v):
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return str(v)


rows = [gen_row(START + timedelta(days=i), i) for i in range(DAYS)]

COLS = (
    "fecha, google_ads_impresiones, google_ads_clics, google_ads_costo_usd, "
    "google_ads_leads, meta_ads_impresiones, meta_ads_clics, meta_ads_costo_usd, "
    "meta_ads_leads, total_leads, cantidad_ventas, vehiculo_tipo_principal, "
    "vehiculo_modelo_principal, ingresos_ventas_usd"
)

DDL = """-- Auto-generated seed: 547 daily rows (~18 months) ending 2026-07-01.
CREATE TABLE IF NOT EXISTS metricas_campanas_ventas (
  fecha DATE PRIMARY KEY,
  google_ads_impresiones INT NOT NULL,
  google_ads_clics INT NOT NULL,
  google_ads_costo_usd DECIMAL(12,2) NOT NULL,
  google_ads_leads INT NOT NULL,
  meta_ads_impresiones INT NOT NULL,
  meta_ads_clics INT NOT NULL,
  meta_ads_costo_usd DECIMAL(12,2) NOT NULL,
  meta_ads_leads INT NOT NULL,
  total_leads INT NOT NULL,
  cantidad_ventas INT NOT NULL,
  vehiculo_tipo_principal VARCHAR(50) NOT NULL,
  vehiculo_modelo_principal VARCHAR(80) NOT NULL,
  ingresos_ventas_usd DECIMAL(14,2) NOT NULL
);
"""

values = ["(" + ", ".join(sql_val(v) for v in r) + ")" for r in rows]
insert = f"INSERT INTO metricas_campanas_ventas ({COLS}) VALUES\n" + ",\n".join(values) + ";\n"

out = "/Users/facundo/Fadua/db/init.sql"
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(DDL + "\n" + insert)

# Self-check: prove coherence of a couple of rows.
r0, rl = rows[0], rows[-1]
ctr0 = r0[2] / r0[1]
roas0 = r0[13] / (r0[3] + r0[7])
print(f"rows={len(rows)}  first={r0[0]}  last={rl[0]}")
print(f"sample row0: g_ctr={ctr0:.3f}  ventas={r0[10]}  ingresos={r0[13]}  roas={roas0:.1f}x")
tot_ventas = sum(r[10] for r in rows)
tot_ing = sum(r[13] for r in rows)
print(f"totals: ventas={tot_ventas}  ingresos={tot_ing:,.0f}")
