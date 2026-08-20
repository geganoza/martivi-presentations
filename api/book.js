'use strict';

/**
 * POST /api/book   body { t: string, startISO: string }
 *
 * Books (or reschedules) one candidate's interview slot on Giorgi's primary
 * Google Calendar, with a Google Meet link, and invites the candidate.
 */

const crypto = require('node:crypto');

const {
  TZ,
  CALENDAR_ID,
  EVENT_KA,
  sendJson,
  handleOptions,
  readJsonBody,
  safeDetail,
  verifyToken,
  getAccessToken,
  gcal,
  buildGrid,
  cohostCalendars,
  findBooking,
  slotIsFree,
  meetLinkOf,
  slotLabelKa,
  isoTbilisi,
  computeAvailability,
  notifyTelegram,
} = require('./_shared.js');

/**
 * Find the requested start time on a freshly recomputed legal grid.
 *
 * The client's arithmetic is never trusted: the timestamp is normalised to
 * epoch milliseconds and matched against the grid, so an equivalent instant
 * expressed in any offset is accepted and anything off-grid is rejected.
 *
 * @param {unknown} startISO
 * @param {number} nowMs
 * @returns {{startMs:number, endMs:number, start:string, end:string, label:string}|null}
 */
function resolveSlot(startISO, nowMs) {
  if (typeof startISO !== 'string' || !startISO.trim() || startISO.length > 64) return null;
  const wantedMs = Date.parse(startISO.trim());
  if (!Number.isFinite(wantedMs)) return null;

  const grid = buildGrid(nowMs);
  for (const day of grid.days) {
    const hit = day.slots.find((s) => s.startMs === wantedMs);
    if (hit) return hit;
  }
  return null;
}

/**
 * Build the Google Calendar event body for a booking.
 *
 * All Georgian copy comes from EVENT_KA, which was produced by the `ka` tool.
 *
 * @param {{id:string, name:string, email:string}} candidate
 * @param {{start:string, end:string}} slot
 * @returns {object}
 */
function buildEvent(candidate, slot) {
  const summary = EVENT_KA.summary
    .replace('{position}', EVENT_KA.position)
    .replace('{name}', candidate.name);
  const description = EVENT_KA.description
    .split('{position}')
    .join(EVENT_KA.position)
    .split('{brand}')
    .join(EVENT_KA.brand)
    .split('{name}')
    .join(candidate.name);

  // One event with the co-hosts invited, never a mirrored copy per calendar.
  // The invitation puts it on their calendar, an unanswered invitation already
  // counts as busy, and a later reschedule or cancellation propagates from this
  // single event. Two parallel events drift apart the first time one is moved.
  const attendees = [{ email: candidate.email, displayName: candidate.name }].concat(
    cohostCalendars().map((email) => ({ email, optional: false })),
  );

  return {
    summary,
    description,
    start: { dateTime: slot.start, timeZone: TZ },
    end: { dateTime: slot.end, timeZone: TZ },
    attendees,
    conferenceData: {
      createRequest: {
        requestId: crypto.randomUUID(),
        conferenceSolutionKey: { type: 'hangoutsMeet' },
      },
    },
    extendedProperties: {
      private: { martiviBooking: '1', candidateId: candidate.id },
    },
    reminders: {
      useDefault: false,
      overrides: [
        { method: 'popup', minutes: 30 },
        { method: 'email', minutes: 1440 },
      ],
    },
    guestsCanModify: false,
    guestsCanInviteOthers: false,
  };
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
    if (handleOptions(req, res, 'POST')) return;
    if (req.method !== 'POST') {
      sendJson(res, 405, { ok: false, error: 'method_not_allowed' });
      return;
    }

    const body = await readJsonBody(req);

    const candidate = verifyToken(body.t);
    if (!candidate) {
      sendJson(res, 403, { ok: false, error: 'invalid_token' });
      return;
    }

    const nowMs = Date.now();
    const slot = resolveSlot(body.startISO, nowMs);
    if (!slot) {
      sendJson(res, 400, { ok: false, error: 'bad_slot' });
      return;
    }

    const accessToken = await getAccessToken();

    // An existing booking is allowed to occupy the slot the candidate is now
    // asking for, since that is a reschedule onto their own time.
    const existing = await findBooking(accessToken, candidate.id);

    // Re-confirming the exact time they already hold is a no-op, not a
    // reschedule. Tearing the event down and rebuilding it would mail them a
    // Google cancellation for an interview that is not being cancelled and mint
    // a fresh Meet URL, killing the link already sitting in their inbox.
    if (existing && existing.startMs === slot.startMs) {
      sendJson(res, 200, {
        ok: true,
        startISO: existing.startISO,
        endISO: existing.endISO,
        meetLink: existing.meetLink,
        label: existing.label,
        rescheduledFrom: null,
        eventId: existing.eventId,
        generatedAt: isoTbilisi(Date.now()),
      });
      return;
    }

    const ignoreEventId = existing ? existing.eventId : null;

    // The double-booking race: re-check this exact slot immediately before the
    // insert, not the stale list the page was rendered from.
    const free = await slotIsFree(accessToken, slot.startMs, slot.endMs, ignoreEventId, existing);
    if (!free) {
      const refreshed = await computeAvailability(accessToken, candidate.id, Date.now());
      sendJson(res, 409, { ok: false, error: 'slot_taken', days: refreshed.days });
      return;
    }

    // Reschedule: remove the old event first so the candidate never ends up
    // holding two slots.
    let rescheduledFrom = null;
    if (existing) {
      rescheduledFrom = existing.startISO;
      try {
        await gcal(accessToken, `/calendars/${encodeURIComponent(CALENDAR_ID)}/events/${encodeURIComponent(existing.eventId)}`, {
          method: 'DELETE',
          query: { sendUpdates: 'all' },
        });
      } catch (err) {
        // 404/410 means it is already gone, which is the state we wanted.
        if (err && (err.status === 404 || err.status === 410)) {
          console.error('book: old event already removed');
        } else {
          throw err;
        }
      }
    }

    const created = await gcal(accessToken, `/calendars/${encodeURIComponent(CALENDAR_ID)}/events`, {
      method: 'POST',
      query: { conferenceDataVersion: '1', sendUpdates: 'all' },
      body: buildEvent(candidate, slot),
    });

    const meetLink = meetLinkOf(created);
    const label = slotLabelKa(slot.startMs);

    // Best effort only. notifyTelegram swallows every failure internally.
    await notifyTelegram(
      [
        'Interview booked',
        `Candidate: ${candidate.nameEn} (${candidate.email})`,
        `When: ${label} (Georgia time)`,
        rescheduledFrom ? `Moved from: ${rescheduledFrom}` : null,
        meetLink ? `Meet: ${meetLink}` : 'Meet link pending',
      ]
        .filter(Boolean)
        .join('\n'),
    );

    sendJson(res, 200, {
      ok: true,
      startISO: slot.start,
      endISO: slot.end,
      meetLink,
      label,
      rescheduledFrom,
      eventId: created && created.id ? created.id : null,
      generatedAt: isoTbilisi(Date.now()),
    });
  } catch (err) {
    console.error('book: failed:', safeDetail(err));
    try {
      sendJson(res, 500, { ok: false, error: 'server_error', detail: safeDetail(err) });
    } catch (_inner) {
      /* response already committed */
    }
  }
};
