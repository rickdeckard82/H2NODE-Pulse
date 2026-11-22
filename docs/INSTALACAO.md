# Instalação em produção

Este guia leva o H2NODE Pulse de um servidor vazio até o portal acessível por HTTPS no
domínio da sua empresa. Leva de 30 a 60 minutos.

## Como fica a instalação

```text
Navegador ──HTTPS──► Proxy reverso ──HTTP──► Servidor do Pulse (porta 8086) ──► containers
                     (faz o HTTPS)           só aceita conexões do proxy
```

O Pulse não cuida do certificado HTTPS. Você precisa de um proxy reverso na frente dele, como
Nginx Proxy Manager, Nginx, Traefik ou Caddy. O proxy recebe o acesso pelo domínio público
e repassa para a porta 8086 do servidor do Pulse, que deve ficar em rede privada.

## 1. O que você precisa

- **Servidor Linux** com Docker Engine e Docker Compose 2.24.4 ou mais novo, 2 CPUs, 8 GB de
  RAM (o antivírus usa 4 GB) e 20 GB de disco livres.
- **Python 3** no servidor, só para o script que gera as senhas.
- **Um domínio**, por exemplo `suporte.suaempresa.com.br`, apontando para o proxy reverso.
- **Proxy reverso com HTTPS** alcançando o servidor do Pulse pela rede.
- **Uma conta de e-mail (SMTP)** para enviar confirmações de cadastro e avisos. Ela é
  configurada pela tela do administrador depois de instalar.
- Opcional: **um servidor FTP** para o backup diário e o `make` (`apt install make`).

## 2. Baixar e gerar as senhas

```sh
sudo mkdir -p /app && sudo chown "$USER" /app && cd /app
git clone https://github.com/rickdeckard82/H2NODE-Pulse.git
cd H2NODE-Pulse
python3 infra/bootstrap.py
cp .env.production.example .env
```

O `bootstrap.py` cria a pasta `secrets/` com cinco senhas aleatórias: as do banco, a chave do
Django e a `identity_key`, que cifra os segredos guardados no banco. Ele nunca sobrescreve uma
senha que já existe. A cópia do `.env.production.example` troca o `.env` de desenvolvimento
pelo de produção.

> **Guarde uma cópia da pasta `secrets/` fora do servidor.** Sem a `identity_key`, a
> configuração de e-mail e do Google Chat salva no banco não pode ser lida. O backup
> automático já inclui essa pasta; ainda assim, mantenha uma cópia num cofre de senhas.

## 3. Preencher o `.env`

Abra o `.env` e ajuste estes campos. Os demais podem ficar como estão.

| Campo | O que colocar | Exemplo |
| --- | --- | --- |
| `DJANGO_ALLOWED_HOSTS` | O domínio do portal e, separado por vírgula, `127.0.0.1` (usado pela checagem de saúde interna) | `suporte.suaempresa.com.br,127.0.0.1` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | O endereço do portal com `https://` | `https://suporte.suaempresa.com.br` |
| `APP_BASE_URL` | O mesmo endereço, usado nos links dos e-mails | `https://suporte.suaempresa.com.br` |
| `BIND_IP` | O IP privado **deste servidor**. A porta só é aberta nesse IP | `192.168.10.20` |
| `HTTP_PORT` | A porta que o proxy vai acessar | `8086` |
| `TRUSTED_PROXY_COUNT` | Quantos proxies existem antes da API, contando o gateway interno do Pulse. Com um proxy reverso, use `2` | `2` |
| `BOOTSTRAP_ADMIN_*` | O primeiro administrador; veja o passo 4 | |
| `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` | Opcional: o captcha Cloudflare Turnstile no login e no cadastro. Vazio = desligado | |
| `BACKUP_*` | Opcional: o backup por FTP; veja [BACKUP.md](BACKUP.md) | |

Se o `TRUSTED_PROXY_COUNT` ficar errado, o sistema registra o IP errado nos chamados, e todos
os usuários passam a dividir o mesmo limite de tentativas de login.

## 4. Criar o primeiro administrador

No `.env`:

```dotenv
BOOTSTRAP_ADMIN_ENABLED=true
BOOTSTRAP_ADMIN_EMAIL=ti@suaempresa.com.br
BOOTSTRAP_ADMIN_NAME=Administrador
BOOTSTRAP_ADMIN_PASSWORD=uma-senha-forte
BOOTSTRAP_ADMIN_TRUST_EMAIL=true
```

`TRUST_EMAIL=true` dispensa a confirmação por e-mail **só desta conta**, porque o e-mail ainda
não está configurado. O domínio do e-mail (`suaempresa.com.br`) passa a ser aceito para novos
cadastros. A conta é criada uma única vez. Depois do primeiro acesso, apague a senha do `.env`:
reiniciar o sistema nunca altera a conta.

## 5. Subir o sistema

```sh
make up
```

Esse comando valida a configuração e sobe todos os serviços, inclusive o backup. Ele espera
cada um ficar saudável; a primeira vez leva até 10 minutos, por causa do antivírus.

Sem backup por FTP, ou sem o `make`, use:

```sh
docker compose -f compose.yaml -f compose.production.yaml up -d --build --wait --wait-timeout 600
```

Para conferir: `make ps` (ou `docker compose ps`). Todos devem estar `healthy`, menos `migrate`
e `db-permissions`, que rodam uma vez e terminam com `Exited (0)`.

## 6. Configurar o proxy reverso

Crie no proxy um site com o domínio do portal apontando para `http://BIND_IP:8086`, com:

- certificado HTTPS e redirecionamento de HTTP para HTTPS;
- o cabeçalho `X-Forwarded-For` repassado (padrão na maioria dos proxies);
- limite de upload de pelo menos 6 MB (o Pulse aceita anexos de até 5 MB).

**Nginx Proxy Manager:** em *Proxy Hosts → Add*, informe o domínio, *Scheme* `http`, o IP
privado do servidor e a porta `8086`. Na aba *SSL*, peça o certificado e marque *Force SSL*.

## 7. Fechar a porta para todo o resto

A porta 8086 deve aceitar conexões **apenas do proxy**. Quem acessa direto passa por cima
do HTTPS.

Atenção com o **UFW**: o Docker cria regras próprias e uma porta publicada pelo Docker não é
bloqueada pelas regras comuns do UFW. Use as regras de encaminhamento (`ufw route`, ou a
ferramenta `ufw-docker`) e informe a porta **interna do container, 8080**, não a 8086. Exemplo
com `ufw-docker`, sendo `10.0.0.5` o IP do proxy:

```sh
sudo ufw route allow proto tcp from 10.0.0.5 to any port 8080
```

Teste de outra máquina da rede: `curl http://BIND_IP:8086` deve falhar; pelo domínio deve
funcionar.

## 8. Testar e terminar a configuração

1. Abra `https://suporte.suaempresa.com.br` e entre com o administrador.
2. Ative a verificação em duas etapas em **Perfil**. É opcional, mas recomendado para o
   administrador.
3. Siga o [Guia do administrador](CONFIGURACOES.md): e-mail (SMTP), domínios, empresa, áreas,
   grupos, categorias e equipe.
4. Configure o backup ([BACKUP.md](BACKUP.md)) e faça um teste de restauração antes de
   colocar dados reais.

## Atualizar para uma nova versão

```sh
cd /app/H2NODE-Pulse
make backup        # backup antes de atualizar
git pull
make up
```

As migrações do banco rodam sozinhas ao subir. Para voltar uma versão, restaure o backup: o
banco nem sempre é compatível com o código anterior. Mais detalhes em [OPERACAO.md](OPERACAO.md).
