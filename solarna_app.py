import streamlit as st
from datetime import datetime, timedelta
from collections import defaultdict
import pandas as pd
import plotly.graph_objs as go
import plotly.express as px
import numpy as np

st.set_page_config(page_title="Solarno punjenje", layout="wide")
st.title("☀️ Solarno punjenje baterije - Detaljna analiza")

# ---------------------------------------------------------
# PARSERI
# ---------------------------------------------------------
def parse_price_line(line):
    line = line.strip()
    if not line or "\t" not in line:
        return None
    try:
        time_part, price_part = line.split("\t")
    except ValueError:
        return None
    
    for tz in ["(CET)", "(CEST)", "(UTC)", "(GMT)"]:
        time_part = time_part.replace(tz, "")
    time_part = time_part.strip()
    
    parts = time_part.split(" - ")
    if len(parts) < 1:
        return None
    
    start_str = parts[0].strip()
    
    start = None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            start = datetime.strptime(start_str, fmt)
            break
        except ValueError:
            start = None
    
    if start is None:
        return None
    
    try:
        price = float(price_part.replace(",", "."))
    except ValueError:
        return None
    
    return start, price

def parse_solar_line(line):
    line = line.strip()
    if not line or line.startswith('time'):
        return None
    
    try:
        parts = line.split('\t')
        if len(parts) < 3:
            return None
        time_str = parts[0]
        sunshine_sec = float(parts[2])
        start = datetime.strptime(time_str, "%Y-%m-%dT%H:%M")
        return start, sunshine_sec
    except Exception:
        return None

# ---------------------------------------------------------
# BOČNI PANEL - PARAMETRI BATERIJE
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Parametri baterije")
    
    CAPACITY_MWH = st.number_input(
        "Kapacitet (MWh)", 
        min_value=0.1, 
        max_value=100.0, 
        value=1.0,
        step=0.1,
        help="Ukupni kapacitet baterije u MWh"
    )
    
    POWER_MW = st.number_input(
        "Snaga (MW)", 
        min_value=0.1, 
        max_value=10.0, 
        value=1.0,
        step=0.1,
        help="Maksimalna snaga punjenja/pražnjenja u MW"
    )
    
    st.markdown("---")
    st.subheader("⚡ Efikasnost")
    
    col1, col2 = st.columns(2)
    with col1:
        ETA_CH = st.number_input(
            "Punjenje", 
            min_value=0.5, 
            max_value=1.0, 
            value=0.95,
            step=0.01,
            help="Efikasnost punjenja (0-1)"
        )
    with col2:
        ETA_DIS = st.number_input(
            "Pražnjenje", 
            min_value=0.5, 
            max_value=1.0, 
            value=0.95,
            step=0.01,
            help="Efikasnost pražnjenja (0-1)"
        )
    
    st.markdown("---")
    st.subheader("☀️ Solarni paneli")
    
    SOLAR_POWER_MW = st.number_input(
        "Instalisana snaga (MW)", 
        min_value=0.1, 
        max_value=10.0, 
        value=1.0,
        step=0.1,
        help="Maksimalna snaga solarnih panela pri punom suncu"
    )
    
    st.markdown("---")
    st.subheader("⏰ Vremenska ograničenja")
    
    MIN_SELL_HOUR = st.number_input(
        "Najranija prodaja (sat)", 
        min_value=0, 
        max_value=23, 
        value=0,
        help="Ne prodaji prije ovog sata"
    )
    
    st.markdown("---")
    st.info("📁 Fajlovi se učitavaju automatski:\n- cijene.txt\n- solarni_podaci.csv")

# ---------------------------------------------------------
# UČITAVANJE PODATAKA
# ---------------------------------------------------------
# Učitaj cijene
try:
    with open("cijene.txt", "r", encoding="utf-8") as f:
        price_text = f.read()
    st.success("✅ Učitan cijene.txt")
    
    prices_by_day = defaultdict(list)
    price_times_by_day = defaultdict(list)
    
    for line in price_text.splitlines():
        parsed = parse_price_line(line)
        if parsed:
            time, price = parsed
            d = time.date()
            price_times_by_day[d].append(time)
            prices_by_day[d].append(price)
    
    st.info(f"📊 Cijene: {len(prices_by_day)} dana")
