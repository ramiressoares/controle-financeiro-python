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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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


def init_session_state() -> None:
    st.session_state.setdefault("editing_id", None)
    st.session_state.setdefault("delete_confirm_id", None)


def reset_action_state() -> None:
    st.session_state["editing_id"] = None
    st.session_state["delete_confirm_id"] = None


def get_user() -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT nome, COALESCE(pin, '') AS pin FROM usuario WHERE id = 1").fetchone()
    if not row:
        return {"nome": "", "pin": ""}
    return {"nome": (row["nome"] or "").strip(), "pin": (row["pin"] or "").strip()}


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
            (tipo.lower(), descricao.strip(), categoria, valor, data_hora),
        )


def buscar_movimento(movimento_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, data_hora, tipo, descricao, categoria, valor
            FROM movimentacoes
            WHERE id = ?
            """,
            (movimento_id,),
        ).fetchone()

    if not row:
        return None

    return {
        "id": int(row["id"]),
        "data_hora": row["data_hora"],
        "tipo": row["tipo"],
        "descricao": row["descricao"],
        "categoria": row["categoria"],
        "valor": float(row["valor"]),
    }


def editar_movimento(movimento_id: int, tipo: str, descricao: str, categoria: str, valor: float) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE movimentacoes
            SET tipo = ?, descricao = ?, categoria = ?, valor = ?
            WHERE id = ?
            """,
            (tipo.lower(), descricao.strip(), categoria, valor, movimento_id),
        )
    return cursor.rowcount > 0


def excluir_movimento(movimento_id: int) -> bool:
    with get_conn() as conn:
        cursor = conn.execute("DELETE FROM movimentacoes WHERE id = ?", (movimento_id,))
    return cursor.rowcount > 0


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
        return pd.DataFrame(columns=["mes", "mes_label", "saldo_mensal"])

    copy_df = df.copy()
    copy_df["sinal"] = copy_df["tipo"].map({"receita": 1, "despesa": -1}).fillna(0)
    copy_df["valor_liquido"] = copy_df["valor"] * copy_df["sinal"]
    copy_df["mes_ref"] = copy_df["data_hora"].dt.to_period("M")

    grouped = (
        copy_df.groupby("mes_ref", as_index=False)["valor_liquido"]
        .sum()
        .rename(columns={"mes_ref": "mes", "valor_liquido": "saldo_mensal"})
    )

    grouped = grouped.sort_values("mes")
    grouped["mes_label"] = grouped["mes"].dt.strftime("%m/%Y")
    grouped["mes"] = grouped["mes"].astype(str)
    return grouped.tail(12)


def format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_data_hora(value) -> str:
    if pd.isna(value):
        return "Data indisponivel"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%d/%m/%Y %H:%M")
    try:
        return pd.to_datetime(value).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return str(value)


def validate_movimentacao(descricao: str, valor: float) -> str:
    if not descricao.strip():
        return "Informe uma descricao para a movimentacao."
    if valor <= 0:
        return "Informe um valor maior que zero."
    return ""


def start_edit(movimento_id: int) -> None:
    st.session_state["editing_id"] = movimento_id
    st.session_state["delete_confirm_id"] = None


def request_delete(movimento_id: int) -> None:
    st.session_state["delete_confirm_id"] = movimento_id
    st.session_state["editing_id"] = None


def cancel_edit() -> None:
    st.session_state["editing_id"] = None


def cancel_delete() -> None:
    st.session_state["delete_confirm_id"] = None


