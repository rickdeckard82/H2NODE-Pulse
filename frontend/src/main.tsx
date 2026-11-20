import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { AboutDialog, version, type AboutDoc } from "./About";
import { api, type Company, type User } from "./api";
import { Auth } from "./Auth";
import { Help } from "./Help";
import { Portal } from "./Portal";
import { Admin } from "./Admin";
import { Account } from "./Account";
import { PasswordChange } from "./PasswordChange";
import { Reports } from "./Reports";
import { Wiki } from "./Wiki";
import { PulseIntro } from "./PulseIntro";
import { Notifications } from "./Notifications";
import "./style.css";

const roleLabels: Record<string, string> = {
  user: "Usuário",
  collaborator: "Colaborador",
  technician: "Técnico",
  manager: "Gestor",
  admin: "Administrador",
};

function savedTheme() {
  try {
    const saved = localStorage.getItem("pulse-theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // Storage blocked: fall back to the system preference.
  }
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
// Applied before the first render so the page never flashes the wrong theme.
document.documentElement.dataset.theme = savedTheme();

function ThemeToggle() {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme);
  const dark = theme === "dark";
  return (
    <button
      type="button"
      className="theme-toggle"
      aria-label={dark ? "Usar tema claro" : "Usar tema escuro"}
      title={dark ? "Tema claro" : "Tema escuro"}
      onClick={() => {
        const next = dark ? "light" : "dark";
        document.documentElement.dataset.theme = next;
        try {
          localStorage.setItem("pulse-theme", next);
        } catch {
          // Not persisted; the choice still holds for this visit.
        }
        setTheme(next);
      }}
    >
      <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
        {dark ? (
          // Sun: shown in dark mode, switches to light.
          <g
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          >
            <circle cx="12" cy="12" r="4.2" />
            <path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6" />
          </g>
        ) : (
          // Moon: shown in light mode, switches to dark.
          <path
            d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinejoin="round"
          />
        )}
      </svg>
    </button>
  );
}

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

function CompanyBadge({ company }: { company: Company }) {
  const content = (
    <>
      {company.logo && <img src={company.logo} alt="" />}
      <span>{company.name}</span>
    </>
  );
  return company.website ? (
    <a
      className="company-badge"
      href={company.website}
      target="_blank"
      rel="noopener noreferrer"
      title={company.name}
      aria-label={`${company.name} (abre em nova aba)`}
    >
      {content}
    </a>
  ) : (
    <div className="company-badge" title={company.name}>
      {content}
    </div>
  );
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  // Links like /wiki/<id> (shared in ticket replies) open that wiki page.
  const wikiLink = /^\/wiki\/([0-9a-f-]{36})\/?$/.exec(
    window.location.pathname,
  );
  const [requested, setView] = useState(wikiLink ? "wiki" : "portal");
  const [error, setError] = useState("");
  const [authNotice, setAuthNotice] = useState("");
  // The "Usuário" role only has the wiki (plus profile, password and help); the API enforces it.
  const wikiOnly = user?.role === "user";
  const view =
    wikiOnly && !["wiki", "account", "password", "help"].includes(requested)
      ? "wiki"
      : requested;
  const [logoPulseKey, setLogoPulseKey] = useState(0);
  const [about, setAbout] = useState<AboutDoc | null>(null);
  const [company, setCompany] = useState<Company | null>(null);

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
  useEffect(() => {
    if (!user) return;
    const expired = () => {
      setAuthNotice("Sua sessão expirou. Entre novamente.");
      setUser(null);
      setView("portal");
    };
    // Also notice an expired session while the tab sat idle, not only on the next click.
    const check = () => {
      if (document.visibilityState === "visible")
        api<User>("auth/me/").catch(() => undefined);
    };
    const timer = window.setInterval(check, 60_000);
    window.addEventListener("pulse:session-expired", expired);
    document.addEventListener("visibilitychange", check);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("pulse:session-expired", expired);
      document.removeEventListener("visibilitychange", check);
    };
  }, [user]);
  useEffect(() => {
    if (!user) return;
    const refresh = () => {
      api<Company>("settings/company/")
        .then(setCompany)
        .catch(() => setCompany(null));
    };
    refresh();
    window.addEventListener("pulse:company-change", refresh);
    return () => window.removeEventListener("pulse:company-change", refresh);
  }, [user]);
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
          aria-label="H2NODE Pulse"
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
            <span className="brand-pulse">H2NODE</span>
            <span className="brand-services">Pulse</span>
          </span>
        </a>
        {user && (
          <>
            <nav aria-label="Navegação principal">
              {!wikiOnly && (
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
              )}
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
              <button
                className="selected"
                aria-current={view === "wiki" ? "page" : undefined}
                onClick={() => {
                  setView("wiki");
                  setLogoPulseKey((k) => k + 1);
                }}
              >
                Wiki
              </button>
            </nav>
            {company?.name && <CompanyBadge company={company} />}
            <ThemeToggle />
            {!wikiOnly && (
              <Notifications
                ref={bell}
                onOpen={(id) => {
                  setView("portal");
                  setOpened((o) => ({ id, n: o.n + 1 }));
                }}
              />
            )}
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
                <button
                  onClick={() => {
                    setView("help");
                    setLogoPulseKey((k) => k + 1);
                  }}
                >
                  Ajuda
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
        ) : view === "wiki" ? (
          <Wiki
            canEdit={["manager", "admin"].includes(user.role)}
            initialPage={wikiLink?.[1]}
          />
        ) : view === "reports" ? (
          <Reports />
        ) : view === "admin" ? (
          <Admin userId={user.id} />
        ) : view === "account" ? (
          <Account
            user={user}
            onChanged={setUser}
            onPasswordChanged={passwordChanged}
          />
        ) : view === "help" ? (
          <Help role={user.role} />
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
          <span>H2NODE Pulse</span>
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
