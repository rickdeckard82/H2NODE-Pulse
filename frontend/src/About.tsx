import { useEffect, useRef } from "react";
import { version } from "../package.json";

export { version };
export type AboutDoc = "terms" | "privacy" | "changelog";

const draft = (
  <p className="notice">
    Minuta pendente de revisão jurídica. A empresa responsável por esta
    instalação deve completar sua identificação, o canal de privacidade, as
    bases legais e os prazos de retenção.
  </p>
);

const documents: Record<AboutDoc, { title: string; body: React.ReactNode }> = {
  terms: {
    title: "Termos de uso",
    body: (
      <>
        {draft}
        <p>
          <small>Versão 1 · 04/11/2026</small>
        </p>
        <h3>Finalidade</h3>
        <p>
          O Pulse Services é o sistema interno de chamados da empresa. Use-o
          somente para pedir e prestar suporte relacionado ao trabalho.
        </p>
        <h3>Conta e acesso</h3>
        <p>
          O cadastro exige e-mail corporativo de domínio autorizado. A conta é
          pessoal: não compartilhe senha nem códigos de verificação, e avise a
          TI se suspeitar de acesso indevido.
        </p>
        <h3>Conteúdo dos chamados</h3>
        <p>
          Você responde pelo que escreve e anexa. Inclua apenas o necessário
          para o atendimento e evite senhas e dados pessoais de terceiros sem
          necessidade. Anexos passam por verificação antivírus.
        </p>
        <h3>Prioridade e prazos</h3>
        <p>
          Escolha a prioridade de boa-fé. Os prazos de atendimento seguem a
          política de SLA configurada pela empresa.
        </p>
        <h3>Registro de atividades</h3>
        <p>
          Ações no sistema ficam registradas com autor, data e hora, para
          segurança e auditoria.
        </p>
        <h3>Alterações</h3>
        <p>
          Estes termos podem mudar. A versão vigente fica sempre disponível
          neste rodapé.
        </p>
      </>
    ),
  },
  privacy: {
    title: "Aviso de privacidade",
    body: (
      <>
        {draft}
        <p>
          <small>Versão 1 · 04/11/2026</small>
        </p>
        <h3>Dados tratados</h3>
        <ul>
          <li>
            Cadastro: nome, e-mail corporativo, foto opcional, área e perfil.
          </li>
          <li>
            Chamados: assunto, descrição, comentários, anexos, categoria,
            prioridade e histórico de atendimento.
          </li>
          <li>
            Segurança: registros de ações, dados de verificação em duas etapas,
            dispositivos confiáveis e endereço IP usado para limitar tentativas
            de acesso.
          </li>
        </ul>
        <h3>Finalidades</h3>
        <p>
          Autenticar usuários, atender chamados, notificar envolvidos, medir
          prazos, gerar relatórios internos e manter a segurança e a auditoria.
          As bases legais são definidas pela empresa.
        </p>
        <h3>Quem acessa</h3>
        <p>
          Você vê seus próprios chamados. Técnicos veem a fila de atendimento,
          gestores veem os chamados dos seus grupos e administradores têm acesso
          total, incluindo notas internas. Pertencer à mesma área não dá acesso
          aos chamados de colegas.
        </p>
        <h3>Compartilhamento</h3>
        <p>
          Notificações podem passar pelos serviços de e-mail e Google Chat
          configurados pela empresa.
        </p>
        <h3>Cookies</h3>
        <p>
          Usamos apenas cookies necessários: sessão, proteção contra requisições
          forjadas e, se você escolher, dispositivo confiável.
        </p>
        <h3>Retenção</h3>
        <p>Os prazos de guarda são definidos pela empresa.</p>
        <h3>Seus direitos</h3>
        <p>
          A Lei Geral de Proteção de Dados garante direitos como confirmação,
          acesso e correção. Para exercê-los, procure o canal de privacidade da
          empresa.
        </p>
      </>
    ),
  },
  changelog: {
    title: `Versão ${version}`,
    body: (
      <>
        <h3>Novidades</h3>
        <ul>
          <li>
            Prioridade definida por categoria, com troca na abertura do chamado.
          </li>
          <li>Prioridades com nome e sugestões de prazo na política de SLA.</li>
          <li>Avisos individuais no Google Chat, com instalação do app.</li>
          <li>Cadastro da empresa, com logo e nome na barra superior.</li>
          <li>Log do sistema com filtros por usuário e data.</li>
          <li>Política de retenção com remoção definitiva de dados.</li>
          <li>Página de ajuda com o passo a passo do sistema.</li>
          <li>Termos de uso e aviso de privacidade no rodapé.</li>
          <li>
            Papéis simplificados: colaborador, técnico, gestor e administrador.
          </li>
          <li>Notificações por e-mail e Google Chat.</li>
          <li>
            SLA com expediente e feriados, e relatórios com exportação CSV.
          </li>
          <li>Papéis de atendimento e numeração sequencial de chamados.</li>
          <li>Portal de chamados com anexos verificados por antivírus.</li>
          <li>
            Cadastro corporativo, verificação em duas etapas e dispositivos
            confiáveis.
          </li>
        </ul>
      </>
    ),
  },
};

export function AboutDialog({
  doc,
  onClose,
}: {
  doc: AboutDoc;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="about-dialog"
      aria-labelledby="about-title"
      onClose={onClose}
    >
      <h2 id="about-title">{documents[doc].title}</h2>
      {documents[doc].body}
      <form method="dialog">
        <button autoFocus>Fechar</button>
      </form>
    </dialog>
  );
}
