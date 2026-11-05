import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import jsQR from "jsqr";
import { readFileSync } from "node:fs";
import { createHmac } from "node:crypto";
const fixture = JSON.parse(readFileSync("../work/e2e-fixture.json", "utf8"));
function totp(secret: string) {
  let bits = "";
  for (const c of secret)
    bits += "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
      .indexOf(c)
      .toString(2)
      .padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const hmac = createHmac("sha1", key).update(counter).digest();
  const offset = hmac[19] & 15;
  return String((hmac.readUInt32BE(offset) & 0x7fffffff) % 1000000).padStart(
    6,
    "0",
  );
}
async function login(page: Page, name: string) {
  await page.goto("/");
  await page.getByLabel("E-mail corporativo").fill(`${name}@company.test`);
  await page.getByLabel("Senha", { exact: true }).fill(fixture.password);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  if (fixture.mfa[name]) {
    await page
      .getByLabel("Código do autenticador ou de recuperação")
      .fill(totp(fixture.mfa[name]));
    await page.getByRole("button", { name: "Verificar código" }).click();
  }
  await expect(
    page.getByRole("heading", {
      name:
        name === "owner" || name === "peer"
          ? "Meus chamados"
          : "Fila de chamados",
    }),
  ).toBeVisible();
}
async function audit(page: Page) {
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
}
async function action(page: Page, name: string, message?: string) {
  await page.getByRole("button", { name, exact: true }).click();
  if (message)
    await page.getByLabel("Mensagem pública", { exact: true }).fill(message);
  if (name === "Resolver chamado")
    await page
      .getByLabel("Classificação da solução")
      .fill("Configuração de acesso");
  await page
    .getByRole("button", { name: "Confirmar ação", exact: true })
    .click();
  await expect(page.getByRole("status")).toHaveText("Alteração registrada.");
}
async function reply(page: Page, message: string) {
  await page.getByLabel("Mensagem", { exact: true }).fill(message);
  await page
    .getByRole("button", { name: "Enviar resposta pública", exact: true })
    .click();
  await expect(page.getByRole("status")).toHaveText("Alteração registrada.");
}
test("portal, MFA, console, isolamento, anexos e ciclo completo", async ({
  browser,
}) => {
  const ownerContext = await browser.newContext();
  const techContext = await browser.newContext();
  const peerContext = await browser.newContext();
  const owner = await ownerContext.newPage();
  const tech = await techContext.newPage();
  const peer = await peerContext.newPage();
  await owner.goto("/");
  await audit(owner);
  await owner.screenshot({
    path: "../work/pulse-login-clean.png",
    fullPage: true,
  });
  await owner.keyboard.press("Tab");
  await expect(
    owner.getByRole("link", { name: "Ir para o conteúdo" }),
  ).toBeFocused();
  await login(owner, "owner");
  await login(tech, "tech");
  await login(peer, "peer");
  await owner
    .getByRole("button", { name: "Abrir chamado", exact: true })
    .click();
  await owner
    .getByLabel("Categoria")
    .selectOption({ label: "Acessos e sistemas" });
  await expect(owner.getByLabel("Prioridade")).toHaveValue("3");
  await owner.getByLabel("Prioridade").selectOption({ label: "Alta (P2)" });
  await owner
    .getByLabel("Assunto", { exact: true })
    .fill("Acesso ao sistema de operações");
  await owner
    .getByLabel("Descrição", { exact: true })
    .fill("Preciso acessar o sistema. Solicitação sintética de teste.");
  await audit(owner);
  await owner
    .getByRole("button", { name: "Criar chamado", exact: true })
    .click();
  await expect(
    owner.getByRole("heading", { name: "Acesso ao sistema de operações" }),
  ).toBeVisible();
  await tech.getByRole("button", { name: "Atualizar lista" }).click();
  await tech
    .getByRole("button")
    .filter({ hasText: "Acesso ao sistema de operações" })
    .click();
  await action(tech, "Assumir chamado");
  await tech
    .getByRole("combobox", { name: /^Destino/ })
    .selectOption("internal");
  await tech
    .getByLabel("Mensagem", { exact: true })
    .fill("Nota confidencial somente para suporte");
  await tech.getByLabel("Anexo opcional").setInputFiles({
    name: "interno.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Evidence internal"),
  });
  await tech
    .getByLabel("Confirmo: publicar somente para a equipe autorizada.")
    .check();
  await tech.getByRole("button", { name: "Publicar nota interna" }).click();
  await expect(tech.getByRole("status")).toHaveText("Alteração registrada.");
  await owner.getByRole("button", { name: "Atualizar chamado" }).click();
  await expect(
    owner.getByText("Nota confidencial somente para suporte"),
  ).toHaveCount(0);
  await expect(owner.getByText("interno.txt", { exact: false })).toHaveCount(0);
  await peer.getByRole("button", { name: "Atualizar lista" }).click();
  await expect(peer.getByText("Acesso ao sistema de operações")).toHaveCount(0);
  await action(tech, "Solicitar informações", "Informe o nome do sistema.");
  await owner.getByRole("button", { name: "Atualizar chamado" }).click();
  await expect(
    owner.getByRole("heading", { name: "Enviar informações" }),
  ).toBeVisible();
  await reply(owner, "Sistema Operações.");
  await tech.getByRole("button", { name: "Atualizar chamado" }).click();
  await action(tech, "Solicitar teste", "Tente entrar novamente.");
  await owner.getByRole("button", { name: "Atualizar chamado" }).click();
  await expect(
    owner.getByRole("heading", { name: "Informar resultado do teste" }),
  ).toBeVisible();
  await owner.getByLabel("Anexo opcional").setInputFiles({
    name: "resultado.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Teste realizado com sucesso"),
  });
  await reply(owner, "Teste realizado com sucesso.");
  await expect(
    owner.getByText("resultado.txt · Em quarentena, aguardando verificação"),
  ).toBeVisible();
  await expect(
    owner.getByRole("link", { name: "Baixar resultado.txt" }),
  ).toHaveCount(0);
  await tech.getByRole("button", { name: "Atualizar chamado" }).click();
  await audit(tech);
  await tech.screenshot({
    path: "../work/etapa-04-console.png",
    fullPage: true,
  });
  await action(tech, "Resolver chamado", "Acesso configurado e validado.");
  await owner.getByRole("button", { name: "Atualizar chamado" }).click();
  await action(owner, "Confirmar solução");
  await expect(owner.locator(".badge")).toHaveText("Fechado");
  await audit(owner);
  await owner.setViewportSize({ width: 390, height: 844 });
  await audit(owner);
  expect(
    await owner.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await owner.screenshot({
    path: "../work/etapa-04-mobile.png",
    fullPage: true,
  });
  await owner.locator("summary[aria-label^='Abrir menu de']").click();
  await audit(owner);
  await owner.screenshot({
    path: "../work/menu-usuario-mobile.png",
    fullPage: true,
  });
  await owner.getByRole("button", { name: "Sair", exact: true }).click();
  await expect(
    owner.getByRole("heading", { name: "Entrar", exact: true }),
  ).toBeVisible();
  await ownerContext.close();
  await techContext.close();
  await peerContext.close();
});
test("administração básica, configuração auditada e layout", async ({
  page,
}) => {
  await login(page, "admin");
  await page.locator("summary[aria-label^='Abrir menu de']").click();
  await page
    .locator(".user-menu-popover")
    .getByRole("button", { name: "Administração", exact: true })
    .click();
  await page
    .getByLabel("Nome", { exact: true })
    .fill("Área criada no navegador");
  await page.getByRole("button", { name: "Salvar configuração" }).click();
  const area = page.locator(".admin-list li", {
    hasText: "Área criada no navegador",
  });
  await expect(area.locator("strong")).toHaveText("Área criada no navegador");
  await audit(page);
  await page.screenshot({ path: "../work/etapa-04-admin.png", fullPage: true });
  page.once("dialog", (dialog) => dialog.accept());
  await area.getByRole("button", { name: "Remover" }).click();
  await expect(page.getByRole("status")).toHaveText("Registro removido.");
  await expect(area).toHaveCount(0);
  await page.getByRole("button", { name: "SMTP", exact: true }).click();
  await page.getByLabel("Servidor SMTP (nome DNS)").fill("smtp.company.test");
  await page.getByLabel("Usuário SMTP").fill("service@company.test");
  await page.getByLabel("Senha SMTP", { exact: true }).fill(fixture.password);
  await page.getByLabel("E-mail remetente").fill("service@company.test");
  await page
    .getByLabel("Justificativa da alteração")
    .fill("Configuração sintética, envios desativados");
  await page.getByRole("button", { name: "Salvar SMTP", exact: true }).click();
  await expect(page.getByRole("status")).toContainText(
    "Configuração SMTP salva",
  );
  await expect(page.getByLabel("Senha SMTP", { exact: true })).toHaveValue("");
  await expect(page.getByText(/Senha cadastrada/)).toBeVisible();
  await audit(page);
  await page.screenshot({
    path: "../work/configuracao-smtp.png",
    fullPage: true,
  });
  // Tab colour transitions would otherwise be sampled mid-animation by axe.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: "Google Chat", exact: true }).click();
  await page
    .getByLabel("Webhook do espaço")
    .fill(
      "https://chat.googleapis.com/v1/spaces/SYNTHETIC/messages?key=k&token=t",
    );
  await page
    .getByLabel("Justificativa da alteração")
    .fill("Webhook sintético, envio desativado");
  await page.getByRole("button", { name: "Salvar Google Chat" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Configuração do Google Chat salva",
  );
  await expect(page.getByLabel("Webhook do espaço")).toHaveValue("");
  await expect(page.getByText(/Webhook protegido e cadastrado/)).toBeVisible();
  await audit(page);
  await page.getByRole("button", { name: "Empresa", exact: true }).click();
  await page.getByLabel("Nome da empresa").fill("Empresa Sintética");
  await page.getByLabel("CNPJ").fill("11.222.333/0001-81");
  await page.getByLabel("Responsável pelas informações").fill("Pessoa Teste");
  await page.getByLabel(/^Logo/).setInputFiles({
    name: "logo.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
      "base64",
    ),
  });
  await expect(page.getByAltText("Prévia do logo")).toBeVisible();
  await page
    .getByLabel("Justificativa da alteração")
    .fill("Identificação sintética");
  await page.getByRole("button", { name: "Salvar empresa" }).click();
  await expect(page.getByText("Dados da empresa salvos.")).toBeVisible();
  await expect(page.locator(".company-badge")).toContainText(
    "Empresa Sintética",
  );
  await expect(page.locator(".company-badge img")).toBeVisible();
  await audit(page);
  await page.getByRole("button", { name: "Entregas", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Diagnóstico de notificações" }),
  ).toBeVisible();
  await audit(page);
  await page
    .getByRole("button", { name: "Política de SLA", exact: true })
    .click();
  await expect(page.getByLabel("Fuso horário (IANA)")).toHaveValue(
    "America/Sao_Paulo",
  );
  const levels = ["Crítica", "Alta", "Média", "Baixa"];
  for (let p = 1; p <= 4; p++) {
    const level = `${levels[p - 1]} (P${p})`;
    await page
      .getByLabel(`${level} · 1ª resposta (min úteis)`)
      .fill(String(60 * p));
    await page
      .getByLabel(`${level} · resolução (min úteis)`)
      .fill(String(240 * p));
  }
  await expect(
    page.getByLabel("Crítica (P1) · resolução (min úteis)"),
  ).toHaveAccessibleDescription(/Sugestão: 240 min \(4 h de expediente\)/);
  await page
    .getByLabel("Feriados (AAAA-MM-DD, separados por espaço)")
    .fill("2026-12-25");
  await page
    .getByLabel("Justificativa", { exact: true })
    .fill("Política sintética de SLA");
  await page.getByRole("button", { name: "Salvar configuração" }).click();
  await expect(page.getByText(/SLA · Política sintética de SLA/)).toBeVisible();
  await audit(page);
  await page
    .getByRole("button", { name: "Contas e perfis", exact: true })
    .click();
  await page.getByLabel("Nome", { exact: true }).fill("Conta Convidada");
  await page.getByLabel("E-mail corporativo").fill("invited@company.test");
  await page
    .getByLabel("Justificativa", { exact: true })
    .fill("Admissão sintética");
  await page.getByRole("button", { name: "Salvar configuração" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Conta criada como Colaborador",
  );
  const invited = page.locator(".admin-list li", {
    hasText: "Conta Convidada · invited@company.test",
  });
  await expect(invited).toContainText("Papel: Colaborador");
  page.once("dialog", (dialog) => dialog.accept("Desligamento sintético"));
  await invited.getByRole("button", { name: "Desativar" }).click();
  await expect(page.getByRole("status")).toHaveText("Registro desativado.");
  await expect(invited.getByRole("button", { name: "Reativar" })).toBeVisible();
  await audit(page);
  await page
    .getByRole("button", { name: "Domínios de confiança", exact: true })
    .click();
  await page
    .getByLabel("Domínio corporativo exato")
    .fill("approved.company.test");
  await page
    .getByLabel("Justificativa", { exact: true })
    .fill("Domínio de teste aprovado");
  await page.getByRole("button", { name: "Salvar configuração" }).click();
  await expect(
    page.getByText("approved.company.test", { exact: true }),
  ).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept("Domínio de teste encerrado"));
  await page.getByRole("button", { name: "Remover" }).last().click();
  await expect(page.getByRole("status")).toHaveText("Registro removido.");
  await expect(
    page.getByText("approved.company.test", { exact: true }),
  ).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await audit(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});

test("QR Code válido e dispositivo lembrado após reabrir o navegador", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
  });
  const page = await context.newPage();
  await page.goto("/");
  await page.getByLabel("E-mail corporativo").fill("enroll@company.test");
  await page.getByLabel("Senha", { exact: true }).fill(fixture.password);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(
    page.getByRole("img", { name: "QR Code para cadastrar o autenticador" }),
  ).toBeVisible();
  const pixels = await page.locator(".mfa-qr svg").evaluate(async (svg) => {
    const source = new XMLSerializer().serializeToString(svg);
    const img = new Image();
    const ready = new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("QR image unavailable"));
    });
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(source);
    await ready;
    const canvas = document.createElement("canvas");
    canvas.width = 224;
    canvas.height = 224;
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(img, 0, 0, 224, 224);
    return Array.from(ctx.getImageData(0, 0, 224, 224).data);
  });
  const decoded = jsQR(new Uint8ClampedArray(pixels), 224, 224);
  expect(decoded !== null).toBeTruthy();
  const uri = new URL(decoded!.data);
  expect(uri.protocol).toBe("otpauth:");
  expect(uri.hostname).toBe("totp");
  expect(uri.searchParams.get("issuer")).toBe("Pulse Services");
  const secret = uri.searchParams.get("secret")!;
  expect(secret === (await page.locator(".secret").innerText())).toBeTruthy();
  await expect(
    page.getByLabel("Lembrar este dispositivo por 30 dias"),
  ).not.toBeChecked();
  await audit(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "../work/mfa-qr-mobile.png",
    fullPage: true,
    mask: [page.locator(".secret")],
  });
  await page
    .getByLabel("Código do autenticador ou de recuperação")
    .fill(totp(secret));
  await page.getByLabel("Lembrar este dispositivo por 30 dias").check();
  await page.getByRole("button", { name: "Verificar código" }).click();
  await page
    .getByRole("button", { name: "Guardei os códigos. Continuar" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Fila de chamados" }),
  ).toBeVisible();
  const remembered = (await context.cookies()).filter(
    (cookie) => cookie.name === "pulse_trusted_device",
  );
  expect(remembered).toHaveLength(1);
  expect(remembered[0].httpOnly).toBeTruthy();
  await context.close();
  const reopened = await browser.newContext();
  await reopened.addCookies(remembered);
  const next = await reopened.newPage();
  await next.goto("/");
  await next.getByLabel("E-mail corporativo").fill("enroll@company.test");
  await next.getByLabel("Senha", { exact: true }).fill(fixture.password);
  await next.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(
    next.getByRole("heading", { name: "Fila de chamados" }),
  ).toBeVisible();
  await expect(
    next.getByRole("button", {
      name: "Sair e esquecer dispositivo",
      exact: true,
    }),
  ).toHaveCount(0);
  await next.locator("summary[aria-label^='Abrir menu de']").click();
  await next.getByRole("button", { name: "Sair", exact: true }).click();
  await next.getByLabel("E-mail corporativo").fill("enroll@company.test");
  await next.getByLabel("Senha", { exact: true }).fill(fixture.password);
  await next.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(
    next.getByRole("heading", { name: "Fila de chamados" }),
  ).toBeVisible();
  await reopened.close();
});