def apply_custom_css() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: radial-gradient(circle at top, rgba(24, 31, 48, 0.88) 0%, #090b11 45%, #06070b 100%);
        }
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
            box-shadow: 0 14px 40px rgba(0, 0, 0, 0.26);
        }
        .app-subtitle {
            color: #b6bdd0;
            margin-top: -0.35rem;
            margin-bottom: 0.6rem;
        }
        .history-card {
            background: linear-gradient(180deg, rgba(17, 20, 28, 0.95) 0%, rgba(12, 14, 20, 0.96) 100%);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 18px;
            padding: 0.95rem 1rem;
            margin-bottom: 0.8rem;
        }
        .history-meta {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.8rem;
            margin-bottom: 0.5rem;
            flex-wrap: wrap;
        }
        .history-badge {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.28rem 0.7rem;
            font-size: 0.82rem;
            font-weight: 700;
            letter-spacing: 0.01em;
        }
        .history-badge.receita {
            background: rgba(48, 196, 141, 0.18);
            color: #5be0a9;
        }
        .history-badge.despesa {
            background: rgba(239, 92, 109, 0.16);
            color: #ff7d8d;
        }
        .history-date {
            color: #9aa7c2;
            font-size: 0.9rem;
        }
        .history-description {
            color: #f5f7ff;
            font-size: 1.05rem;
            font-weight: 600;
            margin-bottom: 0.2rem;
            word-break: break-word;
        }
        .history-category {
            color: #b6bdd0;
            font-size: 0.92rem;
            margin-bottom: 0.65rem;
        }
        .history-value {
            font-size: 1.02rem;
            font-weight: 700;
        }
        .history-value.receita {
            color: #5be0a9;
        }
        .history-value.despesa {
            color: #ff7d8d;
        }
        .confirm-box {
            background: rgba(255, 196, 61, 0.08);
            border: 1px solid rgba(255, 196, 61, 0.18);
            border-radius: 14px;
            padding: 0.85rem 0.95rem;
            margin-top: 0.75rem;
        }
        .stButton > button,
        .stFormSubmitButton > button {
            border-radius: 12px;
            font-weight: 600;
            border: 1px solid rgba(255,255,255,0.10);
            min-height: 2.6rem;
        }
        div[data-testid="column"] .stButton > button,
        div[data-testid="column"] .stFormSubmitButton > button {
            width: 100%;
        }
        @media (max-width: 640px) {
            .app-card,
            .history-card {
                padding: 0.9rem;
                border-radius: 16px;
            }
            .history-meta {
                gap: 0.45rem;
            }
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


def render_nova_movimentacao() -> None:
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
        mensagem_validacao = validate_movimentacao(descricao, float(valor))
        if mensagem_validacao:
            st.error(mensagem_validacao)
        else:
            add_movimentacao(tipo=tipo, descricao=descricao, categoria=categoria, valor=float(valor))
            st.success("Movimentacao salva com sucesso.")
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def render_grafico(df: pd.DataFrame) -> None:
    st.markdown("### 📈 Evolucao Financeira Mensal")
    monthly_df = monthly_dataframe(df)

    if monthly_df.empty:
        st.info("Sem dados suficientes para gerar grafico")
        return

    monthly_df = monthly_df.copy()
    monthly_df["tipo_saldo"] = monthly_df["saldo_mensal"].apply(lambda x: "Positivo" if x >= 0 else "Negativo")
    monthly_df["cor_barra"] = monthly_df["saldo_mensal"].apply(lambda x: "#30c48d" if x >= 0 else "#ef5c6d")
    monthly_df["saldo_label"] = monthly_df["saldo_mensal"].map(format_brl)

    fig = px.bar(
        monthly_df,
        x="mes_label",
        y="saldo_mensal",
        color="tipo_saldo",
        color_discrete_map={"Positivo": "#30c48d", "Negativo": "#ef5c6d"},
        custom_data=["mes_label", "saldo_label"],
    )
    fig.update_traces(
        width=0.58 if len(monthly_df) == 1 else 0.72,
        marker_line_width=0,
        marker=dict(color=monthly_df["cor_barra"].tolist()),
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Saldo liquido: %{customdata[1]}<extra></extra>"
        ),
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        bargap=0.28 if len(monthly_df) > 1 else 0.72,
        bargroupgap=0.0,
        barcornerradius=10,
        hoverlabel=dict(
            bgcolor="rgba(12,16,24,0.96)",
            bordercolor="rgba(255,255,255,0.10)",
            font=dict(color="#f5f7ff", size=13),
        ),
        margin=dict(l=10, r=10, t=20, b=10),
        transition=dict(duration=450, easing="cubic-in-out"),
        xaxis=dict(
            title=None,
            type="category",
            categoryorder="array",
            categoryarray=monthly_df["mes_label"].tolist(),
            tickfont=dict(size=12, color="#b6bdd0"),
            showgrid=False,
            fixedrange=True,
            tickangle=0,
        ),
        yaxis=dict(
            title=None,
            tickprefix="R$ ",
            tickfont=dict(size=12, color="#b6bdd0"),
            zeroline=True,
            zerolinecolor="rgba(255,255,255,0.14)",
            zerolinewidth=1,
            gridcolor="rgba(255,255,255,0.08)",
            griddash="dot",
            fixedrange=True,
        ),
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "displayModeBar": False,
            "responsive": True,
        },
    )


