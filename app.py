import base64
import hashlib
import hmac
import io
import json
import os
import re
import sqlite3
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

DB_PATH = "controle_financeiro.db"
TODOS_OS_MESES = "Todos os meses"
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

# ── PWA: pasta oficial ─────────────────────────────────────────────────────────

_PWA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pwa")


def init_pwa_icons() -> None:
    """Garante os nomes oficiais dos icones dentro da pasta pwa/."""
    os.makedirs(_PWA_DIR, exist_ok=True)

    source_map = {
        "icon-192.png": [
            os.path.join(_PWA_DIR, "icon-192.png"),
            os.path.join(_PWA_DIR, "app financeiro (2).png"),
        ],
        "icon-512.png": [
            os.path.join(_PWA_DIR, "icon-512.png"),
            os.path.join(_PWA_DIR, "app financeiro (1).png"),
        ],
    }

    for filename, candidates in source_map.items():
        source_path = next((candidate for candidate in candidates if os.path.exists(candidate)), None)
        pwa_path = os.path.join(_PWA_DIR, filename)

        if source_path is not None and os.path.abspath(source_path) != os.path.abspath(pwa_path):
            with open(source_path, "rb") as source_file:
                data = source_file.read()
            with open(pwa_path, "wb") as target_file:
                target_file.write(data)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def hash_password(password: str, salt_hex: str | None = None) -> str:
    salt = os.urandom(16) if salt_hex is None else bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    if "$" not in stored_hash:
        return False
    salt_hex, stored_digest = stored_hash.split("$", 1)
    candidate = hash_password(password, salt_hex=salt_hex)
    return hmac.compare_digest(candidate.split("$", 1)[1], stored_digest)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_valid_email(email: str) -> bool:
    return re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email) is not None


def migrate_legacy_data(conn: sqlite3.Connection) -> None:
    legacy_user_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'usuario'"
    ).fetchone()

    if legacy_user_exists:
        legacy_row = conn.execute("SELECT nome FROM usuario WHERE id = 1").fetchone()
    else:
        legacy_row = None

    usuarios_count = conn.execute("SELECT COUNT(*) AS total FROM usuarios").fetchone()["total"]

    if usuarios_count == 0 and legacy_row and (legacy_row["nome"] or "").strip():
        legacy_nome = (legacy_row["nome"] or "").strip()
        legacy_email = "legacy@controle.local"
        legacy_password_hash = hash_password("123456")
        conn.execute(
            """
            INSERT INTO usuarios (nome, email, senha_hash, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (legacy_nome, legacy_email, legacy_password_hash, datetime.now().isoformat(timespec="seconds")),
        )

    target_user = conn.execute("SELECT id FROM usuarios ORDER BY id ASC LIMIT 1").fetchone()
    if target_user is not None:
        conn.execute(
            """
            UPDATE movimentacoes
            SET usuario_id = ?
            WHERE usuario_id IS NULL
            """,
            (int(target_user["id"]),),
        )


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                senha_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS movimentacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER,
                tipo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                categoria TEXT NOT NULL,
                valor REAL NOT NULL,
                data_hora TEXT NOT NULL,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
            """
        )

        ensure_column(conn, "movimentacoes", "usuario_id", "INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_movimentacoes_usuario_id ON movimentacoes(usuario_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios(email)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metas_mensais (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                mes TEXT NOT NULL,
                valor_meta REAL NOT NULL,
                UNIQUE(usuario_id, mes),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orcamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                categoria TEXT NOT NULL,
                mes TEXT NOT NULL,
                valor_orcamento REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(usuario_id, categoria, mes),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
            """
        )

        conn.execute("CREATE INDEX IF NOT EXISTS idx_orcamentos_usuario_mes ON orcamentos(usuario_id, mes)")

        migrate_legacy_data(conn)


def init_session_state() -> None:
    st.session_state.setdefault("editing_id", None)
    st.session_state.setdefault("delete_confirm_id", None)
    st.session_state.setdefault("hist_search", "")
    st.session_state.setdefault("hist_mes", TODOS_OS_MESES)
    st.session_state.setdefault("hist_categoria", "Todos")
    st.session_state.setdefault("hist_tipo", "Todos")
    st.session_state.setdefault("meta_editing", False)

    st.session_state.setdefault("auth_mode", "Entrar")
    st.session_state.setdefault("is_authenticated", False)
    st.session_state.setdefault("current_user_id", None)
    st.session_state.setdefault("current_user_name", "")
    st.session_state.setdefault("current_user_email", "")


def reset_action_state() -> None:
    st.session_state["editing_id"] = None
    st.session_state["delete_confirm_id"] = None


def reset_history_filters() -> None:
    st.session_state["hist_search"] = ""
    st.session_state["hist_mes"] = TODOS_OS_MESES
    st.session_state["hist_categoria"] = "Todos"
    st.session_state["hist_tipo"] = "Todos"


def _orcamentos_file_path(user_id: int) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), f"orcamentos_usuario_{user_id}.json")


def _migrar_orcamentos_json_para_sqlite(user_id: int, mes: str) -> None:
    """Migra orcamentos antigos em JSON para SQLite sem apagar dados existentes."""
    path = _orcamentos_file_path(user_id)
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError, ValueError):
        return

    if not isinstance(data, dict):
        return

    houve_migracao = False
    for categoria, valor in data.items():
        categoria_limpa = str(categoria).strip()
        if categoria_limpa not in CATEGORIAS:
            continue
        try:
            valor_float = float(valor)
        except (TypeError, ValueError):
            continue

        if valor_float > 0:
            salvar_orcamento(user_id=user_id, categoria=categoria_limpa, mes=mes, valor_orcamento=valor_float)
            houve_migracao = True

    if houve_migracao:
        try:
            os.replace(path, f"{path}.migrado")
        except OSError:
            # Se nao for possivel renomear, mantem o arquivo sem interromper o fluxo.
            pass


def load_orcamentos(user_id: int, mes: str) -> dict[str, float]:
    _migrar_orcamentos_json_para_sqlite(user_id, mes)

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT categoria, valor_orcamento
            FROM orcamentos
            WHERE usuario_id = ? AND mes = ?
            ORDER BY categoria ASC
            """,
            (user_id, mes),
        ).fetchall()

    return {
        str(row["categoria"]): float(row["valor_orcamento"])
        for row in rows
        if str(row["categoria"]) in CATEGORIAS and float(row["valor_orcamento"]) > 0
    }


