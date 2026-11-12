"""
Kertoimien kehitys -näkymä (Streamlit). Lukee datan GitHubista tai paikallisesta tiedostosta.
Vaihda DATA_URL omaan repositorioosi: https://raw.githubusercontent.com/KÄYTTÄJÄ/REPO/main/kertoimet.csv
"""
import altair as alt
import pandas as pd
import streamlit as st

DATA_URL = "https://raw.githubusercontent.com/KÄYTTÄJÄ/REPO/main/kertoimet.csv"
LOCAL_FILE = "kertoimet.csv"
TZ = "Europe/Helsinki"

st.set_page_config(page_title="Kertoimien kehitys", layout="wide")
st.title("Kertoimien kehitys (Pinnacle 1X2)")


def stretch(fn, *args, **kwargs):
    """Leveys koko ruudulle sekä uusilla että vanhoilla Streamlit-versioilla."""
    try:
        return fn(*args, width="stretch", **kwargs)
    except TypeError:
        return fn(*args, use_container_width=True, **kwargs)


@st.cache_data(ttl=300)
def load():
    try:
        df = pd.read_csv(DATA_URL)
    except Exception:
        df = pd.read_csv(LOCAL_FILE)
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
    df["commence"] = pd.to_datetime(df["commence"], utc=True, format="ISO8601")
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
    mid: f"{r.commence.tz_convert(TZ):%d.%m. %H:%M}  {r.home} – {r.away}"
    for mid, r in matches.iterrows()
}

mid = st.selectbox("Ottelu", list(labels), format_func=labels.get)
m = d[d["match_id"] == mid].sort_values("ts").copy()
home, away = matches.loc[mid, "home"], matches.loc[mid, "away"]

# Aika Suomen aikaa: ruudulle (naiivi aikaleima) ja vihjetekstiin (valmis merkkijono)
local = m["ts"].dt.tz_convert(TZ)
m["aika_x"] = local.dt.tz_localize(None)
m["aika"] = local.dt.strftime("%d.%m.%Y klo %H:%M")


def curve(col, title):
    """Yksi tulos omana kaaviona, y-akseli zoomattu datan vaihteluun, vihje näyttää ajan ja kertoimen."""
    c = m[["aika_x", "aika", col]].dropna().rename(columns={col: "kerroin"})
    c["kirjuri"] = "Pinnacle"
    lo, hi = float(c["kerroin"].min()), float(c["kerroin"].max())
    pad = max((hi - lo) * 0.2, 0.03)
    return (
        alt.Chart(c, title=title)
        .mark_line(point=alt.OverlayMarkDef(size=80))
        .encode(
            x=alt.X("aika_x:T", title=None, axis=alt.Axis(format="%d.%m. %H:%M", labelAngle=-30)),
            y=alt.Y("kerroin:Q", title=None, scale=alt.Scale(domain=[lo - pad, hi + pad], nice=False),
                    axis=alt.Axis(format=".2f")),
            color=alt.Color("kirjuri:N", legend=None),
            tooltip=[
                alt.Tooltip("aika:N", title="Aika"),
                alt.Tooltip("kirjuri:N", title="Kirjuri"),
                alt.Tooltip("kerroin:Q", title="Kerroin", format=".2f"),
            ],
        )
        .properties(height=170)
    )


for col, title in [("o_home", f"Koti: {home}"), ("o_draw", "Tasapeli"), ("o_away", f"Vieras: {away}")]:
    stretch(st.altair_chart, curve(col, title))

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
stretch(st.dataframe, pd.DataFrame(rows), hide_index=True)