def render_edit_form(movimento: dict) -> None:
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown(f"### Editar movimentacao #{movimento['id']}")

    tipo_atual = "Receita" if movimento["tipo"] == "receita" else "Despesa"
    categoria_atual = movimento["categoria"] if movimento["categoria"] in CATEGORIAS else CATEGORIAS[0]

    with st.form(f"form_editar_{movimento['id']}", clear_on_submit=False):
        col1, col2 = st.columns(2)
        tipo = col1.selectbox(
            "Tipo",
            ["Receita", "Despesa"],
            index=0 if tipo_atual == "Receita" else 1,
            key=f"editar_tipo_{movimento['id']}",
        )
        categoria = col2.selectbox(
            "Categoria",
            CATEGORIAS,
            index=CATEGORIAS.index(categoria_atual),
            key=f"editar_categoria_{movimento['id']}",
        )
        descricao = st.text_input(
            "Descricao",
            value=movimento["descricao"],
            key=f"editar_descricao_{movimento['id']}",
        )
        valor = st.number_input(
            "Valor",
            min_value=0.0,
            value=float(movimento["valor"]),
            step=1.0,
            format="%.2f",
            key=f"editar_valor_{movimento['id']}",
        )

        acao_col1, acao_col2 = st.columns(2)
        salvar = acao_col1.form_submit_button("Salvar Alteracoes", use_container_width=True)
        cancelar = acao_col2.form_submit_button("Cancelar", use_container_width=True)

    if cancelar:
        cancel_edit()
        st.rerun()

    if salvar:
        mensagem_validacao = validate_movimentacao(descricao, float(valor))
        if mensagem_validacao:
            st.error(mensagem_validacao)
        else:
            atualizado = editar_movimento(
                movimento["id"],
                tipo=tipo,
                descricao=descricao,
                categoria=categoria,
                valor=float(valor),
            )
            if atualizado:
                reset_action_state()
                st.success("Movimentacao atualizada com sucesso.")
                st.rerun()
            st.error("Nao foi possivel atualizar esta movimentacao.")

    st.markdown("</div>", unsafe_allow_html=True)


def render_movimento_card(row: pd.Series) -> None:
    movimento_id = int(row["id"])
    tipo = str(row["tipo"])
    tipo_label = "Receita" if tipo == "receita" else "Despesa"
    badge_class = "receita" if tipo == "receita" else "despesa"

    st.markdown("<div class='history-card'>", unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class='history-meta'>
            <span class='history-badge {badge_class}'>{tipo_label}</span>
            <span class='history-date'>{format_data_hora(row['data_hora'])}</span>
        </div>
        <div class='history-description'>{row['descricao']}</div>
        <div class='history-category'>Categoria: {row['categoria']}</div>
        <div class='history-value {badge_class}'>{format_brl(float(row['valor']))}</div>
        """,
        unsafe_allow_html=True,
    )

    acao_col1, acao_col2 = st.columns(2)
    if acao_col1.button("✏️ Editar", key=f"editar_btn_{movimento_id}", use_container_width=True):
        start_edit(movimento_id)
        st.rerun()
    if acao_col2.button("🗑️ Excluir", key=f"excluir_btn_{movimento_id}", use_container_width=True):
        request_delete(movimento_id)
        st.rerun()

    if st.session_state.get("delete_confirm_id") == movimento_id:
        st.markdown("<div class='confirm-box'>", unsafe_allow_html=True)
        st.warning("Confirmar exclusao desta movimentacao?")
        confirmar_col1, confirmar_col2 = st.columns(2)
        if confirmar_col1.button("Confirmar exclusao", key=f"confirmar_excluir_{movimento_id}", use_container_width=True):
            removido = excluir_movimento(movimento_id)
            if removido:
                reset_action_state()
                st.success("Movimentacao excluida com sucesso.")
                st.rerun()
            st.error("Nao foi possivel excluir esta movimentacao.")
        if confirmar_col2.button("Cancelar", key=f"cancelar_excluir_{movimento_id}", use_container_width=True):
            cancel_delete()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


def render_historico(df: pd.DataFrame) -> None:
    st.markdown("### Historico completo")

    editing_id = st.session_state.get("editing_id")
    if editing_id is not None:
        movimento = buscar_movimento(int(editing_id))
        if movimento is None:
            cancel_edit()
            st.warning("A movimentacao em edicao nao foi encontrada.")
        else:
            render_edit_form(movimento)

    if df.empty:
        st.info("Nenhuma movimentacao cadastrada.")
        return

    for _, row in df.iterrows():
        render_movimento_card(row)


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

    render_nova_movimentacao()
    render_grafico(df)
    render_historico(df)


def main() -> None:
    st.set_page_config(
        page_title="Controle Financeiro Web",
        page_icon="icon.png" if os.path.exists("icon.png") else "💰",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    init_db()
    init_session_state()
    apply_custom_css()

    user = get_user()
    if not user["nome"]:
        render_cadastro()
        return

    render_dashboard(user["nome"])


if __name__ == "__main__":
    main()
