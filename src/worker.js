const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const SITE_NAME = "Semi News Daily";
const LEGACY_SITE_HOST = "semi.danielsgarden.work";
const PUBLIC_SITE_HOST = "semi-daily.danielsgarden.work";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.hostname === LEGACY_SITE_HOST) {
      url.hostname = PUBLIC_SITE_HOST;
      return Response.redirect(url.toString(), 308);
    }

    if (request.method === "OPTIONS" && url.pathname.startsWith("/api/")) {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    if (url.pathname === "/api/subscribe") {
      return withCors(await handleSubscribe(request, env));
    }
    if (url.pathname === "/api/confirm") {
      return handleConfirm(request, env);
    }
    if (url.pathname === "/api/unsubscribe") {
      return handleUnsubscribe(request, env);
    }
    if (url.pathname === "/api/send-daily") {
      return withCors(await handleSendDaily(request, env));
    }

    return env.ASSETS.fetch(request);
  },
};

async function handleSubscribe(request, env) {
  if (request.method !== "POST") {
    return json({ ok: false, error: "method_not_allowed" }, 405);
  }
  if (!env.DB) {
    return json({ ok: false, error: "newsletter_storage_not_configured" }, 503);
  }

  const body = await readBody(request);
  if ((body.company || "").trim()) {
    return json({ ok: true, status: "pending" });
  }

  const email = normalizeEmail(body.email);
  const lang = normalizeLang(body.lang);
  if (!email) {
    return json({ ok: false, error: "invalid_email" }, 400);
  }

  const now = new Date().toISOString();
  const existing = await env.DB.prepare(
    "SELECT status, unsubscribe_token FROM subscribers WHERE email = ?"
  ).bind(email).first();

  if (existing?.status === "confirmed") {
    await env.DB.prepare(
      "UPDATE subscribers SET lang = ?, updated_at = ?, source = ?, user_agent = ? WHERE email = ?"
    ).bind(lang, now, "site", request.headers.get("user-agent") || "", email).run();
    return json({ ok: true, status: "confirmed" });
  }

  const confirmationToken = randomToken();
  const unsubscribeToken = existing?.unsubscribe_token || randomToken();

  await env.DB.prepare(`
    INSERT INTO subscribers (
      email, status, lang, confirmation_token, unsubscribe_token,
      created_at, updated_at, source, user_agent
    )
    VALUES (?, 'pending', ?, ?, ?, ?, ?, 'site', ?)
    ON CONFLICT(email) DO UPDATE SET
      status = 'pending',
      lang = excluded.lang,
      confirmation_token = excluded.confirmation_token,
      unsubscribe_token = COALESCE(subscribers.unsubscribe_token, excluded.unsubscribe_token),
      updated_at = excluded.updated_at,
      unsubscribed_at = NULL,
      source = excluded.source,
      user_agent = excluded.user_agent
  `).bind(
    email,
    lang,
    confirmationToken,
    unsubscribeToken,
    now,
    now,
    request.headers.get("user-agent") || ""
  ).run();

  const origin = new URL(request.url).origin;
  const delivery = await sendConfirmationEmail(env, {
    email,
    lang,
    confirmUrl: `${origin}/api/confirm?token=${encodeURIComponent(confirmationToken)}`,
    unsubscribeUrl: `${origin}/api/unsubscribe?token=${encodeURIComponent(unsubscribeToken)}`,
  });

  return json({
    ok: true,
    status: delivery.skipped ? "pending_delivery_unconfigured" : "pending",
  }, delivery.skipped ? 202 : 200);
}

async function handleConfirm(request, env) {
  if (!env.DB) return htmlPage("Newsletter storage is not configured.", 503);
  const token = new URL(request.url).searchParams.get("token") || "";
  if (!token) return htmlPage("Confirmation link is missing a token.", 400);

  const now = new Date().toISOString();
  const result = await env.DB.prepare(`
    UPDATE subscribers
    SET status = 'confirmed',
        confirmed_at = COALESCE(confirmed_at, ?),
        updated_at = ?,
        confirmation_token = NULL
    WHERE confirmation_token = ?
  `).bind(now, now, token).run();

  if (!result.meta?.changes) {
    return htmlPage("This confirmation link is invalid or has already been used.", 404);
  }
  return htmlPage("Subscription confirmed. You will receive the next daily briefing.", 200);
}

