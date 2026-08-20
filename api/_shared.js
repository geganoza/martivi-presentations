'use strict';

/**
 * Shared helpers for the MARTIVI interview self-booking API.
 *
 * Zero npm dependencies on purpose: the presentations project is a static
 * Vercel site with no package.json, so only Node built-ins and global fetch
 * are available. CommonJS, because without "type":"module" that is what the
 * Vercel Node runtime expects.
 */

const crypto = require('node:crypto');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Asia/Tbilisi is UTC+04:00 all year and has no daylight saving time. */
const TZ = 'Asia/Tbilisi';
const TZ_OFFSET_MS = 4 * 60 * 60 * 1000;
const TZ_SUFFIX = '+04:00';

const GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token';
const GCAL_BASE = 'https://www.googleapis.com/calendar/v3';

/**
 * The calendar the interview event is WRITTEN to, and the only one we can read
 * events from. Everything else below is availability-only.
 */
const CALENDAR_ID = 'primary';

/**
 * Co-hosts: people who must also be free for a slot to be offered, and who get
 * invited to the event.
 *
 * Comma-separated in BOOKING_COHOSTS, e.g.
 *   BOOKING_COHOSTS=giorgi.ujmajuridze@martiviconsulting.com
 *
 * Free/busy across a Google Workspace tenant needs no sharing setup: members of
 * the same tenant can read each other's busy blocks by default, across domains
 * (verified 2026-08-08 for martividigital.com -> martiviconsulting.com). A
 * personal @gmail.com address is NOT in the tenant and returns `notFound`, so
 * such a person must share their calendar with the booking account first.
 *
 * Read at call time, not module load: Vercel injects env vars per invocation.
 *
 * @returns {string[]}
 */