except FileNotFoundError:
    st.error("❌ Nedostaje cijene.txt")
    st.stop()

# Učitaj solarne podatke
try:
    with open("solarni_podaci.csv", "r", encoding="utf-8") as f:
        solar_text = f.read()
    st.success("✅ Učitan solarni_podaci.csv")
    
    solar_by_day = defaultdict(list)
    solar_times_by_day = defaultdict(list)
    
    for line in solar_text.splitlines():
        parsed = parse_solar_line(line)
        if parsed:
            time, sunshine = parsed
            d = time.date()
            solar_times_by_day[d].append(time)
            solar_by_day[d].append(sunshine)
    
    st.info(f"📊 Solarni: {len(solar_by_day)} dana")
except FileNotFoundError:
    st.error("❌ Nedostaje solarni_podaci.csv")
    st.stop()

# ---------------------------------------------------------
# UZMI ZAJEDNIČKE DANE
# ---------------------------------------------------------
common_dates = sorted(set(solar_by_day.keys()) & set(prices_by_day.keys()))
st.info(f"📅 Zajedničkih dana: {len(common_dates)}")

if len(common_dates) == 0:
    st.error("Nema zajedničkih dana!")
    st.stop()

# ---------------------------------------------------------
# SIMULACIJA SA DETALJIMA
# ---------------------------------------------------------
def solar_production(sunshine_sec):
    """
    Računa koliko energije solarni paneli proizvedu u 15-min intervalu.
    """
    if sunshine_sec <= 0:
        return 0.0
    
    sun_factor = sunshine_sec / 3600.0
    power_in_interval = SOLAR_POWER_MW * sun_factor
    energy = power_in_interval * 0.25
    
    return energy

