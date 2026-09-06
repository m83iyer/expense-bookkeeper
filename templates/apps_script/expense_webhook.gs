/*
 * Expense Bookkeeper Android-only webhook template.
 *
 * Deploy as a Google Apps Script web app attached to the user's Google Sheet.
 * Set Script Properties:
 *   EXPENSE_BOOKKEEPER_SECRET = random shared secret
 *
 * Android Tasker/MacroDroid POST body:
 *   {"secret":"...", "raw":"AED 87.00 spent at EXAMPLE SHOP on 29/04/2026", "card":"ExampleCard"}
 */

const EXPENSES_TAB = 'EXPENSES';
const MERCHANT_MASTER_TAB = 'MERCHANT_MASTER';
const FALLBACK_CATEGORY = 'Misc';
const FALLBACK_SUBCATEGORY = 'Other';

function doPost(e) {
  const payload = JSON.parse((e && e.postData && e.postData.contents) || '{}');
  const expected = PropertiesService.getScriptProperties().getProperty('EXPENSE_BOOKKEEPER_SECRET') || '';
  if (expected && payload.secret !== expected) {
    return json_({ ok: false, error: 'bad secret' }, 401);
  }
  const raw = String(payload.raw || payload.text || '').trim();
  if (!raw) return json_({ ok: false, error: 'missing raw' }, 400);

  const txn = parseRaw_(raw, payload);
  const resolved = resolveMerchant_(txn.merchant_raw);
  txn.category = resolved.category || FALLBACK_CATEGORY;
  txn.subcategory = resolved.subcategory || FALLBACK_SUBCATEGORY;
  txn.merchant_clean = resolved.merchant_clean || txn.merchant_raw;
  txn.status = resolved.status || 'Confirmed';
  txn.review_reason = resolved.review_reason || '';
  txn.hash = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_1,
    [txn.date, txn.amount.toFixed(2), txn.merchant_raw.toLowerCase()].join('|')
  ).map(function (b) {
    return ('0' + (b & 0xFF).toString(16)).slice(-2);
  }).join('').slice(0, 16);

  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(EXPENSES_TAB);
  if (hashExists_(sheet, txn.hash)) return json_({ ok: true, duplicate: true, hash: txn.hash });
  sheet.appendRow(row_(txn));
  return json_({ ok: true, status: txn.status, merchant: txn.merchant_raw, hash: txn.hash });
}

function parseRaw_(raw, payload) {
  const amountMatch = raw.match(/([A-Z]{3})\s*([0-9,]+(?:\.[0-9]{1,2})?)/i);
  const atMatch = raw.match(/\bat\s+(.+?)(?:\s+on\s+\d{1,2}[\/-]\d{1,2}[\/-]\d{2,4}|$)/i);
  const dateMatch = raw.match(/(\d{1,2})[\/-](\d{1,2})[\/-](\d{2,4})/);
  const date = dateMatch ? normalizeDate_(dateMatch) : Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd');
  return {
    txn_id: 'TXN' + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyyMMddHHmmss'),
    date: date,
    amount: amountMatch ? Number(amountMatch[2].replace(/,/g, '')) : 0,
    currency: amountMatch ? amountMatch[1].toUpperCase() : String(payload.currency || ''),
    txn_type: 'Expense',
    merchant_raw: atMatch ? atMatch[1].trim() : String(payload.merchant || 'Unknown Merchant'),
    card: String(payload.card || ''),
    source: String(payload.source || 'apps_script_webhook'),
    person: String(payload.person || 'Household'),
    notes: raw
  };
}

function resolveMerchant_(merchant) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const tab = ss.getSheetByName(MERCHANT_MASTER_TAB);
  if (!tab) return review_('MERCHANT_MASTER tab missing');
  const values = tab.getDataRange().getValues();
  const headers = values[0].map(String);
  const cKey = headers.indexOf('Merchant_Keyword');
  const cClean = headers.indexOf('Merchant_Clean');
  const cCat = headers.indexOf('Category');
  const cSub = headers.indexOf('Subcategory');
  const input = normalize_(merchant);
  for (let i = 1; i < values.length; i++) {
    const key = normalize_(values[i][cKey]);
    if (key && phraseMatch_(key, input)) {
      return {
        merchant_clean: String(values[i][cClean] || merchant),
        category: String(values[i][cCat] || ''),
        subcategory: String(values[i][cSub] || ''),
        status: values[i][cCat] && values[i][cSub] ? 'Confirmed' : 'Review',
        review_reason: values[i][cCat] && values[i][cSub] ? '' : 'Merchant matched but category incomplete'
      };
    }
  }
  return review_('Unknown merchant captured for manual review');
}

function review_(reason) {
  return { category: FALLBACK_CATEGORY, subcategory: FALLBACK_SUBCATEGORY, status: 'Review', review_reason: reason };
}

function row_(txn) {
  const date = new Date(txn.date + 'T00:00:00');
  const day = Utilities.formatDate(date, Session.getScriptTimeZone(), 'EEE');
  const monthYear = Utilities.formatDate(date, Session.getScriptTimeZone(), 'MMM-yyyy');
  return [txn.txn_id, txn.date, day, monthYear, txn.amount, txn.currency, txn.txn_type,
    txn.category, txn.subcategory, txn.merchant_raw, txn.merchant_clean, txn.card,
    txn.source, txn.person, txn.notes, txn.status, txn.review_reason, txn.hash];
}

function hashExists_(sheet, hash) {
  const values = sheet.getDataRange().getValues();
  if (!values.length) return false;
  const cHash = values[0].indexOf('Hash');
  if (cHash < 0) return false;
  return values.some(function (row, i) { return i > 0 && row[cHash] === hash; });
}

function normalize_(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function phraseMatch_(needle, haystack) {
  const n = needle.split(' ');
  const h = haystack.split(' ');
  for (let i = 0; i <= h.length - n.length; i++) {
    if (h.slice(i, i + n.length).join(' ') === n.join(' ')) return true;
  }
  return false;
}

function normalizeDate_(m) {
  const dd = ('0' + m[1]).slice(-2);
  const mm = ('0' + m[2]).slice(-2);
  const yyyy = m[3].length === 2 ? '20' + m[3] : m[3];
  return yyyy + '-' + mm + '-' + dd;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