function cohostCalendars() {
  return String(process.env.BOOKING_COHOSTS || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

/**
 * Every calendar that gets a say in whether a slot is offered: the host's, plus
 * each co-host's. A slot survives only if it is free on ALL of them.
 *
 * @returns {string[]}
 */
function busyCalendars() {
  return [CALENDAR_ID].concat(cohostCalendars());
}

/**
 * Georgian localisation constants.
 *
 * NOT hand-written. Produced once by piping an English spec through the `ka`
 * CLI (Gemini 2.5 Pro) and pasting the JSON it returned verbatim.
 * WEEKDAYS is indexed by Date#getUTCDay(): 0 = Sunday.
 */
const WEEKDAYS_KA = [
  'კვირა',
  'ორშაბათი',
  'სამშაბათი',
  'ოთხშაბათი',
  'ხუთშაბათი',
  'პარასკევი',
  'შაბათი',
];

const MONTHS_KA = [
  'იანვარი',
  'თებერვალი',
  'მარტი',
  'აპრილი',
  'მაისი',
  'ივნისი',
  'ივლისი',
  'აგვისტო',
  'სექტემბერი',
  'ოქტომბერი',
  'ნოემბერი',
  'დეკემბერი',
];

/** Calendar event copy, also produced by `ka`. {position} / {brand} / {name} are filled in. */
// Position and brand are per-round, so they come from env with the original
// Project Assistant values as fallback. They used to be hardcoded, which meant
// the designer round's first test booking landed titled "გასაუბრება: პროექტის
// ასისტენტი", the wrong role, on a calendar invite the candidate receives.
// Set BOOKING_POSITION_KA and BOOKING_BRAND per round.
const EVENT_KA = {
  position: process.env.BOOKING_POSITION_KA || 'პროექტის ასისტენტი',
  brand: process.env.BOOKING_BRAND || 'MARTIVI CONSULTING',
  summary: 'გასაუბრება: {position}, {name}',
  description:
    'ონლაინ გასაუბრება {position} პოზიციაზე.\n' +
    'ინტერვიუერი: გიორგი ნოზაძე, {brand}.\n' +
    'ხანგრძლივობა: 30 წუთი.\n' +
    'Google Meet-ის ბმული თან ერთვის ამ მოწვევას.',
};

/** @type {Record<string,{name:string,nameEn:string,email:string}>|null} Parsed roster cache. */
let rosterCache = null;

/**
 * The candidate roster, read from the BOOKING_ROSTER environment variable.
 *
 * Deliberately NOT hardcoded here. This repository is public, and the roster
 * pairs five real job applicants' full names with their personal email
 * addresses. The authoritative copy lives in MAIA's
 * `scripts/hr_interview_invites.py`, whose `roster-env` subcommand prints the
 * exact JSON to paste into the Vercel environment variable. That also makes the
 * Python tool the only place candidate ids are written, so the ids it signs
 * tokens over cannot drift from the ids this verifier knows.
 *
 * Expected shape:
 * `{"<candidateId>": {"name": "<Georgian>", "nameEn": "<Latin>", "email": "..."}}`
 * where `<candidateId>` is the id in `workspace/hr/candidates.json`.
 *
 * @returns {Record<string,{name:string,nameEn:string,email:string}>}
 * @throws {Error} When BOOKING_ROSTER is unset, unparseable or empty. That is a
 *         deployment fault, so it must surface as a 500 rather than silently
 *         turning every valid link into a 403.
 */
function candidates() {
  if (rosterCache) return rosterCache;

  const raw = process.env.BOOKING_ROSTER;
  if (!raw || !String(raw).trim()) {
    throw new Error('missing required environment variable BOOKING_ROSTER');
  }

  let parsed = null;
  try {
    parsed = JSON.parse(String(raw));
  } catch (_err) {
    throw new Error('BOOKING_ROSTER is not valid JSON');
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('BOOKING_ROSTER must be a JSON object keyed on candidate id');
  }

  const roster = {};
  for (const [id, entry] of Object.entries(parsed)) {
    if (!id || !entry || typeof entry !== 'object') continue;
    const name = typeof entry.name === 'string' ? entry.name.trim() : '';
    const email = typeof entry.email === 'string' ? entry.email.trim() : '';
    if (!name || !email) continue;
    const nameEn = typeof entry.nameEn === 'string' && entry.nameEn.trim() ? entry.nameEn.trim() : name;
    roster[id] = { name, nameEn, email };
  }
  if (Object.keys(roster).length === 0) {
    throw new Error('BOOKING_ROSTER contains no usable candidate entries');
  }

  rosterCache = roster;
  return rosterCache;
}

const DEFAULTS = {
  days: ['2026-08-04', '2026-08-05'],
  startHour: 10,
  endHour: 18,
  minNoticeHours: 14,
  slotMinutes: 30,
};

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

/**
 * Write a JSON response with caching disabled.
 *
 * @param {import('http').ServerResponse} res
 * @param {number} status
 * @param {object} payload
 */
function sendJson(res, status, payload) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store, max-age=0');
  res.end(JSON.stringify(payload));
}

/**
 * Answer a CORS/OPTIONS preflight. Returns true when the request was handled.
 *
 * @param {import('http').IncomingMessage} req
 * @param {import('http').ServerResponse} res
 * @param {string} methods Comma separated list of allowed methods.
 * @returns {boolean}
 */
function handleOptions(req, res, methods) {
  if (req.method !== 'OPTIONS') return false;
  res.statusCode = 204;
  res.setHeader('Allow', `${methods}, OPTIONS`);
  res.setHeader('Cache-Control', 'no-store, max-age=0');
  res.end();
  return true;
}

/**
 * Read and JSON-parse a request body, tolerating an already-parsed req.body.
 *
 * @param {import('http').IncomingMessage & {body?: unknown}} req
 * @returns {Promise<object>} Parsed object, or {} when the body is empty.
 */
async function readJsonBody(req) {
  const pre = req.body;
  if (pre && typeof pre === 'object' && !Buffer.isBuffer(pre)) return pre;
  let raw = '';
  if (typeof pre === 'string') {
    raw = pre;
  } else if (Buffer.isBuffer(pre)) {
    raw = pre.toString('utf8');
  } else {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    raw = Buffer.concat(chunks).toString('utf8');
  }
  raw = raw.trim();
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (_err) {
    return {};
  }
}

/**
 * Turn an unknown thrown value into a short message that can never contain a
 * secret. Env var values are never interpolated into error messages anywhere
 * in this codebase, so this only needs to bound the length.
 *
 * @param {unknown} err
 * @returns {string}
 */
function safeDetail(err) {
  const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : String(err);
  return msg.replace(/\s+/g, ' ').slice(0, 200);
}

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/**
 * Parse an integer env var, falling back to the default on anything unusable.
 *
 * @param {string|undefined} raw
 * @param {number} fallback
 * @param {number} min Inclusive lower bound.
 * @param {number} max Inclusive upper bound.
 * @returns {number}
 */
function intOr(raw, fallback, min, max) {
  if (raw === undefined || raw === null || String(raw).trim() === '') return fallback;
  const n = Number.parseInt(String(raw).trim(), 10);
  if (!Number.isFinite(n) || n < min || n > max) return fallback;
  return n;
}

/**
 * Read the booking window configuration from the environment.
 *
 * Never throws: an unparseable value silently degrades to its default so a
 * mis-set env var cannot take the whole endpoint down.
 *
 * @returns {{days: string[], startHour: number, endHour: number,
 *            minNoticeHours: number, slotMinutes: number}}
 */
function config() {
  let days = String(process.env.BOOKING_DAYS || '')
    .split(',')
    .map((d) => d.trim())
    .filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d) && Number.isFinite(Date.parse(`${d}T00:00:00${TZ_SUFFIX}`)));
  days = Array.from(new Set(days)).sort();
  if (days.length === 0) days = DEFAULTS.days.slice();

  const startHour = intOr(process.env.BOOKING_START_HOUR, DEFAULTS.startHour, 0, 23);
  let endHour = intOr(process.env.BOOKING_END_HOUR, DEFAULTS.endHour, 1, 24);
  if (endHour <= startHour) endHour = DEFAULTS.endHour > startHour ? DEFAULTS.endHour : 24;

  const minNoticeHours = intOr(process.env.BOOKING_MIN_NOTICE_HOURS, DEFAULTS.minNoticeHours, 0, 720);
  const slotMinutes = intOr(process.env.BOOKING_SLOT_MINUTES, DEFAULTS.slotMinutes, 5, 240);

  return { days, startHour, endHour, minNoticeHours, slotMinutes };
}

