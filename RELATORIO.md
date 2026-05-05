# Relatório do Aplicativo — Controle Financeiro

**Data:** 05/05/2026  
**Autor:** Ramires Apps  

---

## 1. Visão Geral

O **Controle Financeiro** é um sistema de gestão financeira pessoal desenvolvido em Python, disponível em duas versões complementares:

| Versão | Arquivo | Framework | Plataforma |
|--------|---------|-----------|------------|
| Web | `app.py` | Streamlit | Browser (desktop e mobile) |
| Mobile/Desktop | `main.py` | Kivy | Android / Windows / macOS / Linux |

---

## 2. Versão Web (`app.py`)

### 2.1 Tecnologias

| Dependência | Versão mínima | Finalidade |
|-------------|---------------|------------|
| `streamlit` | ≥ 1.35.0 | Interface web |
| `pandas` | ≥ 2.2.0 | Manipulação de dados |
| `plotly` | ≥ 5.22.0 | Gráficos interativos |
| `sqlite3` | stdlib | Banco de dados local |

### 2.2 Banco de Dados (SQLite — `controle_financeiro.db`)

**Tabela `usuarios`**

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | INTEGER PK | Identificador único |
| `nome` | TEXT | Nome do usuário |
| `email` | TEXT UNIQUE | Email (normalizado em minúsculas) |
| `senha_hash` | TEXT | Hash PBKDF2-SHA256 + salt de 16 bytes |
| `created_at` | TEXT | Data/hora de criação (ISO 8601) |

**Tabela `movimentacoes`**

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | INTEGER PK | Identificador único |
| `usuario_id` | INTEGER FK | Referência ao usuário dono |
| `tipo` | TEXT | `receita` ou `despesa` |
| `descricao` | TEXT | Descrição da movimentação |
| `categoria` | TEXT | Categoria selecionada |
| `valor` | REAL | Valor em reais |
| `data_hora` | TEXT | Data/hora de registro (ISO 8601) |

**Tabela `metas_mensais`**

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | INTEGER PK | Identificador único |
| `usuario_id` | INTEGER FK | Usuário dono |
| `mes` | TEXT | Mês no formato `YYYY-MM` |
| `valor_meta` | REAL | Meta de economia em reais |

### 2.3 Funcionalidades

#### Autenticação
- Cadastro de conta com nome, email e senha (mínimo 6 caracteres)
- Login com email e senha
- Senhas armazenadas com **PBKDF2-SHA256**, 200.000 iterações e salt aleatório de 16 bytes
- Comparação de digest com `hmac.compare_digest` (proteção contra timing attacks)
- Migração automática de dados legados (versão anterior sem multi-usuário)

#### Dashboard
- Cabeçalho com saudação ao usuário e botão "Sair"
- **4 cards de métricas** com gradiente colorido:
  - Saldo atual (verde escuro)
  - Total de receitas (azul escuro)
  - Total de despesas (vermelho escuro)
  - Quantidade de movimentações (roxo)

#### Meta Mensal
- Definição de meta de economia para o mês corrente
- Barra de progresso visual com percentual atingido
- Status dinâmico:
  - ✅ "Meta atingida!" — ≥ 100%
  - "Você está quase lá!" — ≥ 70%
  - "Continue economizando" — abaixo de 70%
  - "Saldo negativo no mês" — despesas > receitas

#### Nova Movimentação
- Formulário com tipo (Receita/Despesa), categoria, descrição e valor
- Validação de campos obrigatórios e valor maior que zero

#### Gráfico de Evolução Mensal
- Gráfico de barras interativo (Plotly) com os últimos 12 meses
- Barras verdes para saldo positivo, vermelhas para negativo
- Tooltip personalizado com mês e saldo líquido

#### Histórico Completo
- Listagem de todas as movimentações em cards estilizados
- **Filtros combinados:**
  - Busca por texto na descrição
  - Filtro por mês
  - Filtro por categoria
  - Filtro por tipo (Receita/Despesa)
  - Botão "Limpar filtros"
- **Edição inline** de qualquer movimentação
- **Exclusão** com confirmação obrigatória

