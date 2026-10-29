import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

function App() {
  const [status, setStatus] = useState("Verificando conexão…");

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    fetch("/api/v1/health/ready/", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Unavailable");
        const body: { status?: string } = await response.json();
        if (body.status !== "ready") throw new Error("Unexpected response");
        setStatus("Conexão disponível");
      })
      .catch(() => setStatus("Conexão indisponível no momento"))
      .finally(() => window.clearTimeout(timeout));
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, []);

  return (
    <div className="layout">
      <header>
        <a className="brand" href="/" aria-label="Pulse Services, início">
          <span className="mark">P</span> Pulse <span>Services</span>
        </a>
        <span className="environment">Em preparação</span>
      </header>
      <main>
        <p className="eyebrow">ATENDIMENTO INTERNO DE TI</p>
        <h1>
          Seu suporte.
          <br />
          <span>Mais próximo.</span>
        </h1>
        <p className="intro">
          Um lugar para solicitar ajuda, acompanhar seu atendimento e conversar
          com a equipe de TI.
        </p>
        <section className="notice" aria-labelledby="notice-title">
          <div className="icon" aria-hidden="true">
            ↗
          </div>
          <div>
            <h2 id="notice-title">Estamos preparando seu portal</h2>
            <p>
              A abertura de chamados estará disponível após a configuração do
              serviço.
            </p>
            <p className="connection" role="status">
              {status}
            </p>
          </div>
        </section>
        <div className="features">
          <article>
            <span>01</span>
            <h2>Peça ajuda</h2>
            <p>Descreva o que precisa e reúna as informações em um só lugar.</p>
          </article>
          <article>
            <span>02</span>
            <h2>Acompanhe</h2>
            <p>
              Saiba quem está cuidando da sua solicitação e qual é o próximo
              passo.
            </p>
          </article>
          <article>
            <span>03</span>
            <h2>Resolva junto</h2>
            <p>
              Converse com a equipe e confirme quando tudo estiver funcionando.
            </p>
          </article>
        </div>
      </main>
      <footer>
        Pulse Services <span>Portal de atendimento ao colaborador</span>
      </footer>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
