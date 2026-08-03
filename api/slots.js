'use strict';

/**
 * GET /api/slots?t=<token>
 *
 * Returns the bookable interview slots for one candidate, plus their existing
 * booking if they already have one.
 */

const {
  sendJson,
  handleOptions,
  safeDetail,
  verifyToken,
  getAccessToken,
  computeAvailability,
  isoTbilisi,
} = require('./_shared.js');

/**
 * Pull the `t` query parameter off the request.
 *
 * Never derived from the path: the page is proxied under two different
 * hostnames and path shapes.
 *
 * @param {import('http').IncomingMessage & {query?: Record<string, string|string[]>}} req
 * @returns {string}
 */
function readToken(req) {
  let raw = req.query && typeof req.query.t !== 'undefined' ? req.query.t : undefined;
  if (Array.isArray(raw)) raw = raw[0];
  if (typeof raw === 'string') return raw;
  const url = new URL(req.url || '/', 'http://localhost');
  return url.searchParams.get('t') || '';
}

/**
 * Vercel Node serverless handler.
 *
 * @param {import('http').IncomingMessage} req
 * @param {import('http').ServerResponse} res
 * @returns {Promise<void>}
 */
module.exports = async function handler(req, res) {
  try {
    if (handleOptions(req, res, 'GET')) return;
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      sendJson(res, 405, { ok: false, error: 'method_not_allowed' });
      return;
    }

    const candidate = verifyToken(readToken(req));
    if (!candidate) {
      sendJson(res, 403, { ok: false, error: 'invalid_token' });
      return;
    }

    const accessToken = await getAccessToken();
    const nowMs = Date.now();
    const { days, booking } = await computeAvailability(accessToken, candidate.id, nowMs);

    sendJson(res, 200, {
      ok: true,
      candidate: { id: candidate.id, name: candidate.name },
      days,
      booking: booking
        ? {
            startISO: booking.startISO,
            endISO: booking.endISO,
            meetLink: booking.meetLink,
            label: booking.label,
          }
        : null,
      generatedAt: isoTbilisi(nowMs),
    });
  } catch (err) {
    console.error('slots: failed:', safeDetail(err));
    try {
      sendJson(res, 500, { ok: false, error: 'server_error', detail: safeDetail(err) });
    } catch (_inner) {
      /* response already committed */
    }
  }
};