def salvar_orcamento(user_id: int, categoria: str, mes: str, valor_orcamento: float) -> None:
    if categoria not in CATEGORIAS:
        return
    if valor_orcamento <= 0:
        return

    agora = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO orcamentos (usuario_id, categoria, mes, valor_orcamento, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(usuario_id, categoria, mes)
            DO UPDATE SET valor_orcamento = excluded.valor_orcamento, updated_at = excluded.updated_at
            """,
            (user_id, categoria, mes, float(valor_orcamento), agora, agora),
        )


def excluir_orcamento(user_id: int, categoria: str, mes: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM orcamentos WHERE usuario_id = ? AND categoria = ? AND mes = ?",
            (user_id, categoria, mes),
        )


def set_logged_user(user: dict) -> None:
    st.session_state["is_authenticated"] = True
    st.session_state["current_user_id"] = int(user["id"])
    st.session_state["current_user_name"] = (user["nome"] or "").strip()
    st.session_state["current_user_email"] = (user["email"] or "").strip()


def logout_user() -> None:
    st.session_state["is_authenticated"] = False
    st.session_state["current_user_id"] = None
    st.session_state["current_user_name"] = ""
    st.session_state["current_user_email"] = ""
    reset_action_state()
    reset_history_filters()


def get_user_by_id(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT id, nome, email FROM usuarios WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return None
    return {"id": int(row["id"]), "nome": row["nome"], "email": row["email"]}


def create_user(nome: str, email: str, senha: str) -> tuple[bool, str]:
    nome_limpo = nome.strip()
    email_limpo = normalize_email(email)

    if len(nome_limpo) < 2:
        return False, "Nome deve ter pelo menos 2 caracteres."
    if not is_valid_email(email_limpo):
        return False, "Informe um email valido."
    if len(senha) < 6:
        return False, "Senha deve ter no minimo 6 caracteres."

    senha_hash = hash_password(senha)

    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO usuarios (nome, email, senha_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (nome_limpo, email_limpo, senha_hash, datetime.now().isoformat(timespec="seconds")),
            )
    except sqlite3.IntegrityError:
        return False, "Este email ja esta cadastrado."

    return True, "Conta criada com sucesso."


def authenticate_user(email: str, senha: str) -> dict | None:
    email_limpo = normalize_email(email)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, nome, email, senha_hash FROM usuarios WHERE email = ?",
            (email_limpo,),
        ).fetchone()

    if not row:
        return None

    if not verify_password(senha, row["senha_hash"]):
        return None

    return {"id": int(row["id"]), "nome": row["nome"], "email": row["email"]}


def add_movimentacao(user_id: int, tipo: str, descricao: str, categoria: str, valor: float) -> None:
    data_hora = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO movimentacoes (usuario_id, tipo, descricao, categoria, valor, data_hora)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, tipo.lower(), descricao.strip(), categoria, valor, data_hora),
        )


def buscar_movimento(movimento_id: int, user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, data_hora, tipo, descricao, categoria, valor
            FROM movimentacoes
            WHERE id = ? AND usuario_id = ?
            """,
            (movimento_id, user_id),
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


def editar_movimento(movimento_id: int, user_id: int, tipo: str, descricao: str, categoria: str, valor: float) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE movimentacoes
            SET tipo = ?, descricao = ?, categoria = ?, valor = ?
            WHERE id = ? AND usuario_id = ?
            """,
            (tipo.lower(), descricao.strip(), categoria, valor, movimento_id, user_id),
        )
    return cursor.rowcount > 0


def excluir_movimento(movimento_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM movimentacoes WHERE id = ? AND usuario_id = ?",
            (movimento_id, user_id),
        )
    return cursor.rowcount > 0


def load_movimentacoes(user_id: int) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(
            """
            SELECT id, data_hora, tipo, descricao, categoria, valor
            FROM movimentacoes
            WHERE usuario_id = ?
            ORDER BY data_hora DESC, id DESC
            """,
            conn,
            params=(user_id,),
        )

    if df.empty:
        return df

    df["data_hora"] = pd.to_datetime(df["data_hora"], errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0)
    return df


def get_meta_mensal(user_id: int, mes: str) -> float | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT valor_meta FROM metas_mensais WHERE usuario_id = ? AND mes = ?",
            (user_id, mes),
        ).fetchone()
    return float(row["valor_meta"]) if row else None


def save_meta_mensal(user_id: int, mes: str, valor_meta: float) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO metas_mensais (usuario_id, mes, valor_meta)
            VALUES (?, ?, ?)
            ON CONFLICT(usuario_id, mes) DO UPDATE SET valor_meta = excluded.valor_meta
            """,
            (user_id, mes, valor_meta),
        )


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


def is_mobile_client() -> bool:
    headers = getattr(st.context, "headers", None)
    if not headers:
        return False

    user_agent = str(headers.get("user-agent", "")).lower()
    mobile_hint = str(headers.get("sec-ch-ua-mobile", "")).lower()
    mobile_tokens = (
        "android",
        "iphone",
        "ipad",
        "ipod",
        "mobile",
        "opera mini",
        "iemobile",
    )
    return mobile_hint == "?1" or any(token in user_agent for token in mobile_tokens)