#### Categorias disponíveis
`Alimentacao`, `Transporte`, `Moradia`, `Saude`, `Educacao`, `Lazer`, `Salario`, `Investimentos`, `Outros`

### 2.4 PWA (Progressive Web App)

O aplicativo pode ser instalado como PWA nos dispositivos dos usuários:

- Manifest em `pwa/manifest.webmanifest`
- Service Worker em `pwa/service-worker.js`
- Ícones: `icon-192.png` (192×192) e `icon-512.png` (512×512)
- Cor do tema: `#f5b400` (dourado)
- Modo de exibição: `standalone` (sem barra do navegador)

### 2.5 Design e Responsividade

- Tema escuro com fundo em gradiente radial (`#090b11`)
- Layout responsivo com breakpoint em 640px:
  - Desktop: 4 colunas para métricas, filtros em linha
  - Mobile: 2 colunas para métricas, filtros empilhados
- Detecção automática de cliente mobile via `User-Agent` e `Sec-CH-UA-Mobile`

### 2.6 Como Executar

```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## 3. Versão Mobile/Desktop (`main.py`)

### 3.1 Tecnologias

| Dependência | Finalidade |
|-------------|------------|
| `kivy` | Interface mobile-first |
| `sqlite3` | Banco de dados local |
| `csv` | Exportação de dados |

### 3.2 Funcionalidades

#### Splash Screen
- Tela inicial com nome do app e assinatura "by Ramires Apps" por 2 segundos antes do fluxo principal

#### Primeiro Acesso
- Cadastro de nome do usuário (mínimo 2 caracteres)
- PIN opcional de 4 dígitos para proteger o acesso

#### Tela de PIN
- Login por PIN de 4 dígitos quando configurado
- Saudação personalizada com nome do usuário

#### Gerenciamento de Transações
- Registro de receitas e despesas por categoria
- Visualização de saldo e movimentações
- Mesmo conjunto de categorias da versão web

#### Layout
- Design mobile-first com paleta escura
- Tema de cores definido por constante `ESTILO`:
  - Fundo principal: `(0.04, 0.05, 0.08)`
  - Receita (verde): `(0.24, 0.78, 0.56)`
  - Despesa (vermelho): `(0.89, 0.37, 0.41)`
  - Ação (azul): `(0.16, 0.53, 0.89)`
- Layout responsivo com `Window.bind(size=...)` para reajuste automático

---

## 4. Estrutura de Arquivos

```
controle_financeiro_python/
├── app.py                                      # Versão web (Streamlit)
├── main.py                                     # Versão mobile (Kivy)
├── requirements.txt                            # Dependências da versão web
├── controle_financeiro.db                      # Banco de dados SQLite (gerado em runtime)
├── backup_controle_financeiro_20260418_152923.csv  # Backup de dados em CSV
└── pwa/
    ├── manifest.webmanifest                    # Manifest do PWA
    ├── service-worker.js                       # Service Worker
    ├── icon-192.png                            # Ícone 192×192
    └── icon-512.png                            # Ícone 512×512
```

---

## 5. Segurança

| Aspecto | Implementação |
|---------|---------------|
| Hashing de senhas | PBKDF2-SHA256 com 200.000 iterações e salt de 16 bytes aleatórios |
| Comparação de senhas | `hmac.compare_digest` (proteção contra timing attacks) |
| Isolamento de dados | Todas as queries filtram por `usuario_id` |
| Validação de email | Regex `^[^\s@]+@[^\s@]+\.[^\s@]+$` + normalização em lowercase |
| Validação de entrada | Campos obrigatórios e valor > 0 validados antes de persistir |
| Unicidade de email | Constraint `UNIQUE` no banco + tratamento de `IntegrityError` |

---

## 6. Resumo Técnico

| Item | Detalhe |
|------|---------|
| Linguagem | Python 3.10+ |
| Banco de dados | SQLite (arquivo local) |
| Versão web | Streamlit (roda em `localhost:8501` por padrão) |
| Versão mobile | Kivy (compilável para Android via `buildozer`) |
| Suporte a PWA | Sim (manifest + service worker + ícones) |
| Multi-usuário | Sim (versão web); Não (versão Kivy — usuário único) |
| Tema | Dark mode em ambas as versões |