async function handleUnsubscribe(request, env) {
  if (!env.DB) return htmlPage("Newsletter storage is not configured.", 503);
  const token = new URL(request.url).searchParams.get("token") || "";
  if (!token) return htmlPage("Unsubscribe link is missing a token.", 400);

  const now = new Date().toISOString();
  const result = await env.DB.prepare(`
    UPDATE subscribers
    SET status = 'unsubscribed',
        unsubscribed_at = ?,
        updated_at = ?
    WHERE unsubscribe_token = ?
  `).bind(now, now, token).run();

  if (!result.meta?.changes) {
    return htmlPage("This unsubscribe link is invalid or has already been used.", 404);
  }
  return htmlPage("You have been unsubscribed.", 200);
}

async function handleSendDaily(request, env) {
  if (request.method !== "POST") {
    return json({ ok: false, error: "method_not_allowed" }, 405);
  }
  if (!env.NEWSLETTER_SEND_SECRET) {
    return json({ ok: false, error: "send_secret_not_configured" }, 503);
  }
  if (request.headers.get("x-send-secret") !== env.NEWSLETTER_SEND_SECRET) {
    return json({ ok: false, error: "unauthorized" }, 401);
  }
  if (!env.RESEND_API_KEY || !env.NEWSLETTER_FROM) {
    return json({ ok: false, error: "email_delivery_not_configured" }, 503);
  }
  if (!env.DB) {
    return json({ ok: false, error: "newsletter_storage_not_configured" }, 503);
  }

  const edition = await loadEdition(env);
  const subscribers = await env.DB.prepare(`
    SELECT email, lang, unsubscribe_token
    FROM subscribers
    WHERE status = 'confirmed'
      AND (last_sent_date IS NULL OR last_sent_date != ?)
    ORDER BY confirmed_at ASC
    LIMIT 500
  `).bind(edition.date).all();

  let sent = 0;
  let failed = 0;
  for (const subscriber of subscribers.results || []) {
    const unsubscribeUrl = `${new URL(request.url).origin}/api/unsubscribe?token=${encodeURIComponent(subscriber.unsubscribe_token)}`;
    const result = await sendEditionEmail(env, edition, subscriber, unsubscribeUrl);
    const now = new Date().toISOString();
    if (result.ok) {
      sent += 1;
      await env.DB.prepare(`
        UPDATE subscribers
        SET last_sent_date = ?, send_count = send_count + 1, updated_at = ?
        WHERE email = ?
      `).bind(edition.date, now, subscriber.email).run();
      await recordSend(env, subscriber.email, edition.date, "sent", result.id || "", "", now);
    } else {
      failed += 1;
      await recordSend(env, subscriber.email, edition.date, "failed", "", result.error || "unknown", now);
    }
  }

  return json({
    ok: true,
    edition_date: edition.date,
    attempted: (subscribers.results || []).length,
    sent,
    failed,
  });
}

async function readBody(request) {
  const type = request.headers.get("content-type") || "";
  if (type.includes("application/json")) {
    return await request.json().catch(() => ({}));
  }
  const form = await request.formData().catch(() => null);
  if (!form) return {};
  return Object.fromEntries(form.entries());
}

function normalizeEmail(value) {
  const email = String(value || "").trim().toLowerCase();
  if (email.length < 6 || email.length > 254 || !EMAIL_RE.test(email)) return "";
  return email;
}

function normalizeLang(value) {
  return value === "en" || value === "zh" || value === "both" ? value : "both";
}

