import { useEffect, type ReactNode } from "react";

const support = ["technician", "manager", "admin"];
const everyone = ["collaborator", ...support];

function Shot({ file, alt }: { file: string; alt: string }) {
  return <img src={`/ajuda/${file}`} alt={alt} loading="lazy" />;
}

const sections: {
  id: string;
  title: string;
  roles: string[];
  body: ReactNode;
}[] = [
  {
    id: "primeiros-passos",
    title: "Primeiros passos",
    roles: everyone,
    body: (
      <>
        <p>
          Entre com seu e-mail corporativo e senha. Para proteger melhor a
          conta, ative a <b>Verificação em duas etapas</b> em <b>Perfil</b>, com
          um aplicativo autenticador, e guarde os códigos de recuperação em
          local seguro. Se perder o acesso ao autenticador, peça a um
          administrador para desativar a verificação.
        </p>
        <p>
          No menu com seu nome, você altera a senha e, em <b>Perfil</b>, a foto
          e o nome.
        </p>
      </>
    ),
  },
  {
    id: "abrir-chamado",
    title: "Abrir e acompanhar um chamado",
    roles: everyone,
    body: (
      <>
        <ol>
          <li>
            Em <b>Chamados</b>, clique em <b>Abrir chamado</b>.
          </li>
          <li>
            Escolha a <b>Categoria</b>. Ela define a equipe que vai atender e
            sugere a prioridade.
          </li>
          <li>
            Preencha <b>Assunto</b> e <b>Descrição</b>. Não envie senhas nem
            dados pessoais desnecessários.
          </li>
          <li>
            Ajuste a <b>Prioridade</b> se o caso exigir e clique em{" "}
            <b>Criar chamado</b>.
          </li>
        </ol>
        <Shot file="novo-chamado.jpg" alt="Formulário de novo chamado" />
        <p>
          Abra o chamado na lista para responder, anexar arquivos e acompanhar o
          andamento. Anexos passam por antivírus antes de serem liberados. Em
          atendimento, você pode encerrar o chamado; depois de resolvido, pode
          confirmar a solução ou reabrir.
        </p>
      </>
    ),
  },
  {
    id: "chat-usuario",
    title: "Receber avisos no Google Chat",
    roles: everyone,
    body: (
      <ol>
        <li>
          No Google Chat, clique em <b>Novo chat</b> e procure o app da empresa.
        </li>
        <li>Abra a conversa com o app. Ele confirma o vínculo.</li>
        <li>
          Se não houver confirmação, mande qualquer mensagem. O e-mail do Chat
          precisa ser o mesmo do sistema.
        </li>
      </ol>
    ),
  },
  {
    id: "wiki",
    title: "Wiki",
    roles: everyone,
    body: (
      <>
        <p>
          Em <b>Wiki</b> ficam os guias e procedimentos da equipe. Use o menu
          lateral para filtrar por tag ou a busca para achar uma página pelo
          título. Todos leem; somente gestores e administradores criam, editam e
          excluem páginas.
        </p>
        <p>
          Gestores e administradores usam <b>Nova página</b>, informam título,
          até 5 tags separadas por vírgula e escrevem o conteúdo com a barra de
          ferramentas: título, negrito, itálico, tachado, citação, código, link,
          imagem, anexo, listas, tabela, alinhamento, tamanho e emoji. A
          pré-visualização ao lado mostra o resultado enquanto você escreve.
          Imagens (PNG, JPG, GIF, WebP) e anexos (PDF, TXT, DOCX, XLSX) têm até
          5 MiB e são verificados contra vírus ao enviar; também funciona colar
          ou arrastar uma imagem para a caixa de texto. Não registre senhas nem
          dados de clientes. Criações, edições, exclusões e envios de arquivos
          ficam no log do sistema.
        </p>
      </>
    ),
  },
  {
    id: "atender",
    title: "Atender chamados",
    roles: support,
    body: (
      <>
        <p>
          Técnicos veem toda a fila, e gestores veem os chamados dos seus
          grupos. Chamados de categorias restritas exigem a permissão{" "}
          <b>Pode ver restritos</b>.
        </p>
        <ol>
          <li>
            Abra um chamado novo e clique em <b>Assumir chamado</b>. Outro
            técnico pode usar <b>Participar do atendimento</b>.
          </li>
          <li>
            Use <b>resposta pública</b> para falar com o solicitante e{" "}
            <b>nota interna</b> para falar com a equipe. O solicitante nunca vê
            notas internas.
          </li>
          <li>
            Peça informações ou teste quando depender do solicitante, e resolva
            informando a solução.
          </li>
          <li>Encerre ou reabra quando necessário.</li>
        </ol>
        <p>
          Reabrir um chamado fechado depende da política de reabertura. Quem
          atende recebe avisos por e-mail e Chat, mesmo fora do grupo.
        </p>
      </>
    ),
  },
  {
    id: "relatorios",
    title: "Relatórios",
    roles: ["manager", "admin"],
    body: (
      <p>
        Em <b>Relatórios</b>, escolha o período para ver indicadores, prazos de
        SLA e chamados abertos, e exporte em CSV. Gestores veem os dados dos
        seus grupos, e administradores veem todos.
      </p>
    ),
  },
  {
    id: "configurar",
    title: "Configurar o sistema, na ordem",
    roles: ["admin"],
    body: (
      <>
        <p>
          Abra o menu com seu nome e clique em <b>Administração</b>. Siga esta
          ordem, porque cada etapa depende da anterior.
        </p>
        <h3>1. Empresa</h3>
        <p>
          Informe nome, CNPJ, responsável, site e logo em PNG. O logo e o nome
          aparecem na barra superior.
        </p>
        <Shot file="empresa.jpg" alt="Tela de cadastro da empresa" />
        <h3>2. Domínios de confiança</h3>
        <p>
          Cadastre o domínio do e-mail corporativo. Só esses domínios podem
          criar conta.
        </p>
        <Shot file="dominios.jpg" alt="Tela de domínios de confiança" />
        <h3>3. SMTP</h3>
        <p>
          Configure o envio de e-mails e teste em <b>Entregas</b>. Sem isso,
          convites e avisos não saem.
        </p>
        <Shot file="smtp.jpg" alt="Tela de configuração do servidor SMTP" />
        <h3>4. Áreas e grupos</h3>
        <p>
          <b>Áreas</b> são os setores da empresa, como Financeiro. <b>Grupos</b>{" "}
          são as equipes que atendem chamados, como Suporte. Pertencer a uma
          área não dá acesso aos chamados dos colegas.
        </p>
        <h3>5. Categorias</h3>
        <p>
          Cada categoria indica o grupo que atende e a prioridade sugerida. Sem
          categoria, ninguém consegue abrir chamado.
        </p>
        <Shot file="categorias.jpg" alt="Tela de categorias" />
        <h3>6. Contas e perfis</h3>
        <p>
          Crie as contas: a pessoa recebe um convite por e-mail e começa como
          Colaborador. Use <b>Editar</b> para definir o papel. A verificação em
          duas etapas de outra pessoa pode ser desativada aqui, conta por conta;
          a sua é desativada em <b>Perfil</b>.
        </p>
        <Shot file="contas.jpg" alt="Tela de contas e perfis" />
        <table>
          <thead>
            <tr>
              <th>Papel</th>
              <th>O que pode fazer</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Colaborador</td>
              <td>Abrir, responder e encerrar os próprios chamados</td>
            </tr>
            <tr>
              <td>Técnico</td>
              <td>Atuar em toda a fila, encerrar e reabrir</td>
            </tr>
            <tr>
              <td>Gestor</td>
              <td>O mesmo nos seus grupos, e relatórios deles</td>
            </tr>
            <tr>
              <td>Administrador</td>
              <td>Acesso total</td>
            </tr>
          </tbody>
        </table>
        <h3>7. Membros dos grupos</h3>
        <p>
          Ligue técnicos e gestores aos grupos que atendem.{" "}
          <b>Sem esse vínculo, ninguém recebe aviso de chamado novo</b> por
          e-mail ou Chat, e o gestor não vê a fila.
        </p>
        <Shot file="membros.jpg" alt="Tela de membros dos grupos" />
        <h3>8. Política de SLA e de reabertura</h3>
        <p>
          Defina expediente, feriados e os prazos de cada prioridade, em minutos
          úteis. Cada campo traz uma sugestão. Sem política de reabertura,
          chamados fechados não podem ser reabertos.
        </p>
        <Shot file="sla.jpg" alt="Tela de política de SLA" />
        <h3>9. Log do sistema</h3>
        <p>
          Consulte quem fez o quê, com filtros por usuário e período. Inclui
          entradas, saídas e logins recusados.
        </p>
        <Shot file="log.jpg" alt="Tela de log do sistema" />
        <h3>10. Retenção de dados</h3>
        <p>
          <b>Atenção:</b> depois do prazo, os dados são apagados
          definitivamente. Revise os prazos com o jurídico antes de ativar. A
          remoção vem desligada, e backups não são alterados.
        </p>
      </>
    ),
  },
  {
    id: "google-chat",
    title: "Configurar a Google Chat API",
    roles: ["admin"],
    body: (
      <>
        <p>
          Permite que cada pessoa receba avisos em uma conversa privada. É
          preciso ter Google Workspace, e o e-mail do Chat deve ser igual ao do
          sistema.
        </p>
        <h3>1. Crie o app no Google Cloud</h3>
        <ol>
          <li>
            Em <b>console.cloud.google.com</b>, entre com a conta do Workspace,
            crie um projeto e ative a <b>Google Chat API</b>.
          </li>
          <li>
            Abra a aba <b>Configuração</b> da API e desmarque{" "}
            <b>Criar este app do Chat como um complemento do Workspace</b>. Essa
            escolha não pode ser desfeita.
          </li>
          <li>
            Preencha nome, avatar (PNG quadrado) e descrição, deixe o status
            como <b>ATIVO</b> e ligue os <b>recursos interativos</b>.
          </li>
        </ol>
        <Shot
          file="cloud-app.png"
          alt="Google Cloud: status, nome, avatar e recursos interativos do app"
        />
        <h3>2. Configure a conexão</h3>
        <ol>
          <li>
            Em <b>URL do endpoint HTTP</b>, informe o endereço mostrado na tela
            Google Chat do sistema, terminado em{" "}
            <code>/api/v1/integrations/google-chat/events/</code>.
          </li>
          <li>
            Em <b>Público-alvo de autenticação</b>, escolha{" "}
            <b>Número do projeto</b>.
          </li>
        </ol>
        <Shot
          file="cloud-conexao.png"
          alt="Google Cloud: URL do endpoint e público-alvo de autenticação"
        />
        <h3>3. Libere os usuários</h3>
        <p>
          Em <b>Visibilidade</b>, informe pessoas ou grupos e clique em{" "}
          <b>Salvar</b>. A liberação pode levar até 24 horas.
        </p>
        <Shot
          file="cloud-visibilidade.png"
          alt="Google Cloud: visibilidade do app"
        />
        <h3>4. Crie a chave</h3>
        <ol>
          <li>
            Em <b>IAM e admin → Contas de serviço</b>, crie uma conta, sem
            papéis.
          </li>
          <li>
            Na aba <b>Chaves</b>, use{" "}
            <b>Adicionar chave → Criar nova chave → JSON</b>. O arquivo baixa
            uma única vez.
          </li>
        </ol>
        <p>
          A chave é uma credencial: não a envie por mensagem nem a guarde em
          pastas compartilhadas. Abra o arquivo no Bloco de Notas para copiar.
        </p>
        <h3>5. Cadastre no sistema</h3>
        <ol>
          <li>
            Em <b>Administração → Google Chat</b>, informe o número do projeto e
            cole o conteúdo do JSON.
          </li>
          <li>
            Preencha a justificativa e salve. Depois apague o arquivo baixado.
          </li>
          <li>
            Espere sair a mensagem de aguardando certificados, mande uma
            mensagem ao app e use <b>Entregas → Testar Chat individual</b>.
          </li>
        </ol>
        <Shot
          file="chat-pulse.jpg"
          alt="Tela do app do Google Chat no sistema"
        />
        <h3>Se não funcionar</h3>
        <ul>
          <li>
            <b>O app diz que não está respondendo:</b> a requisição do Google
            não chegou. Verifique o URL e regras de proxy ou firewall, que devem
            liberar o caminho do endpoint para origens externas.
          </li>
          <li>
            <b>"Não encontrei uma conta":</b> o e-mail do Chat é diferente do
            cadastrado, ou a conta está inativa.
          </li>
          <li>
            <b>Teste com código chat_not_linked:</b> a sua conta ainda não
            mandou mensagem ao app.
          </li>
        </ul>
      </>
    ),
  },
];

export function Help({ role }: { role: string }) {
  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);
  const visible = sections.filter((section) => section.roles.includes(role));
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">AJUDA</p>
          <h1>Como usar o sistema</h1>
          <p>Passo a passo do que você pode fazer com o seu perfil.</p>
        </div>
      </div>
      <nav className="panel help-index" aria-label="Tópicos da ajuda">
        <ul>
          {visible.map((section) => (
            <li key={section.id}>
              <a href={`#${section.id}`}>{section.title}</a>
            </li>
          ))}
        </ul>
      </nav>
      {visible.map((section) => (
        <section
          className="panel help-section"
          id={section.id}
          key={section.id}
        >
          <h2>{section.title}</h2>
          {section.body}
        </section>
      ))}
    </>
  );
}
