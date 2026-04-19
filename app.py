import hashlib
import hmac
import os
import re
import shutil
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

# ── PWA: sincronizacao dos icones personalizados do projeto ───────────────────

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
_PWA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pwa")
_PWA_VERSION = "3"


def init_pwa_icons() -> None:
    """Sincroniza icones personalizados da pasta pwa/ para static/."""
    os.makedirs(_STATIC_DIR, exist_ok=True)
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
        static_path = os.path.join(_STATIC_DIR, filename)
        pwa_path = os.path.join(_PWA_DIR, filename)

        if source_path is not None:
            if os.path.abspath(source_path) != os.path.abspath(pwa_path):
                shutil.copyfile(source_path, pwa_path)
            shutil.copyfile(pwa_path, static_path)


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

        migrate_legacy_data(conn)


def init_session_state() -> None:
    st.session_state.setdefault("editing_id", None)
    st.session_state.setdefault("delete_confirm_id", None)
    st.session_state.setdefault("hist_search", "")
    st.session_state.setdefault("hist_mes", "Todos")
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
    st.session_state["hist_mes"] = "Todos"
    st.session_state["hist_categoria"] = "Todos"
    st.session_state["hist_tipo"] = "Todos"


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
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_pwa() -> None:
    """Injeta manifest link, meta tags e registro do Service Worker na pagina."""
    st.markdown(
                f"""
                <link rel="manifest" href="/app/static/manifest.webmanifest?v={_PWA_VERSION}">
        <meta name="mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
                <meta name="apple-mobile-web-app-title" content="Controle Financeiro">
                <meta name="theme-color" content="#f5b400">
                <link rel="apple-touch-icon" href="/app/static/icon-192.png?v={_PWA_VERSION}">
        <script>
                    if ('serviceWorker' in navigator) {{
                        window.addEventListener('load', function () {{
              navigator.serviceWorker
                                .register('/app/static/sw.js?v={_PWA_VERSION}')
                                .then(function (reg) {{
                  console.log('[PWA] Service Worker registrado. Scope:', reg.scope);
                                }})
                                .catch(function (err) {{
                  console.warn('[PWA] Registro do Service Worker falhou:', err);
                                }});
                        }});
                    }}
        </script>
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

    month_options = ["Todos"]
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
        st.session_state["hist_mes"] = "Todos"
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

    filtered_df = df.copy()
    busca = st.session_state["hist_search"].strip().lower()
    if busca:
        filtered_df = filtered_df[
            filtered_df["descricao"].fillna("").astype(str).str.lower().str.contains(busca, na=False)
        ]

    if st.session_state["hist_mes"] != "Todos":
        mes_ref = st.session_state["hist_mes"]
        filtered_df = filtered_df[
            filtered_df["data_hora"].dt.strftime("%m/%Y") == mes_ref
        ]

    if st.session_state["hist_categoria"] != "Todos":
        filtered_df = filtered_df[
            filtered_df["categoria"].astype(str) == st.session_state["hist_categoria"]
        ]

    if st.session_state["hist_tipo"] != "Todos":
        filtered_df = filtered_df[
            filtered_df["tipo"].astype(str) == st.session_state["hist_tipo"].lower()
        ]

    st.markdown(
        f"<div class='filters-result'>{len(filtered_df)} movimentacoes encontradas</div>",
        unsafe_allow_html=True,
    )

    if df.empty:
        st.info("Nenhuma movimentacao cadastrada.")
        return

    if filtered_df.empty:
        st.info("Nenhuma movimentacao encontrada para os filtros selecionados.")
        return

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

    render_metric_cards(metrics, len(df))
    render_meta_mensal(df, user_id)
    render_nova_movimentacao(user_id)
    render_grafico(df)
    render_historico(df, user_id)


def main() -> None:
    st.set_page_config(
        page_title="Controle Financeiro Web",
        page_icon=os.path.join(_STATIC_DIR, "icon-192.png") if os.path.exists(os.path.join(_STATIC_DIR, "icon-192.png")) else "💰",
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
