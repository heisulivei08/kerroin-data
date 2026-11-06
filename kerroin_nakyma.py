"""
Kertoimien kehitys -näkymä (Streamlit). Lukee datan GitHubista tai paikallisesta tiedostosta.
Vaihda DATA_URL omaan repositorioosi: https://raw.githubusercontent.com/KÄYTTÄJÄ/REPO/main/kertoimet.csv
"""
import pandas as pd
import streamlit as st

DATA_URL = "https://raw.githubusercontent.com/heisulivei08/kerroin-data/main/kertoimet.csv"
LOCAL_FILE = "kertoimet.csv"

st.set_page_config(page_title="Kertoimien kehitys", layout="wide")
st.title("Kertoimien kehitys (Pinnacle 1X2)")


@st.cache_data(ttl=300)
def load():
    try:
        df = pd.read_csv(DATA_URL, parse_dates=["ts", "commence"])
    except Exception:
        df = pd.read_csv(LOCAL_FILE, parse_dates=["ts", "commence"])
    return df


try:
    df = load()
except Exception:
    st.error("Dataa ei löydy. Tarkista DATA_URL ja että keräilijä on ajanut vähintään kerran.")
    st.stop()

if df.empty:
    st.info("Ei vielä dataa.")
    st.stop()

league = st.sidebar.selectbox("Liiga", sorted(df["league"].unique()))
only_upcoming = st.sidebar.checkbox("Vain tulevat ottelut", value=True)

d = df[df["league"] == league]
now = pd.Timestamp.now(tz="UTC")
if only_upcoming:
    d = d[d["commence"] > now]

matches = (
    d.groupby("match_id")
    .agg(home=("home", "first"), away=("away", "first"), commence=("commence", "first"))
    .sort_values("commence")
)
if matches.empty:
    st.info("Ei otteluita valitulla suodatuksella.")
    st.stop()

labels = {
    mid: f"{r.commence:%d.%m. %H:%M}  {r.home} – {r.away}" for mid, r in matches.iterrows()
}

mid = st.selectbox("Ottelu", list(labels), format_func=labels.get)
m = d[d["match_id"] == mid].sort_values("ts").set_index("ts")
home, away = matches.loc[mid, "home"], matches.loc[mid, "away"]
chart = m[["o_home", "o_draw", "o_away"]].rename(
    columns={"o_home": home, "o_draw": "Tasapeli", "o_away": away}
)
st.line_chart(chart)

first, last = m.iloc[0], m.iloc[-1]
c1, c2, c3 = st.columns(3)
for col, name, key in [(c1, home, "o_home"), (c2, "Tasapeli", "o_draw"), (c3, away, "o_away")]:
    col.metric(name, f"{last[key]:.2f}", f"{last[key] - first[key]:+.2f} avauksesta")

st.subheader(f"{league}: kertoimien muutos avauksesta")
rows = []
for mid_, g in d.sort_values("ts").groupby("match_id"):
    f, l = g.iloc[0], g.iloc[-1]
    rows.append({
        "Ottelu": labels[mid_],
        "Koti avaus": f.o_home, "Koti nyt": l.o_home,
        "Tasapeli avaus": f.o_draw, "Tasapeli nyt": l.o_draw,
        "Vieras avaus": f.o_away, "Vieras nyt": l.o_away,
        "Koti %": round((l.o_home / f.o_home - 1) * 100, 1),
        "Vieras %": round((l.o_away / f.o_away - 1) * 100, 1),
    })
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
