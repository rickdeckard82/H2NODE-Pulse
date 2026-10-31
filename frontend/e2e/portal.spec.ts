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
  await owner.getByRole("button", { name: "Abrir menu", exact: true }).click();
  await expect(owner.locator(".sidebar")).toHaveClass(/open/);
  await audit(owner);
  await owner.screenshot({
    path: "../work/pulse-style-sidebar-mobile.png",
    fullPage: true,
  });
  await owner
    .getByRole("button", { name: "Fechar menu", exact: true })
    .last()
    .click();
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
  await page
    .getByRole("button", { name: "Recolher menu", exact: true })
    .click();
  await expect(page.locator(".app-shell")).toHaveClass(/sidebar-collapsed/);
  await page
    .getByRole("button", { name: "Expandir menu", exact: true })
    .click();
  await expect(page.locator(".app-shell")).not.toHaveClass(/sidebar-collapsed/);
  await page.locator("summary[aria-label^='Abrir menu de']").click();
  await page
    .locator(".user-menu-popover")
    .getByRole("button", { name: "Administração", exact: true })
    .click();
  await page
    .getByLabel("Nome", { exact: true })
    .fill("Área criada no navegador");
  await page.getByRole("button", { name: "Salvar configuração" }).click();
  await expect(page.getByText(/Área criada no navegador/)).toBeVisible();
  await audit(page);
  await page.screenshot({ path: "../work/etapa-04-admin.png", fullPage: true });
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
  await expect(page.getByText(/#.*approved.company.test/)).toBeVisible();
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
  await page.goto("/");
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

test("confirmação do novo e-mail fica na conta autenticada", async ({
  page,
}) => {
  await login(page, "owner");
  await expect(page.locator(".avatar")).toHaveText("A");
  await page.locator("summary[aria-label^='Abrir menu de']").click();
  await expect(
    page.getByRole("button", { name: "Administração", exact: true }),
  ).toHaveCount(0);
  await page
    .locator(".user-menu-popover")
    .getByRole("button", { name: "Alterar senha", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Alterar senha" }),
  ).toBeVisible();
  await page.locator("summary[aria-label^='Abrir menu de']").click();
  await page
    .locator(".user-menu-popover")
    .getByRole("button", { name: "Perfil", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Alterar e-mail" }),
  ).toBeVisible();
  await page
    .getByLabel("Novo e-mail corporativo")
    .fill("owner-updated@company.test");
  await page.getByLabel("Senha atual").fill(fixture.password);
  await page
    .getByRole("button", { name: "Enviar código de confirmação", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Confirmar novo e-mail" }),
  ).toBeVisible();
  await expect(
    page.getByText(/Enviamos um código ao novo e-mail/),
  ).toBeVisible();
  await audit(page);
});