def simulate_day(prices, sunshine):
    """Punjenje iz solara + direktna prodaja"""
    # Proširi sunčanost na 15-min
    sun_15min = []
    for s in sunshine:
        sun_15min.extend([s] * 4)
    
    # Izračunaj solarnu proizvodnju za svaki interval
    solar_energy_15min = []
    solar_power_15min = []
    total_produced = 0.0  # UKUPNO PROIZVEDENO
    
    for s in sun_15min[:96]:
        energy = solar_production(s)
        solar_energy_15min.append(energy)
        solar_power_15min.append(energy / 0.25 if energy > 0 else 0)
        total_produced += energy
    
    # Parametri
    max_charge_per_interval = POWER_MW * 0.25
    max_discharge_per_interval = POWER_MW * 0.25
    
    soc = 0.0
    soc_history = [0.0]
    actions = []
    total_charged = 0.0
    charge_intervals = []
    
    # DIREKTNA PRODAJA
    direct_sale_revenue = 0.0
    direct_sale_energy = 0.0
    
    # Punjenje - redom kroz dan
    for i in range(96):
        solar = solar_energy_15min[i]
        
        # Prvo punimo bateriju ako ima mjesta
        if solar > 0 and soc < CAPACITY_MWH:
            space = CAPACITY_MWH - soc
            charge = min(solar * ETA_CH, max_charge_per_interval, space)
            
            if charge > 0:
                soc += charge
                total_charged += charge
                charge_intervals.append(i)
                actions.append({
                    'interval': i,
                    'tip': 'punjenje',
                    'energija': charge,
                    'solar': solar,
                    'cijena': prices[i],
                    'soc': soc
                })
                
                # Ostatak solarne energije ide u direktnu prodaju
                remaining_solar = solar - (charge / ETA_CH)
                if remaining_solar > 0:
                    direct_sale_revenue += remaining_solar * prices[i]
                    direct_sale_energy += remaining_solar
                    actions.append({
                        'interval': i,
                        'tip': 'direktna prodaja',
                        'energija': remaining_solar,
                        'cijena': prices[i],
                        'soc': soc
                    })
            else:
                # Ne možemo puniti, sve ide u direktnu prodaju
                direct_sale_revenue += solar * prices[i]
                direct_sale_energy += solar
                actions.append({
                    'interval': i,
                    'tip': 'direktna prodaja',
                    'energija': solar,
                    'cijena': prices[i],
                    'soc': soc
                })
        elif solar > 0:
            # Baterija puna, sve ide u direktnu prodaju
            direct_sale_revenue += solar * prices[i]
            direct_sale_energy += solar
            actions.append({
                'interval': i,
                'tip': 'direktna prodaja',
                'energija': solar,
                'cijena': prices[i],
                'soc': soc
            })
        
        soc_history.append(soc)
    
    # Prodaja iz baterije
    battery_sale_profit = 0
    battery_sale_price = 0
    battery_sale_intervals = []
    battery_sale_energy = 0  # ISPORUČENO IZ BATERIJE
    remaining = soc
    
    if charge_intervals and soc > 0:
        last_charge = charge_intervals[-1]
        
        sell_candidates = []
        for i in range(last_charge + 1, 96):
            if i // 4 >= MIN_SELL_HOUR and prices[i] > 0:
                sell_candidates.append((i, prices[i]))
        
        sell_candidates.sort(key=lambda x: x[1], reverse=True)
        
        for interval, price in sell_candidates:
            if remaining <= 0:
                break
            
            sell_amount = min(remaining, max_discharge_per_interval)
            if sell_amount > 0:
                sell_energy = sell_amount * ETA_DIS
                battery_sale_profit += sell_energy * price
                battery_sale_energy += sell_energy  # ISPORUČENO U MREŽU
                remaining -= sell_amount
                battery_sale_intervals.append(interval)
                
                actions.append({
                    'interval': interval,
                    'tip': 'praznjenje',
                    'energija': sell_amount,
                    'cijena': price,
                    'soc': remaining
                })
                
                for j in range(interval + 1, 97):
                    if j < len(soc_history):
                        soc_history[j] = remaining
        
        if battery_sale_intervals:
            battery_sale_price = np.mean([p for i, p in sell_candidates if i in battery_sale_intervals])
    
    # UKUPNO ISPORUČENO = direktna prodaja + prodaja iz baterije
    total_delivered = direct_sale_energy + battery_sale_energy
    total_revenue = direct_sale_revenue + battery_sale_profit
    
    return {
        'total_produced': total_produced,              # Proizvedeno iz solara
        'total_delivered': total_delivered,            # UKUPNO ISPORUČENO U MREŽU
        'direct_sale_energy': direct_sale_energy,
        'direct_sale_revenue': direct_sale_revenue,
        'battery_charged': total_charged,
        'battery_sold': battery_sale_energy,           # ISPORUČENO IZ BATERIJE
        'battery_profit': battery_sale_profit,
        'total_revenue': total_revenue,
        'battery_sale_price': battery_sale_price,
        'battery_sale_intervals': battery_sale_intervals,
        'charge_intervals': charge_intervals,
        'actions': actions,
        'soc_history': soc_history,
        'solar_power': solar_power_15min,
        'prices': prices,
        'final_soc': remaining
    }

# ---------------------------------------------------------
# IZRAČUNAJ SVE DANE
# ---------------------------------------------------------
results = {}
charge_hours = []
sell_hours = []
direct_sell_hours = []

progress_bar = st.progress(0)