// ---------------------------------------------------------------------------
// Time helpers (fixed +04:00, never the server's local timezone)
// ---------------------------------------------------------------------------

/**
 * Split an epoch timestamp into Asia/Tbilisi calendar fields.
 *
 * @param {number} ms Epoch milliseconds.
 * @returns {{year:number, month:number, day:number, hour:number, minute:number, dow:number}}
 */
function tbilisiParts(ms) {
  const d = new Date(ms + TZ_OFFSET_MS);
  return {
    year: d.getUTCFullYear(),
    month: d.getUTCMonth() + 1,
    day: d.getUTCDate(),
    hour: d.getUTCHours(),
    minute: d.getUTCMinutes(),
    dow: d.getUTCDay(),
  };
}

/** @param {number} n @param {number} width @returns {string} */
function pad(n, width) {
  return String(n).padStart(width, '0');
}

/**
 * Render an epoch timestamp as an ISO-8601 string with an explicit +04:00.
 *
 * @param {number} ms Epoch milliseconds.
 * @returns {string} e.g. "2026-08-04T10:00:00+04:00"
 */
function isoTbilisi(ms) {
  const p = tbilisiParts(ms);
  return (
    `${pad(p.year, 4)}-${pad(p.month, 2)}-${pad(p.day, 2)}` +
    `T${pad(p.hour, 2)}:${pad(p.minute, 2)}:${pad(0, 2)}${TZ_SUFFIX}`
  );
}

/**
 * Epoch milliseconds for a wall-clock time on a given Asia/Tbilisi date.
 *
 * @param {string} dateStr "YYYY-MM-DD"
 * @param {number} minutesOfDay Minutes since 00:00 local.
 * @returns {number}
 */
function tbilisiMs(dateStr, minutesOfDay) {
  const base = Date.parse(`${dateStr}T00:00:00${TZ_SUFFIX}`);
  return base + minutesOfDay * 60 * 1000;
}

/**
 * Georgian label for a calendar date, e.g. "სამშაბათი, 4 აგვისტო".
 *
 * @param {string} dateStr "YYYY-MM-DD"
 * @returns {string}
 */
function dayLabelKa(dateStr) {
  const [y, m, d] = dateStr.split('-').map((v) => Number.parseInt(v, 10));
  const dow = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return `${WEEKDAYS_KA[dow]}, ${d} ${MONTHS_KA[m - 1]}`;
}

/**
 * Georgian label for a specific slot, e.g. "სამშაბათი, 4 აგვისტო, 10:00".
 *
 * @param {number} ms Epoch milliseconds of the slot start.
 * @returns {string}
 */
function slotLabelKa(ms) {
  const p = tbilisiParts(ms);
  const dateStr = `${pad(p.year, 4)}-${pad(p.month, 2)}-${pad(p.day, 2)}`;
  return `${dayLabelKa(dateStr)}, ${pad(p.hour, 2)}:${pad(p.minute, 2)}`;
}