function randomToken() {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function loadEdition(env) {
  const response = await env.ASSETS.fetch(new Request("https://assets.local/edition.json"));
  if (!response.ok) throw new Error("edition.json unavailable");
  return response.json();
}

async function sendConfirmationEmail(env, data) {
  if (!env.RESEND_API_KEY || !env.NEWSLETTER_FROM) return { skipped: true };
  const subject = data.lang === "zh" ? "确认订阅 Semi News Daily" : "Confirm your Semi News Daily subscription";
  const text = data.lang === "zh"
    ? `请确认订阅：${data.confirmUrl}\n\n退订：${data.unsubscribeUrl}`
    : `Confirm your subscription: ${data.confirmUrl}\n\nUnsubscribe: ${data.unsubscribeUrl}`;
  return sendEmail(env, {
    to: data.email,
    subject,
    html: `<p>${escapeHtml(text).replace(/\n/g, "<br>")}</p>`,
    text,
  });
}

async function sendEditionEmail(env, edition, subscriber, unsubscribeUrl) {
  const useZh = subscriber.lang === "zh";
  const theme = edition.theme || {};
  const dek = edition.dek || {};
  const subject = useZh
    ? `Semi News Daily: ${theme.zh || theme.en || edition.date}`
    : `Semi News Daily: ${theme.en || theme.zh || edition.date}`;
  const siteUrl = (env.PUBLIC_SITE_URL || `https://${PUBLIC_SITE_HOST}`).replace(/\/+$/, "");
  const headlineUrl = `${siteUrl}/`;
  const researchUrl = `${siteUrl}/research.html`;
  const stories = collectStories(edition).slice(0, 8);
  const intro = useZh ? (dek.zh || dek.en || "") : (dek.en || dek.zh || "");
  const html = renderEditionHtml({ edition, stories, subject, intro, headlineUrl, researchUrl, unsubscribeUrl, useZh });
  const text = renderEditionText({ edition, stories, subject, intro, headlineUrl, researchUrl, unsubscribeUrl, useZh });
  return sendEmail(env, { to: subscriber.email, subject, html, text });
}

async function sendEmail(env, message) {
  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.RESEND_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      from: env.NEWSLETTER_FROM,
      to: [message.to],
      subject: message.subject,
      html: message.html,
      text: message.text,
    }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    return { ok: false, error: data.message || data.error || `HTTP ${response.status}` };
  }
  return { ok: true, id: data.id || "" };
}

function collectStories(edition) {
  const stories = [];
  for (const section of edition.sections || []) {
    for (const story of section.stories || []) {
      stories.push(story);
    }
  }
  return stories;
}

function renderEditionHtml(data) {
  const items = data.stories.map((story) => {
    const title = pickLang(story.title, data.useZh);
    const summary = pickLang(story.summary, data.useZh);
    return `<li><a href="${escapeHtml(story.url)}">${escapeHtml(title)}</a><br><span>${escapeHtml(summary)}</span></li>`;
  }).join("");
  const read = data.useZh ? "阅读今日要闻" : "Read today's headlines";
  const research = data.useZh ? "阅读研究页" : "Read research";
  const unsubscribe = data.useZh ? "退订" : "Unsubscribe";
  return `<!doctype html><html><body style="font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',Arial,sans-serif;line-height:1.55;color:#18181b">
    <h1>${escapeHtml(data.subject)}</h1>
    <p>${escapeHtml(data.intro)}</p>
    <ul>${items}</ul>
    <p><a href="${data.headlineUrl}">${read}</a> · <a href="${data.researchUrl}">${research}</a></p>
    <p style="font-size:12px;color:#6b6b6b"><a href="${escapeHtml(data.unsubscribeUrl)}">${unsubscribe}</a></p>
  </body></html>`;
}

function renderEditionText(data) {
  const lines = [data.subject, "", data.intro, ""];
  for (const story of data.stories) {
    lines.push(`- ${pickLang(story.title, data.useZh)}`);
    lines.push(`  ${story.url}`);
  }
  lines.push("", data.headlineUrl, data.researchUrl, "", data.unsubscribeUrl);
  return lines.join("\n");
}

function pickLang(field, useZh) {
  if (!field) return "";
  return useZh ? (field.zh || field.en || "") : (field.en || field.zh || "");
}

async function recordSend(env, email, date, status, providerId, error, now) {
  await env.DB.prepare(`
    INSERT OR REPLACE INTO newsletter_sends (
      email, edition_date, status, provider_id, error, created_at
    )
    VALUES (?, ?, ?, ?, ?, ?)
  `).bind(email, date, status, providerId, error, now).run();
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { ...JSON_HEADERS, ...corsHeaders() },
  });
}

function withCors(response) {
  const next = new Response(response.body, response);
  for (const [key, value] of Object.entries(corsHeaders())) {
    next.headers.set(key, value);
  }
  return next;
}

function corsHeaders() {
  return {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "POST, OPTIONS",
    "access-control-allow-headers": "content-type, x-send-secret",
  };
}

function htmlPage(message, status) {
  return new Response(`<!doctype html><html lang="en"><meta charset="utf-8"><title>${escapeHtml(SITE_NAME)}</title><body style="font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',Arial,sans-serif;line-height:1.5;max-width:640px;margin:48px auto;padding:0 20px"><p>${escapeHtml(message)}</p><p><a href="/">Semi News Daily</a></p></body></html>`, {
    status,
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
  });
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
