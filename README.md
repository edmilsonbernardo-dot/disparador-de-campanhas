# Disparador de Campanhas de E-mail

Aplicação web (Flask) para disparar e-mails em lote a partir de um CSV, agendar a
data/hora do disparo, acompanhar quem abriu cada e-mail em um dashboard e enviar
automaticamente um e-mail de seguimento para quem abrir o e-mail original.

## O que o sistema faz

- **Upload de CSV** com colunas de nome e e-mail (aceita cabeçalhos como
  `nome`/`name` e `email`/`e-mail`, em qualquer ordem; vírgula ou ponto-e-vírgula
  como separador). Linhas com e-mail inválido ou duplicado são ignoradas
  automaticamente e reportadas na tela.
- **Agendamento de disparo**: você define data e hora, e o sistema dispara
  sozinho quando chegar a hora (checagem a cada 30 segundos).
- **Caixa de envio configurável**: tela de Configurações para informar o
  e-mail e a senha de app do Gmail (ou qualquer outro SMTP) que vai disparar
  as campanhas. A senha fica criptografada no banco.
- **Dashboard de aberturas**: cada e-mail enviado carrega um pixel de
  rastreamento único por contato. Quando o destinatário abre o e-mail (e o
  cliente de e-mail carrega imagens), o sistema registra a abertura. O
  dashboard mostra total enviado, total aberto, taxa de abertura por
  campanha, e uma tabela por contato.
- **Disparo automático por abertura**: ao criar a campanha, você pode
  habilitar um e-mail de seguimento que é enviado automaticamente, uma única
  vez, para cada contato assim que ele abrir o e-mail original (com um atraso
  configurável em minutos).

## Limitações importantes (leia antes de usar em produção)

1. **Rastreamento de abertura tem limite técnico conhecido no mercado.** Ele
   depende do cliente de e-mail carregar a imagem do pixel. Gmail, por
   exemplo, costuma carregar imagens automaticamente (o que ajuda a captar
   aberturas), mas Outlook e alguns apps corporativos podem bloquear imagens
   por padrão — nesses casos a abertura não é registrada mesmo que a pessoa
   tenha lido o e-mail. Trate a taxa de abertura como uma estimativa, não
   como número exato.
2. **"Abertura" pode ser falso positivo.** Alguns provedores pré-carregam
   imagens automaticamente por segurança (proxy de imagens), o que pode
   registrar uma abertura sem que a pessoa tenha realmente visto o e-mail.
   Por isso o e-mail de seguimento tem um atraso configurável (padrão: 10
   minutos) antes de disparar.
3. **Limite de envio do Gmail.** Uma conta Gmail comum tem limite de
   aproximadamente 500 e-mails por dia (Google Workspace tem limites
   maiores). O sistema já envia com um intervalo entre e-mails (2 segundos,
   ajustável) para reduzir o risco de bloqueio, mas para volumes grandes
   considere um provedor transacional (SendGrid, Amazon SES, Mailgun) — o
   sistema aceita qualquer SMTP.
4. **Evite ser marcado como spam.** Só envie para contatos que deram
   permissão de contato, inclua identificação clara do remetente, e evite
   linguagem tipicamente associada a spam. Isso está fora do controle do
   sistema, mas afeta diretamente a entregabilidade.
5. **Horário do agendamento é em UTC.** O campo de data/hora do disparo é
   interpretado no fuso do servidor (UTC). São Paulo está em UTC-3 (sem
   horário de verão atualmente), então para disparar às 9h de São Paulo,
   agende para 12h no formulário.
6. **Rode com apenas 1 worker/processo web.** O agendador (que dispara
   campanhas e follow-ups) roda dentro do mesmo processo da aplicação. Se
   você rodar múltiplos processos (`gunicorn -w 2` ou mais), cada um vai ter
   seu próprio agendador e os e-mails podem ser **enviados em duplicidade**.
   O `Procfile` já está configurado com `-w 1 --threads 4`, o que é
   suficiente para o uso normal do painel. Não altere para mais de 1 worker
   sem mover o agendador para um processo separado.
7. **Banco de dados SQLite em arquivo.** Simples e suficiente para uso de um
   usuário/uma equipe pequena. Em serviços de nuvem "sem servidor" ou com
   disco efêmero, os dados podem ser perdidos a cada novo deploy — por isso
   as instruções abaixo pedem um disco persistente.

## Como funciona o pixel de rastreamento

Cada contato recebe um link único (`/track/<token>.gif`) embutido como uma
imagem invisível de 1x1 pixel no final do e-mail. Quando essa imagem é
carregada, o sistema sabe que aquele contato específico abriu aquele e-mail
específico. Por isso a aplicação **precisa estar publicamente acessível pela
internet** (não funciona rodando só na sua máquina sem expor a porta) — é
para isso que existe a etapa de deploy abaixo.

---