test("cadastro e recuperação conduzem às confirmações contextuais", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Entrar" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Versão/ })).toHaveCount(0);
  const icon = await page.request.get("/pulse-icon.png");
  expect(icon.headers()["content-type"]).toBe("image/png");
  await expect(page.locator(".brand-icon-ecg")).toBeVisible();
  for (const name of ["Termos de uso", "Aviso de privacidade"]) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await audit(page);
    await page.getByRole("button", { name: "Fechar", exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  }
  // Footer sits at the bottom of a short page without creating a scrollbar.
  expect(
    await page.evaluate(() => ({
      scroll: document.documentElement.scrollHeight <= innerHeight,
      footer: Math.round(
        document.querySelector("footer")!.getBoundingClientRect().bottom,
      ),
    })),
  ).toEqual({ scroll: true, footer: 900 });
  await expect(
    page.getByRole("button", { name: "Confirmar cadastro", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Definir nova senha", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Confirmar novo e-mail", exact: true }),
  ).toHaveCount(0);

  await page.getByRole("button", { name: "Criar conta", exact: true }).click();
  await page.getByLabel("Nome").fill("Novo Colaborador");
  await page.getByLabel("E-mail corporativo").fill("new-signup@company.test");
  await page.getByLabel("Senha", { exact: true }).fill(fixture.password);
  await page.getByRole("button", { name: "Criar conta", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Confirme seu cadastro" }),
  ).toBeVisible();
  await expect(
    page.getByText(/Enviamos o código de confirmação/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reenviar código", exact: true }),
  ).toBeVisible();
  await audit(page);

  await page
    .getByRole("button", { name: "Recuperar senha", exact: true })
    .click();
  await page.getByLabel("E-mail corporativo").fill("owner@company.test");
  await page
    .getByRole("button", { name: "Recuperar senha", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Definir nova senha" }),
  ).toBeVisible();
  await expect(
    page.getByText(/Enviamos o código de recuperação/),
  ).toBeVisible();
});

test("perfil altera foto e nome, mas não o e-mail", async ({ page }) => {
  await login(page, "owner");
  await expect(page.locator(".avatar")).toHaveText("A");
  await page.getByRole("button", { name: /^Versão \d/ }).click();
  await expect(page.getByRole("heading", { name: "Novidades" })).toBeVisible();
  await audit(page);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const menu = page.locator("summary[aria-label^='Abrir menu de']");
  await menu.click();
  await expect(
    page.getByRole("button", { name: "Administração", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("heading", { name: "Meus chamados" }).click();
  await expect(page.locator(".user-menu-popover")).toBeHidden();
  await menu.click();
  await page.keyboard.press("Escape");
  await expect(page.locator(".user-menu-popover")).toBeHidden();
  await menu.click();
  await page
    .locator(".user-menu-popover")
    .getByRole("button", { name: "Perfil", exact: true })
    .click();
  await expect(page.getByLabel("E-mail corporativo")).toHaveAttribute(
    "readonly",
  );
  await expect(page.getByLabel("Novo e-mail corporativo")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Alterar senha" }),
  ).toBeVisible();
  await page.getByLabel("Escolher imagem").setInputFiles({
    name: "foto.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
      "base64",
    ),
  });
  await expect(page.getByRole("img", { name: "Sua foto" })).toBeVisible();
  await page.getByLabel("Nome").fill("Ana Perfil");
  await page
    .getByRole("button", { name: "Salvar perfil", exact: true })
    .click();
  await expect(page.getByText("Perfil atualizado.")).toBeVisible();
  await expect(menu).toHaveAttribute("aria-label", "Abrir menu de Ana Perfil");
  await expect(page.locator("summary img.avatar")).toHaveAttribute(
    "src",
    /^data:image\/jpeg;base64,/,
  );
  await audit(page);
});

test("gestor consulta relatórios e exporta CSV com prazo", async ({ page }) => {
  await login(page, "manager");
  await page.getByRole("button", { name: "Relatórios", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Relatórios e SLA" }),
  ).toBeVisible();
  await expect(
    page.getByText("Abertos no período", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Abertos agora por técnico" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Exportar CSV", exact: true }).click();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Baixar CSV" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^chamados-.*\.csv$/);
  const content = readFileSync(await download.path(), "utf8");
  expect(content).toContain("numero,aberto_em,estado");
  await audit(page);
  await page.screenshot({
    path: "../work/etapa-06-relatorios.png",
    fullPage: true,
  });
});
