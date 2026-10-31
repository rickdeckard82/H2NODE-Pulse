import { StrictMode, useEffect, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { api, type User } from "./api";
import { Auth } from "./Auth";
import { Portal } from "./Portal";
import { Admin } from "./Admin";
import { Account } from "./Account";
import { PasswordChange } from "./PasswordChange";
import "./style.css";

const roleLabels: Record<string, string> = {
  collaborator: "Colaborador",
  technician: "Técnico",
  manager: "Gestor de TI",
  admin: "Administrador",
  privacy: "Responsável por privacidade",
};

type IconName = "ticket" | "admin" | "profile" | "password";

function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    ticket: (
      <>
        <path d="M4 5h16v14H4z" />
        <path d="M8 9h8M8 13h5" />
      </>
    ),
    admin: (
      <>
        <circle cx="12" cy="8" r="3" />
        <path d="M6 20v-2a6 6 0 0 1 12 0v2M19 5v6M16 8h6" />
      </>
    ),
    profile: (
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21a8 8 0 0 1 16 0" />
      </>
    ),
    password: (
      <>
        <rect x="4" y="10" width="16" height="11" rx="2" />
        <path d="M8 10V7a4 4 0 0 1 8 0v3M12 15v2" />
      </>
    ),
  };
  return (
    <svg
      className="nav-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}

function Waves() {
  return (
    <div className="waves" aria-hidden="true">
      <span />
      <span />
      <span />
    </div>
  );
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState("portal");
  const [error, setError] = useState("");
  const [authNotice, setAuthNotice] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem("pulse_services_sidebar_collapsed") === "1";
    } catch {
      return false;
    }
  });

  const load = () => {
    setLoading(true);
    api<User>("auth/me/")
      .then((value) => {
        setUser(value);
        setAuthNotice("");
      })
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);
  useEffect(() => {
    try {
      localStorage.setItem(
        "pulse_services_sidebar_collapsed",
        sidebarCollapsed ? "1" : "0",
      );
    } catch {
      // Preferência visual opcional; modo privado pode impedir persistência.
    }
  }, [sidebarCollapsed]);
  useEffect(() => {
    if (!sidebarOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [sidebarOpen]);

  const navigate = (next: string) => {
    setView(next);
    setSidebarOpen(false);
  };

  if (loading)
    return (
      <div className="auth-screen">
        <Waves />
        <p className="loading-card" role="status">
          Carregando seu portal…
        </p>
      </div>
    );

  if (!user)
    return (
      <div className="auth-screen">
        <Waves />
        <a className="skip" href="#main">
          Ir para o conteúdo
        </a>
        <main id="main" className="auth-main">
          <Auth onLogin={load} initialNotice={authNotice} />
        </main>
        <footer>
          Pulse Services · Horários de Brasília (America/Sao_Paulo)
        </footer>
      </div>
    );

  return (
    <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <a className="skip" href="#main">
        Ir para o conteúdo
      </a>
      {sidebarOpen && (
        <button
          className="sidebar-backdrop"
          aria-label="Fechar menu"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="sidebar-brand">
          <span className="logo-mark" aria-hidden="true">
            P
          </span>
          <span className="logo-name">
            Pulse <small>Services</small>
          </span>
          <button
            className="sidebar-close"
            aria-label="Fechar menu"
            onClick={() => setSidebarOpen(false)}
          >
            ×
          </button>
          <button
            className="sidebar-collapse"
            aria-label={sidebarCollapsed ? "Expandir menu" : "Recolher menu"}
            title={sidebarCollapsed ? "Expandir menu" : "Recolher menu"}
            onClick={() => setSidebarCollapsed((value) => !value)}
          >
            ‹‹
          </button>
        </div>
        <nav className="sidebar-nav" aria-label="Navegação principal">
          <button
            className={view === "portal" ? "active" : ""}
            onClick={() => navigate("portal")}
            title="Chamados"
          >
            <Icon name="ticket" />
            <span>Chamados</span>
          </button>
          {user.role === "admin" && (
            <button
              className={view === "admin" ? "active" : ""}
              onClick={() => navigate("admin")}
              title="Administração"
            >
              <Icon name="admin" />
              <span>Administração</span>
            </button>
          )}
          <p className="sidebar-section">
            <span>Conta</span>
          </p>
          <button
            className={view === "account" ? "active" : ""}
            onClick={() => navigate("account")}
            title="Perfil"
          >
            <Icon name="profile" />
            <span>Perfil</span>
          </button>
          <button
            className={view === "password" ? "active" : ""}
            onClick={() => navigate("password")}
            title="Alterar senha"
          >
            <Icon name="password" />
            <span>Alterar senha</span>
          </button>
        </nav>
        <div className="sidebar-footer">
          <span>Pulse Services</span>
          <small>Portal de atendimento</small>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <Waves />
          <button
            className="menu-toggle"
            aria-label="Abrir menu"
            onClick={() => setSidebarOpen(true)}
          >
            <span />
            <span />
            <span />
          </button>
          <details className="user-menu">
            <summary aria-label={`Abrir menu de ${user.first_name}`}>
              <span className="avatar" aria-hidden="true">
                {user.first_name.trim().charAt(0).toUpperCase() || "U"}
              </span>
              <span className="user-identity">
                <strong>{user.first_name}</strong>
                <small>{roleLabels[user.role] || user.role}</small>
              </span>
              <span className="menu-chevron" aria-hidden="true">
                ⌄
              </span>
            </summary>
            <div
              className="user-menu-popover"
              onClick={(event) => {
                if ((event.target as HTMLElement).closest("button"))
                  event.currentTarget.parentElement?.removeAttribute("open");
              }}
            >
              <p>
                <small>CONTA</small>
                <strong>{user.first_name}</strong>
              </p>
              <button onClick={() => navigate("password")}>
                Alterar senha
              </button>
              <button onClick={() => navigate("account")}>Perfil</button>
              {user.role === "admin" && (
                <button onClick={() => navigate("admin")}>Administração</button>
              )}
              <button
                onClick={async () => {
                  try {
                    await api("auth/logout/", {});
                    setUser(null);
                    setView("portal");
                  } catch (err) {
                    setError((err as Error).message);
                  }
                }}
              >
                Sair
              </button>
            </div>
          </details>
        </header>
        <main id="main" className="content">
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {view === "admin" ? (
            <Admin />
          ) : view === "account" ? (
            <Account user={user} onChanged={load} />
          ) : view === "password" ? (
            <PasswordChange
              onCompleted={() => {
                setAuthNotice(
                  "Senha alterada. Entre novamente com a nova senha.",
                );
                setUser(null);
                setView("portal");
              }}
            />
          ) : (
            <Portal user={user} onExpired={load} />
          )}
        </main>
        <footer className="app-footer">
          <Waves />
          <span>Pulse Services · Horários de Brasília (America/Sao_Paulo)</span>
        </footer>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