/**
 * Short time label for a slot, e.g. "10:30".
 *
 * @param {number} ms Epoch milliseconds.
 * @returns {string}
 */
function timeLabel(ms) {
  const p = tbilisiParts(ms);
  return `${pad(p.hour, 2)}:${pad(p.minute, 2)}`;
}

// ---------------------------------------------------------------------------
// Tokens
// ---------------------------------------------------------------------------

/**
 * Read BOOKING_SECRET or throw.
 *
 * @returns {string}
 */
function bookingSecret() {
  const secret = process.env.BOOKING_SECRET;
  if (!secret || !String(secret).trim()) {
    throw new Error('missing required environment variable BOOKING_SECRET');
  }
  return String(secret);
}

/**
 * Sign a candidate id into a shareable token.
 *
 * @param {string} candidateId
 * @returns {string} "<id>.<16 chars of base64url HMAC-SHA256>"
 */
function signToken(candidateId) {
  const sig = crypto
    .createHmac('sha256', bookingSecret())
    .update(String(candidateId), 'utf8')
    .digest('base64url')
    .slice(0, 16);
  return `${candidateId}.${sig}`;
}

/**
 * Verify a token and resolve it to a candidate.
 *
 * @param {unknown} token
 * @returns {{id: string, name: string, nameEn: string, email: string}|null}
 *          null when the token is malformed, unknown or badly signed.
 * @throws {Error} When BOOKING_SECRET or BOOKING_ROSTER is unset. That is a
 *         deployment fault, not a bad token, so it must surface as a 500 rather
 *         than silently turning every valid link into a 403.
 */
function verifyToken(token) {
  if (typeof token !== 'string') return null;
  const t = token.trim();
  if (!t || t.length > 200) return null;
  const dot = t.indexOf('.');
  if (dot <= 0 || dot === t.length - 1) return null;

  const roster = candidates();
  const id = t.slice(0, dot);
  const sig = t.slice(dot + 1);
  const candidate = Object.prototype.hasOwnProperty.call(roster, id) ? roster[id] : null;
  if (!candidate) return null;

  const expected = signToken(id).slice(id.length + 1);

  const a = Buffer.from(sig, 'utf8');
  const b = Buffer.from(expected, 'utf8');
  // timingSafeEqual throws on differing lengths, so guard first.
  if (a.length !== b.length) return null;
  if (!crypto.timingSafeEqual(a, b)) return null;

  return { id, name: candidate.name, nameEn: candidate.nameEn, email: candidate.email };
}

// ---------------------------------------------------------------------------
// Google OAuth
// ---------------------------------------------------------------------------

/** @type {{token: string, expiresAtMs: number}|null} Warm-lambda token cache. */
let tokenCache = null;

/**
 * Get a Google API access token via the refresh-token grant.
 *
 * The token is cached in module scope until 60 seconds before its expiry so
 * warm invocations reuse it.
 *
 * @returns {Promise<string>}
 * @throws {Error} When an env var is missing or Google rejects the refresh.
 */
async function getAccessToken() {
  const clientId = process.env.GCAL_CLIENT_ID;
  const clientSecret = process.env.GCAL_CLIENT_SECRET;
  const refreshToken = process.env.GCAL_REFRESH_TOKEN;

  const missing = [];
  if (!clientId) missing.push('GCAL_CLIENT_ID');
  if (!clientSecret) missing.push('GCAL_CLIENT_SECRET');
  if (!refreshToken) missing.push('GCAL_REFRESH_TOKEN');
  if (missing.length) {
    throw new Error(`missing required environment variable(s): ${missing.join(', ')}`);
  }

  const now = Date.now();
  if (tokenCache && tokenCache.expiresAtMs > now) return tokenCache.token;

  const body = new URLSearchParams({
    client_id: clientId,
    client_secret: clientSecret,
    refresh_token: refreshToken,
    grant_type: 'refresh_token',
  });

  const resp = await fetch(GOOGLE_TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  });

  if (!resp.ok) {
    // Deliberately does not echo the response body: it is an OAuth error
    // document and must never reach the client or the logs verbatim.
    throw new Error(`google token refresh failed with status ${resp.status}`);
  }

  const data = await resp.json().catch(() => null);
  if (!data || typeof data.access_token !== 'string' || !data.access_token) {
    throw new Error('google token refresh returned no access_token');
  }

  const expiresIn = Number.isFinite(data.expires_in) ? Number(data.expires_in) : 3600;
  tokenCache = { token: data.access_token, expiresAtMs: now + Math.max(0, expiresIn - 60) * 1000 };
  return tokenCache.token;
}

