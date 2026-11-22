# Portal e anexos privados

O gateway serve o portal React e encaminha a API na mesma origem. A sessão fica
em cookie HttpOnly e cada mutação solicita CSRF. Nenhuma credencial ou token é
persistido em localStorage. Textos de tickets são renderizados como texto React.
Horários são exibidos em America/Sao_Paulo. O servidor continua responsável por
permissões, transições, concorrência, idempotência e visibilidade.

## Uso

Entre com sua conta corporativa confirmada. Contas de domínios não cadastrados não acessam o
portal. Sem SMTP configurado, ninguém recebe o código de confirmação do cadastro; não existe
senha padrão. O primeiro administrador é criado pelo `BOOTSTRAP_ADMIN_*` (veja
[INSTALACAO.md](INSTALACAO.md)).

No portal, abra um chamado escolhendo a categoria; a prioridade vem sugerida por ela e pode ser trocada. Anexos são
incluídos em uma resposta depois da abertura. O colaborador vê seus chamados;
o técnico vê também os grupos autorizados. Responda ao pedido de informações ou
teste no próprio chamado. Após a resolução, confirme ou informe a falha.

Notas internas têm fundo e rótulo distintos e exigem confirmação de destinatário.
Mensagens de transição/transferência são públicas. Na administração, IDs das
áreas, grupos e usuários são exibidos junto aos registros para configuração de
vínculos; ações não disponíveis ao perfil continuam negadas pela API.

## Contrato de anexos

- `GET /api/v1/tickets/{uuid}/attachments/`: lista paginada no escopo do usuário.
- `POST` na mesma rota: multipart com `expected_version`, `body`, `visibility`,
  `file` e opcional `corrects`. Exige CSRF e `Idempotency-Key` UUID. Cria comentário,
  anexo, evento, auditoria e outbox na mesma transação. Em conflito, recarregue o
  chamado; retry com a mesma chave e payload recupera o recibo original.
- `GET /api/v1/tickets/{uuid}/attachments/{id}/download/`: exige sessão e acesso
  atual ao chamado e à visibilidade do comentário. Somente status `clean` permite
  download. `quarantine` e `blocked` retornam 409; objeto não autorizado, 404.
- `GET /api/v1/tickets/{uuid}/transfer-options/`: opções paginadas para técnico
  autorizado a transferir, limitadas aos grupos e técnicos elegíveis no escopo.

Limite de 5 MiB por arquivo; gateway limita requisição inteira a 6 MiB. Permitidos:
TXT UTF-8 sem marcação HTML/controles binários, PDF, PNG e JPEG. Extensão, MIME
informado e assinatura básica devem concordar; isso não substitui antimalware nem
prova que todo documento é semanticamente válido. ZIP, SVG, HTML e executáveis
não são aceitos. Downloads sempre usam `application/octet-stream`, disposition
`attachment`, `nosniff`, `no-store` e CSP restritiva, sem preview inline.

## Armazenamento e scanner

Volume `attachments`, acessível apenas à API/worker em `/var/lib/pulse/attachments`.
Arquivos têm nome UUID sem extensão e modo 0600, proprietário UID 10001. O nome
exibido é normalizado e nunca usado para resolver caminhos. O gateway e o ClamAV
não montam esse volume. O worker envia bytes pelo protocolo INSTREAM na rede
interna; o serviço não publica porta no host. SHA-256 é verificado antes de scan e
download. Ausência de arquivo ou integridade inválida bloqueia a entrega.

`antimalware` usa imagem oficial ClamAV fixada por digest e volume `clamav_data`
para assinaturas. Rede `scanner_updates` permite baixar atualizações; limitar saída
aos servidores de atualização do ClamAV, se a sua rede permitir. Recomenda-se reservar
4 GiB para o scanner. A API continua funcionando se o scanner ficar indisponível;
anexos permanecem em quarentena. Verifique `docker compose ps antimalware` e os
logs do scanner, sem registrar conteúdo de documentos. O estado `healthy` e a data
das definições devem ser monitorados pela operação; o healthcheck da API não
certifica a atualização das assinaturas.

O worker registra cada tentativa, usa backoff até 1 hora e retenta indefinidamente
sem liberar arquivos não verificados. A transação/lock é liberada quando o processo
morre, permitindo recuperação. Não existe operação pública de liberar manualmente
arquivo. Arquivos bloqueados continuam privados e são apagados pela retenção de dados junto
com o chamado. O backup inclui o banco, o volume de anexos e a chave de identidade.

Referências técnicas: [ClamAV Docker](https://docs.clamav.net/manual/Installing/Docker.html),
[protocolo INSTREAM](https://docs.clamav.net/manual/Usage/ClamdProtocol.html),
[Playwright](https://playwright.dev/docs/intro).