## Rodando localmente (para testar antes do deploy)

Pré-requisitos: Python 3.10+.

```bash
cd email_campaign_app
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edite o .env e preencha ADMIN_PASSWORD e SECRET_KEY

python app.py
```

Acesse `http://localhost:5000`, entre com a senha definida em
`ADMIN_PASSWORD`, e configure a caixa de envio em "Configurações". Localmente
o rastreamento de abertura só vai funcionar se você mesmo abrir o e-mail em um
lugar que consiga acessar `http://localhost:5000` (ou seja, na prática, só
serve para testar o fluxo — para rastreamento real, faça o deploy).

Um CSV de exemplo está incluído: `exemplo_contatos.csv`.

Um script de teste automatizado (`test_flow.py`) simula todo o fluxo — login,
configuração, upload de CSV, disparo, abertura via pixel e follow-up
automático — sem enviar e-mails reais. Rode com `python test_flow.py`.

### Como gerar a senha de app do Gmail

1. Ative a verificação em duas etapas na sua Conta Google, se ainda não
   tiver: https://myaccount.google.com/security
2. Acesse https://myaccount.google.com/apppasswords
3. Crie uma senha de app (nome sugerido: "Disparador de Campanhas") e copie a
   senha gerada (16 caracteres).
4. Use essa senha no campo "Senha de app" da tela de Configurações — **não**
   é a senha normal da sua conta Google.

---

## Deploy (para rastreamento de abertura funcionar de verdade)

### Opção A: Render.com (recomendado, tem plano gratuito)

1. Crie um repositório no GitHub com este projeto (ou peça para eu te ajudar
   a subir o código lá).
2. Em https://render.com, clique em **New +** → **Blueprint**, conecte o
   repositório. O arquivo `render.yaml` já está configurado com:
   - um serviço web Python rodando `gunicorn -w 1`
   - um disco persistente de 1 GB montado em `instance/` (onde fica o banco
     SQLite), para os dados não se perderem a cada deploy
3. Preencha as variáveis de ambiente pedidas: `ADMIN_PASSWORD`,
   `ENCRYPTION_KEY` (gere uma com o comando abaixo) e `BASE_URL` (a URL que o
   Render vai atribuir ao serviço, ex: `https://disparador-de-campanhas.onrender.com`
   — você pode preencher isso depois do primeiro deploy e fazer um redeploy).

   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

4. Depois do deploy, acesse a URL gerada, entre com `ADMIN_PASSWORD` e
   configure a caixa de envio em "Configurações".

Observação sobre o plano gratuito do Render: o serviço "dorme" após um
período sem acesso e demora alguns segundos para acordar na próxima
requisição — isso pode atrasar o disparo de uma campanha agendada se ninguém
acessar o painel perto do horário. Para uso mais sério, o plano pago (a
partir de poucos dólares/mês) mantém o serviço sempre ativo.

### Opção B: Railway.app

1. Crie um novo projeto a partir do repositório GitHub.
2. Adicione um **Volume** persistente montado em `/app/instance`.
3. Configure as variáveis de ambiente (mesmas da Opção A).
4. O Railway detecta o `Procfile` automaticamente.

### Opção C: Seu próprio servidor/VPS

```bash
git clone <seu-repositorio>
cd email_campaign_app
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # preencha as variáveis
gunicorn -w 1 --threads 4 -b 0.0.0.0:8000 app:app
```

Configure um proxy reverso (Nginx/Caddy) com HTTPS na frente, e defina
`BASE_URL` no `.env` como a URL pública com HTTPS (o pixel de rastreamento
precisa de uma URL acessível pela internet).

---

## Estrutura do projeto

```
app.py            → rotas da aplicação (login, dashboard, campanhas, pixel)
models.py         → modelos do banco (Settings, Campaign, Contact)
mailer.py         → envio de e-mail via SMTP + montagem do pixel de rastreamento
scheduler.py      → agendador em segundo plano (disparo agendado + follow-up)
utils.py          → leitura tolerante do CSV de contatos
crypto_utils.py   → criptografia da senha de app salva no banco
config.py         → configuração via variáveis de ambiente
templates/        → páginas HTML (Bootstrap)
test_flow.py       → teste automatizado de ponta a ponta (não envia e-mail real)
exemplo_contatos.csv → CSV de exemplo para testar o upload
```

## Próximos passos sugeridos (não incluídos nesta primeira versão)

- Editor de e-mail em texto rico (hoje o corpo é HTML "cru" — funciona bem,
  mas exige digitar tags HTML simples como `<p>`, `<b>`, etc.)
- Suporte a múltiplos usuários/times com login individual
- Reenvio automático para quem **não** abriu após X dias (a automação atual
  cobre apenas "enviar seguimento para quem abriu", conforme solicitado)
- Métricas adicionais (cliques em links, taxa de rejeição/bounce)