/**
 * Call the Google Calendar API and return parsed JSON (null for 204).
 *
 * @param {string} accessToken
 * @param {string} path Path below /calendar/v3, must start with "/".
 * @param {{method?: string, body?: object, query?: Record<string,string>}} [opts]
 * @returns {Promise<any>}
 * @throws {Error} On any non-2xx response, with a message safe to surface.
 */
async function gcal(accessToken, path, opts) {
  const options = opts || {};
  const url = new URL(`${GCAL_BASE}${path}`);
  for (const [k, v] of Object.entries(options.query || {})) url.searchParams.set(k, v);

  const init = {
    method: options.method || 'GET',
    headers: { Authorization: `Bearer ${accessToken}`, Accept: 'application/json' },
  };
  if (options.body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(options.body);
  }

  const resp = await fetch(url, init);
  if (resp.status === 204) return null;

  const text = await resp.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (_err) {
    data = null;
  }

  if (!resp.ok) {
    const reason =
      (data && data.error && (data.error.message || data.error.status)) ||
      (typeof data === 'string' ? data : '') ||
      'unknown error';
    const err = new Error(`calendar api ${resp.status}: ${String(reason).slice(0, 160)}`);
    err.status = resp.status;
    throw err;
  }
  return data;
}

// ---------------------------------------------------------------------------
// Slot grid
// ---------------------------------------------------------------------------

/**
 * Build every legal bookable slot, already filtered by the minimum-notice rule
 * and by "is in the past".
 *
 * Days with no remaining slots are still returned (with an empty slot list) so
 * callers can decide how to present them.
 *
 * @param {number} [now] Epoch milliseconds treated as "now".
 * @returns {{cfg: object, windowStartMs: number, windowEndMs: number,
 *            days: Array<{date: string, label: string,
 *                         slots: Array<{startMs:number, endMs:number, start:string,
 *                                       end:string, label:string}>}>}}
 */
function buildGrid(now) {
  const nowMs = Number.isFinite(now) ? Number(now) : Date.now();
  const cfg = config();
  const earliestMs = nowMs + cfg.minNoticeHours * 60 * 60 * 1000;

  const days = cfg.days.map((date) => {
    const slots = [];
    const lastStart = cfg.endHour * 60 - cfg.slotMinutes;
    for (let m = cfg.startHour * 60; m <= lastStart; m += cfg.slotMinutes) {
      const startMs = tbilisiMs(date, m);
      const endMs = startMs + cfg.slotMinutes * 60 * 1000;
      if (startMs <= nowMs) continue;
      if (startMs < earliestMs) continue;
      slots.push({
        startMs,
        endMs,
        start: isoTbilisi(startMs),
        end: isoTbilisi(endMs),
        label: timeLabel(startMs),
      });
    }
    return { date, label: dayLabelKa(date), slots };
  });

  const allDayStarts = cfg.days.map((d) => tbilisiMs(d, 0));
  const windowStartMs = allDayStarts.length ? Math.min(...allDayStarts) : nowMs;
  const windowEndMs = allDayStarts.length ? Math.max(...allDayStarts) + 24 * 60 * 60 * 1000 : nowMs;

  return { cfg, windowStartMs, windowEndMs, days };
}

/**
 * Strip the internal epoch fields before sending a day list to the client.
 *
 * @param {Array<object>} days
 * @param {boolean} [dropEmpty] Omit days that have no slots left.
 * @returns {Array<{date:string, label:string, slots:Array<{start:string,end:string,label:string}>}>}
 */
function publicDays(days, dropEmpty) {
  const out = days.map((d) => ({
    date: d.date,
    label: d.label,
    slots: d.slots
      .slice()
      .sort((a, b) => a.startMs - b.startMs)
      .map((s) => ({ start: s.start, end: s.end, label: s.label })),
  }));
  return dropEmpty === false ? out : out.filter((d) => d.slots.length > 0);
}

/**
 * True when [aStart, aEnd) and [bStart, bEnd) intersect.
 *
 * Touching intervals do not count: a slot ending exactly when a meeting starts
 * is free, and so is a slot starting exactly when a meeting ends.
 *
 * @param {number} aStart @param {number} aEnd @param {number} bStart @param {number} bEnd
 * @returns {boolean}
 */