def render_metric_cards(metrics: dict, total_movimentacoes: int) -> None:
    st.markdown(
        f"""
        <div class='metric-grid'>
            <div class='metric-card saldo'>
                <div class='metric-label'>Saldo Atual</div>
                <div class='metric-value'>{format_brl(metrics['saldo'])}</div>
            </div>
            <div class='metric-card receita'>
                <div class='metric-label'>Receita</div>
                <div class='metric-value'>{format_brl(metrics['receitas'])}</div>
            </div>
            <div class='metric-card despesa'>
                <div class='metric-label'>Despesa</div>
                <div class='metric-value'>{format_brl(metrics['despesas'])}</div>
            </div>
            <div class='metric-card movimentos'>
                <div class='metric-label'>Movimentacoes</div>
                <div class='metric-value'>{total_movimentacoes}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def filtrar_historico(
    df: pd.DataFrame,
    busca: str,
    mes: str,
    categoria: str,
    tipo: str,
) -> pd.DataFrame:
    filtered_df = df.copy()

    busca_limpa = busca.strip().lower()
    if busca_limpa:
        filtered_df = filtered_df[
            filtered_df["descricao"].fillna("").astype(str).str.lower().str.contains(busca_limpa, na=False)
        ]

    if mes != TODOS_OS_MESES:
        filtered_df = filtered_df[
            filtered_df["data_hora"].dt.strftime("%m/%Y") == mes
        ]

    if categoria != "Todos":
        filtered_df = filtered_df[
            filtered_df["categoria"].astype(str) == categoria
        ]

    if tipo != "Todos":
        filtered_df = filtered_df[
            filtered_df["tipo"].astype(str) == tipo.lower()
        ]

    return filtered_df


def _status_orcamento(percentual: float) -> tuple[str, str]:
    if percentual <= 70:
        return "Dentro do planejado", "#30c48d"
    if percentual <= 100:
        return "Em alerta", "#f9c846"
    return "Acima do orcamento", "#ef5c6d"


def _dados_mensais(df: pd.DataFrame, ano_mes: str) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    return df[df["data_hora"].dt.strftime("%Y-%m") == ano_mes].copy()


def _dados_despesas_mes(df_mes: pd.DataFrame) -> pd.DataFrame:
    if df_mes.empty:
        return df_mes.copy()
    return df_mes[df_mes["tipo"].astype(str).str.lower() == "despesa"].copy()


def render_orcamentos(df: pd.DataFrame, user_id: int) -> None:
    st.markdown("### Orcamentos")
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("Defina seu orcamento mensal por categoria e acompanhe a execucao em tempo real.")

    mes_ref = datetime.now().strftime("%Y-%m")
    mes_label = datetime.now().strftime("%m/%Y")
    orcamentos = load_orcamentos(user_id, mes_ref)

    with st.form("novo_orcamento_form", clear_on_submit=True):
        col1, col2 = st.columns(2 if not is_mobile_client() else [1, 1])
        categoria = col1.selectbox("Categoria do orcamento", CATEGORIAS, index=0)
        valor_orcamento = col2.number_input("Valor mensal (R$)", min_value=0.0, step=50.0, format="%.2f")
        salvar = st.form_submit_button("Salvar orcamento", use_container_width=True)

    if salvar:
        if valor_orcamento <= 0:
            st.error("Informe um valor maior que zero para o orcamento.")
        else:
            salvar_orcamento(user_id=user_id, categoria=categoria, mes=mes_ref, valor_orcamento=float(valor_orcamento))
            st.success(f"Orcamento salvo para {categoria}.")
            st.rerun()

    df_mes = _dados_mensais(df, mes_ref)
    despesas_mes = _dados_despesas_mes(df_mes)
    gasto_por_categoria = (
        despesas_mes.groupby("categoria", as_index=False)["valor"].sum() if not despesas_mes.empty else pd.DataFrame(columns=["categoria", "valor"])
    )
    mapa_gastos = {
        str(row["categoria"]): float(row["valor"]) for _, row in gasto_por_categoria.iterrows()
    }

    if not orcamentos:
        st.info("Nenhum orcamento cadastrado ainda.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown(f"#### Acompanhamento de {mes_label}")

    for categoria_nome in sorted(orcamentos.keys()):
        valor_limite = float(orcamentos[categoria_nome])
        valor_gasto = float(mapa_gastos.get(categoria_nome, 0.0))
        percentual = (valor_gasto / valor_limite * 100.0) if valor_limite > 0 else 0.0
        percentual_clamped = max(0.0, min(percentual, 100.0))
        status, cor = _status_orcamento(percentual)

        st.markdown("<div class='budget-card'>", unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class='budget-head'>
                <div class='budget-title'>{categoria_nome}</div>
                <div class='budget-status' style='color:{cor}'>{status}</div>
            </div>
            <div class='budget-values'>
                <span>Gasto: {format_brl(valor_gasto)}</span>
                <span>Orcamento: {format_brl(valor_limite)}</span>
                <span>Uso: {percentual:.1f}%</span>
            </div>
            <div class='budget-bar-bg'>
                <div class='budget-bar-fill' style='width:{percentual_clamped:.2f}%; background:{cor};'></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        bcol1, bcol2 = st.columns(2)
        edit_key = f"orc_edit_{categoria_nome}"
        if bcol1.button("Editar", key=f"btn_{edit_key}", use_container_width=True):
            st.session_state[edit_key] = True
            st.rerun()

        if bcol2.button("Excluir", key=f"btn_del_{categoria_nome}", use_container_width=True):
            excluir_orcamento(user_id=user_id, categoria=categoria_nome, mes=mes_ref)
            st.success(f"Orcamento removido para {categoria_nome}.")
            st.rerun()

        if st.session_state.get(edit_key, False):
            novo_valor = st.number_input(
                f"Novo valor para {categoria_nome}",
                min_value=0.0,
                value=float(valor_limite),
                step=50.0,
                format="%.2f",
                key=f"input_{edit_key}",
            )
            ecol1, ecol2 = st.columns(2)
            if ecol1.button("Salvar alteracao", key=f"save_{edit_key}", use_container_width=True):
                if novo_valor <= 0:
                    st.error("Informe um valor maior que zero.")
                else:
                    salvar_orcamento(
                        user_id=user_id,
                        categoria=categoria_nome,
                        mes=mes_ref,
                        valor_orcamento=float(novo_valor),
                    )
                    st.session_state[edit_key] = False
                    st.success("Orcamento atualizado.")
                    st.rerun()

            if ecol2.button("Cancelar", key=f"cancel_{edit_key}", use_container_width=True):
                st.session_state[edit_key] = False
                st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


def render_resumo_financeiro(df: pd.DataFrame, user_id: int) -> None:
    del user_id  # reservado para evolucoes futuras sem quebrar assinatura
    st.markdown("### Resumo Financeiro")

    mes_atual = datetime.now().strftime("%Y-%m")
    mes_anterior = (pd.Period(mes_atual, freq="M") - 1).strftime("%Y-%m")

    df_mes_atual = _dados_mensais(df, mes_atual)
    df_mes_anterior = _dados_mensais(df, mes_anterior)

    receitas_mes = df_mes_atual[df_mes_atual["tipo"] == "receita"] if not df_mes_atual.empty else df_mes_atual
    despesas_mes = df_mes_atual[df_mes_atual["tipo"] == "despesa"] if not df_mes_atual.empty else df_mes_atual

    receita_total = float(receitas_mes["valor"].sum()) if not receitas_mes.empty else 0.0
    despesa_total = float(despesas_mes["valor"].sum()) if not despesas_mes.empty else 0.0
    saldo_mes = receita_total - despesa_total
    qtd_receitas = int(len(receitas_mes))
    qtd_despesas = int(len(despesas_mes))

    if not despesas_mes.empty:
        gasto_categoria = despesas_mes.groupby("categoria", as_index=False)["valor"].sum().sort_values("valor", ascending=False)
        maior_categoria = str(gasto_categoria.iloc[0]["categoria"])
        valor_maior_categoria = float(gasto_categoria.iloc[0]["valor"])
        maior_despesa = float(despesas_mes["valor"].max())
        menor_despesa = float(despesas_mes["valor"].min())
        top5 = despesas_mes.nlargest(5, "valor")[ ["descricao", "categoria", "valor", "data_hora"] ]
    else:
        gasto_categoria = pd.DataFrame(columns=["categoria", "valor"])
        maior_categoria = "Sem despesas no mes"
        valor_maior_categoria = 0.0
        maior_despesa = 0.0
        menor_despesa = 0.0
        top5 = pd.DataFrame(columns=["descricao", "categoria", "valor", "data_hora"])

    dia_atual = max(1, datetime.now().day)
    media_diaria_gastos = despesa_total / float(dia_atual)

    metricas_anterior = compute_metrics(df_mes_anterior)
    saldo_anterior = float(metricas_anterior["saldo"])

    ano_atual = datetime.now().strftime("%Y")
    df_ano = df[df["data_hora"].dt.strftime("%Y") == ano_atual] if not df.empty else df
    total_economizado_ano = float(compute_metrics(df_ano)["saldo"]) if not df_ano.empty else 0.0

    def _card_resumo(titulo: str, valor: str) -> None:
        st.markdown(
            f"""
            <div class='summary-card'>
                <div class='summary-label'>{titulo}</div>
                <div class='summary-value'>{valor}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    c1, c2, c3 = st.columns(3)
    with c1:
        _card_resumo("Receita do mes", format_brl(receita_total))
    with c2:
        _card_resumo("Despesas do mes", format_brl(despesa_total))
    with c3:
        _card_resumo("Saldo do mes", format_brl(saldo_mes))

    c4, c5, c6 = st.columns(3)
    with c4:
        _card_resumo("Quantidade de receitas", str(qtd_receitas))
    with c5:
        _card_resumo("Quantidade de despesas", str(qtd_despesas))
    with c6:
        _card_resumo("Media diaria de gastos", format_brl(media_diaria_gastos))

    c7, c8, c9 = st.columns(3)
    with c7:
        _card_resumo("Categoria com maior gasto", maior_categoria)
    with c8:
        _card_resumo("Valor da maior categoria", format_brl(valor_maior_categoria))
    with c9:
        _card_resumo("Total economizado no ano", format_brl(total_economizado_ano))

    c10, c11, c12 = st.columns(3)
    with c10:
        _card_resumo("Maior despesa", format_brl(maior_despesa))
    with c11:
        _card_resumo("Menor despesa", format_brl(menor_despesa))
    with c12:
        variacao_saldo = saldo_mes - saldo_anterior
        _card_resumo("Comparativo saldo mes anterior", f"{format_brl(variacao_saldo)}")

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### Cinco maiores gastos do mes")
    if top5.empty:
        st.info("Sem despesas no mes atual.")
    else:
        top5_exibicao = top5.copy()
        top5_exibicao["data_hora"] = top5_exibicao["data_hora"].map(format_data_hora)
        top5_exibicao["valor"] = top5_exibicao["valor"].map(format_brl)
        top5_exibicao = top5_exibicao.rename(
            columns={"descricao": "Descricao", "categoria": "Categoria", "valor": "Valor", "data_hora": "Data"}
        )
        st.dataframe(top5_exibicao, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)

    g1, g2 = st.columns(2)

    with g1:
        st.markdown("#### Pizza de gastos por categoria")
        if gasto_categoria.empty:
            st.info("Sem despesas para gerar o grafico de pizza.")
        else:
            fig_pizza = px.pie(
                gasto_categoria,
                names="categoria",
                values="valor",
                hole=0.45,
                color_discrete_sequence=["#ef5c6d", "#f9c846", "#30c48d", "#4f7fff", "#9a6dff", "#66c2a5"],
            )
            fig_pizza.update_layout(
                template="plotly_dark",
                margin=dict(l=8, r=8, t=16, b=8),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                legend_title_text="Categoria",
            )
            st.plotly_chart(fig_pizza, use_container_width=True)

    with g2:
        st.markdown("#### Barras: receitas x despesas")
        comparativo_df = pd.DataFrame(
            {
                "tipo": ["Receitas", "Despesas"],
                "valor": [receita_total, despesa_total],
            }
        )
        fig_barras = px.bar(
            comparativo_df,
            x="tipo",
            y="valor",
            color="tipo",
            color_discrete_map={"Receitas": "#30c48d", "Despesas": "#ef5c6d"},
            text="valor",
        )
        fig_barras.update_traces(texttemplate="R$ %{text:.2f}", textposition="outside")
        fig_barras.update_layout(
            template="plotly_dark",
            margin=dict(l=8, r=8, t=16, b=8),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
            yaxis_title="Valor (R$)",
            xaxis_title="",
        )
        st.plotly_chart(fig_barras, use_container_width=True)

    st.markdown("#### Evolucao dos ultimos 12 meses")
    if df.empty:
        st.info("Sem dados para a evolucao mensal.")
        return

    serie = df.copy()
    serie["mes_ref"] = serie["data_hora"].dt.to_period("M").astype(str)
    serie["receita_val"] = serie.apply(lambda row: float(row["valor"]) if row["tipo"] == "receita" else 0.0, axis=1)
    serie["despesa_val"] = serie.apply(lambda row: float(row["valor"]) if row["tipo"] == "despesa" else 0.0, axis=1)

    evolucao = (
        serie.groupby("mes_ref", as_index=False)[["receita_val", "despesa_val"]]
        .sum()
        .sort_values("mes_ref")
        .tail(12)
    )
    evolucao["saldo"] = evolucao["receita_val"] - evolucao["despesa_val"]
    evolucao["mes_label"] = pd.PeriodIndex(evolucao["mes_ref"], freq="M").strftime("%m/%Y")

    fig_linha = px.line(
        evolucao,
        x="mes_label",
        y=["receita_val", "despesa_val", "saldo"],
        markers=True,
        color_discrete_map={
            "receita_val": "#30c48d",
            "despesa_val": "#ef5c6d",
            "saldo": "#4f7fff",
        },
    )
    fig_linha.update_traces(mode="lines+markers")
    fig_linha.update_layout(
        template="plotly_dark",
        margin=dict(l=8, r=8, t=16, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis_title="Valor (R$)",
        xaxis_title="Mes",
        legend_title_text="Serie",
    )
    st.plotly_chart(fig_linha, use_container_width=True)


def gerar_pdf_historico(
    filtered_df: pd.DataFrame,
    mes_selecionado: str,
    categoria_selecionada: str,
    tipo_selecionado: str,
) -> bytes:
    metricas = compute_metrics(filtered_df)
    categoria_label = "Todas" if categoria_selecionada == "Todos" else categoria_selecionada

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="Relatorio do historico",
    )
    styles = getSampleStyleSheet()

    elementos = [
        Paragraph("Relatorio de movimentacoes", styles["Title"]),
        Spacer(1, 4 * mm),
        Paragraph(f"Mes de referencia: {mes_selecionado}", styles["Normal"]),
        Paragraph(f"Categoria selecionada: {categoria_label}", styles["Normal"]),
        Paragraph(f"Tipo selecionado: {tipo_selecionado}", styles["Normal"]),
        Paragraph(f"Total de receitas: {format_brl(metricas['receitas'])}", styles["Normal"]),
        Paragraph(f"Total de despesas: {format_brl(metricas['despesas'])}", styles["Normal"]),
        Paragraph(f"Saldo da selecao: {format_brl(metricas['saldo'])}", styles["Normal"]),
        Paragraph(f"Quantidade de lancamentos exportados: {len(filtered_df)}", styles["Normal"]),
        Spacer(1, 6 * mm),
    ]

    tabela = [["Data", "Tipo", "Descricao", "Categoria", "Valor"]]
    for _, row in filtered_df.iterrows():
        tipo_raw = str(row["tipo"]).lower()
        tipo_label = "Receita" if tipo_raw == "receita" else "Despesa"
        valor_assinado = float(row["valor"]) if tipo_raw == "receita" else -float(row["valor"])
        tabela.append(
            [
                format_data_hora(row["data_hora"]),
                tipo_label,
                str(row["descricao"]),
                str(row["categoria"]),
                format_brl(valor_assinado),
            ]
        )

    tabela_pdf = Table(
        tabela,
        colWidths=[26 * mm, 22 * mm, 62 * mm, 34 * mm, 30 * mm],
        repeatRows=1,
    )
    tabela_pdf.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2a44")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6fb")]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c3cadb")),
                ("ALIGN", (4, 1), (4, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elementos.append(tabela_pdf)

    doc.build(elementos)
    return buffer.getvalue()


def compartilhar_pdf_whatsapp(pdf_bytes: bytes, nome_arquivo: str, mensagem: str) -> None:
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    mensagem_js = mensagem.replace("\\", "\\\\").replace("'", "\\'")
    nome_js = nome_arquivo.replace("\\", "\\\\").replace("'", "\\'")

    components.html(
        f"""
        <script>
        (async () => {{
            const pdfBase64 = '{pdf_b64}';
            const fileName = '{nome_js}';
            const texto = '{mensagem_js}';

            const toUint8 = (base64) => {{
                const binary = atob(base64);
                const len = binary.length;
                const bytes = new Uint8Array(len);
                for (let i = 0; i < len; i += 1) bytes[i] = binary.charCodeAt(i);
                return bytes;
            }};

            let compartilhou = false;
            try {{
                if (navigator.share && navigator.canShare) {{
                    const blob = new Blob([toUint8(pdfBase64)], {{ type: 'application/pdf' }});
                    const file = new File([blob], fileName, {{ type: 'application/pdf' }});
                    if (navigator.canShare({{ files: [file] }})) {{
                        await navigator.share({{
                            title: 'Relatorio Financeiro',
                            text: texto,
                            files: [file],
                        }});
                        compartilhou = true;
                    }}
                }}
            }} catch (e) {{
                compartilhou = false;
            }}

            if (!compartilhou) {{
                const url = 'https://wa.me/?text=' + encodeURIComponent(texto);
                window.open(url, '_blank');
            }}
        }})();
        </script>
        """,
        height=0,
    )


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
        .auth-wrap {
            max-width: 560px;
            margin: 1rem auto 0;
        }
        .auth-card {
            background: linear-gradient(180deg, rgba(20, 23, 33, 0.95) 0%, rgba(13, 15, 22, 0.96) 100%);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 20px;
            padding: 1rem 1.05rem;
            box-shadow: 0 18px 38px rgba(0, 0, 0, 0.24);
        }
        .auth-title {
            color: #f3f6ff;
            font-size: 1.2rem;
            font-weight: 800;
            margin-bottom: 0.2rem;
        }
        .auth-subtitle {
            color: #adb8d2;
            font-size: 0.93rem;
            margin-bottom: 0.8rem;
        }
        .metric-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.85rem;
            margin: 0.9rem 0 1rem;
        }
        .metric-card {
            position: relative;
            overflow: hidden;
            border-radius: 20px;
            padding: 1rem 1rem 1.05rem;
            min-height: 116px;
            border: 1px solid rgba(255,255,255,0.08);
            box-shadow: 0 18px 32px rgba(0, 0, 0, 0.24);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .metric-card::after {
            content: "";
            position: absolute;
            inset: auto -20px -35px auto;
            width: 96px;
            height: 96px;
            border-radius: 999px;
            background: rgba(255,255,255,0.10);
            filter: blur(8px);
        }
        .metric-card.saldo {
            background: linear-gradient(180deg, rgba(23, 92, 65, 0.96) 0%, rgba(16, 61, 43, 0.98) 100%);
        }
        .metric-card.receita {
            background: linear-gradient(180deg, rgba(20, 77, 146, 0.96) 0%, rgba(15, 52, 102, 0.98) 100%);
        }
        .metric-card.despesa {
            background: linear-gradient(180deg, rgba(143, 39, 55, 0.96) 0%, rgba(94, 26, 39, 0.98) 100%);
        }
        .metric-card.movimentos {
            background: linear-gradient(180deg, rgba(92, 54, 162, 0.96) 0%, rgba(59, 33, 106, 0.98) 100%);
        }
        .metric-label {
            color: rgba(244, 247, 255, 0.78);
            font-size: 0.88rem;
            font-weight: 600;
            letter-spacing: 0.01em;
            text-align: left;
        }
        .metric-value {
            color: #f8fbff;
            font-size: 1.3rem;
            line-height: 1.15;
            font-weight: 800;
            text-align: left;
            word-break: break-word;
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
        .filters-card {
            background: linear-gradient(180deg, rgba(20, 23, 33, 0.95) 0%, rgba(13, 15, 22, 0.96) 100%);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 16px;
            padding: 0.9rem 0.95rem;
            margin-bottom: 0.8rem;
            box-shadow: 0 12px 28px rgba(0, 0, 0, 0.20);
        }
        .filters-title {
            color: #f3f6ff;
            font-weight: 700;
            font-size: 0.95rem;
            margin-bottom: 0.55rem;
        }
        .filters-result {
            color: #aeb8cf;
            font-size: 0.9rem;
            margin-top: 0.35rem;
            margin-bottom: 0.15rem;
        }
        .export-summary-card {
            background: linear-gradient(180deg, rgba(21, 27, 40, 0.92) 0%, rgba(14, 19, 30, 0.94) 100%);
            border: 1px solid rgba(255, 255, 255, 0.10);
            border-radius: 14px;
            padding: 0.78rem 0.9rem;
            margin-top: 0.5rem;
            margin-bottom: 0.7rem;
            color: #f3f6ff;
            font-size: 0.94rem;
            font-weight: 700;
        }
        .history-card {
            background: linear-gradient(180deg, rgba(17, 20, 28, 0.95) 0%, rgba(12, 14, 20, 0.96) 100%);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 18px;
            padding: 0.95rem 1rem;
            margin-bottom: 0.8rem;
            box-shadow: 0 16px 34px rgba(0, 0, 0, 0.22);
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
        .stTextInput input,
        .stNumberInput input {
            min-height: 3rem;
        }
        .stSelectbox [data-baseweb="select"] > div {
            min-height: 3rem;
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
            .block-container {
                padding-top: 0.8rem;
                padding-bottom: 1rem;
                padding-left: 0.8rem;
                padding-right: 0.8rem;
            }
            .auth-wrap {
                margin-top: 0.5rem;
            }
            .auth-card {
                border-radius: 16px;
                padding: 0.9rem;
            }
            .auth-title {
                font-size: 1.05rem;
            }
            .auth-subtitle {
                font-size: 0.85rem;
                margin-bottom: 0.6rem;
            }
            .metric-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.65rem;
                margin: 0.7rem 0 0.85rem;
            }
            .metric-card {
                min-height: 102px;
                border-radius: 18px;
                padding: 0.9rem 0.9rem 0.95rem;
            }
            .metric-label {
                font-size: 0.8rem;
            }
            .metric-value {
                font-size: 1.1rem;
            }
            .app-card,
            .history-card {
                padding: 0.9rem;
                border-radius: 16px;
            }
            .app-subtitle {
                margin-bottom: 0.45rem;
            }
            .filters-card {
                border-radius: 14px;
                padding: 0.85rem;
                margin-bottom: 0.7rem;
            }
            .filters-title {
                font-size: 0.9rem;
                margin-bottom: 0.45rem;
            }
            .filters-result {
                font-size: 0.82rem;
            }
            .history-meta {
                gap: 0.45rem;
            }
            .history-description {
                font-size: 0.98rem;
            }
            .history-category,
            .history-date {
                font-size: 0.84rem;
            }
            .history-value {
                font-size: 0.96rem;
            }
            .stTextInput input,
            .stNumberInput input {
                min-height: 3.2rem;
                font-size: 1rem;
            }
            .stSelectbox [data-baseweb="select"] > div {
                min-height: 3.2rem;
                font-size: 1rem;
            }
            .stButton > button,
            .stFormSubmitButton > button {
                min-height: 3rem;
            }
        }
        .meta-progress-wrap {
            margin: 0.55rem 0 0.25rem;
        }
        .meta-info-row {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 0.55rem;
        }
        .meta-status-label {
            color: #b6bdd0;
            font-size: 0.92rem;
            font-weight: 600;
        }
        .meta-pct {
            font-size: 1.35rem;
            font-weight: 800;
            line-height: 1;
        }
        .meta-bar-bg {
            background: rgba(255,255,255,0.09);
            border-radius: 999px;
            height: 13px;
            overflow: hidden;
            margin-bottom: 0.6rem;
        }
        .meta-bar-fill {
            height: 100%;
            border-radius: 999px;
            transition: width 0.65s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .meta-values-row {
            display: flex;
            align-items: baseline;
            gap: 0.38rem;
            flex-wrap: wrap;
        }
        .meta-val-atual {
            font-size: 1rem;
            font-weight: 700;
        }
        .meta-val-sep {
            color: #7e8a9e;
            font-size: 0.85rem;
        }
        .meta-val-meta {
            color: #c4ccd8;
            font-size: 0.95rem;
            font-weight: 600;
        }
        .budget-card {
            background: linear-gradient(180deg, rgba(17, 20, 28, 0.95) 0%, rgba(12, 14, 20, 0.96) 100%);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 16px;
            padding: 0.82rem 0.92rem;
            margin-top: 0.65rem;
            margin-bottom: 0.2rem;
        }
        .budget-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.7rem;
            margin-bottom: 0.45rem;
            flex-wrap: wrap;
        }
        .budget-title {
            color: #f5f7ff;
            font-size: 0.98rem;
            font-weight: 700;
        }
        .budget-status {
            font-size: 0.86rem;
            font-weight: 700;
        }
        .budget-values {
            color: #b8c2d9;
            font-size: 0.86rem;
            display: flex;
            justify-content: space-between;
            gap: 0.5rem;
            margin-bottom: 0.45rem;
            flex-wrap: wrap;
        }
        .budget-bar-bg {
            width: 100%;
            height: 11px;
            border-radius: 999px;
            background: rgba(255,255,255,0.10);
            overflow: hidden;
            margin-bottom: 0.28rem;
        }
        .budget-bar-fill {
            height: 100%;
            border-radius: 999px;
            transition: width 0.5s ease;
        }
        .summary-card {
            background: linear-gradient(180deg, rgba(20, 23, 33, 0.95) 0%, rgba(13, 15, 22, 0.96) 100%);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 16px;
            padding: 0.84rem 0.9rem;
            margin-bottom: 0.65rem;
            min-height: 98px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            box-shadow: 0 10px 28px rgba(0, 0, 0, 0.18);
        }
        .summary-label {
            color: #b7c1d7;
            font-size: 0.84rem;
            font-weight: 600;
        }
        .summary-value {
            color: #f6f8ff;
            font-size: 1.05rem;
            font-weight: 800;
            line-height: 1.2;
            word-break: break-word;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_pwa() -> None:
    """Injeta o manifest oficial da pasta pwa/."""
    st.markdown(
        """
<link rel="manifest" href="/pwa/manifest.webmanifest?v=5">
<meta name="theme-color" content="#f5b400">
<link rel="apple-touch-icon" href="/pwa/icon-192.png?v=5">
        """,
        unsafe_allow_html=True,
    )


def render_auth_screen() -> None:
    # Troca para tela de login solicitada por rerun anterior (evita alterar key de widget ja renderizado)
    if st.session_state.pop("_pending_switch_to_login", False):
        st.session_state["auth_mode"] = "Entrar"

    st.markdown("<div class='auth-wrap'>", unsafe_allow_html=True)
    st.markdown("<div class='auth-card'>", unsafe_allow_html=True)
    st.markdown("<div class='auth-title'>Controle Financeiro</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='auth-subtitle'>Entrar na sua conta ou criar um novo acesso.</div>",
        unsafe_allow_html=True,
    )

    modo = st.radio(
        "Modo",
        options=["Entrar", "Criar conta"],
        key="auth_mode",
        horizontal=True,
        label_visibility="collapsed",
    )

    if modo == "Entrar":
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input("Email", placeholder="seuemail@exemplo.com")
            senha = st.text_input("Senha", type="password", placeholder="Digite sua senha")
            entrar = st.form_submit_button("Entrar", use_container_width=True)

        if entrar:
            if not email.strip() or not senha:
                st.error("Preencha email e senha para entrar.")
            else:
                user = authenticate_user(email, senha)
                if user is None:
                    st.error("Email ou senha invalidos.")
                else:
                    set_logged_user(user)
                    reset_history_filters()
                    reset_action_state()
                    st.success("Login realizado com sucesso.")
                    st.rerun()
    else:
        with st.form("signup_form", clear_on_submit=False):
            nome = st.text_input("Nome", placeholder="Seu nome")
            email = st.text_input("Email", placeholder="seuemail@exemplo.com")
            senha = st.text_input("Senha", type="password", placeholder="Minimo 6 caracteres")
            confirmar_senha = st.text_input("Confirmar senha", type="password", placeholder="Repita sua senha")
            criar = st.form_submit_button("Criar conta", use_container_width=True)

        if criar:
            if senha != confirmar_senha:
                st.error("Senha e confirmacao precisam ser iguais.")
            else:
                ok, mensagem = create_user(nome, email, senha)
                if not ok:
                    st.error(mensagem)
                else:
                    st.success(mensagem + " Agora faca login.")
                    st.session_state["_pending_switch_to_login"] = True
                    st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_nova_movimentacao(user_id: int) -> None:
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("### Nova movimentacao")

    with st.form("nova_movimentacao", clear_on_submit=True):
        col1, col2 = st.columns(2 if not is_mobile_client() else [1, 1])
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
            add_movimentacao(user_id=user_id, tipo=tipo, descricao=descricao, categoria=categoria, valor=float(valor))
            st.success("Movimentacao salva com sucesso.")
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def render_grafico(df: pd.DataFrame) -> None:
    is_mobile = is_mobile_client()
    titulo_html = (
        "<h3 style='margin-bottom:0.4rem;font-size:1rem;'>📈 Evolução Mensal</h3>"
        if is_mobile
        else "### 📈 Evolução Mensal"
    )
    st.markdown(titulo_html, unsafe_allow_html=is_mobile)
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
        width=0.44 if len(monthly_df) == 1 and is_mobile else 0.58 if len(monthly_df) == 1 else 0.54 if is_mobile else 0.72,
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
        height=230 if is_mobile else 360,
        bargap=0.46 if is_mobile and len(monthly_df) > 1 else 0.28 if len(monthly_df) > 1 else 0.8 if is_mobile else 0.72,
        bargroupgap=0.0,
        barcornerradius=10,
        hoverlabel=dict(
            bgcolor="rgba(12,16,24,0.96)",
            bordercolor="rgba(255,255,255,0.10)",
            font=dict(color="#f5f7ff", size=11 if is_mobile else 13),
        ),
        margin=dict(l=4, r=4, t=8, b=4) if is_mobile else dict(l=10, r=10, t=20, b=10),
        transition=dict(duration=450, easing="cubic-in-out"),
        xaxis=dict(
            title=None,
            type="category",
            categoryorder="array",
            categoryarray=monthly_df["mes_label"].tolist(),
            tickfont=dict(size=10 if is_mobile else 12, color="#b6bdd0"),
            showgrid=False,
            fixedrange=True,
            tickangle=0,
            automargin=True,
        ),
        yaxis=dict(
            title=None,
            tickprefix="R$ ",
            tickfont=dict(size=10 if is_mobile else 12, color="#b6bdd0"),
            zeroline=True,
            zerolinecolor="rgba(255,255,255,0.14)",
            zerolinewidth=1,
            gridcolor="rgba(255,255,255,0.08)",
            griddash="dot",
            fixedrange=True,
            automargin=True,
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


def render_edit_form(movimento: dict, user_id: int) -> None:
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown(f"### Editar movimentacao #{movimento['id']}")

    tipo_atual = "Receita" if movimento["tipo"] == "receita" else "Despesa"
    categoria_atual = movimento["categoria"] if movimento["categoria"] in CATEGORIAS else CATEGORIAS[0]

    with st.form(f"form_editar_{movimento['id']}", clear_on_submit=False):
        col1, col2 = st.columns(2 if not is_mobile_client() else [1, 1])
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
                movimento_id=movimento["id"],
                user_id=user_id,
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


def render_movimento_card(row: pd.Series, user_id: int) -> None:
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

    acao_col1, acao_col2 = st.columns(2, gap="small")
    if acao_col1.button("✏️ Editar", key=f"editar_btn_{movimento_id}", use_container_width=True):
        start_edit(movimento_id)
        st.rerun()
    if acao_col2.button("🗑️ Excluir", key=f"excluir_btn_{movimento_id}", use_container_width=True):
        request_delete(movimento_id)
        st.rerun()

    if st.session_state.get("delete_confirm_id") == movimento_id:
        st.markdown("<div class='confirm-box'>", unsafe_allow_html=True)
        st.warning("Confirmar exclusao desta movimentacao?")
        confirmar_col1, confirmar_col2 = st.columns(2, gap="small")
        if confirmar_col1.button("Confirmar exclusao", key=f"confirmar_excluir_{movimento_id}", use_container_width=True):
            removido = excluir_movimento(movimento_id, user_id)
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


def render_historico(df: pd.DataFrame, user_id: int) -> None:
    st.markdown("### Historico completo")

    editing_id = st.session_state.get("editing_id")
    if editing_id is not None:
        movimento = buscar_movimento(int(editing_id), user_id)
        if movimento is None:
            cancel_edit()
            st.warning("A movimentacao em edicao nao foi encontrada.")
        else:
            render_edit_form(movimento, user_id)

    st.markdown("<div class='filters-card'>", unsafe_allow_html=True)
    st.markdown("<div class='filters-title'>Busca e filtros</div>", unsafe_allow_html=True)

    is_mobile = is_mobile_client()
    def limpar_filtros() -> None:
        reset_history_filters()

    search_col, clear_col = st.columns([0.73, 0.27]) if is_mobile else st.columns([0.84, 0.16])
    search_col.text_input(
        "Buscar na descricao",
        key="hist_search",
        placeholder="Ex: mercado, aluguel, farmacia...",
        label_visibility="collapsed",
    )
    clear_col.button(
        "Limpar filtros",
        key="limpar_filtros_historico",
        use_container_width=True,
        on_click=limpar_filtros,
    )

    month_options = [TODOS_OS_MESES]
    categoria_options = ["Todos"]

    if not df.empty:
        month_options.extend(
            sorted(
                [m for m in df["data_hora"].dt.strftime("%m/%Y").dropna().unique().tolist() if m],
                reverse=True,
            )
        )
        categoria_options.extend(sorted(df["categoria"].dropna().astype(str).unique().tolist()))

    tipo_options = ["Todos", "Receita", "Despesa"]

    if st.session_state["hist_mes"] not in month_options:
        st.session_state["hist_mes"] = TODOS_OS_MESES
    if st.session_state["hist_categoria"] not in categoria_options:
        st.session_state["hist_categoria"] = "Todos"
    if st.session_state["hist_tipo"] not in tipo_options:
        st.session_state["hist_tipo"] = "Todos"

    if is_mobile:
        st.selectbox("Mes", month_options, key="hist_mes")
        st.selectbox("Categoria", categoria_options, key="hist_categoria")
        st.selectbox("Tipo", tipo_options, key="hist_tipo")
    else:
        fcol1, fcol2, fcol3 = st.columns(3)
        fcol1.selectbox("Mes", month_options, key="hist_mes")
        fcol2.selectbox("Categoria", categoria_options, key="hist_categoria")
        fcol3.selectbox("Tipo", tipo_options, key="hist_tipo")

    st.markdown("</div>", unsafe_allow_html=True)

    mes_selecionado = st.session_state["hist_mes"]
    categoria_selecionada = st.session_state["hist_categoria"]
    tipo_selecionado = st.session_state["hist_tipo"]

    filtered_df = filtrar_historico(
        df=df,
        busca=st.session_state["hist_search"],
        mes=mes_selecionado,
        categoria=categoria_selecionada,
        tipo=tipo_selecionado,
    )

    metricas_filtradas = compute_metrics(filtered_df)
    total_filtrado = metricas_filtradas["saldo"]

    if categoria_selecionada != "Todos" and mes_selecionado != TODOS_OS_MESES:
        resumo_total = "Total da categoria no mês"
    elif categoria_selecionada != "Todos":
        resumo_total = "Total da categoria"
    elif mes_selecionado != TODOS_OS_MESES:
        resumo_total = "Total do mês"
    else:
        resumo_total = "Total filtrado"

    st.markdown(
        f"<div class='filters-result'>{len(filtered_df)} movimentacoes encontradas | {resumo_total}: {format_brl(total_filtrado)}</div>",
        unsafe_allow_html=True,
    )

    if df.empty:
        st.info("Nenhuma movimentacao cadastrada.")
        return

    if filtered_df.empty:
        st.info("Nenhuma movimentacao encontrada para os filtros selecionados.")
        return

    nome_pdf = f"relatorio_historico_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf_bytes = gerar_pdf_historico(
        filtered_df=filtered_df,
        mes_selecionado=mes_selecionado,
        categoria_selecionada=categoria_selecionada,
        tipo_selecionado=tipo_selecionado,
    )

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("### Relatorio filtrado")

    st.download_button(
        "Baixar PDF mensal",
        data=pdf_bytes,
        file_name=nome_pdf,
        mime="application/pdf",
        key="baixar_pdf_historico",
        use_container_width=True,
    )

    if categoria_selecionada != "Todos":
        texto_resumo_card = f"Total da categoria: {format_brl(metricas_filtradas['saldo'])}"
    else:
        texto_resumo_card = f"Total geral do mes: {format_brl(metricas_filtradas['saldo'])}"

    st.markdown(
        f"<div class='export-summary-card'>{texto_resumo_card}</div>",
        unsafe_allow_html=True,
    )

    if st.button("Enviar pelo WhatsApp", key="enviar_whatsapp_pdf", use_container_width=True):
        categoria_label = "Todas" if categoria_selecionada == "Todos" else categoria_selecionada
        mensagem_whatsapp = (
            f"Relatorio financeiro - Mes: {mes_selecionado} | "
            f"Categoria: {categoria_label} | "
            f"Receitas: {format_brl(metricas_filtradas['receitas'])} | "
            f"Despesas: {format_brl(metricas_filtradas['despesas'])} | "
            f"Saldo: {format_brl(metricas_filtradas['saldo'])} | "
            f"Lancamentos: {len(filtered_df)}"
        )
        compartilhar_pdf_whatsapp(pdf_bytes=pdf_bytes, nome_arquivo=nome_pdf, mensagem=mensagem_whatsapp)
        st.info(
            "Tentando compartilhar o PDF. Se o anexo nao for suportado no navegador, o WhatsApp sera aberto para voce escolher o contato."
        )

    st.markdown("</div>", unsafe_allow_html=True)

    for _, row in filtered_df.iterrows():
        render_movimento_card(row, user_id)


def _set_meta_editing_true() -> None:
    st.session_state["meta_editing"] = True


def _set_meta_editing_false() -> None:
    st.session_state["meta_editing"] = False


def render_meta_mensal(df: pd.DataFrame, user_id: int) -> None:
    mes_atual = datetime.now().strftime("%Y-%m")
    mes_label = datetime.now().strftime("%m/%Y")

    economizado = 0.0
    if not df.empty:
        df_mes = df[df["data_hora"].dt.strftime("%Y-%m") == mes_atual]
        receitas = float(df_mes.loc[df_mes["tipo"] == "receita", "valor"].sum())
        despesas = float(df_mes.loc[df_mes["tipo"] == "despesa", "valor"].sum())
        economizado = receitas - despesas

    meta = get_meta_mensal(user_id, mes_atual)
    editing = st.session_state.get("meta_editing", False)

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)

    header_col, btn_col = st.columns([0.78, 0.22])
    header_col.markdown("### 🎯 Meta do mês")

    if meta is not None and not editing:
        percentual_raw = (economizado / meta * 100) if meta > 0 else 0.0
        percentual_clamped = min(max(percentual_raw, 0.0), 100.0)

        if percentual_raw >= 100:
            cor = "#30c48d"
            status_msg = "✅ Meta atingida!"
        elif percentual_raw >= 70:
            cor = "#f9c846"
            status_msg = "Você está quase lá!"
        elif economizado >= 0:
            cor = "#ef5c6d"
            status_msg = "Continue economizando"
        else:
            cor = "#ef5c6d"
            status_msg = "Saldo negativo no mês"

        btn_col.button(
            "✏️ Editar",
            key="meta_alterar_btn",
            use_container_width=True,
            on_click=_set_meta_editing_true,
        )

        st.markdown(
            f"""
            <div class='meta-progress-wrap'>
                <div class='meta-info-row'>
                    <span class='meta-status-label'>{status_msg}</span>
                    <span class='meta-pct' style='color:{cor}'>{percentual_raw:.1f}%</span>
                </div>
                <div class='meta-bar-bg'>
                    <div class='meta-bar-fill'
                         style='width:{percentual_clamped:.2f}%;background:{cor};box-shadow:0 0 10px {cor}66;'>
                    </div>
                </div>
                <div class='meta-values-row'>
                    <span class='meta-val-atual' style='color:{cor}'>{format_brl(max(economizado, 0.0))}</span>
                    <span class='meta-val-sep'>economizados de</span>
                    <span class='meta-val-meta'>{format_brl(meta)}</span>
                    <span class='meta-val-sep'>em {mes_label}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        if editing:
            btn_col.button(
                "✕ Cancelar",
                key="meta_cancelar_btn",
                use_container_width=True,
                on_click=_set_meta_editing_false,
            )

        valor_default = meta if meta is not None else 0.0

        with st.form("form_meta_mensal", clear_on_submit=False):
            nova_meta = st.number_input(
                f"Meta de economia para {mes_label} (R$)",
                min_value=0.0,
                value=float(valor_default),
                step=100.0,
                format="%.2f",
                help="Quanto você deseja economizar este mês (receitas − despesas)",
            )
            salvar = st.form_submit_button("💾 Salvar meta", use_container_width=True)

        if salvar:
            if nova_meta <= 0:
                st.error("Informe um valor maior que zero para a meta.")
            else:
                save_meta_mensal(user_id, mes_atual, float(nova_meta))
                st.session_state["meta_editing"] = False
                st.success("Meta salva com sucesso!")
                st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def render_dashboard(user: dict) -> None:
    user_id = int(user["id"])

    top_left, top_right = st.columns([0.75, 0.25])
    top_left.markdown(f"## Ola, {user['nome']}")
    top_left.markdown("<p class='app-subtitle'>Painel financeiro pessoal</p>", unsafe_allow_html=True)

    if top_right.button("Sair", use_container_width=True):
        logout_user()
        st.rerun()

    df = load_movimentacoes(user_id)
    metrics = compute_metrics(df)

    abas = st.tabs(["Painel", "Orcamentos", "Resumo Financeiro"])

    with abas[0]:
        render_metric_cards(metrics, len(df))
        render_meta_mensal(df, user_id)
        render_nova_movimentacao(user_id)
        render_grafico(df)
        render_historico(df, user_id)

    with abas[1]:
        render_orcamentos(df, user_id)

    with abas[2]:
        render_resumo_financeiro(df, user_id)


def main() -> None:
    st.set_page_config(
        page_title="Controle Financeiro Web",
        page_icon=os.path.join(_PWA_DIR, "icon-192.png") if os.path.exists(os.path.join(_PWA_DIR, "icon-192.png")) else "💰",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    init_pwa_icons()
    init_db()
    init_session_state()
    apply_custom_css()
    inject_pwa()

    if not st.session_state["is_authenticated"]:
        render_auth_screen()
        return

    current_user_id = st.session_state.get("current_user_id")
    if current_user_id is None:
        logout_user()
        render_auth_screen()
        return

    user = get_user_by_id(int(current_user_id))
    if user is None:
        logout_user()
        st.warning("Sua sessao expirou. Faca login novamente.")
        render_auth_screen()
        return

    render_dashboard(user)


if __name__ == "__main__":
    main()