for i, date in enumerate(common_dates):
    prices = prices_by_day[date]
    sunshine = solar_by_day[date]
    
    if len(prices) == 96 and len(sunshine) == 24:
        res = simulate_day(prices, sunshine)
        results[date] = res
        
        if res['battery_charged'] > 0 and res['charge_intervals']:
            charge_hours.append(res['charge_intervals'][0] // 4)
        if res['battery_sale_intervals']:
            for interval in res['battery_sale_intervals']:
                sell_hours.append(interval // 4)
        
        for a in res['actions']:
            if a['tip'] == 'direktna prodaja':
                direct_sell_hours.append(a['interval'] // 4)
    
    progress_bar.progress((i + 1) / len(common_dates))

progress_bar.empty()

# ---------------------------------------------------------
# TABELA REZULTATA - DODATA total_delivered
# ---------------------------------------------------------
daily_results = []
for date in common_dates:
    if date in results:
        r = results[date]
        
        daily_results.append({
            'Datum': date,
            'Proizvedeno (MWh)': round(r['total_produced'], 3),
            'Isporučeno (MWh)': round(r['total_delivered'], 3),  # NOVO
            'Ukupni prihod (€)': round(r['total_revenue'], 2),
            'Direktno (MWh)': round(r['direct_sale_energy'], 3),
            'Iz baterije (MWh)': round(r['battery_sold'], 3),
            'Direktni prihod (€)': round(r['direct_sale_revenue'], 2),
            'Baterija prihod (€)': round(r['battery_profit'], 2),
            'Cijena (€/MWh)': round(r['battery_sale_price'], 2)
        })

df = pd.DataFrame(daily_results)
st.subheader("📊 Rezultati po danima")
st.dataframe(df, use_container_width=True, hide_index=True)

# ---------------------------------------------------------
# GRAFIKONI - DODAT grafikoni za isporučenu energiju
# ---------------------------------------------------------
col1, col2 = st.columns(2)

with col1:
    st.subheader("💰 Prihod po danima")
    fig1 = go.Figure()
    fig1.add_trace(go.Bar(
        x=df['Datum'],
        y=df['Ukupni prihod (€)'],
        name='Ukupno',
        marker_color='green',
        text=df['Ukupni prihod (€)'].round(1),
        textposition='outside'
    ))
    fig1.add_trace(go.Bar(
        x=df['Datum'],
        y=df['Direktni prihod (€)'],
        name='Direktno',
        marker_color='orange'
    ))
    fig1.add_trace(go.Bar(
        x=df['Datum'],
        y=df['Baterija prihod (€)'],
        name='Iz baterije',
        marker_color='blue'
    ))
    fig1.update_layout(
        height=400, 
        xaxis_tickangle=45,
        barmode='group',
        title='Poređenje prihoda'
    )
    st.plotly_chart(fig1, use_container_width=True)

with col2:
    st.subheader("🔋 Energija po danima")
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        x=df['Datum'],
        y=df['Proizvedeno (MWh)'],
        name='Proizvedeno',
        marker_color='yellow',
        text=df['Proizvedeno (MWh)'].round(2),
        textposition='outside'
    ))
    fig2.add_trace(go.Bar(
        x=df['Datum'],
        y=df['Isporučeno (MWh)'],
        name='Isporučeno',
        marker_color='lightgreen'
    ))
    fig2.update_layout(
        height=400, 
        xaxis_tickangle=45,
        barmode='group',
        title='Proizvedeno vs Isporučeno'
    )
    st.plotly_chart(fig2, use_container_width=True)

# Dodatni grafikon - raspodjela isporuke
st.subheader("📊 Isporučena energija - izvor")
fig3 = go.Figure()
fig3.add_trace(go.Bar(
    x=df['Datum'],
    y=df['Direktno (MWh)'],
    name='Direktno iz solara',
    marker_color='orange',
    text=df['Direktno (MWh)'].round(2),
    textposition='inside'
))
fig3.add_trace(go.Bar(
    x=df['Datum'],
    y=df['Iz baterije (MWh)'],
    name='Iz baterije',
    marker_color='blue',
    text=df['Iz baterije (MWh)'].round(2),
    textposition='inside'
))
fig3.update_layout(
    height=400,
    xaxis_tickangle=45,
    barmode='stack',
    title='Odakle dolazi isporučena energija'
)
st.plotly_chart(fig3, use_container_width=True)

# ---------------------------------------------------------
# DETALJNA ANALIZA IZABRANOG DANA
# ---------------------------------------------------------
st.markdown("---")
st.subheader("🔍 Detaljna analiza dana")

if len(df) > 0:
    selected_date = st.selectbox(
        "Izaberi dan za detaljni prikaz:",
        options=df['Datum'],
        format_func=lambda x: x.strftime('%Y-%m-%d')
    )
    
    if selected_date and selected_date in results:
        data = results[selected_date]
        
        times = []
        base_time = datetime.combine(selected_date, datetime.min.time())
        for i in range(96):
            times.append(base_time + timedelta(minutes=i*15))
        
        # KPI metrike - dodata isporučena energija
        col1, col2, col3, col4, col5 = st.columns(5)
        
        day_data = df[df['Datum'] == selected_date].iloc[0]
        col1.metric("💰 Ukupno", f"{day_data['Ukupni prihod (€)']} €")
        col2.metric("☀️ Proizvedeno", f"{day_data['Proizvedeno (MWh)']} MWh")
        col3.metric("📤 Isporučeno", f"{day_data['Isporučeno (MWh)']} MWh")  # NOVO
        col4.metric("🔋 U bateriju", f"{day_data['Direktno (MWh)']} MWh")
        col5.metric("⚡ Cijena", f"{day_data['Cijena (€/MWh)']} €/MWh")
        
        # DETALJNI GRAFIKON
        fig = go.Figure()
        
        # Cijene (desna osa)
        fig.add_trace(go.Scatter(
            x=times,
            y=data['prices'],
            mode='lines',
            name='Cijena',
            line=dict(color='orange', width=2),
            yaxis='y2'
        ))
        
        # Solarna snaga
        fig.add_trace(go.Bar(
            x=times,
            y=data['solar_power'],
            name='Solarna snaga',
            marker_color='yellow',
            opacity=0.5
        ))
        
        # Direktna prodaja
        direct_times = []
        direct_values = []
        for a in data['actions']:
            if a['tip'] == 'direktna prodaja':
                direct_times.append(times[a['interval']])
                direct_values.append(a['energija'] / 0.25)
        
        if direct_times:
            fig.add_trace(go.Bar(
                x=direct_times,
                y=direct_values,
                name='Direktna prodaja',
                marker_color='orange',
                opacity=0.7
            ))
        
        # Punjenje
        charge_times = []
        charge_values = []
        for a in data['actions']:
            if a['tip'] == 'punjenje':
                charge_times.append(times[a['interval']])
                charge_values.append(a['energija'] / 0.25)
        
        if charge_times:
            fig.add_trace(go.Bar(
                x=charge_times,
                y=charge_values,
                name='Punjenje',
                marker_color='green',
                opacity=0.7
            ))
        
        # Pražnjenje
        discharge_times = []
        discharge_values = []
        for a in data['actions']:
            if a['tip'] == 'praznjenje':
                discharge_times.append(times[a['interval']])
                discharge_values.append(a['energija'] / 0.25)
        
        if discharge_times:
            fig.add_trace(go.Bar(
                x=discharge_times,
                y=discharge_values,
                name='Pražnjenje',
                marker_color='red',
                opacity=0.7
            ))
        
        # SoC
        fig.add_trace(go.Scatter(
            x=times + [times[-1] + timedelta(minutes=15)],
            y=data['soc_history'],
            mode='lines+markers',
            name='SoC',
            line=dict(color='cyan', width=3),
            marker=dict(size=4)
        ))
        
        fig.update_layout(
            title=f'Detaljna analiza za {selected_date}',
            xaxis_title='Vrijeme',
            yaxis_title='Snaga (MW)',
            yaxis2=dict(
                title='Cijena (€/MWh)',
                overlaying='y',
                side='right'
            ),
            hovermode='x unified',
            height=600,
            barmode='group'
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # TABELA AKCIJA
        st.markdown("### 📝 Detaljne akcije")
        
        actions_df = pd.DataFrame([{
            'Vrijeme': times[a['interval']].strftime('%H:%M'),
            'Akcija': a['tip'],
            'Energija (MWh)': round(a['energija'], 3),
            'Cijena (€/MWh)': round(a['cijena'], 2),
            'SoC (MWh)': round(a['soc'], 3)
        } for a in data['actions']])
        
        st.dataframe(actions_df, use_container_width=True, hide_index=True)

# ---------------------------------------------------------
# STATISTIKA SATI
# ---------------------------------------------------------
st.markdown("---")
col1, col2 = st.columns(2)

with col1:
    st.subheader("🔋 Sat početka punjenja")
    if charge_hours:
        charge_counts = pd.Series(charge_hours).value_counts().sort_index()
        fig4 = go.Figure()
        fig4.add_trace(go.Bar(
            x=charge_counts.index,
            y=charge_counts.values,
            marker_color='green'
        ))
        fig4.update_layout(
            title='Kada počinje punjenje baterije',
            xaxis_title='Sat',
            yaxis_title='Broj dana',
            xaxis=dict(tickmode='linear', tick0=0, dtick=1)
        )
        st.plotly_chart(fig4, use_container_width=True)
    else:
        st.info("Nema podataka")

with col2:
    st.subheader("⚡ Satovi prodaje iz baterije")
    if sell_hours:
        sell_counts = pd.Series(sell_hours).value_counts().sort_index()
        fig5 = go.Figure()
        fig5.add_trace(go.Bar(
            x=sell_counts.index,
            y=sell_counts.values,
            marker_color='red'
        ))
        fig5.update_layout(
            title='Kada se prodaje energija iz baterije',
            xaxis_title='Sat',
            yaxis_title='Broj intervala',
            xaxis=dict(tickmode='linear', tick0=0, dtick=1)
        )
        st.plotly_chart(fig5, use_container_width=True)
    else:
        st.info("Nema podataka")

st.subheader("☀️ Direktna prodaja po satima")
if direct_sell_hours:
    direct_counts = pd.Series(direct_sell_hours).value_counts().sort_index()
    fig6 = go.Figure()
    fig6.add_trace(go.Bar(
        x=direct_counts.index,
        y=direct_counts.values,
        marker_color='orange'
    ))
    fig6.update_layout(
        title='Kada se direktno prodaje solarna energija',
        xaxis_title='Sat',
        yaxis_title='Broj intervala',
        xaxis=dict(tickmode='linear', tick0=0, dtick=1)
    )
    st.plotly_chart(fig6, use_container_width=True)
else:
    st.info("Nema podataka")

# ---------------------------------------------------------
# UKUPNI REZULTATI - dodati za isporučenu energiju
# ---------------------------------------------------------
st.markdown("---")
col1, col2, col3, col4, col5 = st.columns(5)

total_produced = df['Proizvedeno (MWh)'].sum()
total_delivered = df['Isporučeno (MWh)'].sum()
total_revenue = df['Ukupni prihod (€)'].sum()
total_direct = df['Direktni prihod (€)'].sum()
total_battery = df['Baterija prihod (€)'].sum()

col1.metric("☀️ Proizvedeno", f"{total_produced:.2f} MWh")
col2.metric("📤 Isporučeno", f"{total_delivered:.2f} MWh")
col3.metric("💰 Ukupan prihod", f"{total_revenue:.2f} €")
col4.metric("📊 Iskorištenje", f"{(total_delivered/total_produced*100):.1f}%" if total_produced > 0 else "0%")
col5.metric("🔋 Udio baterije", f"{(total_battery/total_revenue*100):.1f}%" if total_revenue > 0 else "0%")

# ---------------------------------------------------------
# DOWNLOAD
# ---------------------------------------------------------
st.markdown("---")
csv = df.to_csv(index=False, sep=';', encoding='utf-8')
st.download_button(
    "📥 Preuzmi rezultate (CSV)",
    data=csv,
    file_name="solarno_punjenje_rezultati.csv",
    mime="text/csv"
)

st.markdown("---")
st.markdown("☀️ **Solarno punjenje - Sa isporučenom energijom**")