function overlaps(aStart, aEnd, bStart, bEnd) {
  return aStart < bEnd && bStart < aEnd;
}

// ---------------------------------------------------------------------------
// Calendar queries
// ---------------------------------------------------------------------------

/**
 * Query free/busy across one or more calendars and return the UNION of their
 * busy blocks. Union of busy is intersection of free: a slot survives only if
 * every listed calendar is free for it.
 *
 * Fails closed. If any calendar errors (typically `notFound`, meaning it was
 * never shared with the booking account) the whole call throws rather than
 * quietly treating that person as free all week, which is exactly how you
 * double-book someone. A loud 500 is recoverable; a silent double-booking of a
 * real interview is not.
 *
 * @param {string} accessToken
 * @param {string[]} ids Calendar ids to query.
 * @param {number|string} timeMin Epoch ms or an ISO string.
 * @param {number|string} timeMax Epoch ms or an ISO string.
 * @returns {Promise<Array<{startMs:number, endMs:number}>>} Busy blocks.
 */
async function freeBusyFor(accessToken, ids, timeMin, timeMax) {
  const wanted = (Array.isArray(ids) ? ids : [ids]).filter(Boolean);
  if (!wanted.length) return [];

  const min = typeof timeMin === 'number' ? isoTbilisi(timeMin) : String(timeMin);
  const max = typeof timeMax === 'number' ? isoTbilisi(timeMax) : String(timeMax);

  const data = await gcal(accessToken, '/freeBusy', {
    method: 'POST',
    body: {
      timeMin: min,
      timeMax: max,
      timeZone: TZ,
      items: wanted.map((id) => ({ id })),
    },
  });

  const calendars = (data && data.calendars) || {};
  const blocks = [];

  for (const id of wanted) {
    const entry = calendars[id] || {};
    if (Array.isArray(entry.errors) && entry.errors.length) {
      const reason = entry.errors.map((e) => e && e.reason).filter(Boolean).join(', ');
      throw new Error(
        `freeBusy error for ${id}: ${String(reason || 'unknown').slice(0, 120)}`,
      );
    }
    for (const b of Array.isArray(entry.busy) ? entry.busy : []) {
      const startMs = Date.parse(b.start);
      const endMs = Date.parse(b.end);
      if (Number.isFinite(startMs) && Number.isFinite(endMs) && endMs > startMs) {
        blocks.push({ startMs, endMs });
      }
    }
  }

  return blocks.sort((a, b) => a.startMs - b.startMs);
}

/**
 * Busy blocks for everyone who has a say: the host plus every co-host.
 *
 * @param {string} accessToken
 * @param {number|string} timeMin Epoch ms or an ISO string.
 * @param {number|string} timeMax Epoch ms or an ISO string.
 * @returns {Promise<Array<{startMs:number, endMs:number}>>} Busy blocks.
 */
async function freeBusy(accessToken, timeMin, timeMax) {
  return freeBusyFor(accessToken, busyCalendars(), timeMin, timeMax);
}

/**
 * Extract the Google Meet URL from an event resource.
 *
 * @param {object|null} event
 * @returns {string|null}
 */
function meetLinkOf(event) {
  if (!event) return null;
  if (typeof event.hangoutLink === 'string' && event.hangoutLink) return event.hangoutLink;
  const entries = (event.conferenceData && event.conferenceData.entryPoints) || [];
  const video = entries.find((e) => e && e.entryPointType === 'video' && e.uri);
  return video ? video.uri : null;
}

/**
 * Find this candidate's existing booking inside the bookable window.
 *
 * @param {string} accessToken
 * @param {string} candidateId
 * @param {number} [timeMin] Epoch ms; defaults to the configured window.
 * @param {number} [timeMax] Epoch ms; defaults to the configured window.
 * @returns {Promise<{eventId:string, startMs:number, endMs:number, startISO:string,
 *                    endISO:string, meetLink:string|null, label:string}|null>}
 */
