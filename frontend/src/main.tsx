import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { AboutDialog, version, type AboutDoc } from "./About";
import { api, type User } from "./api";
import { Auth } from "./Auth";
import { Portal } from "./Portal";
import { Admin } from "./Admin";
import { Account } from "./Account";
import { PasswordChange } from "./PasswordChange";
import { Reports } from "./Reports";
import { PulseIntro } from "./PulseIntro";
import { Notifications } from "./Notifications";
import "./style.css";

const roleLabels: Record<string, string> = {
  collaborator: "Colaborador",
  technician: "Técnico",
  manager: "Gestor",
  admin: "Administrador",
};

function Waves() {
  return (
    <div className="waves" aria-hidden="true">
      <svg viewBox="0 0 2880 320" preserveAspectRatio="none">
        <path d="M0,160 C240,220 480,100 720,160 C960,220 1200,100 1440,160 C1680,220 1920,100 2160,160 C2400,220 2640,100 2880,160 L2880,320 L0,320 Z" />
      </svg>
      <svg viewBox="0 0 2880 320" preserveAspectRatio="none">
        <path d="M0,180 C240,120 480,240 720,180 C960,120 1200,240 1440,180 C1680,120 1920,240 2160,180 C2400,120 2640,240 2880,180 L2880,320 L0,320 Z" />
      </svg>
      <svg viewBox="0 0 2880 320" preserveAspectRatio="none">
        <path d="M0,140 C240,200 480,80 720,140 C960,200 1200,80 1440,140 C1680,200 1920,80 2160,140 C2400,200 2640,80 2880,140 L2880,320 L0,320 Z" />
      </svg>
    </div>
  );
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState("portal");
  const [error, setError] = useState("");
  const [authNotice, setAuthNotice] = useState("");
  const [logoPulseKey, setLogoPulseKey] = useState(0);
  const [about, setAbout] = useState<AboutDoc | null>(null);

  useEffect(() => {
    setLogoPulseKey((k) => k + 1);
  }, [view, user]);

  useEffect(() => {
    const onPageChange = () => setLogoPulseKey((k) => k + 1);
    window.addEventListener("pulse:page-change", onPageChange);
    return () => window.removeEventListener("pulse:page-change", onPageChange);
  }, []);

  const load = () => {
    setLoading(true);
    api<User>("auth/me/")
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);
  const menu = useRef<HTMLDetailsElement>(null);
  const bell = useRef<HTMLDetailsElement>(null);
  const [opened, setOpened] = useState({ id: "", n: 0 });
  useEffect(() => {
    const close = (event: Event) => {
      for (const ref of [menu, bell])
        if (
          (event instanceof KeyboardEvent
            ? event.key === "Escape"
            : !ref.current?.contains(event.target as Node)) &&
          ref.current?.open
        )
          ref.current.open = false;
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", close);
    };
  }, []);
  const passwordChanged = () => {
    setAuthNotice("Senha alterada. Entre novamente com a nova senha.");
    setUser(null);
    setView("portal");
  };
  return (
    <>
      <PulseIntro />
      <a className="skip" href="#main">
        Ir para o conteúdo
      </a>
      <header className="topbar">
        <a
          key={logoPulseKey}
          className="brand brand-animated"
          href="/"
          aria-label="Pulse Services"
          onClick={(e) => {
            e.preventDefault();
            if (view !== "portal") setView("portal");
            setLogoPulseKey((k) => k + 1);
          }}
        >
          <span className="brand-icon-wrap" aria-hidden="true">
            <span className="brand-icon-ripple" />
            <span className="brand-icon">
              <svg viewBox="0 0 32 32" width="32" height="32">
                <rect width="32" height="32" rx="9" fill="#174dcc" />
                <path
                  className="brand-icon-ecg"
                  d="M5 17 h6 l2 4.5 l3.5 -11.5 l3 9 l2 -3.5 h5.5"
                  fill="none"
                  stroke="#ffffff"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
          </span>
          <span className="brand-text">
            <span className="brand-pulse">pulse</span>
            <span className="brand-services">services</span>
          </span>
        </a>
        {user && (
          <>
            <nav aria-label="Navegação principal">
              <button
                className="selected"
                aria-current={view === "portal" ? "page" : undefined}
                onClick={() => {
                  setView("portal");
                  setLogoPulseKey((k) => k + 1);
                }}
              >
                Chamados
              </button>
              {["manager", "admin"].includes(user.role) && (
                <button
                  className="selected"
                  aria-current={view === "reports" ? "page" : undefined}
                  onClick={() => {
                    setView("reports");
                    setLogoPulseKey((k) => k + 1);
                  }}
                >
                  Relatórios
                </button>
              )}
            </nav>
            <Notifications
              ref={bell}
              onOpen={(id) => {
                setView("portal");
                setOpened((o) => ({ id, n: o.n + 1 }));
              }}
            />
            <details className="user-menu" ref={menu}>
              <summary aria-label={`Abrir menu de ${user.first_name}`}>
                {user.avatar ? (
                  <img className="avatar" src={user.avatar} alt="" />
                ) : (
                  <span className="avatar" aria-hidden="true">
                    {user.first_name.trim().charAt(0).toUpperCase() || "U"}
                  </span>
                )}
                <span className="user-identity">
                  <strong>{user.first_name}</strong>
                  <small>{roleLabels[user.role] || user.role}</small>
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
                <button
                  onClick={() => {
                    setView("password");
                    setLogoPulseKey((k) => k + 1);
                  }}
                >
                  Alterar senha
                </button>
                <button
                  onClick={() => {
                    setView("account");
                    setLogoPulseKey((k) => k + 1);
                  }}
                >
                  Perfil
                </button>
                {user.role === "admin" && (
                  <button
                    onClick={() => {
                      setView("admin");
                      setLogoPulseKey((k) => k + 1);
                    }}
                  >
                    Administração
                  </button>
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
          </>
        )}
      </header>
      <main id="main">
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {loading ? (
          <p role="status">Carregando seu portal…</p>
        ) : !user ? (
          <Auth onLogin={load} initialNotice={authNotice} />
        ) : view === "reports" ? (
          <Reports />
        ) : view === "admin" ? (
          <Admin />
        ) : view === "account" ? (
          <Account
            user={user}
            onChanged={setUser}
            onPasswordChanged={passwordChanged}
          />
        ) : view === "password" ? (
          <PasswordChange onCompleted={passwordChanged} />
        ) : (
          <Portal
            key={opened.n}
            open={opened.id || undefined}
            user={user}
            onExpired={load}
          />
        )}
      </main>
      <footer>
        <Waves />
        <nav className="footer-links" aria-label="Informações do sistema">
          <span>Pulse Services</span>
          <button className="link" onClick={() => setAbout("terms")}>
            Termos de uso
          </button>
          <button className="link" onClick={() => setAbout("privacy")}>
            Aviso de privacidade
          </button>
          {user && (
            <button className="link" onClick={() => setAbout("changelog")}>
              Versão {version}
            </button>
          )}
        </nav>
      </footer>
      {about && (about !== "changelog" || user) && (
        <AboutDialog doc={about} onClose={() => setAbout(null)} />
      )}
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
