import os
import sqlite3
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

DB_PATH = "controle_financeiro.db"
CATEGORIAS = [
    "Alimentacao",
    "Transporte",
    "Moradia",
    "Saude",
    "Educacao",
    "Lazer",
    "Salario",
    "Investimentos",
    "Outros",
]


def get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usuario (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                nome TEXT NOT NULL,
                pin TEXT
            )
            """
        )
        ensure_column(conn, "usuario", "pin", "TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS movimentacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                categoria TEXT NOT NULL,
                valor REAL NOT NULL,
                data_hora TEXT NOT NULL
            )
            """
        )


def get_user() -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT nome, COALESCE(pin, '') FROM usuario WHERE id = 1").fetchone()
    if not row:
        return {"nome": "", "pin": ""}
    return {"nome": (row[0] or "").strip(), "pin": (row[1] or "").strip()}


def save_user(nome: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO usuario (id, nome, pin)
            VALUES (1, ?, COALESCE((SELECT pin FROM usuario WHERE id = 1), ''))
            ON CONFLICT(id) DO UPDATE SET nome = excluded.nome
            """,
            (nome,),
        )


def add_movimentacao(tipo: str, descricao: str, categoria: str, valor: float) -> None:
    data_hora = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO movimentacoes (tipo, descricao, categoria, valor, data_hora)
            VALUES (?, ?, ?, ?, ?)
            """,
            (tipo.lower(), descricao, categoria, valor, data_hora),
        )


def load_movimentacoes() -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(
            """
            SELECT id, data_hora, tipo, descricao, categoria, valor
            FROM movimentacoes
            ORDER BY data_hora DESC, id DESC
            """,
            conn,
        )

    if df.empty:
        return df

    df["data_hora"] = pd.to_datetime(df["data_hora"], errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0)
    return df


def compute_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "saldo": 0.0,
            "receitas": 0.0,
            "despesas": 0.0,
        }

    receitas = float(df.loc[df["tipo"] == "receita", "valor"].sum())
    despesas = float(df.loc[df["tipo"] == "despesa", "valor"].sum())
    saldo = receitas - despesas

    return {
        "saldo": saldo,
        "receitas": receitas,
        "despesas": despesas,
    }


def monthly_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["mes", "saldo_mensal"])

    copy_df = df.copy()
    copy_df["sinal"] = copy_df["tipo"].map({"receita": 1, "despesa": -1}).fillna(0)
    copy_df["valor_liquido"] = copy_df["valor"] * copy_df["sinal"]
    copy_df["mes_ref"] = copy_df["data_hora"].dt.to_period("M").astype(str)

    grouped = (
        copy_df.groupby("mes_ref", as_index=False)["valor_liquido"]
        .sum()
        .rename(columns={"mes_ref": "mes", "valor_liquido": "saldo_mensal"})
    )

    grouped = grouped.sort_values("mes")
    return grouped.tail(12)


def format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def apply_custom_css() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.2rem;
            padding-bottom: 1.8rem;
            max-width: 1080px;
        }
        .app-card {
            background: linear-gradient(180deg, rgba(24,26,34,0.92) 0%, rgba(14,16,22,0.92) 100%);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 18px;
            padding: 1rem 1.1rem;
            margin-bottom: 0.9rem;
        }
        .app-subtitle {
            color: #b6bdd0;
            margin-top: -0.35rem;
            margin-bottom: 0.6rem;
        }
        .stButton > button {
            border-radius: 12px;
            font-weight: 600;
            border: 1px solid rgba(255,255,255,0.10);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_cadastro() -> None:
    st.markdown("### Primeiro acesso")
    st.markdown("Informe seu nome para liberar o painel financeiro.")

    with st.form("cadastro_usuario", clear_on_submit=False):
        nome = st.text_input("Nome", max_chars=60, placeholder="Digite seu nome")
        salvar = st.form_submit_button("Salvar e continuar", use_container_width=True)

    if salvar:
        nome = nome.strip()
        if len(nome) < 2:
            st.error("Digite um nome valido com pelo menos 2 caracteres.")
            return
        save_user(nome)
        st.success("Cadastro concluido.")
        st.rerun()


def render_dashboard(nome: str) -> None:
    st.markdown(f"## Ola, {nome}")
    st.markdown("<p class='app-subtitle'>Painel financeiro pessoal</p>", unsafe_allow_html=True)

    df = load_movimentacoes()
    metrics = compute_metrics(df)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Saldo atual", format_brl(metrics["saldo"]))
    c2.metric("Receita total", format_brl(metrics["receitas"]))
    c3.metric("Despesa total", format_brl(metrics["despesas"]))
    c4.metric("Movimentacoes", f"{len(df)}")

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("### Nova movimentacao")

    with st.form("nova_movimentacao", clear_on_submit=True):
        col1, col2 = st.columns(2)
        tipo = col1.selectbox("Tipo", ["Receita", "Despesa"], index=0)
        categoria = col2.selectbox("Categoria", CATEGORIAS, index=0)

        descricao = st.text_input("Descricao", placeholder="Ex: Mercado do mes")
        valor = st.number_input("Valor", min_value=0.0, step=1.0, format="%.2f")

        salvar = st.form_submit_button("Salvar movimentacao", use_container_width=True)

    if salvar:
        descricao_limpa = descricao.strip() or "Sem descricao"
        if valor <= 0:
            st.error("Informe um valor maior que zero.")
        else:
            add_movimentacao(tipo=tipo, descricao=descricao_limpa, categoria=categoria, valor=float(valor))
            st.success("Movimentacao salva com sucesso.")
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("### Grafico mensal interativo")
    monthly_df = monthly_dataframe(df)

    if monthly_df.empty:
        st.info("Ainda nao ha dados para o grafico mensal.")
    else:
        monthly_df["tipo_saldo"] = monthly_df["saldo_mensal"].apply(lambda x: "Positivo" if x >= 0 else "Negativo")
        fig = px.bar(
            monthly_df,
            x="mes",
            y="saldo_mensal",
            color="tipo_saldo",
            color_discrete_map={"Positivo": "#30c48d", "Negativo": "#ef5c6d"},
            title="Saldo liquido por mes",
        )
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend_title_text="",
            margin=dict(l=20, r=20, t=50, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Historico completo")
    if df.empty:
        st.info("Nenhuma movimentacao cadastrada.")
    else:
        exibir = df.copy()
        exibir["data"] = exibir["data_hora"].dt.strftime("%d/%m/%Y %H:%M")
        exibir["tipo"] = exibir["tipo"].str.capitalize()
        exibir["valor"] = exibir["valor"].map(format_brl)
        exibir = exibir[["data", "tipo", "descricao", "categoria", "valor"]]
        st.dataframe(exibir, use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(
        page_title="Controle Financeiro Web",
        page_icon="icon.png" if os.path.exists("icon.png") else "💰",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    init_db()
    apply_custom_css()

    user = get_user()
    if not user["nome"]:
        render_cadastro()
        return

    render_dashboard(user["nome"])


if __name__ == "__main__":
    main()