async function findBooking(accessToken, candidateId, timeMin, timeMax) {
  let minMs = timeMin;
  let maxMs = timeMax;
  if (!Number.isFinite(minMs) || !Number.isFinite(maxMs)) {
    const grid = buildGrid(Date.now());
    minMs = grid.windowStartMs;
    maxMs = grid.windowEndMs;
  }

  const data = await gcal(accessToken, `/calendars/${encodeURIComponent(CALENDAR_ID)}/events`, {
    query: {
      privateExtendedProperty: `candidateId=${candidateId}`,
      timeMin: isoTbilisi(minMs),
      timeMax: isoTbilisi(maxMs),
      singleEvents: 'true',
      showDeleted: 'false',
      orderBy: 'startTime',
      maxResults: '10',
    },
  });

  const items = (data && Array.isArray(data.items) ? data.items : []).filter(
    (ev) => ev && ev.status !== 'cancelled' && ev.start && ev.start.dateTime,
  );
  if (!items.length) return null;

  const ev = items[items.length - 1];
  const startMs = Date.parse(ev.start.dateTime);
  const endMs = Date.parse(ev.end && ev.end.dateTime ? ev.end.dateTime : ev.start.dateTime);
  if (!Number.isFinite(startMs)) return null;

  return {
    eventId: ev.id,
    startMs,
    endMs: Number.isFinite(endMs) && endMs > startMs ? endMs : startMs + 30 * 60 * 1000,
    startISO: isoTbilisi(startMs),
    endISO: isoTbilisi(Number.isFinite(endMs) && endMs > startMs ? endMs : startMs + 30 * 60 * 1000),
    meetLink: meetLinkOf(ev),
    label: slotLabelKa(startMs),
  };
}

/**
 * List real (non-cancelled, non-transparent) events overlapping a window.
 *
 * Used only as an exactness check on top of freeBusy, because freeBusy merges
 * adjacent busy blocks and therefore cannot tell "only the candidate's own
 * event is here" from "their event plus somebody else's".
 *
 * @param {string} accessToken
 * @param {number} startMs
 * @param {number} endMs
 * @returns {Promise<Array<{id:string, startMs:number, endMs:number}>>}
 */
async function eventsInWindow(accessToken, startMs, endMs) {
  const data = await gcal(accessToken, `/calendars/${encodeURIComponent(CALENDAR_ID)}/events`, {
    query: {
      timeMin: isoTbilisi(startMs),
      timeMax: isoTbilisi(endMs),
      singleEvents: 'true',
      showDeleted: 'false',
      orderBy: 'startTime',
      maxResults: '50',
    },
  });

  return (data && Array.isArray(data.items) ? data.items : [])
    .filter((ev) => ev && ev.status !== 'cancelled' && ev.transparency !== 'transparent')
    .filter((ev) => ev.start && ev.start.dateTime && ev.end && ev.end.dateTime)
    .map((ev) => ({ id: ev.id, startMs: Date.parse(ev.start.dateTime), endMs: Date.parse(ev.end.dateTime) }))
    .filter((ev) => Number.isFinite(ev.startMs) && Number.isFinite(ev.endMs));
}

/**
 * Decide whether a single slot is still bookable, right now.
 *
 * @param {string} accessToken
 * @param {number} startMs
 * @param {number} endMs
 * @param {string|null} ignoreEventId Event allowed to occupy the slot (a
 *        reschedule onto the candidate's own current time).
 * @param {{startMs:number, endMs:number}|null} [ownWindow] The candidate's
 *        existing booking window, if they hold one.
 * @returns {Promise<boolean>}
 */
async function slotIsFree(accessToken, startMs, endMs, ignoreEventId, ownWindow) {
  // Re-selecting the slot you already hold is a no-op, and it must succeed.
  //
  // We invite the co-hosts to the booking, so the candidate's own event sits on
  // the co-host's calendar too and reads as busy there. Without this escape the
  // co-host check below rejects the candidate's own current time, while
  // computeAvailability deliberately keeps that slot on their grid. The
  // candidate would see their slot offered and get a 409 every time they picked
  // it, forever.
  //
  // Matched on start time alone, exactly as computeAvailability matches when it
  // puts the slot back on the grid. Matching start AND end here instead would
  // reopen the loop for any event whose end was edited by hand: the grid would
  // keep offering the slot while this refused it. Whatever the grid re-adds,
  // this excuses.
  //
  // A different slot gets the full strict check, so this can never let a
  // booking land on a time a co-host is genuinely busy. Re-confirming the slot
  // you already occupy changes nothing on anyone's calendar, so there is no
  // conflict for it to create.
  const isOwnSlot = Boolean(ownWindow && ownWindow.startMs === startMs);

  // Co-hosts otherwise checked first, and strictly. `ignoreEventId` excuses
  // exactly one event on the HOST calendar; it can never excuse a co-host's busy
  // block. We could not honour it there anyway: we hold free/busy access to a
  // co-host's calendar, not read access, so their busy blocks carry no event ids
  // to compare against.
  const cohosts = cohostCalendars();
  if (cohosts.length && !isOwnSlot) {
    const cohostBusy = await freeBusyFor(accessToken, cohosts, startMs, endMs);
    if (cohostBusy.some((b) => overlaps(startMs, endMs, b.startMs, b.endMs))) return false;
  }

  const busy = await freeBusyFor(accessToken, [CALENDAR_ID], startMs, endMs);
  const hits = busy.filter((b) => overlaps(startMs, endMs, b.startMs, b.endMs));
  if (hits.length === 0) return true;
  if (!ignoreEventId) return false;

  const events = await eventsInWindow(accessToken, startMs, endMs);
  const blockers = events.filter(
    (ev) => ev.id !== ignoreEventId && overlaps(startMs, endMs, ev.startMs, ev.endMs),
  );
  return blockers.length === 0;
}

