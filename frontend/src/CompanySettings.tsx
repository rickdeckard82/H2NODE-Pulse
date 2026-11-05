import { useEffect, useState } from "react";
import { api, type Company } from "./api";

const LOGO_MAX_BYTES = 256 * 1024;

const formatCnpj = (cnpj: string) =>
  cnpj.replace(/^(.{2})(.{3})(.{3})(.{4})(.{2})$/, "$1.$2.$3/$4-$5");

export function CompanySettings() {
  const [company, setCompany] = useState<Company | null>(null);
  const [logo, setLogo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    api<Company>("settings/company/")
      .then((data) => {
        setCompany(data);
        setLogo(data.logo);
      })
      .catch((err) => setError(err.message));
  }, []);

  return (
    <section className="panel narrow">
      <h2>Empresa</h2>
      <p>
        Identifica a empresa que usa o sistema. O logo e o nome aparecem na
        barra superior para todos os usuários.
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="notice">
          {notice}
        </p>
      )}
      {!company ? (
        <p>Carregando configuração…</p>
      ) : (
        <form
          key={revision}
          onSubmit={async (event) => {
            event.preventDefault();
            if (busy) return;
            setBusy(true);
            setError("");
            setNotice("");
            const data = new FormData(event.currentTarget);
            try {
              const result = await api<Company>(
                "settings/company/",
                {
                  name: data.get("name"),
                  cnpj: data.get("cnpj"),
                  responsible: data.get("responsible"),
                  responsible_email: data.get("responsible_email"),
                  website: data.get("website"),
                  logo,
                  reason: data.get("reason"),
                },
                "PATCH",
              );
              setCompany(result);
              setRevision((value) => value + 1);
              setNotice("Dados da empresa salvos.");
              window.dispatchEvent(new CustomEvent("pulse:company-change"));
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Nome da empresa
            <input
              name="name"
              required
              maxLength={120}
              defaultValue={company.name}
            />
          </label>
          <label>
            CNPJ
            <input
              name="cnpj"
              required
              maxLength={18}
              autoComplete="off"
              defaultValue={formatCnpj(company.cnpj)}
            />
          </label>
          <label>
            Responsável pelas informações
            <input
              name="responsible"
              required
              maxLength={120}
              defaultValue={company.responsible}
            />
          </label>
          <label>
            E-mail do responsável
            <input
              name="responsible_email"
              type="email"
              maxLength={254}
              defaultValue={company.responsible_email}
            />
          </label>
          <label>
            Site da empresa
            <input
              name="website"
              type="url"
              placeholder="https://www.empresa.com.br"
              maxLength={200}
              defaultValue={company.website}
            />
          </label>
          <label>
            Logo (PNG de até 256 KB)
            <input
              type="file"
              accept="image/png"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                setError("");
                if (file.type !== "image/png" || file.size > LOGO_MAX_BYTES) {
                  setError("Envie uma imagem PNG de até 256 KB.");
                  event.target.value = "";
                  return;
                }
                const reader = new FileReader();
                reader.onload = () => setLogo(String(reader.result));
                reader.readAsDataURL(file);
              }}
            />
          </label>
          {logo && (
            <div className="company-logo-preview">
              <img src={logo} alt="Prévia do logo" />
              <button
                type="button"
                className="secondary"
                onClick={() => setLogo("")}
              >
                Remover logo
              </button>
            </div>
          )}
          <label>
            Justificativa da alteração
            <input name="reason" required maxLength={300} />
          </label>
          <button disabled={busy}>
            {busy ? "Salvando…" : "Salvar empresa"}
          </button>
        </form>
      )}
    </section>
  );
}
