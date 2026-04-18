import csv
import os
import sqlite3
from datetime import datetime

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget


class ControleFinanceiroApp(App):
    """Controle Financeiro em Kivy com SQLite, PIN opcional e layout mobile-first."""

    ESTILO = {
        "fundo_1": (0.04, 0.05, 0.08, 1),
        "fundo_2": (0.08, 0.10, 0.14, 1),
        "card": (0.10, 0.12, 0.17, 1),
        "card_soft": (0.12, 0.14, 0.20, 1),
        "texto": (0.95, 0.97, 1, 1),
        "texto_soft": (0.69, 0.74, 0.83, 1),
        "receita": (0.24, 0.78, 0.56, 1),
        "despesa": (0.89, 0.37, 0.41, 1),
        "acao": (0.16, 0.53, 0.89, 1),
        "aviso": (0.98, 0.74, 0.34, 1),
    }

    CATEGORIAS = [
        "Alimentação",
        "Transporte",
        "Moradia",
        "Saúde",
        "Educação",
        "Lazer",
        "Salário",
        "Investimentos",
        "Outros",
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.db_path = "controle_financeiro.db"
        self.nome_usuario = ""
        self.pin_usuario = ""
        self.saldo = 0.0
        self.movimentacoes = []
        self._layout_mobile = False

        self.app_container = None
        self.root_principal = None
        self.cadastro_root = None
        self.pin_root = None
        self.splash_root = None

    # ---------------------------
    # Ciclo do app
    # ---------------------------
    def build(self):
        self.title = "Controle Financeiro"
        Window.softinput_mode = "below_target"
        self._configurar_icone_app()
        self._inicializar_banco()

        self.app_container = BoxLayout(orientation="vertical")
        self._aplicar_fundo(self.app_container, cor=self.ESTILO["fundo_1"])

        self._mostrar_tela_splash()
        Window.bind(size=self._on_window_resize)
        return self.app_container

    def _configurar_icone_app(self):
        if os.path.exists("icon.png"):
            self.icon = "icon.png"

    def _mostrar_tela_splash(self):
        self.splash_root = BoxLayout(
            orientation="vertical",
            padding=[dp(24), dp(24), dp(24), dp(24)],
            spacing=dp(8),
        )

        self.splash_root.add_widget(Widget(size_hint_y=0.42))

        titulo = Label(
            text="[b]Controle Financeiro[/b]",
            markup=True,
            size_hint_y=None,
            height=dp(58),
            font_size="36sp",
            color=self.ESTILO["texto"],
            font_name="Roboto",
        )
        assinatura = Label(
            text="by Ramires Apps",
            size_hint_y=None,
            height=dp(30),
            font_size="18sp",
            color=self.ESTILO["texto_soft"],
            font_name="Roboto",
        )

        self.splash_root.add_widget(titulo)
        self.splash_root.add_widget(assinatura)
        self.splash_root.add_widget(Widget(size_hint_y=0.58))

        self.app_container.clear_widgets()
        self.app_container.add_widget(self.splash_root)
        Clock.schedule_once(self._iniciar_fluxo_inicial, 2.0)

    def _iniciar_fluxo_inicial(self, _dt):
        usuario = self._carregar_usuario_db()
        self.nome_usuario = usuario["nome"]
        self.pin_usuario = usuario["pin"]

        if not self.nome_usuario:
            self._mostrar_tela_cadastro_primeiro_acesso()
            return

        if self.pin_usuario:
            self._mostrar_tela_pin()
            return

        self._mostrar_tela_principal()

    # ---------------------------
    # Tela de primeiro acesso
    # ---------------------------
    def _mostrar_tela_cadastro_primeiro_acesso(self):
        self.cadastro_root = BoxLayout(
            orientation="vertical",
            padding=[dp(24), dp(24), dp(24), dp(20)],
            spacing=dp(14),
        )

        card = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(340),
            padding=[dp(18), dp(18), dp(18), dp(16)],
            spacing=dp(12),
        )
        self._aplicar_fundo(card, cor=self.ESTILO["card"], raio=18)

        titulo = Label(
            text="[b]Primeiro acesso[/b]",
            markup=True,
            size_hint_y=None,
            height=dp(42),
            color=self.ESTILO["texto"],
            font_size="24sp",
            font_name="Roboto",
            halign="left",
            valign="middle",
        )
        titulo.bind(size=titulo.setter("text_size"))

        subtitulo = Label(
            text="Cadastre seu nome e, opcionalmente, um PIN de 4 dígitos.",
            size_hint_y=None,
            height=dp(34),
            color=self.ESTILO["texto_soft"],
            font_size="15sp",
            font_name="Roboto",
            halign="left",
            valign="middle",
        )
        subtitulo.bind(size=subtitulo.setter("text_size"))

        self.cadastro_nome_input = self._criar_input_estilizado("Seu nome", tamanho="16sp")
        self.cadastro_nome_input.size_hint_y = None
        self.cadastro_nome_input.height = dp(52)

        self.cadastro_pin_input = self._criar_input_estilizado("PIN opcional (4 dígitos)", filtro="int", tamanho="16sp")
        self.cadastro_pin_input.password = True
        self.cadastro_pin_input.size_hint_y = None
        self.cadastro_pin_input.height = dp(52)

        self.cadastro_mensagem_label = Label(
            text="",
            size_hint_y=None,
            height=dp(24),
            color=self.ESTILO["despesa"],
            font_size="14sp",
            font_name="Roboto",
            halign="left",
            valign="middle",
        )
        self.cadastro_mensagem_label.bind(size=self.cadastro_mensagem_label.setter("text_size"))

        botao_salvar = self._criar_botao_estilizado(
            "Salvar e continuar",
            self.ESTILO["acao"],
            self._salvar_primeiro_acesso,
        )
        botao_salvar.size_hint_y = None
        botao_salvar.height = dp(50)

        card.add_widget(titulo)
        card.add_widget(subtitulo)
        card.add_widget(self.cadastro_nome_input)
        card.add_widget(self.cadastro_pin_input)
        card.add_widget(self.cadastro_mensagem_label)
        card.add_widget(botao_salvar)

        self.cadastro_root.add_widget(Widget(size_hint_y=0.34))
        self.cadastro_root.add_widget(card)
        self.cadastro_root.add_widget(Widget(size_hint_y=0.42))

        self.app_container.clear_widgets()
        self.app_container.add_widget(self.cadastro_root)
        self._aplicar_layout_responsivo(Window, Window.width, Window.height)
        Clock.schedule_once(self._animar_entrada_cadastro, 0.05)

    def _salvar_primeiro_acesso(self):
        nome = self.cadastro_nome_input.text.strip()
        pin = self.cadastro_pin_input.text.strip()

        if len(nome) < 2:
            self._mostrar_mensagem("Digite um nome válido (mínimo 2 caracteres).", "erro")
            return

        if pin and (not pin.isdigit() or len(pin) != 4):
            self._mostrar_mensagem("PIN deve ter exatamente 4 dígitos.", "erro")
            return

        self._salvar_usuario_db(nome, pin)
        self.nome_usuario = nome
        self.pin_usuario = pin
        self._mostrar_tela_principal()

    # ---------------------------
    # Tela de PIN
    # ---------------------------
    def _mostrar_tela_pin(self):
        self.pin_root = BoxLayout(
            orientation="vertical",
            padding=[dp(24), dp(24), dp(24), dp(20)],
            spacing=dp(14),
        )

        card = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(290),
            padding=[dp(18), dp(18), dp(18), dp(16)],
            spacing=dp(12),
        )
        self._aplicar_fundo(card, cor=self.ESTILO["card"], raio=18)

        titulo = Label(
            text="[b]Segurança PIN[/b]",
            markup=True,
            size_hint_y=None,
            height=dp(42),
            color=self.ESTILO["texto"],
            font_size="24sp",
            font_name="Roboto",
            halign="left",
            valign="middle",
        )
        titulo.bind(size=titulo.setter("text_size"))

        subtitulo = Label(
            text=f"Olá, {self.nome_usuario}. Digite seu PIN para continuar.",
            size_hint_y=None,
            height=dp(34),
            color=self.ESTILO["texto_soft"],
            font_size="15sp",
            font_name="Roboto",
            halign="left",
            valign="middle",
        )
        subtitulo.bind(size=subtitulo.setter("text_size"))

        self.pin_login_input = self._criar_input_estilizado("PIN (4 dígitos)", filtro="int", tamanho="18sp")
        self.pin_login_input.password = True
        self.pin_login_input.size_hint_y = None
        self.pin_login_input.height = dp(54)

        self.pin_mensagem_label = Label(
            text="",
            size_hint_y=None,
            height=dp(24),
            color=self.ESTILO["despesa"],
            font_size="14sp",
            font_name="Roboto",
            halign="left",
            valign="middle",
        )
        self.pin_mensagem_label.bind(size=self.pin_mensagem_label.setter("text_size"))

        botao_entrar = self._criar_botao_estilizado("Entrar", self.ESTILO["acao"], self._validar_pin_entrada)
        botao_entrar.size_hint_y = None
        botao_entrar.height = dp(50)

        card.add_widget(titulo)
        card.add_widget(subtitulo)
        card.add_widget(self.pin_login_input)
        card.add_widget(self.pin_mensagem_label)
        card.add_widget(botao_entrar)

        self.pin_root.add_widget(Widget(size_hint_y=0.35))
        self.pin_root.add_widget(card)
        self.pin_root.add_widget(Widget(size_hint_y=0.45))

        self.app_container.clear_widgets()
        self.app_container.add_widget(self.pin_root)
        self._aplicar_layout_responsivo(Window, Window.width, Window.height)
        Clock.schedule_once(self._animar_entrada_pin, 0.05)

    def _validar_pin_entrada(self):
        pin_digitado = self.pin_login_input.text.strip()
        if pin_digitado == self.pin_usuario:
            self._mostrar_tela_principal()
            return
        self._mostrar_mensagem("PIN inválido.", "erro")

    # ---------------------------
    # Tela principal
    # ---------------------------
    def _mostrar_tela_principal(self):
        self.root_principal = self._montar_interface_principal()
        self.app_container.clear_widgets()
        self.app_container.add_widget(self.root_principal)

        self._carregar_dados_iniciais()
        self._aplicar_layout_responsivo(Window, Window.width, Window.height)
        Clock.schedule_once(self._animar_entrada_painel, 0.05)

    def _montar_interface_principal(self):
        root = BoxLayout(orientation="vertical", padding=[dp(20), dp(20), dp(20), dp(16)], spacing=dp(12))
        self._aplicar_fundo(root, cor=(0, 0, 0, 0))

        root.add_widget(self._criar_saudacao())
        root.add_widget(self._criar_titulo())
        root.add_widget(self._criar_saldo_box())
        root.add_widget(self._criar_mensagem_label())
        root.add_widget(self._criar_formulario())
        root.add_widget(self._criar_botoes_principais())
        root.add_widget(self._criar_secao_grafico())
        root.add_widget(self._criar_secao_historico())
        return root

    def _criar_saudacao(self):
        self.saudacao_label = Label(
            text=f"Olá, {self.nome_usuario or 'Usuário'}",
            font_size="17sp",
            size_hint_y=None,
            height=dp(30),
            color=self.ESTILO["texto_soft"],
            font_name="Roboto",
            halign="left",
            valign="middle",
        )
        self.saudacao_label.bind(size=self.saudacao_label.setter("text_size"))
        return self.saudacao_label

    def _criar_titulo(self):
        self.titulo_label = Label(
            text="[b]Controle Financeiro[/b]",
            markup=True,
            font_size="34sp",
            size_hint_y=None,
            height=dp(58),
            color=self.ESTILO["texto"],
            font_name="Roboto",
        )
        return self.titulo_label

    def _criar_saldo_box(self):
        saldo_box = BoxLayout(size_hint_y=None, height=dp(82), padding=[dp(16), dp(10)], spacing=dp(8))
        self._aplicar_fundo(saldo_box, cor=self.ESTILO["fundo_2"], raio=16)

        self.saldo_label = Label(
            text="Saldo atual: R$ 0,00",
            font_size="26sp",
            bold=True,
            color=self.ESTILO["receita"],
            font_name="Roboto",
        )
        saldo_box.add_widget(self.saldo_label)
        return saldo_box

    def _criar_mensagem_label(self):
        self.mensagem_label = Label(
            text="",
            font_size="15sp",
            size_hint_y=None,
            height=dp(26),
            color=self.ESTILO["texto_soft"],
            font_name="Roboto",
            halign="left",
            valign="middle",
        )
        self.mensagem_label.bind(size=self.mensagem_label.setter("text_size"))
        return self.mensagem_label

    def _criar_formulario(self):
        self.formulario = GridLayout(cols=3, spacing=dp(10), size_hint_y=None, height=dp(58))

        self.descricao_input = self._criar_input_estilizado("Descrição", tamanho="16sp")
        self.valor_input = self._criar_input_estilizado("Valor (ex: 120.50)", filtro="float", tamanho="16sp")
        self.categoria_spinner = Spinner(
            text="Categoria",
            values=self.CATEGORIAS,
            background_normal="",
            background_color=self.ESTILO["card_soft"],
            color=self.ESTILO["texto"],
            font_size="16sp",
            font_name="Roboto",
        )
        self._aplicar_fundo(self.categoria_spinner, cor=self.ESTILO["card_soft"], raio=12)

        self.formulario.add_widget(self.descricao_input)
        self.formulario.add_widget(self.valor_input)
        self.formulario.add_widget(self.categoria_spinner)
        return self.formulario

    def _criar_botoes_principais(self):
        self.botoes = BoxLayout(size_hint_y=None, height=dp(58), spacing=dp(10))

        botao_receita = self._criar_botao_estilizado("Adicionar Receita", self.ESTILO["receita"], self._adicionar_movimentacao, "receita")
        botao_despesa = self._criar_botao_estilizado("Adicionar Despesa", self.ESTILO["despesa"], self._adicionar_movimentacao, "despesa")
        botao_exportar = self._criar_botao_estilizado("Exportar Dados", self.ESTILO["acao"], self._exportar_dados_csv)

        self.botoes.add_widget(botao_receita)
        self.botoes.add_widget(botao_despesa)
        self.botoes.add_widget(botao_exportar)
        return self.botoes

    def _criar_secao_grafico(self):
        self.secao_grafico = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None, height=dp(220))

        titulo = Label(
            text="Gráfico mensal (saldo líquido)",
            size_hint_y=None,
            height=dp(32),
            color=self.ESTILO["texto_soft"],
            halign="left",
            valign="middle",
            font_size="16sp",
            font_name="Roboto",
        )
        titulo.bind(size=titulo.setter("text_size"))
        self.secao_grafico.add_widget(titulo)

        grafico_container = BoxLayout(orientation="vertical", padding=[dp(12), dp(10)], spacing=dp(6))
        self._aplicar_fundo(grafico_container, cor=self.ESTILO["card"], raio=14)

        self.grafico_layout = GridLayout(cols=1, spacing=dp(8), size_hint_y=None)
        self.grafico_layout.bind(minimum_height=self.grafico_layout.setter("height"))

        scroll_grafico = ScrollView(
            bar_width=dp(5),
            do_scroll_x=False,
            do_scroll_y=True,
            scroll_type=["bars", "content"],
            scroll_wheel_distance=dp(48),
        )
        scroll_grafico.add_widget(self.grafico_layout)

        grafico_container.add_widget(scroll_grafico)
        self.secao_grafico.add_widget(grafico_container)
        return self.secao_grafico

    def _criar_secao_historico(self):
        secao = BoxLayout(orientation="vertical", spacing=dp(6))

        titulo = Label(
            text="Histórico de movimentações",
            size_hint_y=None,
            height=dp(32),
            color=self.ESTILO["texto_soft"],
            halign="left",
            valign="middle",
            font_size="16sp",
            font_name="Roboto",
        )
        titulo.bind(size=titulo.setter("text_size"))
        secao.add_widget(titulo)

        self.historico_layout = GridLayout(cols=1, spacing=dp(8), size_hint_y=None, padding=[0, 0, 0, dp(8)])
        self.historico_layout.bind(minimum_height=self.historico_layout.setter("height"))

        scroll = ScrollView(
            bar_width=dp(6),
            do_scroll_x=False,
            do_scroll_y=True,
            scroll_type=["bars", "content"],
            scroll_wheel_distance=dp(52),
        )
        scroll.add_widget(self.historico_layout)
        secao.add_widget(scroll)
        return secao

    # ---------------------------
    # Banco de dados
    # ---------------------------
    def _inicializar_banco(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usuario (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    nome TEXT NOT NULL,
                    pin TEXT
                )
                """
            )
            self._garantir_coluna(conn, "usuario", "pin", "TEXT")
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

    @staticmethod
    def _garantir_coluna(conn, tabela, coluna, tipo_coluna):
        colunas = [row[1] for row in conn.execute(f"PRAGMA table_info({tabela})").fetchall()]
        if coluna not in colunas:
            conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo_coluna}")

    def _salvar_usuario_db(self, nome, pin):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO usuario (id, nome, pin)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET nome = excluded.nome, pin = excluded.pin
                """,
                (nome, pin or ""),
            )

    def _carregar_usuario_db(self):
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT nome, COALESCE(pin, '') FROM usuario WHERE id = 1").fetchone()

        if not row:
            return {"nome": "", "pin": ""}
        return {"nome": (row[0] or "").strip(), "pin": (row[1] or "").strip()}

    def _salvar_movimentacao_db(self, tipo, descricao, categoria, valor):
        data_hora = datetime.now().isoformat(timespec="seconds")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO movimentacoes (tipo, descricao, categoria, valor, data_hora)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tipo, descricao, categoria, valor, data_hora),
            )

    def _excluir_movimentacao_db(self, movimento_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM movimentacoes WHERE id = ?", (movimento_id,))

    def _carregar_movimentacoes_db(self):
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, tipo, descricao, categoria, valor, data_hora
                FROM movimentacoes
                ORDER BY data_hora DESC, id DESC
                """
            ).fetchall()

        self.movimentacoes = [
            {
                "id": row[0],
                "tipo": row[1],
                "descricao": row[2],
                "categoria": row[3],
                "valor": float(row[4]),
                "data_hora": row[5],
            }
            for row in rows
        ]

    # ---------------------------
    # Fluxo de dados
    # ---------------------------
    def _carregar_dados_iniciais(self):
        self._carregar_movimentacoes_db()
        self._recalcular_saldo()
        self._atualizar_saudacao()
        self._renderizar_historico()
        self._renderizar_grafico_mensal()

    def _adicionar_movimentacao(self, tipo):
        descricao = self.descricao_input.text.strip() or "Sem descrição"
        valor_texto = self.valor_input.text.strip().replace(",", ".")
        categoria = self.categoria_spinner.text.strip()

        erro = self._validar_entrada(valor_texto, categoria)
        if erro:
            self._mostrar_mensagem(erro, "erro")
            return

        valor = float(valor_texto)
        self._salvar_movimentacao_db(tipo, descricao, categoria, valor)

        self._carregar_dados_iniciais()
        self._limpar_campos()
        self._mostrar_mensagem("Movimentação salva com sucesso.", "sucesso")
        self._animar_saldo()

    def _excluir_movimentacao(self, movimento_id):
        self._excluir_movimentacao_db(movimento_id)
        self._carregar_dados_iniciais()
        self._mostrar_mensagem("Movimentação excluída.", "aviso")

    def _exportar_dados_csv(self):
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT data_hora, tipo, descricao, categoria, valor
                FROM movimentacoes
                ORDER BY data_hora ASC, id ASC
                """
            ).fetchall()

        nome_arquivo = f"backup_controle_financeiro_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        caminho_arquivo = os.path.join(os.getcwd(), nome_arquivo)

        with open(caminho_arquivo, "w", newline="", encoding="utf-8") as arquivo_csv:
            writer = csv.writer(arquivo_csv)
            writer.writerow(["data", "tipo", "descricao", "categoria", "valor"])
            for data_hora, tipo, descricao, categoria, valor in rows:
                writer.writerow([self._formatar_data(data_hora), tipo, descricao, categoria, f"{valor:.2f}"])

        self._mostrar_mensagem(f"CSV exportado: {nome_arquivo}", "sucesso")

    def _validar_entrada(self, valor_texto, categoria):
        if not valor_texto:
            return "Informe um valor."

        try:
            valor = float(valor_texto)
        except ValueError:
            return "Digite um valor numérico válido."

        if valor <= 0:
            return "O valor deve ser maior que zero."

        if categoria == "Categoria":
            return "Selecione uma categoria."

        return ""

    def _limpar_campos(self):
        self.descricao_input.text = ""
        self.valor_input.text = ""
        self.categoria_spinner.text = "Categoria"

    # ---------------------------
    # Renderização
    # ---------------------------
    def _recalcular_saldo(self):
        saldo = 0.0
        for mov in self.movimentacoes:
            saldo += mov["valor"] if mov["tipo"] == "receita" else -mov["valor"]
        self.saldo = saldo
        self._atualizar_saldo_label()

    def _atualizar_saldo_label(self):
        self.saldo_label.color = self.ESTILO["receita"] if self.saldo >= 0 else self.ESTILO["despesa"]
        self.saldo_label.text = f"Saldo atual: R$ {self._formatar_valor(self.saldo)}"

    def _atualizar_saudacao(self):
        if hasattr(self, "saudacao_label"):
            self.saudacao_label.text = f"Olá, {self.nome_usuario or 'Usuário'}"

    def _renderizar_historico(self):
        self.historico_layout.clear_widgets()

        if not self.movimentacoes:
            self.historico_layout.add_widget(
                Label(
                    text="Nenhuma movimentação registrada.",
                    size_hint_y=None,
                    height=dp(42),
                    color=self.ESTILO["texto_soft"],
                    font_name="Roboto",
                    font_size="15sp",
                )
            )
            return

        for mov in self.movimentacoes:
            card = self._criar_card_movimentacao(mov)
            self.historico_layout.add_widget(card)
            self._animar_widget_aparecer(card, duracao=0.16)

    def _criar_card_movimentacao(self, mov):
        card = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(96),
            spacing=dp(10),
            padding=[dp(12), dp(10), dp(12), dp(10)],
        )
        self._aplicar_fundo(card, cor=self.ESTILO["card"], raio=14)

        tipo_texto = "Receita" if mov["tipo"] == "receita" else "Despesa"
        horario = self._formatar_data(mov["data_hora"])

        detalhe = Label(
            text=(
                f"[b]{tipo_texto}[/b]  [color=#A8B4CF]{mov['categoria']}[/color]\n"
                f"{mov['descricao']}\n"
                f"[size=12]{horario}[/size]"
            ),
            markup=True,
            halign="left",
            valign="middle",
            color=self.ESTILO["texto"],
            font_name="Roboto",
            font_size="15sp",
        )
        detalhe.bind(size=detalhe.setter("text_size"))

        coluna_direita = BoxLayout(orientation="vertical", size_hint_x=0.36, spacing=dp(6))

        cor_valor = self.ESTILO["receita"] if mov["tipo"] == "receita" else self.ESTILO["despesa"]
        prefixo = "+" if mov["tipo"] == "receita" else "-"
        valor_label = Label(
            text=f"{prefixo} R$ {self._formatar_valor(mov['valor'])}",
            bold=True,
            color=cor_valor,
            halign="right",
            valign="middle",
            font_name="Roboto",
            font_size="15sp",
        )
        valor_label.bind(size=valor_label.setter("text_size"))

        botao_excluir = self._criar_botao_estilizado("Excluir", (0.57, 0.24, 0.29, 1), self._excluir_movimentacao, mov["id"])
        botao_excluir.size_hint_y = None
        botao_excluir.height = dp(34)

        coluna_direita.add_widget(valor_label)
        coluna_direita.add_widget(botao_excluir)
        card.add_widget(detalhe)
        card.add_widget(coluna_direita)
        return card

    def _renderizar_grafico_mensal(self):
        self.grafico_layout.clear_widgets()
        dados = self._buscar_dados_grafico()

        if not dados:
            self.grafico_layout.add_widget(
                Label(
                    text="Sem dados para o gráfico mensal.",
                    size_hint_y=None,
                    height=dp(36),
                    color=self.ESTILO["texto_soft"],
                    font_name="Roboto",
                    font_size="15sp",
                )
            )
            return

        maior_valor = max(abs(item[1]) for item in dados) if dados else 0.0
        for mes, saldo_mes in dados:
            proporcao = (abs(saldo_mes) / maior_valor) if maior_valor > 0 else 0
            linha = self._criar_linha_grafico(mes, saldo_mes, proporcao)
            self.grafico_layout.add_widget(linha)

    def _criar_linha_grafico(self, mes, saldo_mes, proporcao):
        linha = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(8))

        mes_label = Label(
            text=mes,
            size_hint_x=0.22,
            color=self.ESTILO["texto_soft"],
            halign="left",
            valign="middle",
            font_name="Roboto",
            font_size="14sp",
        )
        mes_label.bind(size=mes_label.setter("text_size"))

        area_barra = BoxLayout(size_hint_x=0.52)
        preenchido = BoxLayout(size_hint_x=max(proporcao, 0.03))
        cor_barra = self.ESTILO["receita"] if saldo_mes >= 0 else self.ESTILO["despesa"]
        self._aplicar_fundo(preenchido, cor=cor_barra, raio=6)
        area_barra.add_widget(preenchido)
        area_barra.add_widget(Widget(size_hint_x=max(0.0, 1 - max(proporcao, 0.03))))

        valor_label = Label(
            text=f"R$ {self._formatar_valor(saldo_mes)}",
            size_hint_x=0.26,
            color=self.ESTILO["texto_soft"],
            halign="right",
            valign="middle",
            font_name="Roboto",
            font_size="14sp",
        )
        valor_label.bind(size=valor_label.setter("text_size"))

        linha.add_widget(mes_label)
        linha.add_widget(area_barra)
        linha.add_widget(valor_label)
        return linha

    def _buscar_dados_grafico(self):
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    strftime('%m/%Y', data_hora) AS mes,
                    SUM(CASE WHEN tipo = 'receita' THEN valor ELSE -valor END) AS saldo_mensal
                FROM movimentacoes
                GROUP BY strftime('%Y-%m', data_hora)
                ORDER BY strftime('%Y-%m', data_hora) DESC
                LIMIT 6
                """
            ).fetchall()
        return list(reversed([(row[0], float(row[1])) for row in rows]))

    # ---------------------------
    # Utilitários
    # ---------------------------
    def _criar_input_estilizado(self, hint, filtro=None, tamanho="15sp"):
        return TextInput(
            hint_text=hint,
            multiline=False,
            input_filter=filtro,
            background_color=self.ESTILO["card_soft"],
            foreground_color=self.ESTILO["texto"],
            hint_text_color=self.ESTILO["texto_soft"],
            cursor_color=self.ESTILO["texto"],
            padding=[dp(12), dp(14), dp(12), dp(10)],
            font_size=tamanho,
            font_name="Roboto",
        )

    def _criar_botao_estilizado(self, texto, cor, callback, callback_arg=None):
        botao = Button(
            text=texto,
            bold=True,
            background_normal="",
            background_color=cor,
            color=(1, 1, 1, 1),
            font_size="15sp",
            font_name="Roboto",
        )
        self._aplicar_animacao_botao(botao, cor)

        if callback_arg is None:
            botao.bind(on_press=lambda _btn: callback())
        else:
            botao.bind(on_press=lambda _btn: callback(callback_arg))
        return botao

    def _aplicar_fundo(self, widget, cor, raio=0):
        with widget.canvas.before:
            Color(*cor)
            if raio > 0:
                widget._bg_shape = RoundedRectangle(pos=widget.pos, size=widget.size, radius=[raio])
            else:
                widget._bg_shape = Rectangle(pos=widget.pos, size=widget.size)
        widget.bind(pos=self._atualizar_fundo_widget, size=self._atualizar_fundo_widget)

    @staticmethod
    def _atualizar_fundo_widget(widget, _valor):
        if hasattr(widget, "_bg_shape"):
            widget._bg_shape.pos = widget.pos
            widget._bg_shape.size = widget.size

    def _on_window_resize(self, window, size):
        self._aplicar_layout_responsivo(window, size[0], size[1])

    def _aplicar_layout_responsivo(self, _window, largura, _altura):
        mobile = largura < dp(860)
        if mobile == self._layout_mobile:
            return

        self._layout_mobile = mobile

        if self.root_principal is not None:
            self.formulario.cols = 1 if mobile else 3
            self.formulario.height = dp(186) if mobile else dp(58)

            self.botoes.orientation = "vertical" if mobile else "horizontal"
            self.botoes.height = dp(190) if mobile else dp(58)

            self.secao_grafico.height = dp(180) if mobile else dp(220)
            self.root_principal.padding = [dp(14), dp(14), dp(14), dp(10)] if mobile else [dp(20), dp(20), dp(20), dp(16)]

            self.titulo_label.font_size = "29sp" if mobile else "34sp"
            self.saudacao_label.font_size = "15sp" if mobile else "17sp"
            self.saldo_label.font_size = "24sp" if mobile else "26sp"

        if self.cadastro_root is not None:
            self.cadastro_root.padding = [dp(14), dp(14), dp(14), dp(10)] if mobile else [dp(24), dp(24), dp(24), dp(20)]

        if self.pin_root is not None:
            self.pin_root.padding = [dp(14), dp(14), dp(14), dp(10)] if mobile else [dp(24), dp(24), dp(24), dp(20)]

    def _aplicar_animacao_botao(self, botao, cor_base):
        cor_hover = (
            min(1.0, cor_base[0] + 0.08),
            min(1.0, cor_base[1] + 0.08),
            min(1.0, cor_base[2] + 0.08),
            1,
        )

        def animar_press(_instance):
            Animation.cancel_all(botao, "background_color")
            (Animation(background_color=cor_hover, d=0.08) + Animation(background_color=cor_base, d=0.18)).start(botao)

        botao.bind(on_press=animar_press)

    def _animar_widget_aparecer(self, widget, duracao=0.20):
        widget.opacity = 0
        Animation(opacity=1, d=duracao, t="out_quad").start(widget)

    def _animar_entrada_painel(self, _dt):
        widgets = [
            self.saudacao_label,
            self.titulo_label,
            self.saldo_label,
            self.mensagem_label,
            self.formulario,
            self.botoes,
            self.secao_grafico,
            self.historico_layout,
        ]
        for indice, widget in enumerate(widgets):
            widget.opacity = 0
            Clock.schedule_once(
                lambda _inner_dt, w=widget: Animation(opacity=1, d=0.24, t="out_cubic").start(w),
                indice * 0.03,
            )

    def _animar_entrada_cadastro(self, _dt):
        if not self.cadastro_root:
            return
        for indice, widget in enumerate(self.cadastro_root.children):
            widget.opacity = 0
            Clock.schedule_once(
                lambda _inner_dt, w=widget: Animation(opacity=1, d=0.22, t="out_cubic").start(w),
                indice * 0.04,
            )

    def _animar_entrada_pin(self, _dt):
        if not self.pin_root:
            return
        for indice, widget in enumerate(self.pin_root.children):
            widget.opacity = 0
            Clock.schedule_once(
                lambda _inner_dt, w=widget: Animation(opacity=1, d=0.22, t="out_cubic").start(w),
                indice * 0.04,
            )

    def _animar_saldo(self):
        Animation.cancel_all(self.saldo_label)
        (Animation(font_size=sp(28), d=0.08, t="out_quad") + Animation(font_size=sp(26), d=0.16, t="out_quad")).start(
            self.saldo_label
        )

    def _mostrar_mensagem(self, texto, tipo="info"):
        cor = self.ESTILO["texto_soft"]
        if tipo == "erro":
            cor = self.ESTILO["despesa"]
        elif tipo == "sucesso":
            cor = self.ESTILO["receita"]
        elif tipo == "aviso":
            cor = self.ESTILO["aviso"]

        if hasattr(self, "mensagem_label") and self.mensagem_label.parent is not None:
            self.mensagem_label.text = texto
            self.mensagem_label.color = cor

        if hasattr(self, "cadastro_mensagem_label") and self.cadastro_mensagem_label.parent is not None:
            self.cadastro_mensagem_label.text = texto
            self.cadastro_mensagem_label.color = cor

        if hasattr(self, "pin_mensagem_label") and self.pin_mensagem_label.parent is not None:
            self.pin_mensagem_label.text = texto
            self.pin_mensagem_label.color = cor

    @staticmethod
    def _formatar_valor(valor):
        return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    @staticmethod
    def _formatar_data(data_hora_iso):
        try:
            return datetime.fromisoformat(data_hora_iso).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            return data_hora_iso


if __name__ == "__main__":
    ControleFinanceiroApp().run()