/**
 * Compute the bookable slots for one candidate, plus their existing booking.
 *
 * Shared by /api/slots and by the 409 payload of /api/book so both produce an
 * identical `days` shape.
 *
 * @param {string} accessToken
 * @param {string} candidateId
 * @param {number} [now] Epoch milliseconds treated as "now".
 * @returns {Promise<{days: Array<object>, booking: object|null}>}
 */
async function computeAvailability(accessToken, candidateId, now) {
  const nowMs = Number.isFinite(now) ? Number(now) : Date.now();
  const grid = buildGrid(nowMs);

  const [busy, booking] = await Promise.all([
    freeBusy(accessToken, grid.windowStartMs, grid.windowEndMs),
    findBooking(accessToken, candidateId, grid.windowStartMs, grid.windowEndMs),
  ]);

  const days = grid.days.map((day) => ({
    date: day.date,
    label: day.label,
    slots: day.slots.filter(
      (slot) => !busy.some((b) => overlaps(slot.startMs, slot.endMs, b.startMs, b.endMs)),
    ),
  }));

  // The candidate's own booking shows up as busy in freeBusy. Their own slot
  // must stay selectable, so put it back if it is still on the legal grid.
  if (booking) {
    for (let i = 0; i < grid.days.length; i += 1) {
      const own = grid.days[i].slots.find((s) => s.startMs === booking.startMs);
      if (!own) continue;
      if (!days[i].slots.some((s) => s.startMs === own.startMs)) {
        days[i].slots = days[i].slots.concat([own]).sort((a, b) => a.startMs - b.startMs);
      }
      break;
    }
  }

  return { days: publicDays(days), booking };
}

// ---------------------------------------------------------------------------
// Telegram (best effort, never fatal)
// ---------------------------------------------------------------------------

/**
 * Notify Giorgi about a booking. Silently does nothing when either Telegram env
 * var is unset, and swallows every error: a Telegram failure must never fail a
 * booking.
 *
 * @param {string} text Plain text, no parse mode.
 * @returns {Promise<void>}
 */
async function notifyTelegram(text) {
  const botToken = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;
  if (!botToken || !chatId) return;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 3000);
  try {
    await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: chatId, text, disable_web_page_preview: true }),
      signal: controller.signal,
    });
  } catch (_err) {
    // Intentionally ignored. Never log the error: it can contain the URL,
    // which contains the bot token.
    console.error('booking: telegram notification failed');
  } finally {
    clearTimeout(timer);
  }
}

module.exports = {
  TZ,
  TZ_SUFFIX,
  TZ_OFFSET_MS,
  CALENDAR_ID,
  WEEKDAYS_KA,
  MONTHS_KA,
  EVENT_KA,
  candidates,
  DEFAULTS,
  sendJson,
  handleOptions,
  readJsonBody,
  safeDetail,
  config,
  tbilisiParts,
  tbilisiMs,
  isoTbilisi,
  dayLabelKa,
  slotLabelKa,
  timeLabel,
  signToken,
  verifyToken,
  getAccessToken,
  gcal,
  buildGrid,
  publicDays,
  overlaps,
  cohostCalendars,
  busyCalendars,
  freeBusyFor,
  freeBusy,
  findBooking,
  eventsInWindow,
  slotIsFree,
  meetLinkOf,
  computeAvailability,
  notifyTelegram,
};
